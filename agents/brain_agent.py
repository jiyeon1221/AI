#!/usr/bin/env python3
"""BrainAgent — 자연어 → tool JSON 변환 후 실행. 서버 시작부터 종료까지 상주."""

import json
import re
import time
import threading
import queue
import traceback
from typing import Dict, Any, Optional

from agents.base_agent import BaseAgent
from agents.io_handler import WebSocketIO


TOOL_LOCK_MAP = {
    "daq_run": "daq",
    "dqm_plot": None,
    "run_log": None,
    "hv_read": "hv",
    "hv_write": "hv",
    "motor_move": None,
    "motor_status": None,
    "motor_alarm_reset": None,
    "hodoscope_hv_read": None,
    "hodoscope_hv_write": None,
}

TOOLS_NEED_CONFIRM = {"daq_run", "hv_write", "hodoscope_hv_write", "motor_move"}



SYSTEM_PROMPT = """You are the Brain Agent for a test beam experiment (KEK/CERN).
Your job is to interpret the operator's ad-hoc request and call the right tool.

Available tools:
- daq_run: Run DAQ data collection. params: {"events": int}
- dqm_plot: Generate DQM plots for a run and display in the DQM panel.
  params: {"run_number": int, "method": "IntADC"|"PeakADC", "type": "full"|"heatmap"|"single", "modules": [list]}
  - type defaults to "full" (all towers + heatmap). No modules needed for full.
  - "heatmap": modules must be ["MCPPMT"]. method: IntADC or PeakADC.
  - "single": modules is a list of channel names, e.g. ["T1-C"], ["T1-S","T1-C"], or ["T1"] (T1 auto-expands).
  - method defaults to "IntADC". Use "PeakADC" only when explicitly requested.
- run_log: Google Sheets run log.
  Read:   params: {"command": "read", "run_num": int}
  Update: params: {"command": "update", "run_num": int, "<column>": "<value>"}
  Updatable columns: program, notes, config, beam_energy, beam_type, trigger_setup, hv_drc, hv_aux
- hv_read: Read current HV status (CAEN HV + Hodoscope both). params: {"command": "status"}
  Use for ANY HV status query including hodoscope queries.
- hv_write: Change CAEN HV voltage or turn channels on/off. User confirmation required.
  Voltage: {"command": "voltage", "channels": <ch_spec>, "voltage": <V as float>}
  On/off:  {"command": "on"|"off", "channels": <ch_spec>}
  Valid channel names (ONLY these): T1C, T1S, T2C, T2S, T3C, T3S, T4C, T4S, T5C, T5S,
    T6C, T6S, T7C, T7S, T8C, T8S, T9C, T9S, TRIG1, TRIG2, MCP-S, MCP-C
  Channel spec (<ch_spec>) options:
    "all"          — 전체 채널 (ONLY when user says 전체/모든/all)
    "even"         — 짝수 번호 채널 전체
    "odd"          — 홀수 번호 채널 전체
    "N-M"          — ch 번호 N~M 범위 (예: "0-8", "2-12")
    "N,M,K"        — ch 번호 목록 (예: "1,2,5,6")
    ["T1C","T2C"]  — 이름 목록
    "slot:S"       — 슬롯 S 전체
    "slot:S:even/odd" — 슬롯 S 짝/홀수
- motor_move: Move X-axis motor to an absolute position. params: {"x": <mm>}
  User confirmation required.
- motor_status: Read current motor position. params: {}
- motor_alarm_reset: Reset motor alarm/fault. params: {}
- hodoscope_hv_read: Read hodoscope HV from set file. params: {"command": "read"}
- hodoscope_hv_write: Change hodoscope HV. ONLY when user explicitly says "호도스코프"/"호도"/"hodoscope".
  params: {"command": "write", "value": <V as float>}  (value: 0.0 to turn off)
  User confirmation required.

Current experiment state is provided so you can resolve relative references
like "방금", "이번 런", "지금" to concrete run numbers or energies.

Respond with a single JSON object:
{"tool": "<tool_name>", "params": {<params>}, "reason": "<short explanation>"}

If the request is unclear or you cannot determine a tool, respond:
{"tool": "none", "message": "<ask the user for clarification>"}

RULES:
0. All "message" and "reason" field values MUST be written in Korean (한국어) only. Never use Chinese characters (한자).
1. Output ONLY valid JSON. No markdown, no explanation outside JSON.
2. Always resolve relative references using the provided state.
3. For run_log updates, extract column and value from the user's message.
4. run_log supports both READ and WRITE:
   - VIEW/CHECK a log (확인, 보여줘, 읽어줘) WITHOUT a value → {"command": "read", "run_num": ...}
   - WRITE with column+value (e.g. "프로그램에 EM 추가") → {"command": "update", "run_num": ..., "<column>": "<value>"}
5. hv_read for ANY HV status. "HV 확인", "HV 상태", "호도스코프 HV 확인" → all use hv_read.
6. DAQ requires an event count. If the user says "DAQ 돌려줘" without a number, ask how many events.
7. Channel names like T1C, T1S, T2C, ..., T9S are HV channels — NOT log columns.
   A SINGLE channel name + voltage → channels: [that single channel].
   ONLY use channels: "all" when the input explicitly says 전체/모든/전 채널/all channels.
8. For daq_run, hv_write, motor_move, and hodoscope_hv_write, the system asks the user to confirm before execution.
9. "플롯", "그려줘", "그래프" → dqm_plot. Default type: full.
   Method: ONLY set it when the user explicitly says IntADC/intADC/적분 (→ "IntADC") or PeakADC/peakADC/피크 (→ "PeakADC").
   If method is not mentioned, respond with tool:none asking "IntADC로 그릴까요, PeakADC로 그릴까요?"
10. Specific tower/channel (T1, T1-C, T1-S, T5 etc.) → type: single, modules: [name].
11. "heatmap" or "MCPPMT" mentioned → type: heatmap, modules: ["MCPPMT"].
12. dqm_plot requires run_number. Infer from state (last completed run) if not specified.
    If truly unknown, ask which run number.
13. motor_move — always absolute. Extract target position in mm.
14. hodoscope_hv_write: ONLY when user explicitly says "호도스코프"/"호도"/"hodoscope".
    "꺼줘" / "off" → value: 0.0
15. hv_write: for all other HV write requests (not hodoscope).
"""


