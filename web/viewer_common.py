#!/usr/bin/env python3
"""전체 서버와 최소 서버가 공유하는 HV·DQM 뷰어 라우트."""

import asyncio
import json
import os
import re
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from tools.config_loader import CONFIG_FILE, PROJECT_ROOT
from tools.dqm_tool import DQM_DIR, MONIT_BIN, OUTPUT_DIR as DQM_OUTPUT_DIR
from tools.dqm_tool import build_monit_command, kill_process_group
from tools.hv_control_tool import HVControlTool


# 뷰어 경로.
STATIC_DIR = Path(__file__).parent / "static"


def mount_viewer_static(app) -> None:
    """Mount the static dirs the viewer pages need (/static, /dqm-output, /jsroot).

    Called by both server.py and min_server.py so neither can forget one.
    server.py mounts its extra /plots dir separately.
    """
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    # monit이 생성한 캔버스와 ROOT 파일.
    app.mount("/dqm-output", StaticFiles(directory=str(DQM_OUTPUT_DIR)), name="dqm_output")
    # DQM에 포함된 JSROOT 번들.
    app.mount("/jsroot", StaticFiles(directory=str(DQM_DIR)), name="jsroot")


router = APIRouter()


# DQM 출력 파일명 파싱.
# Bundled ROOT file:  Run<N>_<type>_<method>[_<module>][_AuxCut].root
#   type   = full | heatmap | module | single
#   method = IntADC | PeakADC | AvgTimeStruc | ...   (no underscore)
#   module = MCPPMT | M1 | All | ...  (optional; absent for "full")
# Single-waveform:    Run<N>_SingleWaveform.gif
_DQM_ROOT_RE = re.compile(r'^Run(\d+)_([^_]+)_([^_]+)(?:_(.+))?$')


def _parse_dqm_file(p):
    """Parse one DQM output file (.root bundle or _SingleWaveform.gif) into a
    descriptor, or None if it doesn't match the DQM naming scheme. Each file is
    a self-contained bundle; individual canvases are enumerated client-side from
    the ROOT file's TKeys (JSROOT.openFile), so there is no per-canvas listing."""
    name = p.name
    stem = p.stem

    # 단일 파형 애니메이션 GIF.
    if name.startswith("Run") and name.endswith("_SingleWaveform.gif"):
        m = re.match(r'^Run(\d+)_SingleWaveform$', stem)
        if not m:
            return None
        return {
            "filename": name,
            "run_number": int(m.group(1)),
            "type": "single_waveform",
            "method": "",
            "module": "",
            "auxcut": False,
            "kind": "gif",
            "mtime": int(p.stat().st_mtime * 1000),
        }

    if not name.endswith(".root"):
        return None

    auxcut = stem.endswith("_AuxCut")
    if auxcut:
        stem = stem[:-len("_AuxCut")]

    # WC와 호도스코프가 포함된 AUX 번들.
    m_aux = re.match(r'^Run(\d+)_AUX$', stem)
    if m_aux:
        return {
            "filename": name,
            "run_number": int(m_aux.group(1)),
            "type": "AUX",
            "method": "",
            "module": "",
            "auxcut": auxcut,
            "kind": "root",
            "mtime": int(p.stat().st_mtime * 1000),
        }

    m = _DQM_ROOT_RE.match(stem)
    if not m:
        return None
    return {
        "filename": name,
        "run_number": int(m.group(1)),
        "type": m.group(2),
        "method": m.group(3),
        "module": m.group(4) or "",
        "auxcut": auxcut,
        "kind": "root",
        "mtime": int(p.stat().st_mtime * 1000),
    }


