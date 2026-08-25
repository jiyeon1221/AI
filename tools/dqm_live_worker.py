#!/usr/bin/env python3
"""DQM Live Worker — monit --LIVE 프로세스 관리 및 실시간 dqm_refresh 전송"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from typing import Optional

import yaml

from tools.config_loader import PROJECT_ROOT
from tools.dqm_tool import (
    DQM_DIR,
    MONIT_BIN,
    OUTPUT_DIR,
    build_monit_command,
    kill_process_group,
    live_base_prefix,
    run_artifact_patterns,
)


# DQM 경로.
MANIFEST_PATH = PROJECT_ROOT / "dqm_dashboards.yml"

# monit 실행 환경은 DQM/envset.sh에서 상속한다.


# 대시보드 설정 로더.
_manifest_cache: Optional[dict] = None
_manifest_mtime: float = 0.0


def _load_manifest() -> dict:
    """Load (and hot-reload) the agent → dashboard manifest."""
    global _manifest_cache, _manifest_mtime
    if not MANIFEST_PATH.exists():
        return {}
    mtime = MANIFEST_PATH.stat().st_mtime
    if _manifest_cache is None or mtime != _manifest_mtime:
        with open(MANIFEST_PATH) as f:
            _manifest_cache = yaml.safe_load(f) or {}
        _manifest_mtime = mtime
    return _manifest_cache


_VAR_RE = re.compile(r'\$\{(\w+)\}')


def _substitute(template: str, ctx: dict) -> str:
    """Replace ${var} with ctx[var]; leave token unchanged if missing."""
    return _VAR_RE.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), template)


# DQM 실시간 세션.
class DQMLiveSession:
    """동시에 하나의 DQM 실시간 세션만 관리한다."""

    def __init__(self):
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._watcher: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._run_number: Optional[int] = None
        self._base_prefix: Optional[str] = None
        self._output_queue: Optional[queue.Queue] = None
        self._cells: list[str] = []

    # 공개 API.
    def start(
        self,
        run_number: int,
        agent_type: str,
        output_queue: queue.Queue,
        context: Optional[dict] = None,
    ) -> None:
        """Stop any existing session, then spawn monit --LIVE for this run."""
        # 세션은 한 번에 하나만 실행한다.
        self.stop()

        with self._lock:
            context = context or {}
            manifest = _load_manifest()
            # 에이전트 이름은 대소문자를 구분하지 않는다.
            agent_cfg = (
                manifest.get(agent_type)
                or next((v for k, v in manifest.items() if k.lower() == agent_type.lower()), None)
                or manifest.get("default")
                or {}
            )
            live_cfg = agent_cfg.get("live") or {"type": "full", "method": "PeakADC"}
            cell_templates = agent_cfg.get("cells") or ["fCanvasHeatmap"]

            cells = [_substitute(c, context) for c in cell_templates]

            type_ = live_cfg.get("type", "full")
            method = live_cfg.get("method", "PeakADC")
            flags = live_cfg.get("flags") or []
            base_prefix = live_base_prefix(
                run_number, type_, method, aux_cut="AUXcut" in flags
            )

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            # 같은 실행 번호의 이전 플롯을 지운다.
            for pat in run_artifact_patterns(run_number):
                for old in OUTPUT_DIR.glob(pat):
                    try:
                        old.unlink()
                    except OSError:
                        pass

            cmd = build_monit_command(
                run_number,
                type_=type_,
                method=method,
                flags=("LIVE", *flags),
            )

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(DQM_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setpgrp,
                )
            except FileNotFoundError as e:
                output_queue.put({
                    "type": "error",
                    "content": f"DQM monit binary not found: {MONIT_BIN}",
                })
                self._proc = None
                return

            self._run_number = run_number
            self._base_prefix = base_prefix
            self._output_queue = output_queue
            self._cells = cells

            output_queue.put({
                "type": "dqm_live_start",
                "run_number": run_number,
                "agent": agent_type,
                "plot_type": type_,
                "method": method,
                "base_prefix": base_prefix,
                "cells": cells,
            })

            self._stop_event.clear()
            self._watcher = threading.Thread(
                target=self._watch_loop, daemon=True, name="DQMLiveWatcher",
            )
            self._watcher.start()

    def stop(self) -> None:
        """Kill the monit LIVE process (no graceful sentinel — the DQM LIVE
        loop runs until killed, matching the old serve_rootfiles behaviour),
        then clear state."""
        with self._lock:
            if self._proc is None:
                return

            run_number = self._run_number

            kill_process_group(self._proc)

            self._stop_event.set()
            if self._watcher and self._watcher.is_alive():
                self._watcher.join(timeout=3)

            # monit 종료 후 브라우저에 마지막 새로고침을 보낸다.
            if self._output_queue is not None and self._base_prefix is not None:
                self._output_queue.put({
                    "type": "dqm_refresh",
                    "run_number": run_number,
                    "stamp": int(time.time() * 1000),
                })

            if self._output_queue is not None:
                self._output_queue.put({
                    "type": "dqm_live_end",
                    "run_number": run_number,
                })

            self._proc = None
            self._watcher = None
            self._run_number = None
            self._base_prefix = None
            self._output_queue = None
            self._cells = []

    # 내부 처리.
    def _watch_loop(self) -> None:
        """Poll OUTPUT_DIR for a rewritten <base_prefix>.root bundle and emit a
        single dqm_refresh each time monit rewrites it. The browser re-opens the
        bundle (JSROOT.openFile) and redraws every shown cell."""
        run_number = self._run_number
        base_prefix = self._base_prefix
        if run_number is None or base_prefix is None:
            return

        root_path = OUTPUT_DIR / f"{base_prefix}.root"
        last_mtime: Optional[float] = None

        while not self._stop_event.is_set():
            try:
                mtime = root_path.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    if self._output_queue is not None:
                        self._output_queue.put({
                            "type": "dqm_refresh",
                            "run_number": run_number,
                            "stamp": int(mtime * 1000),
                        })
            except OSError:
                pass  # 출력 번들이 아직 생성되지 않았다.
            except Exception:
                pass

            self._stop_event.wait(0.5)


# DAQ 도구가 공유하는 단일 세션 인스턴스.
dqm_session = DQMLiveSession()
