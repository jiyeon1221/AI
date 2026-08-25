#!/usr/bin/env python3
"""
Web Server
----------
FastAPI + WebSocket bridge between browser and AgentRunner.
"""

import asyncio
import queue
import re
import json
import threading
import tempfile
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from agents.agent_runner import AgentRunner
# HV와 DQM 뷰어 라우트는 viewer_common에서 공유한다.
from web import viewer_common
from web.viewer_common import STATIC_DIR, PROJECT_ROOT, DQM_DIR, DQM_OUTPUT_DIR, _parse_dqm_file


# FastAPI 앱.
app = FastAPI(title="autoTB Control Panel")

MANIFEST_PATH = PROJECT_ROOT / "dqm_dashboards.yml"
PLOT_DIR = Path(tempfile.gettempdir())

# 공용 정적 경로와 전체 서버의 플롯 경로를 등록한다.
viewer_common.mount_viewer_static(app)
app.mount("/plots", StaticFiles(directory=str(PLOT_DIR)), name="plots")

# 공용 뷰어, DQM, HV 라우트를 등록한다.
app.include_router(viewer_common.router)

runner = AgentRunner()

# 서버 수명 동안 유지하는 BrainAgent.
@app.on_event("startup")
def _startup_brain():
    """Load BrainAgent at server start so it's ready for ad-hoc requests."""
    try:
        runner.start_brain(use_base_model=False)
        print("✅ BrainAgent loaded and ready")
    except Exception as e:
        print(f"⚠️ BrainAgent failed to load (will use fallback): {e}")

from web.whisper_prompt import get_model as _get_whisper, PROMPT as _WHISPER_PROMPT, fix_physics as _fix_physics


# 명령 파싱 함수.

# 수정 가능한 실행 로그 열의 표시명.
_COL_DISPLAY = {
    "program":       "Program (프로그램)",
    "notes":         "Notes (노트)",
    "config":        "Config (설정)",
    "beam_energy":   "Beam Energy (빔 에너지)",
    "beam_type":     "Beam Type (빔 타입)",
    "trigger_setup": "Trigger Setup (트리거)",
    "hv_drc":        "HV DRC",
    "hv_aux":        "HV Aux",
}

_COL_KEYWORDS = {
    "program":       [r'프로그램', r'program'],
    "notes":         [r'노트', r'note', r'비고', r'메모'],
    "config":        [r'config', r'설정'],
    "beam_energy":   [r'빔\s*에너지', r'beam.?energy', r'에너지'],
    "beam_type":     [r'빔\s*타입', r'beam.?type', r'타입'],
    "trigger_setup": [r'트리거', r'trigger'],
    "hv_drc":        [r'hv\s*drc', r'drc'],
    "hv_aux":        [r'hv\s*aux', r'aux'],
}

_COL_ASK_MSG = (
    "어느 열에 추가할까요?\n"
    "  program / notes / config / beam_energy / beam_type\n"
    "  trigger_setup / hv_drc / hv_aux"
)

def _parse_log_column(text: str):
    """Return column key if a known column is mentioned, else None."""
    t = text.lower()
    for col, patterns in _COL_KEYWORDS.items():
        if any(re.search(p, t) for p in patterns):
            return col
    return None