@router.get("/api/dqm/runs")
async def api_dqm_runs():
    """List all runs available in the DQM output directory, grouped by run number.
    Each entry lists the run's output FILES (one .root bundle per type/method,
    plus the single-waveform gif), not individual canvases."""
    runs: dict[int, list] = {}
    for p in sorted(DQM_OUTPUT_DIR.glob("Run*_*")):
        d = _parse_dqm_file(p)
        if not d:
            continue
        runs.setdefault(d["run_number"], []).append(d)
    result = []
    for run_num in sorted(runs.keys(), reverse=True):
        files = runs[run_num]
        methods = sorted(set(f["method"] for f in files if f["method"]))
        has_auxcut = any(f["auxcut"] for f in files)
        result.append({
            "run_number": run_num,
            "methods": methods,
            "auxcut": has_auxcut,
            "count": len(files),
            "files": files,
        })
    return result


# 뷰어 페이지.
@router.get("/dqm/freeform")
async def dqm_freeform():
    """Standalone JSROOT viewer: list all canvases for a run, click to draw.
    Open in a separate window for the dual-monitor workflow."""
    return FileResponse(str(STATIC_DIR / "dqm_freeform.html"))


@router.get("/hv/check")
async def hv_check_page():
    """Standalone HV status viewer page."""
    return FileResponse(str(STATIC_DIR / "hv_check.html"))


# HV API.
@router.get("/api/hv/status-all")
async def api_hv_status_all(expert: bool = False):
    """Fetch HV status for all channels using HVControlTool.

    expert=True: try extended fields (ramp up/down/max) as well.
    """
    def _blocking_status():
        tool = HVControlTool()
        if not expert:
            result = tool.execute({"command": "status", "channels": "all"})
            return {"ok": True, "output": result, "expert": False}

        # 전문가 모드는 모든 필드를 한 번에 조회한다.
        if not tool._ensure_connection():
            return {"ok": False, "error": "HV SSH connection failed", "status": 500}

        cmd = "./HVWrappdemo --ch all --Status --VMon --IMon --V0Set --I0Set --RUp --RDWn --SVMax"
        stdout, stderr = tool._run_remote_command(cmd)
        if not stdout or not stdout.strip():
            return {"ok": False, "error": (stderr.strip() if stderr else "No output"),
                    "command": cmd, "status": 500}

        lines = [
            "📊 HV Status Query (Expert)",
            "📋 Request: Channels all",
            f"💻 Command: {cmd}",
            "",
            "📄 Output:",
            *stdout.strip().split('\n'),
        ]
        if stderr and stderr.strip():
            lines.extend(["", "⚠️ Stderr:", *stderr.strip().split('\n')])
        return {"ok": True, "output": "\n".join(lines), "expert": True}

    try:
        # blocking SSH는 event loop를 막지 않도록 worker thread에서 실행한다.
        result = await asyncio.to_thread(_blocking_status)
        if not result.get("ok"):
            return JSONResponse(result, status_code=result.pop("status", 500))
        return result
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/api/hv/hodoscope")
async def api_hv_hodoscope():
    """Return current hodoscope HV setting read from the DAQ set file."""
    try:
        from tools.hodoscope_hv_tool import read_hv_from_setfile
        hv = await asyncio.to_thread(read_hv_from_setfile)
        if hv is None:
            return JSONResponse({"ok": False, "error": "Set file을 읽을 수 없습니다."}, status_code=500)
        return {"ok": True, "hv": hv}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


class HvSetRequest(BaseModel):
    command: str           # "voltage" | "on" | "off" | "i0set" | "svmax" | "rup" | "rdown" | "name"
    channels: object       # str | list
    voltage: float = None
    current: float = None
    svmax: float = None
    rup: float = None
    rdown: float = None
    name: str = None


# HV 명령을 직렬 실행한다.
_hv_cmd_lock = asyncio.Lock()


