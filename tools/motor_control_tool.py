#!/usr/bin/env python3
"""Thin helper: build and run azd_kren commands. All settings from config_general.yml Motor section."""

import subprocess
from tools.config_loader import load_config


def _cfg() -> dict:
    cfg = load_config()
    m = cfg.get("Motor")
    if not m:
        raise RuntimeError("config_general.yml에 'Motor' 섹션이 없습니다.")
    return m


def _run_cmd(cmd: list) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return True, r.stdout.strip() or "완료"
        return False, r.stderr.strip() or "unknown error"
    except subprocess.TimeoutExpired:
        return False, "Motor move timed out (120 s)"
    except FileNotFoundError:
        return False, f"azd_kren not found: {cmd[0]}"


def _base_cmd(m: dict) -> list:
    return [
        m["EZSBinary"],
        "--ip",    m["IP"],
        "--port",  str(m["Port"]),
        "--speed", str(m["Speed"]),
        "--acc",   str(m["Acc"]),
        "--dec",   str(m["Dec"]),
    ]


def move_x(x_scan: float) -> tuple[bool, str]:
    """절대 이동: azd_kren --moveto <mm>"""
    m = _cfg()
    target_mm = x_scan * m["UnitScale"]
    cmd = _base_cmd(m) + ["--moveto", f"{target_mm:.3f}"]
    ok, msg = _run_cmd(cmd)
    return (True, f"X축 이동 완료: {target_mm:.3f} mm") if ok else (False, msg)



def get_position() -> tuple[bool, str]:
    """현재 위치 읽기: azd_kren --pos"""
    m = _cfg()
    cmd = [m["EZSBinary"], "--ip", m["IP"], "--port", str(m["Port"]), "--pos"]
    return _run_cmd(cmd)


def alarm_reset() -> tuple[bool, str]:
    """모터 알람 리셋: azd_kren --alarm-reset (범위 초과/폴트 후 재사용 가능하게)"""
    m = _cfg()
    cmd = [m["EZSBinary"], "--ip", m["IP"], "--port", str(m["Port"]), "--alarm-reset"]
    ok, msg = _run_cmd(cmd)
    return (True, "모터 알람 리셋 완료. 이제 다시 이동할 수 있습니다.") if ok else (False, f"알람 리셋 실패: {msg}")