def _extract_log_value(text: str, column: str):
    """
    Try to extract the value to write from the original command.
    e.g. "run 12345 프로그램에 EM 추가해줘" → "EM"
    Returns None if not extractable.
    """
    patterns = _COL_KEYWORDS.get(column, [])
    for kw in patterns:
        m = re.search(
            rf'{kw}\s*(?:에|으로|에다)?\s+(.+?)\s*(?:추가|add|입력|써|넣|update)',
            text, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()
    return None


# 에이전트 없이 실행하는 직접 도구 명령.

def _parse_direct_command(text: str):
    """
    Parse simple direct commands when no agent is running.
    Returns a dict describing the command, or None.
    """
    t = text.strip()

    # 실행 번호와 열 키워드가 있으면 로그 수정으로 해석한다.
    log_kw = r'로그|log|노트|note|비고|메모|추가|기록|수정|update|program|프로그램|config|설정|에너지|energy|트리거|trigger|hv'
    m = re.search(rf'(?:run\s*)?(\d{{4,6}}).*?(?:{log_kw})', t, re.IGNORECASE)
    if m and not re.search(r'waveform|wave|파형|plot|그래프|그려|peakadc|intadc', t, re.IGNORECASE):
        run_number = int(m.group(1))
        column = _parse_log_column(t)
        value = _extract_log_value(t, column) if column else None
        return {"tool": "log_update", "run_number": run_number, "column": column, "value": value}


    # 이벤트 수와 실행 표현이 있으면 DAQ 요청으로 해석한다.
    m = re.search(r'(?:run\s+)?(\d+)\s*(?:개|events?)', t, re.IGNORECASE)
    if m:
        return {"tool": "daq_run", "events": int(m.group(1))}

    return None


def _run_direct_tool(cmd: dict, output_queue: queue.Queue, stop_event: threading.Event):
    """Execute a direct tool call in a background thread."""
    from agents.io_handler import WebSocketIO
    import queue as q

    dummy_input = q.Queue()
    io = WebSocketIO(dummy_input, output_queue, stop_event)

    try:
        if cmd["tool"] == "daq_run":
            from tools.daq_tool import DAQRunTool
            io.send_status("DAQ 실행 중...")
            DAQRunTool().execute({"events": cmd["events"]}, line_callback=io.send_tool_output)
            io.send_status("대기 중")


    except Exception as e:
        output_queue.put({"type": "error", "content": str(e)})
        output_queue.put({"type": "status", "content": "오류 발생"})


def _update_run_log(run_number: int, column: str, value: str,
                    output_queue: queue.Queue, stop_event: threading.Event):
    """Update a single column of a run log row in Google Sheets."""
    from agents.io_handler import WebSocketIO
    import queue as q

    dummy_input = q.Queue()
    io = WebSocketIO(dummy_input, output_queue, stop_event)

    io.send_status("로그 업데이트 중...")
    try:
        from tools.run_log_tool import RunLogTool
        result = RunLogTool().execute({"command": "update", "run_num": run_number, column: value})
        io.send_tool_output(result)
        label = _COL_DISPLAY.get(column, column)
        io.send_ai_message(f"Run {run_number}  {label} 열이 업데이트되었습니다.")
    except Exception as e:
        output_queue.put({"type": "error", "content": str(e)})
    io.send_status("대기 중")


_HELP_MSG = (
    "실행 중인 에이전트가 없습니다.\n\n"
    "직접 실행 가능한 명령:\n"
    "  • 100개 돌려줘  →  DAQ 100 events\n"
    "  • run 12345 프로그램에 EM 추가해줘  →  Google Sheets 열 업데이트\n"
    "  • run 12345 waveform 그려줘  →  Waveform 플롯\n"
    "  • run 12345 그려줘  →  플롯 종류 선택 후 그리기\n\n"
    "또는 상단 버튼으로 에이전트를 선택하세요."
)




@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    """Receive browser audio blob, run faster-whisper, return transcript."""
    data = await audio.read()
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp_path = f.name
    try:
        model = _get_whisper()
        segments, _ = model.transcribe(
            tmp_path, language="ko", beam_size=5, initial_prompt=_WHISPER_PROMPT
        )
        text = _fix_physics("".join(s.text for s in segments).strip())
        return JSONResponse({"text": text})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/status")
async def api_status():
    return {"running": runner.is_running, "brain_ready": runner.brain_ready}


@app.get("/api/dqm/manifest")
async def api_dqm_manifest():
    """Return the per-agent DQM dashboard manifest as JSON."""
    import yaml
    if not MANIFEST_PATH.exists():
        return {}
    try:
        with open(MANIFEST_PATH) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/dqm/canvases/{run_number}")
async def api_dqm_canvases(run_number: int):
    """List all DQM output files (ROOT bundles + single-waveform gif) for a run.
    Canvases inside each .root are enumerated client-side after JSROOT.openFile."""
    items = []
    for p in sorted(DQM_OUTPUT_DIR.glob(f"Run{run_number}_*")):
        d = _parse_dqm_file(p)
        if d:
            items.append(d)
    return items


@app.get("/api/motor/position")
async def api_motor_position():
    """현재 모터 X축 위치를 반환 (azd_kren --pos). DQM 패널 하단 실시간 표시용."""
    try:
        from tools.motor_control_tool import get_position
        ok, pos = await asyncio.get_event_loop().run_in_executor(None, get_position)
        return {"ok": ok, "position": pos}
    except Exception as e:
        return {"ok": False, "position": f"Error: {e}"}


# WebSocket 처리.
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # 중첩 코루틴이 공유하는 확인 버튼 상태.
    _cm = [False]       # 일반 완료 버튼.
    _hv_cm = [False]    # HV 완료·수정 버튼.
    _retry_cm = [False] # 다시 시도 버튼.

    async def pump_output():
        """
        Drain output_queue and forward to browser.
        - tool_output lines are batched per cycle to reduce send() calls
          (DAQ can produce hundreds of lines; each send() is a potential failure)
        - ai_message / plot / status / awaiting_input are sent immediately
        """
        from starlette.websockets import WebSocketState

        tool_buf = []
        tool_flush_interval = 0.5
        last_tool_flush = asyncio.get_running_loop().time()

        async def flush_tool(force: bool = False):
            nonlocal tool_buf, last_tool_flush
            if tool_buf:
                combined = "\n".join(tool_buf)
                now = asyncio.get_running_loop().time()
                is_termination = "received termination" in combined.lower()
                if not force and not is_termination and now - last_tool_flush < tool_flush_interval:
                    return
                try:
                    await ws.send_json({"type": "tool_output", "content": combined})
                except Exception:
                    pass
                # DAQ 정상 종료를 브라우저 알림 이벤트로 바꾼다.
                if is_termination:
                    try:
                        await ws.send_json({"type": "daq_complete"})
                    except Exception:
                        pass
                tool_buf = []
                last_tool_flush = now

        while True:
            if ws.client_state != WebSocketState.CONNECTED:
                break

            drained_any = False
            # 현재 큐의 메시지를 모두 처리한다.
            while True:
                try:
                    msg = runner.output_queue.get_nowait()
                    drained_any = True
                    is_brain = msg.get("source") == "brain"

                    # 완료 버튼 표시 상태를 갱신한다.
                    if msg.get("type") == "awaiting_input":
                        _cm[0] = True
                    elif msg.get("type") == "awaiting_hv_confirm":
                        _cm[0] = True
                        _hv_cm[0] = True
                    elif msg.get("type") == "awaiting_retry":
                        _cm[0] = True
                        _retry_cm[0] = True

                    if msg.get("type") == "tool_output" and not is_brain:
                        # 시나리오 도구 출력을 묶어서 전송한다.
                        tool_buf.append(msg["content"])
                        await flush_tool()
                    elif is_brain:
                        # Brain 메시지는 시나리오 버퍼 뒤에 즉시 전송한다.
                        await flush_tool(force=True)

                        out_msg = msg
                        mtype = msg.get("type")
                        # 추가 질문은 상태와 관계없이 원형 그대로 보낸다.
                        if mtype == "adhoc_confirm":
                            # 클라이언트에 시나리오 실행 여부를 전달한다.
                            out_msg = {**msg, "scenario_running": runner.is_running}
                        elif mtype in ("tool_output", "plot", "html_content"):
                            # 유휴 상태의 결과는 기본 패널로 보낸다.
                            if not runner.is_running:
                                out_msg = {k: v for k, v in msg.items()
                                           if k != "source"}

                        try:
                            await ws.send_json(out_msg)
                        except Exception:
                            pass
                        # Brain이 실행한 DAQ의 종료 알림도 감지한다.
                        if (mtype == "tool_output"
                                and "received termination" in str(msg.get("content", "")).lower()):
                            try:
                                await ws.send_json({"type": "daq_complete"})
                            except Exception:
                                pass
                        # Brain 응답 후 필요한 시나리오 확인 버튼을 다시 표시한다.
                        if (out_msg.get("type") == "ai_message"
                                and _cm[0]
                                and runner.waiting_flag.is_set()):
                            try:
                                retype = "awaiting_hv_confirm" if _hv_cm[0] else "awaiting_input"
                                await ws.send_json({"type": retype})
                            except Exception:
                                pass
                    else:
                        # 일반 메시지는 도구 출력 버퍼 뒤에 전송한다.
                        await flush_tool(force=True)
                        try:
                            await ws.send_json(msg)
                        except Exception:
                            pass
                except queue.Empty:
                    break

            # 남은 도구 출력을 전송한다.
            await flush_tool()

            if not drained_any:
                await asyncio.sleep(0.05)

    pump_task = asyncio.create_task(pump_output())

    # 여러 입력이 필요한 직접 명령의 세션 상태.
    pending: dict | None = None

    async def _send(msg_type: str, content: str):
        await ws.send_json({"type": msg_type, "content": content})

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            # 사용자 텍스트와 완료 버튼 입력.
            if msg_type == "user_input":
                content = data.get("content", "").strip()
                if runner.is_running:
                    # 완료·종료 응답은 시나리오로, 작업 중 자유 입력은 Brain으로 보낸다.
                    if runner.waiting_flag.is_set():
                        if content in ("retry", "skip") and _retry_cm[0]:
                            _cm[0] = False
                            _retry_cm[0] = False
                            runner.send_input(content)
                        elif content in ("완료", "종료", "exit"):
                            _cm[0] = False
                            _hv_cm[0] = False
                            _retry_cm[0] = False
                            runner.send_input(content)
                        elif _hv_cm[0]:
                            # HV 수정 입력은 시나리오로 보낸다.
                            runner.send_input(content)
                        elif _cm[0] and runner.brain_ready and content not in ("retry", "skip"):
                            # 확인 대기 중 자유 입력은 별도 요청으로 처리한다.
                            runner.send_adhoc(content)
                        else:
                            # 설정값 입력은 시나리오로 보낸다.
                            runner.send_input(content)
                    elif content in ("완료", "종료", "exit"):
                        runner.send_input(content)
                    elif runner.brain_ready:
                        # 별도 요청은 백그라운드 BrainAgent로 보낸다.
                        runner.send_adhoc(content)
                    else:
                        # BrainAgent가 없으면 시나리오로 전달한다.
                        runner.send_input(content)

                elif pending is not None:
                    step = pending["step"]

                    if step == "log_ask_column":
                        col = _parse_log_column(content)
                        if col is None:
                            await _send("ai_message", f"열을 인식하지 못했습니다.\n{_COL_ASK_MSG}")
                        else:
                            pending = {"step": "log_ask_value",
                                       "run_number": pending["run_number"], "column": col}
                            await _send("ai_message",
                                        f"{_COL_DISPLAY[col]} 열에 어떤 내용을 입력할까요?")

                    elif step == "log_ask_value":
                        run_number = pending["run_number"]
                        column = pending["column"]
                        pending = None
                        threading.Thread(
                            target=_update_run_log,
                            args=(run_number, column, content,
                                  runner.output_queue, runner.stop_event),
                            daemon=True,
                        ).start()


                else:
                    cmd = _parse_direct_command(content)
                    if cmd is None:
                        # 직접 해석하지 못한 명령은 BrainAgent에 맡긴다.
                        if runner.brain_ready:
                            runner.send_adhoc(content)
                            continue
                        await _send("ai_message", _HELP_MSG)

                    elif cmd["tool"] == "log_update":
                        run_number = cmd["run_number"]
                        column = cmd.get("column")
                        value = cmd.get("value")

                        if column is None:
                            # 수정할 열을 입력받는다.
                            pending = {"step": "log_ask_column", "run_number": run_number}
                            await _send("ai_message",
                                        f"Run {run_number} 로그를 수정합니다.\n{_COL_ASK_MSG}")
                        elif value is None:
                            # 열은 확인됐지만 값이 없으면 값을 입력받는다.
                            pending = {"step": "log_ask_value",
                                       "run_number": run_number, "column": column}
                            await _send("ai_message",
                                        f"{_COL_DISPLAY[column]} 열에 어떤 내용을 입력할까요?")
                        else:
                            # 열과 값이 모두 있으면 즉시 수정한다.
                            threading.Thread(
                                target=_update_run_log,
                                args=(run_number, column, value,
                                      runner.output_queue, runner.stop_event),
                                daemon=True,
                            ).start()


                    else:
                        threading.Thread(
                            target=_run_direct_tool,
                            args=(cmd, runner.output_queue, runner.stop_event),
                            daemon=True,
                        ).start()

            # 전문 에이전트 시작.
            elif msg_type == "start_agent":
                if runner.is_running:
                    await ws.send_json({
                        "type": "error",
                        "content": "다른 에이전트가 이미 실행 중입니다."
                    })
                else:
                    agent_name = data.get("agent")
                    params = data.get("params", {})
                    _cm[0] = False      # 이전 확인 상태를 초기화한다.
                    _hv_cm[0] = False
                    _retry_cm[0] = False
                    try:
                        runner.start(agent_name, params)
                        await ws.send_json({
                            "type": "status",
                            "content": f"{agent_name} 에이전트 시작됨"
                        })
                    except Exception as e:
                        await ws.send_json({"type": "error", "content": str(e)})

            # 실행 중인 에이전트 중지.
            elif msg_type == "stop_agent":
                if runner.is_running:
                    runner.stop()
                    await ws.send_json({"type": "status", "content": "에이전트 중지 요청됨"})

            # 별도 요청 확인 응답.
            elif msg_type == "adhoc_confirm":
                confirmed = bool(data.get("confirmed", False))
                runner.send_confirm(confirmed)

            # 추가 질문 응답.
            elif msg_type == "clarify_reply":
                content = data.get("content", "").strip()
                if content:
                    runner.send_clarify(content)

            # 현재 DAQ 실행 중지.
            elif msg_type == "kill_run":
                try:
                    from tools.daq_tool import WORKDIR
                    from tools.ssh_utils import run_studio_ssh
                    run_studio_ssh(f"touch {WORKDIR}/KILLME", timeout=10, check=True)
                    await ws.send_json({"type": "tool_output", "content": "🛑 KILLME 생성 → DAQ 중지 요청"})
                except Exception as e:
                    await ws.send_json({"type": "error", "content": f"KILLME 생성 실패: {e}"})

    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