@router.post("/api/hv/set")
async def api_hv_set(req: HvSetRequest):
    async with _hv_cmd_lock:
        try:
            tool = HVControlTool()
            params: dict = {"command": req.command, "channels": req.channels}
            if req.command == "voltage":
                if req.voltage is None:
                    return JSONResponse({"ok": False, "error": "voltage 값이 필요합니다"}, status_code=400)
                params["voltage"] = req.voltage
            if req.command == "i0set":
                if req.current is None:
                    return JSONResponse({"ok": False, "error": "current 값이 필요합니다"}, status_code=400)
                params["command"] = "current"
                params["current"] = req.current
            if req.command == "svmax":
                if req.svmax is None:
                    return JSONResponse({"ok": False, "error": "svmax 값이 필요합니다"}, status_code=400)
                params["svmax"] = req.svmax
            if req.command == "rup":
                if req.rup is None:
                    return JSONResponse({"ok": False, "error": "rup 값이 필요합니다"}, status_code=400)
                params["rup"] = req.rup
            if req.command == "rdown":
                if req.rdown is None:
                    return JSONResponse({"ok": False, "error": "rdown 값이 필요합니다"}, status_code=400)
                params["rdown"] = req.rdown
            if req.command == "name":
                if not req.name:
                    return JSONResponse({"ok": False, "error": "name 값이 필요합니다"}, status_code=400)
                params["name"] = req.name
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, tool.execute, params)
            return {"ok": True, "output": result}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/api/hv/expert-metrics")
