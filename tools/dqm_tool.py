#!/usr/bin/env python3
"""DQM Tool — C++ monit 실행으로 ROOT 파일 생성.

경로·파일명·monit 인자 규칙도 여기 둔다. monit을 부르거나 그 산출물을 찾는 쪽은
이 모듈을 import한다. 규칙이 바뀌면 여기만 고치면 된다.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .base_tool import BaseTool
from .config_loader import CONFIG_FILE as CONFIG_YML_PATH
from .config_loader import get_dqm_dir, get_dqm_output_dir


# DQM 경로, 파일명, monit 명령.
DQM_DIR: Path = get_dqm_dir()
OUTPUT_DIR: Path = get_dqm_output_dir()
MONIT_BIN: Path = DQM_DIR / "monit"
MONIT_EXECUTABLE = str(MONIT_BIN)
DQM_OUTPUT_DIR = str(OUTPUT_DIR)

# monit이 지원하는 불리언 플래그.
MONIT_FLAGS = ("LIVE", "AUXcut", "AUX")

DEFAULT_HEATMAP_MODULE = "MCPPMT"


def base_prefix(run_number: int, type_: str, method: str, module: str = "") -> str:
    """monit이 만드는 산출물 이름의 공통 앞부분 (확장자 없음).

    single은 C++ 쪽 fModule이 빈 문자열이라 접미 언더스코어가 하나 남는다.
    """
    if type_ == "full":
        return f"Run{run_number}_full_{method}"
    if type_ in ("heatmap", "module"):
        return f"Run{run_number}_{type_}_{method}_{module or DEFAULT_HEATMAP_MODULE}"
    return f"Run{run_number}_single_{method}_"


def root_filename(run_number: int, type_: str, method: str, module: str = "") -> str:
    return f"{base_prefix(run_number, type_, method, module)}.root"


def live_base_prefix(run_number: int, type_: str, method: str, aux_cut: bool = False) -> str:
    """--LIVE로 돌 때 monit이 갱신하는 번들 이름. AUXcut이면 접미가 붙는다."""
    prefix = f"Run{run_number}_{type_}_{method}"
    return f"{prefix}_AuxCut" if aux_cut else prefix


def run_artifact_patterns(run_number: int) -> tuple:
    """해당 run이 남긴 모든 산출물 glob 패턴 (오래된 플롯 정리용)."""
    return (f"Run{run_number}_*.root", f"Run{run_number}_*.gif")


def build_monit_command(
    run_number: int,
    *,
    type_: str = "full",
    method: str = "IntADC",
    modules: Optional[Sequence[str]] = None,
    max_event: Optional[int] = None,
    flags: Iterable[str] = (),
    aux_cut_mode: Optional[str] = None,
    aux_mode: Optional[str] = None,
) -> List[str]:
    """monit 실행 인자를 조립한다."""
    flags = tuple(flags)
    cmd = [
        str(MONIT_BIN),
        "--RunNumber", str(run_number),
        "--Config", str(CONFIG_YML_PATH),
        "--type", type_,
        "--method", method,
    ]
    if modules:
        cmd.extend(["--module"] + list(modules))
    if max_event:
        cmd.extend(["--MaxEvent", str(max_event)])
    for flag in flags:
        if flag in MONIT_FLAGS:
            cmd.append(f"--{flag}")
    # AUXcut은 AUX 플롯 없이도 적용할 수 있다.
    if aux_cut_mode and aux_cut_mode != "none":
        cmd.extend(["--AUXCutMode", aux_cut_mode])
    # AUX 범위 옵션은 AUX 플롯과 함께 사용한다.
    if "AUX" in flags and aux_mode in ("WC", "Hodo", "WCHodo"):
        cmd.extend(["--AUXMode", aux_mode])
    return cmd


def kill_process_group(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """monit은 graceful 종료 경로가 없어 프로세스 그룹째 SIGTERM → SIGKILL 한다.

    os.setpgrp로 띄운 프로세스에만 쓸 것.
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait()


