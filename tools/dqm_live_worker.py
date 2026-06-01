#!/usr/bin/env python3
"""DQM Live Worker — monit --LIVE 프로세스 관리 및 실시간 dqm_refresh 전송"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import yaml

from tools.config_loader import get_path_config, CONFIG_FILE as CONFIG_YML_PATH


# ── Paths ─────────────────────────────────────────────────────────────────────
DQM_DIR = Path(get_path_config("DqmDir"))
OUTPUT_DIR = DQM_DIR / "output"
MONIT_BIN = DQM_DIR / "monit"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _build_monit_env() -> dict:
    """Build a subprocess env where ROOT paths match the monit binary's link-time ROOT."""
    import shutil
    env = os.environ.copy()
    rc = shutil.which("root-config")
    if rc is None:
        rc = "/opt/homebrew/opt/root/bin/root-config"
    try:
        rootsys = subprocess.check_output([rc, "--prefix"], text=True).strip()
        libdir = subprocess.check_output([rc, "--libdir"], text=True).strip()
    except Exception:
        rootsys = "/opt/homebrew/opt/root"
        libdir = "/opt/homebrew/opt/root/lib/root"
    env["ROOTSYS"] = rootsys
    env["DYLD_LIBRARY_PATH"] = libdir
    return env
MANIFEST_PATH = PROJECT_ROOT / "dqm_dashboards.yml"


# ── Manifest loader ───────────────────────────────────────────────────────────
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


# ── Session ───────────────────────────────────────────────────────────────────
class DQMLiveSession:
    """Single-slot manager. Starting a new session stops the previous one."""

    def __init__(self):
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._watcher: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._run_number: Optional[int] = None
        self._base_prefix: Optional[str] = None
        self._output_queue: Optional[queue.Queue] = None
        self._cells: list[str] = []

    # ── public API ────────────────────────────────────────────────────────────
    def start(
        self,
        run_number: int,
        agent_type: str,
        output_queue: queue.Queue,
        context: Optional[dict] = None,
    ) -> None:
        """Stop any existing session, then spawn monit --LIVE for this run."""
        # Always stop previous session first — single slot
        self.stop()

        with self._lock:
            context = context or {}
            manifest = _load_manifest()
            # Case-insensitive lookup: "em_scan" matches "EM_scan" in yaml
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
            base_prefix = f"Run{run_number}_{type_}_{method}"
            if "AUXcut" in flags:
                base_prefix += "_AuxCut"

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            sentinel = OUTPUT_DIR / f"Run{run_number}_END"
            sentinel.unlink(missing_ok=True)
            for old in OUTPUT_DIR.glob(f"Run{run_number}_*.json"):
                try:
                    old.unlink()
                except OSError:
                    pass

            cmd = [
                str(MONIT_BIN),
                "--RunNumber", str(run_number),
                "--Config", str(CONFIG_YML_PATH),
                "--type", type_,
                "--method", method,
                "--LIVE",
            ]
            for flag in flags:
                if flag in ("AUXcut",):
                    cmd.append(f"--{flag}")

            monit_env = _build_monit_env()

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(DQM_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    env=monit_env,
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
        """Touch sentinel, wait for monit to exit, then clear state."""
        with self._lock:
            if self._proc is None:
                return

            run_number = self._run_number
            sentinel = OUTPUT_DIR / f"Run{run_number}_END"
            try:
                sentinel.touch()
            except OSError:
                pass

            # Wait for graceful exit; escalate if monit hangs
            try:
                self._proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()

            self._stop_event.set()
            if self._watcher and self._watcher.is_alive():
                self._watcher.join(timeout=3)

            # monit has exited and flushed final JSON.  Push one
            # dqm_refresh per canvas so the browser renders the final
            # state even when the watcher thread missed the last writes
            # (common when monit finishes faster than the 500 ms poll).
            if self._output_queue is not None and self._base_prefix is not None:
                pfx = f"{self._base_prefix}_"
                for p in sorted(OUTPUT_DIR.glob(f"{self._base_prefix}_*.json")):
                    name = p.name
                    if not name.endswith(".json"):
                        continue
                    canvas = name[len(pfx):-len(".json")]
                    self._output_queue.put({
                        "type": "dqm_refresh",
                        "run_number": run_number,
                        "canvas": canvas,
                        "filename": name,
                        "stamp": int(time.time() * 1000),
                    })

            if self._output_queue is not None:
                self._output_queue.put({
                    "type": "dqm_live_end",
                    "run_number": run_number,
                })

            sentinel.unlink(missing_ok=True)

            self._proc = None
            self._watcher = None
            self._run_number = None
            self._base_prefix = None
            self._output_queue = None
            self._cells = []

    # ── internals ─────────────────────────────────────────────────────────────
    def _watch_loop(self) -> None:
        """Poll OUTPUT_DIR for new/updated JSON files and emit dqm_refresh."""
        run_number = self._run_number
        base_prefix = self._base_prefix
        if run_number is None or base_prefix is None:
            return

        last_mtimes: dict[str, float] = {}
        prefix_match = f"{base_prefix}_"

        while not self._stop_event.is_set():
            try:
                for path in OUTPUT_DIR.glob(f"{base_prefix}_*.json"):
                    name = path.name
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    if last_mtimes.get(name) == mtime:
                        continue
                    last_mtimes[name] = mtime

                    if not name.startswith(prefix_match) or not name.endswith(".json"):
                        continue
                    canvas = name[len(prefix_match):-len(".json")]

                    if self._output_queue is not None:
                        self._output_queue.put({
                            "type": "dqm_refresh",
                            "run_number": run_number,
                            "canvas": canvas,
                            "filename": name,
                            "stamp": int(mtime * 1000),
                        })
            except Exception:
                pass

            self._stop_event.wait(0.5)


# Module-level singleton — DAQRunTool grabs this instance.
dqm_session = DQMLiveSession()