async def api_hv_expert_metrics():
    """Return only expert metrics (RampUp/RampDown/Max) for all channels.

    This is intentionally separate from /api/hv/status-all so the frontend can
    refresh ramp/max less frequently than the main status.
    """
    try:
        tool = HVControlTool()

        if not tool._ensure_connection():
            return JSONResponse({"ok": False, "error": "HV SSH connection failed"}, status_code=500)

        # CAEN 래퍼에서 사용하는 매개변수명.
        #  - Ramp up:   RUp
        #  - Ramp down: RDWn
        #  - Max:       SVMax
        rup_cmd = "./HVWrappdemo --ch all --RUp"
        rdown_cmd = "./HVWrappdemo --ch all --RDWn"
        vmax_cmd = "./HVWrappdemo --ch all --SVMax"

        def _run(cmd: str):
            stdout, stderr = tool._run_remote_command(cmd)
            return {
                "ok": bool(stdout and stdout.strip()),
                "command": cmd,
                "output": stdout.strip() if stdout else "",
                "stderr": stderr.strip() if stderr else "",
            }

        return {
            "ok": True,
            "expert_outputs": {
                "rup": _run(rup_cmd),
                "rdown": _run(rdown_cmd),
                "vmax": _run(vmax_cmd),
            },
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# DQM monit 실행 요청 모델.
class MonitRequest(BaseModel):
    run_number: int
    type: str = "full"
    method: str = "IntADC"
    modules: List[str] = []
    max_event: Optional[int] = None
    flags: List[str] = []
    # AUX 컷 범위: none, WC 또는 WCHodo.
    aux_cut_mode: Optional[str] = None
    # AUX 플롯 대상: WC, Hodo 또는 WCHodo.
    aux_mode: Optional[str] = None


# 자유 실행 DQM 프로세스 추적.
_freeform_live_proc: Optional[subprocess.Popen] = None
_freeform_live_run: Optional[int] = None
_freeform_live_lock = threading.Lock()
# 실시간 로그는 약 6시간 분량을 메모리에 보관한다.
_freeform_live_log: deque = deque(maxlen=200_000)
_freeform_live_log_lock = threading.Lock()
# 누적 로그 번호는 deque 순환과 무관하게 계속 증가한다.
_freeform_live_log_seq: int = 0

# 일반 실행과 실시간 실행의 프로세스를 별도로 추적한다.
_freeform_blocking_proc: Optional[subprocess.Popen] = None
_freeform_blocking_run: Optional[int] = None
_freeform_blocking_lock = threading.Lock()


_ANSI_ESC = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (colours, cursor moves, etc.)."""
    return _ANSI_ESC.sub('', text)


def _read_live_stdout(proc: "subprocess.Popen") -> None:
    """monit 출력을 정리해 실시간 로그 큐에 누적한다."""
    global _freeform_live_log_seq
    try:
        for raw in proc.stdout:
            line = _strip_ansi(raw.rstrip("\n")).lstrip("\r")
            if line:
                with _freeform_live_log_lock:
                    _freeform_live_log.append(line)
                    _freeform_live_log_seq += 1
    except Exception:
        pass


@router.post("/api/dqm/run-monit")
async def api_run_monit(req: MonitRequest, request: Request):
    """Execute monit with custom parameters and return generated canvases."""
    global _freeform_live_proc, _freeform_live_run, _freeform_live_log_seq

    deny = _check_action_password(request)
    if deny:
        return deny

    if not MONIT_BIN.exists():
        return JSONResponse({"error": f"monit not found: {MONIT_BIN}"}, status_code=500)

    cmd = build_monit_command(
        req.run_number,
        type_=req.type,
        method=req.method,
        modules=req.modules,
        max_event=req.max_event,
        flags=req.flags,
        aux_cut_mode=req.aux_cut_mode,
        aux_mode=req.aux_mode,
    )

    generated_cmd = " ".join(cmd)

    # 실시간 모드는 백그라운드 프로세스 그룹으로 실행한다.
    if "LIVE" in req.flags:
        with _freeform_live_lock:
            # 기존 실시간 실행을 먼저 종료한다.
            if _freeform_live_proc is not None:
                kill_process_group(_freeform_live_proc, grace=2)

            with _freeform_live_log_lock:
                _freeform_live_log.clear()
                _freeform_live_log_seq = 0

            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(DQM_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setpgrp,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError as e:
                return JSONResponse({"error": str(e), "command": generated_cmd}, status_code=500)

            _freeform_live_proc = proc
            _freeform_live_run = req.run_number

            threading.Thread(
                target=_read_live_stdout, args=(proc,),
                daemon=True, name="FreeformLiveLog",
            ).start()

        return {
            "command": generated_cmd,
            "live": True,
            "run_number": req.run_number,
            "pid": proc.pid,
            "canvases": [],
        }

    # 일반 모드는 요청을 유지하며 출력을 실시간 로그에 추가한다.
    global _freeform_blocking_proc, _freeform_blocking_run

    with _freeform_live_log_lock:
        _freeform_live_log.clear()
        _freeform_live_log_seq = 0

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(DQM_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setpgrp,  # 중지할 수 있도록 별도 프로세스 그룹을 만든다.
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e), "command": generated_cmd}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e), "command": generated_cmd}, status_code=500)

    with _freeform_blocking_lock:
        _freeform_blocking_proc = proc
        _freeform_blocking_run = req.run_number

    reader = threading.Thread(
        target=_read_live_stdout, args=(proc,),
        daemon=True, name="FreeformBlockingLog",
    )
    reader.start()

    loop = asyncio.get_event_loop()
    try:
        # 장시간 실행은 시간 제한 없이 사용자 중지만 허용한다.
        exit_code = await loop.run_in_executor(None, proc.wait)
    except Exception as e:
        with _freeform_blocking_lock:
            if _freeform_blocking_proc is proc:
                _freeform_blocking_proc = None
                _freeform_blocking_run = None
        return JSONResponse({"error": str(e), "command": generated_cmd}, status_code=500)

    reader.join(timeout=2)

    with _freeform_blocking_lock:
        if _freeform_blocking_proc is proc:
            _freeform_blocking_proc = None
            _freeform_blocking_run = None

    # 응답 본문에는 실시간 로그의 마지막 부분을 포함한다.
    with _freeform_live_log_lock:
        _tail = list(_freeform_live_log)[-50:]
    output = "\n".join(_tail)

    # 실행 조건에 맞는 ROOT 출력 번들을 수집한다.
    auxcut_set = "AUXcut" in req.flags
    files = []
    seen = set()
    for p in sorted(DQM_OUTPUT_DIR.glob(f"Run{req.run_number}_{req.type}_{req.method}*.root")):
        d = _parse_dqm_file(p)
        if d and d["auxcut"] == auxcut_set and d["filename"] not in seen:
            files.append(d)
            seen.add(d["filename"])

    # AUX 실행이면 WC·호도스코프 번들도 수집한다.
    if "AUX" in req.flags:
        for p in sorted(DQM_OUTPUT_DIR.glob(f"Run{req.run_number}_AUX*.root")):
            d = _parse_dqm_file(p)
            if d and d["auxcut"] == auxcut_set and d["filename"] not in seen:
                files.append(d)
                seen.add(d["filename"])

    return {
        "command": generated_cmd,
        "exit_code": proc.returncode,
        "output": output[-500:] if len(output) > 500 else output,
        "files": files,
    }


@router.post("/api/dqm/kill-live")
async def api_kill_live():
    """Force-stop the freeform LIVE monit process, same as Kill-All.

    Sends SIGTERM to the process group (spawned with setpgrp), waits a short
    grace period, then escalates to SIGKILL. No sentinel-file graceful
    shutdown — this terminates immediately like the Kill-All button.
    """
    global _freeform_live_proc, _freeform_live_run

    with _freeform_live_lock:
        proc = _freeform_live_proc
        run_number = _freeform_live_run

        if proc is None or proc.poll() is not None:
            _freeform_live_proc = None
            _freeform_live_run = None
            return {"ok": True, "msg": "no live process running"}

        sentinel = DQM_OUTPUT_DIR / f"Run{run_number}_END"

        def _kill_now():
            kill_process_group(proc, grace=2)
            try:
                sentinel.unlink(missing_ok=True)
            except OSError:
                pass

        await asyncio.get_event_loop().run_in_executor(None, _kill_now)

        _freeform_live_proc = None
        _freeform_live_run = None

    return {"ok": True, "run_number": run_number}


@router.post("/api/dqm/kill-blocking")
async def api_kill_blocking():
    """실행 중인 일반 monit 프로세스 그룹을 즉시 종료한다."""
    with _freeform_blocking_lock:
        proc = _freeform_blocking_proc
        run_number = _freeform_blocking_run

    if proc is None or proc.poll() is not None:
        return {"ok": True, "msg": "no blocking process running"}

    await asyncio.get_event_loop().run_in_executor(
        None, lambda: kill_process_group(proc, grace=2)
    )

    return {"ok": True, "run_number": run_number}


def _enumerate_monit_processes() -> list[dict]:
    """웹 서버를 제외한 실행 중인 monit 프로세스를 찾는다."""
    try:
        import psutil
    except ImportError:
        return []

    own_pid = os.getpid()
    procs: list[dict] = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "username"]):
        try:
            info = p.info
            pid = info.get("pid")
            if pid is None or pid == own_pid:
                continue
            cmdline = info.get("cmdline") or []
            if not cmdline:
                continue
            argv0 = cmdline[0]
            name = info.get("name") or ""
            is_relative_monit = argv0 == "./monit"
            is_absolute_monit = (
                os.path.basename(argv0) == "monit" and name == "monit"
            )
            if not (is_relative_monit or is_absolute_monit):
                continue
            procs.append({
                "pid": pid,
                "username": info.get("username") or "",
                "cmdline": " ".join(cmdline),
                "argv0": argv0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs


@router.get("/api/dqm/find-monit-processes")
async def api_find_monit_processes():
    """List every running ./monit process for the confirmation modal."""
    procs = _enumerate_monit_processes()
    return {"ok": True, "count": len(procs), "processes": procs}


def _get_action_password() -> str:
    """Read the password gating the EXECUTE / Kill-All ./monit buttons.

    Read fresh from config_general.yml on each call so the operator can
    change it without restarting the server. Missing/blank key -> "".
    """
    import yaml
    try:
        with open(CONFIG_FILE) as f:
            cfg = yaml.safe_load(f) or {}
        return str(cfg.get("dqm_action_password") or "")
    except Exception:
        return ""


def _check_action_password(request: Request) -> Optional[JSONResponse]:
    """Return a 403 JSONResponse if the X-DQM-Password header is wrong.

    Returns None when the password matches, so callers do:
        deny = _check_action_password(request)
        if deny: return deny
    """
    expected = _get_action_password()
    supplied = request.headers.get("X-DQM-Password", "")
    if not expected or supplied != expected:
        return JSONResponse({"error": "비밀번호가 올바르지 않습니다."}, status_code=403)
    return None


@router.post("/api/dqm/verify-password")
async def api_verify_password(request: Request):
    """Verify the ./monit action password for the UI's one-time gate."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    expected = _get_action_password()
    supplied = str((body or {}).get("password", ""))
    return {"ok": bool(expected) and supplied == expected}


@router.post("/api/dqm/kill-all-monit")
async def api_kill_all_monit(request: Request):
    """모든 monit 프로세스를 종료하고 PID별 결과를 반환한다."""
    deny = _check_action_password(request)
    if deny:
        return deny

    try:
        import psutil
    except ImportError:
        return {"ok": False, "error": "psutil not available", "killed_count": 0}

    own_pid = os.getpid()
    targets = _enumerate_monit_processes()

    killed: list[int] = []
    failed: list[dict] = []

    for proc_info in targets:
        pid = proc_info["pid"]
        if pid == own_pid:
            continue
        try:
            p = psutil.Process(pid)
        except psutil.NoSuchProcess:
            continue

        try:
            p.send_signal(signal.SIGTERM)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            failed.append({"pid": pid, "reason": str(e)})
            continue

        try:
            p.wait(timeout=2.0)
            killed.append(pid)
            continue
        except psutil.TimeoutExpired:
            pass

        try:
            p.send_signal(signal.SIGKILL)
            p.wait(timeout=2.0)
            killed.append(pid)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied) as e:
            failed.append({"pid": pid, "reason": str(e)})

    msg = f"Killed {len(killed)} ./monit process(es)"
    if failed:
        msg += f"; {len(failed)} failed"

    return {
        "ok": True,
        "message": msg,
        "killed_count": len(killed),
        "failed_count": len(failed),
        "killed_pids": killed,
        "failed": failed,
    }