class BrainAgent(BaseAgent):

    def __init__(self, shared_state: Optional[Dict] = None,
                 shared_locks: Optional[Dict[str, threading.Lock]] = None,
                 io_handler=None, use_base_model: bool = False,
                 confirm_queue: Optional[queue.Queue] = None,
                 clarify_queue: Optional[queue.Queue] = None):
        import sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).parent.parent))
        from config import AGENT_MODELS

        model_cfg = AGENT_MODELS["brain"]
        model_path = model_cfg["base_model"] if use_base_model else model_cfg["fine_tuned_path"]

        super().__init__(model_path=model_path, agent_name="BrainAgent", io_handler=io_handler)

        self.shared_state = shared_state or {}
        self.shared_locks = shared_locks or {}
        self.confirm_queue = confirm_queue or queue.Queue()
        self.clarify_queue = clarify_queue or queue.Queue()
        self._last_daq_run: Optional[int] = None  # run number from last brain-initiated DAQ

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _build_state_context(self) -> str:
        s = self.shared_state
        lines = []

        if s.get("agent_type"):
            lines.append(f"Running agent: {s['agent_type']}")
        if s.get("current_run"):
            lines.append(f"Current run number: {s['current_run']}")

        last_run = s.get("last_run") or s.get("last_run_number") or self._last_daq_run
        if last_run:
            lines.append(f"Last completed run: {last_run}")

        if s.get("current_tower"):
            lines.append(f"Current tower: {s['current_tower']}")
        if s.get("current_energy"):
            lines.append(f"Current energy: {s['current_energy']} GeV")
        if s.get("phase"):
            lines.append(f"Phase: {s['phase']}")
        return "\n".join(lines) if lines else "(No scenario agent running)"

    def run(self):
        """Not used — BrainAgent uses handle_request() for single-turn dispatch."""
        pass

    def handle_request(self, user_input: str, io: WebSocketIO) -> None:
        context = self.build_full_context(current_input=user_input)

        io.send_status("BrainAgent 처리 중...")
        decision = self.decide(context)
        self.log(f"[Brain] tool={decision.get('tool','?')} | params={decision.get('params',{})} | reason={decision.get('reason','')!r} | message={decision.get('message','')!r}")

        if "error" in decision:
            io.send_ai_message(f"요청을 이해하지 못했습니다: {decision.get('raw_output', '')[:200]}")
            io.send_status("대기 중")
            return

        self.add_to_history("user", user_input)
        self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))

        tool_name = decision.get("tool", "none")
        reason = decision.get("reason", "")

        if tool_name == "none":
            fallback = self._apply_fallback_rules(user_input)
            if fallback:
                self.log(f"[Brain] tool:none → fallback: {fallback['tool']}")
                decision = fallback
                tool_name = fallback["tool"]
                reason = fallback.get("reason", "")
            else:
                msg = decision.get("message", reason or "무엇을 도와드릴까요?")
                if not msg or msg.strip().startswith("<"):
                    msg = "요청을 좀 더 구체적으로 말씀해 주세요."
                io.output_queue.put({"type": "adhoc_clarify", "question": msg, "source": "brain"})
                io.send_status("대기 중")
                return

        params = decision.get("params", {})

        # "방금"/"이번"/"last"/"지금" → infer run_number from state instead of asking
        if tool_name == "dqm_plot" and not params.get("run_number"):
            if re.search(r'(방금|이번|last|지금)', user_input.lower()):
                run_num = (self.shared_state.get("last_run")
                           or self.shared_state.get("last_run_number")
                           or self._last_daq_run)
                if run_num:
                    params["run_number"] = int(run_num)

        missing = self._validate_params(tool_name, params)
        if missing:
            _, question = missing
            io.output_queue.put({"type": "adhoc_clarify", "question": question, "source": "brain"})
            io.send_status("대기 중")
            return

        if tool_name in TOOLS_NEED_CONFIRM:
            preview = self._format_confirm_preview(tool_name, params)
            io.send_ai_message(self._format_dispatch_msg(tool_name, params, reason))
            while not self.confirm_queue.empty():  # drain stale replies
                try: self.confirm_queue.get_nowait()
                except queue.Empty: break
            io.output_queue.put({
                "type": "adhoc_confirm",
                "preview": preview,
                "tool": tool_name,
            })
            io.send_status("사용자 확인 대기 중...")
            try:
                confirmed = self.confirm_queue.get(timeout=120)
            except queue.Empty:
                io.send_ai_message("확인 대기 시간 초과 — 요청을 취소했습니다.")
                io.send_status("대기 중")
                return
            if not confirmed:
                io.send_ai_message("요청이 취소되었습니다.")
                io.send_status("대기 중")
                return
        else:
            io.send_ai_message(self._format_dispatch_msg(tool_name, params, reason))

        lock_key = TOOL_LOCK_MAP.get(tool_name)
        lock = self.shared_locks.get(lock_key) if lock_key else None

        if lock and not lock.acquire(blocking=False):
            resource = {"daq": "DAQ", "hv": "HV"}.get(lock_key, lock_key)
            io.send_ai_message(f"{resource}가 현재 사용 중이라 지금은 실행할 수 없습니다.")
            io.send_status("대기 중")
            return

        try:
            self._execute_tool(tool_name, params, io)
        finally:
            if lock:
                lock.release()

        io.send_status("대기 중")

    @staticmethod
    def _format_dispatch_msg(tool_name: str, params: dict, reason: str) -> str:
        lines = [f"Tool: {tool_name}"]
        if params:
            for k, v in params.items():
                lines.append(f"  {k}: {v}")
        if reason:
            lines.append(reason)
        return "\n".join(lines)

    @staticmethod
    def _format_confirm_preview(tool_name: str, params: dict) -> str:
        if tool_name == "daq_run":
            events = params.get("events", "?")
            return f"DAQ 실행\n  이벤트 수: {events:,}" if isinstance(events, int) else f"DAQ 실행\n  이벤트 수: {events}"
        if tool_name == "hv_write":
            cmd = params.get("command", "?")
            ch = params.get("channels", "?")
            ch_str = ch if isinstance(ch, str) else ", ".join(ch)
            if cmd == "voltage":
                v = params.get("voltage", "?")
                return f"HV 전압 변경\n  채널: {ch_str}\n  전압: {v} V"
            if cmd == "current":
                c = params.get("current", "?")
                return f"HV 전류 변경\n  채널: {ch_str}\n  전류: {c} μA"
            if cmd == "on":
                return f"HV 켜기\n  채널: {ch_str}"
            if cmd == "off":
                return f"HV 끄기\n  채널: {ch_str}"
        if tool_name == "hodoscope_hv_write":
            cmd = params.get("command", "write")
            v = params.get("value", "?")
            try:
                if float(v) == 0.0:
                    return "Hodoscope HV 끄기\n  value: 0.0 V (off)"
            except (ValueError, TypeError):
                pass
            return f"Hodoscope HV 변경\n  value: {v} V"
        if tool_name == "motor_move":
            x = params.get("x", "?")
            return f"X축 이동\n  목표 위치: {x} mm"
        return f"{tool_name}\n  params: {params}"

    @staticmethod
    def _validate_params(tool_name: str, params: dict):
        if tool_name == "daq_run":
            events = params.get("events")
            if not events or (isinstance(events, (int, float)) and events <= 0):
                return ("events", "몇 개의 이벤트를 수집할까요?")
        if tool_name == "dqm_plot":
            if not params.get("run_number"):
                return ("run_number", "어떤 런 번호의 DQM 플롯을 그릴까요?")
            if not params.get("method"):
                return ("method", "IntADC로 그릴까요, PeakADC로 그릴까요?")
            if params.get("type") == "single" and not params.get("modules"):
                return ("modules", "어떤 채널을 그릴까요? (예: T1, T1-C, T1-S)")
        if tool_name == "run_log":
            if not params.get("run_num"):
                return ("run_num", "어떤 런 번호의 로그를 처리할까요?")
        if tool_name == "motor_move":
            if params.get("x") is None:
                return ("x", "X축 목표 위치를 mm 단위로 알려주세요. (예: 100mm로 이동)")
        return None

    def _apply_fallback_rules(self, user_input: str) -> Optional[dict]:
        """모델이 tool:none을 출력했을 때 규칙 기반으로 재시도."""
        u = user_input.lower()

        # HV status check (English / Korean)
        if re.search(r'hv.*(status|check)', u) or re.search(r'(hv|고압).*(확인|상태)', u):
            return {"tool": "hv_read", "params": {"command": "status"}, "reason": "HV 상태 확인"}

        # 방금 / 이번 / last run + plot
        if re.search(r'(방금|이번|last)', u) and re.search(r'(plot|플롯|그려|그래프)', u):
            run_num = (self.shared_state.get("last_run")
                       or self.shared_state.get("last_run_number")
                       or self._last_daq_run)
            if run_num:
                return {"tool": "dqm_plot",
                        "params": {"run_number": int(run_num), "type": "full"},
                        "reason": f"Run {run_num} 플롯 (방금 런)"}

        return None

    def _ask_clarify(self, question: str, io, timeout: int = 120) -> Optional[str]:
        while not self.clarify_queue.empty():  # drain stale replies
            try: self.clarify_queue.get_nowait()
            except queue.Empty: break
        io.output_queue.put({"type": "adhoc_clarify", "question": question})
        io.send_status("추가 정보 입력 대기 중...")
        try:
            return self.clarify_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _execute_tool(self, tool_name: str, params: dict, io: WebSocketIO, max_retries: int = 3):
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                if tool_name == "daq_run":
                    from tools.daq_tool import DAQRunTool
                    io.send_status("DAQ 실행 중...")
                    daq_lines: list[str] = []
                    def _daq_cb(line: str):
                        daq_lines.append(line)
                        io.send_tool_output(line)
                    DAQRunTool().execute(params, line_callback=_daq_cb)
                    for _line in daq_lines:
                        m = re.search(r'Run:\s*(\d+)', _line)
                        if m:
                            self._last_daq_run = int(m.group(1))
                            break

                elif tool_name == "dqm_plot":
                    from tools.dqm_tool import DQMPlotTool
                    from tools.dqm_live_worker import OUTPUT_DIR
                    run_number = int(params.get("run_number", 0))
                    method = params.get("method", "IntADC")
                    type_ = params.get("type", "full")
                    modules = params.get("modules", [])
                    io.send_status("DQM 플롯 생성 중...")

                    result = DQMPlotTool().execute(params)
                    io.send_tool_output(result)

                    if type_ == "full":
                        base_prefix = f"Run{run_number}_full_{method}"
                    elif type_ in ("heatmap", "module"):
                        mod = modules[0] if modules else "MCPPMT"
                        base_prefix = f"Run{run_number}_{type_}_{method}_{mod}"
                    else:
                        base_prefix = f"Run{run_number}_single_{method}_"

                    pfx = f"{base_prefix}_"
                    canvases = [
                        p.name[len(pfx):-len(".json")]
                        for p in sorted(OUTPUT_DIR.glob(f"{base_prefix}_*.json"))
                        if p.name.endswith(".json")
                    ]
                    if canvases:
                        io.output_queue.put({
                            "type": "dqm_canvases",
                            "base_prefix": base_prefix,
                            "canvases": canvases,
                            "run_number": run_number,
                        })
                    else:
                        io.send_ai_message(f"Run {run_number} DQM JSON 파일을 찾을 수 없습니다.")

                elif tool_name in ("run_log", "run_log_read"):
                    from tools.run_log_tool import RunLogTool
                    result = RunLogTool().execute(params)
                    io.send_tool_output(result)

                elif tool_name in ("hv_read", "hv_status"):
                    from tools.hv_control_tool import HVControlTool
                    from tools.hodoscope_hv_tool import HodoscopeHVTool
                    params.setdefault("command", "status")
                    result_caen = HVControlTool().execute(params)
                    try:
                        result_hodo = HodoscopeHVTool().execute({"command": "read"})
                    except Exception as e:
                        result_hodo = f"[Hodoscope HV 읽기 실패: {e}]"
                    io.send_tool_output(result_caen + "\n\n─────────────────────\n" + result_hodo)

                elif tool_name == "hv_write":
                    from tools.hv_control_tool import HVControlTool
                    io.send_status("HV 변경 중...")
                    result = HVControlTool().execute(params)
                    io.send_tool_output(result)

                elif tool_name == "motor_move":
                    from tools.motor_control_tool import move_x
                    x = float(params.get("x", 0))
                    io.send_status(f"[Motor] 절대 이동: {x:.3f} mm")
                    ok, msg = move_x(x)
                    if not ok:
                        raise RuntimeError(msg)
                    io.send_tool_output(f"[Motor] {msg}")

                elif tool_name == "motor_status":
                    from tools.motor_control_tool import get_position
                    ok, msg = get_position()
                    if not ok:
                        raise RuntimeError(msg)
                    io.send_tool_output(f"[Motor] 현재 위치: {msg}")

                elif tool_name == "motor_alarm_reset":
                    from tools.motor_control_tool import alarm_reset
                    io.send_status("모터 알람 리셋 중...")
                    ok, msg = alarm_reset()
                    if not ok:
                        raise RuntimeError(msg)
                    io.send_tool_output(f"[Motor] {msg}")

                elif tool_name == "hodoscope_hv_read":
                    from tools.hodoscope_hv_tool import HodoscopeHVTool
                    result = HodoscopeHVTool().execute({"command": "read"})
                    io.send_tool_output(result)

                elif tool_name == "hodoscope_hv_write":
                    from tools.hodoscope_hv_tool import HodoscopeHVTool
                    io.send_status("Hodoscope HV 변경 중...")
                    result = HodoscopeHVTool().execute(params)
                    io.send_tool_output(result)

                else:
                    io.send_ai_message(f"알 수 없는 도구: {tool_name}")

                return

            except RuntimeError as e:
                last_error = e
                self.log(f"[Retry {attempt}/{max_retries}] Tool '{tool_name}' 실패: {e}")
                if attempt < max_retries:
                    time.sleep(2)

            except Exception as e:
                io.send_ai_message(f"도구 실행 중 오류: {e}")
                return

        io.send_tool_error(tool_name, str(last_error), max_retries)