class DQMPlotTool(BaseTool):
    """DQM Plot 생성 Tool"""

    def __init__(self):
        super().__init__(
            name="dqm_plot_tool",
            description="Generate DQM plots for test-beam data analysis"
        )

        os.makedirs(DQM_OUTPUT_DIR, exist_ok=True)

    @staticmethod
    def _normalize_module(name: str) -> str:
        """T1S → T1-S, T3C → T3-C. Leaves T1, MCPPMT, T1-S unchanged."""
        return re.sub(r'^(T\d)([SC])$', r'\1-\2', name)

    def execute(self, params: Dict[str, Any]) -> str:
        """Run 번호와 플롯 조건에 맞는 DQM 결과를 생성한다."""
        valid, error = self.validate_params(params, ["run_number"])
        if not valid:
            raise RuntimeError(f"파라미터 오류: {error}")

        run_number = params["run_number"]
        method = params.get("method", "IntADC")
        type_ = params.get("type", "full")
        modules = [self._normalize_module(m) for m in params.get("modules", [])]
        max_event = params.get("max_event", None)

        try:
            run_number = int(run_number)
            if run_number <= 0:
                raise RuntimeError("Run 번호는 양수여야 합니다")
        except (TypeError, ValueError):
            raise RuntimeError(f"잘못된 Run 번호: {run_number}")

        if method not in ('PeakADC', 'IntADC'):
            raise RuntimeError(f"잘못된 method: {method} (허용: IntADC, PeakADC)")
        if type_ not in ('full', 'heatmap', 'module', 'single'):
            raise RuntimeError(f"잘못된 type: {type_} (허용: full, heatmap, module, single)")

        if not os.path.exists(MONIT_EXECUTABLE):
            raise RuntimeError(f"monit 실행파일을 찾을 수 없습니다: {MONIT_EXECUTABLE}")
        if not os.path.exists(CONFIG_YML_PATH):
            raise RuntimeError(f"설정 파일을 찾을 수 없습니다: {CONFIG_YML_PATH}")

        # heatmap과 module 유형은 MCPPMT 모듈을 사용한다.
        if type_ in ('heatmap', 'module'):
            module_str = modules[0] if modules else "MCPPMT"
        else:
            module_str = ""

        try:
            output_lines = []
            output_lines.append("📊 DQM Plot 생성 시작")
            output_lines.append(f"🔢 Run Number: {run_number}")
            output_lines.append(f"📈 Method: {method}")
            output_lines.append(f"🗂️  Type: {type_}" + (f" · Module: {module_str}" if module_str else "") + (f" · Channels: {' '.join(modules)}" if type_ == "single" and modules else ""))
            if max_event:
                output_lines.append(f"🔢 Max Event: {max_event}")
            else:
                output_lines.append(f"🔢 Max Event: 전체 (all events)")
            output_lines.append("")

            output_lines.append("⚙️  C++ monit 실행 중...")

            if type_ in ('heatmap', 'module'):
                cmd_modules = [module_str]
            elif type_ == "single" and modules:
                cmd_modules = modules
            else:
                cmd_modules = None

            if max_event is not None:
                try:
                    max_event = int(max_event)
                except (TypeError, ValueError):
                    output_lines.append(f"⚠️  잘못된 max_event 값: {max_event}, 무시하고 계속 진행")
                    max_event = None

            cmd = build_monit_command(
                run_number,
                type_=type_,
                method=method,
                modules=cmd_modules,
                max_event=max_event,
            )

            result = subprocess.run(
                cmd,
                cwd=str(DQM_DIR),
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:
                output_lines.append(f"⚙️  monit 종료 (Exit Code: {result.returncode})")
                if result.stderr and result.stderr.strip():
                    output_lines.append(f"⚠️  stderr: {result.stderr.strip()[:400]}")
                elif result.stdout and result.stdout.strip():
                    output_lines.append(f"📄 stdout: {result.stdout.strip()[-300:]}")
            else:
                output_lines.append("✅ monit 정상 종료")

            expected = root_filename(run_number, type_, method, module_str)
            if not (OUTPUT_DIR / expected).exists():
                # single 유형의 다른 접미사도 허용한다.
                root_pattern = f"Run{run_number}_{type_}_{method}*.root"
                matches = list(OUTPUT_DIR.glob(root_pattern))
                if matches:
                    expected = matches[0].name
                else:
                    raise RuntimeError("ROOT 파일이 생성되지 않았습니다")

            output_lines.append(f"📁 ROOT 파일: {expected}")
            output_lines.append("")
            output_lines.append("✅ DQM Plot 생성 완료!")

            return "\n".join(output_lines)

        except RuntimeError:
            raise
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Plot 생성 타임아웃 (10분 초과) — Run {run_number}의 데이터가 너무 큽니다."
            )
        except Exception as e:
            raise RuntimeError(f"Plot 생성 중 오류: {str(e)}") from e