@router.get("/api/dqm/live-status")
async def api_live_status():
    """Return whether a freeform LIVE process is currently running."""
    with _freeform_live_lock:
        proc = _freeform_live_proc
        run_number = _freeform_live_run
        alive = proc is not None and proc.poll() is None
    return {"alive": alive, "run_number": run_number if alive else None}


@router.get("/api/dqm/live-log")
async def api_live_log(since: int = 0):
    """지정한 순번 이후의 monit 실시간 로그를 반환한다."""
    with _freeform_live_log_lock:
        lines = list(_freeform_live_log)
        total = _freeform_live_log_seq
    # deque에 남아 있는 첫 로그의 직전 번호.
    first_seq = total - len(lines)
    if since >= total:
        new_lines: list = []
    elif since <= first_seq:
        # 클라이언트가 너무 뒤처지면 남아 있는 로그를 모두 반환한다.
        new_lines = lines
    else:
        new_lines = lines[since - first_seq:]
    return {"lines": new_lines, "total": total}


@router.get("/api/dqm/live-log/stream")
async def api_live_log_stream(request: Request, since: int = 0):
    """monit 로그를 Server-Sent Events로 실시간 전송한다."""
    # EventSource 재연결 시 마지막 이벤트 ID부터 전송한다.
    last_id = request.headers.get("last-event-id")
    if last_id is not None:
        try:
            since = int(last_id)
        except ValueError:
            pass

    async def _events():
        sent = since
        # 약 15초마다 하트비트를 보내 연결 상태를 확인한다.
        idle_ticks = 0
        while True:
            with _freeform_live_log_lock:
                lines = list(_freeform_live_log)
                total = _freeform_live_log_seq
            first_seq = total - len(lines)
            if sent < total:
                if sent <= first_seq:
                    new_lines = lines
                else:
                    new_lines = lines[sent - first_seq:]
                sent = total
                payload = json.dumps({"lines": new_lines, "total": total})
                yield f"id: {total}\ndata: {payload}\n\n"
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks >= 150:  # 0.1초 간격 기준 약 15초.
                    idle_ticks = 0
                    yield ": keep-alive\n\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