class _BrainOutputQueue:
    """모든 메시지에 source='brain'을 태깅해서 output_queue로 전달."""

    def __init__(self, real_queue: queue.Queue):
        self._q = real_queue

    def put(self, item):
        if isinstance(item, dict):
            item = {**item, "source": "brain"}
        self._q.put(item)

    def get(self, *args, **kwargs):
        return self._q.get(*args, **kwargs)

    def get_nowait(self):
        return self._q.get_nowait()

    def empty(self):
        return self._q.empty()


def run_brain_thread(
    brain_agent: BrainAgent,
    adhoc_queue: queue.Queue,
    output_queue: queue.Queue,
    stop_event: threading.Event,
    confirm_queue: Optional[queue.Queue] = None,
    clarify_queue: Optional[queue.Queue] = None,
):
    if confirm_queue is not None:
        brain_agent.confirm_queue = confirm_queue
    if clarify_queue is not None:
        brain_agent.clarify_queue = clarify_queue
    tagged_queue = _BrainOutputQueue(output_queue)
    io = WebSocketIO(
        input_queue=queue.Queue(),  # 입력 없음 — BrainAgent는 단방향 dispatch
        output_queue=tagged_queue,
        stop_event=stop_event,
    )

    while not stop_event.is_set():
        try:
            user_input = adhoc_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if user_input in ("종료", "exit"):
            break

        try:
            brain_agent.handle_request(user_input, io)
        except Exception:
            tb = traceback.format_exc()
            output_queue.put({"type": "error", "content": f"BrainAgent error:\n{tb}"})
