#!/usr/bin/env python3
"""
Hodoscope HV Tool
-----------------
Set file  (single value)  → read via NFS/Thunderbolt mount, write via SSH to Mac Studio.
Run log   (4 actual values) → parsed separately by run_log_tool after each DAQ run.

Set file format (one relevant line):
  hv <value>        e.g.  hv 4.5   or   hv 0.0
"""

import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from .base_tool import BaseTool
from .config_loader import get_path_config
from .ssh_utils import run_studio_ssh


def _get_setfile_path() -> str:
    return get_path_config("HodoscopeSetFile")


def _get_logdir_path() -> str:
    return get_path_config("DaqLogDir")


# 실행 로그에서도 사용하는 공개 보조 함수.

def read_hv_from_setfile() -> Optional[float]:
    """Return the single 'hv <value>' from the set file, or None on error."""
    try:
        for line in Path(_get_setfile_path()).read_text().splitlines():
            m = re.match(r'^\s*hv\s+([+-]?\d+(?:\.\d+)?)', line)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return None


def read_hv_from_log(run_num: str) -> Optional[Dict[int, float]]:
    """
    Parse log_set_anc_{run_num}.log → {1: v1, 2: v2}.
    Expected line format: DAQ[N] high voltage ch1 = 46.832615 V
    Returns None if file not found or no HV lines.
    """
    try:
        log_path = Path(_get_logdir_path()) / f"log_set_anc_{run_num}.log"
        result = {}
        for line in log_path.read_text().splitlines():
            m = re.search(r'high voltage ch(\d)\s*=\s*([+-]?\d+(?:\.\d+)?)', line, re.IGNORECASE)
            if m:
                ch = int(m.group(1))
                val = float(m.group(2))
                result[ch] = val
        return result if result else None
    except Exception:
        return None


def write_hv_via_ssh(value: float) -> str:
    """Replace 'hv <old>' with 'hv <new>' in the set file on Mac Studio via SSH."""
    # MacBook 마운트 경로를 Mac Studio 경로로 바꾼다.
    remote_path = get_path_config("HodoscopeSetFile").replace(
        "/Volumes/yhep", "/Users/yhep"
    )

    value_str = f"{value:.6g}"   # 불필요한 뒤쪽 0을 생략한다.

    sed_cmd = f"sed -i '' 's/^hv [^ ]*/hv {value_str}/' {remote_path}"
    result = run_studio_ssh(sed_cmd)
    if result.returncode != 0:
        raise RuntimeError(
            f"SSH sed failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return f"✅ Hodoscope HV → {value_str} V (set file updated)"


# 도구 클래스.

class HodoscopeHVTool(BaseTool):
    """Read / write hodoscope HV via the DAQ set file."""

    def __init__(self):
        super().__init__(
            name="hodoscope_hv_tool",
            description="Read or modify hodoscope HV in the DAQ set file",
        )

    def execute(self, params: Dict[str, Any]) -> str:
        command = params.get("command", "read")

        if command == "read":
            hv = read_hv_from_setfile()
            if hv is None:
                return "⚠️ Set file을 읽을 수 없습니다. 경로를 확인하세요."
            if hv == 0.0:
                return "📡 Hodoscope HV: 0.0 V (off)"
            return f"📡 Hodoscope HV: {hv} V"

        if command == "write":
            value = params.get("value")
            if value is None:
                raise RuntimeError("'value' 파라미터가 필요합니다.")
            value = float(value)
            if value < 0:
                raise RuntimeError("HV 값은 0 이상이어야 합니다.")
            return write_hv_via_ssh(value)

        raise RuntimeError(f"지원하지 않는 command: {command}  (read | write)")
