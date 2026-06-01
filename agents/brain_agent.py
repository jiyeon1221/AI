#!/usr/bin/env python3
"""
BrainAgent
----------
Background agent that handles ad-hoc user requests while a scenario agent
is running.  Takes natural language, infers the right tool + params via a
fine-tuned Qwen2.5-1.5B, and executes it.

Designed to stay loaded in memory at all times (server start → server stop).
"""

import json
import re
import time
import threading
import queue
import traceback
from typing import Dict, Any, Optional

from agents.base_agent import BaseAgent
from agents.io_handler import WebSocketIO


# Map tool names to shared lock keys.  None means no lock needed.
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

# Tools that require user confirmation before execution.
TOOLS_NEED_CONFIRM = {"hv_write", "hodoscope_hv_write", "motor_move"}



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
- hv_read: Read current HV status. params: {"command": "status"} (optional: "channels": "all" | list)
- hv_write: Change HV voltage or turn channels on/off. User confirmation will be asked before execution.
  Voltage: {"command": "voltage", "channels": <channel_spec>, "voltage": <V as float>}
  On/off:  {"command": "on"|"off", "channels": <channel_spec>}
  channel_spec options:
    - Single channel: ["T1C"], ["TRIG1"], ["MCP-S"]
    - Multiple channels: ["T1C", "T2C"], ["TRIG1", "TRIG2"]
    - All DRC channels: "all"  ← use ONLY when user says 전체/모든/전 채널/all channels
    - S-side only: ["T1S","T2S","T3S","T4S","T5S","T6S","T7S","T8S","T9S"]
    - C-side only: ["T1C","T2C","T3C","T4C","T5C","T6C","T7C","T8C","T9C"]
    - Even channels: "0,2,4,6,8,10,12,14,16,18,20,22"
    - Odd channels: "1,3,5,7,9,11,13,15,17,19,21,23"
    - Channel range: "0-8"
  Named channels: T1C/T1S~T9C/T9S (DRC towers), TRIG1/TRIG2 (trigger PMTs), MCP-S/MCP-C (MCP PMTs)
- motor_move: Move X-axis motor to an absolute position.
  params: {"x": <mm>}
  Always absolute — specify the target position in mm.
- motor_status: Read current motor position. params: {} (no params needed).
  Use when user asks for current position, "지금 위치", "position status", "pos", "현재 위치 확인" etc.
- motor_alarm_reset: Reset motor alarm/fault after hitting position limit or fault state.
  params: {} (no params needed)
  Use when: motor is locked, won't move, alarm/fault triggered, "알람", "락", "에러", "범위 초과", "안움직여" after a failed move.
- hodoscope_hv_read: Read current hodoscope HV setting from the DAQ set file.
  params: {"command": "read"}
  Returns a single value (the 'hv' line in the set file that applies to all 4 hodoscope channels).
- hodoscope_hv_write: Change hodoscope HV in the DAQ set file. User confirmation required.
  Set voltage: {"command": "write", "value": <V as float>}
  Turn off:    {"command": "write", "value": 0.0}
  Channel names: N/A — set file has one 'hv' value shared by all 4 hodoscope channels.

Current experiment state is provided so you can resolve relative references
like "방금", "이번 런", "지금" to concrete run numbers or energies.

Respond with a single JSON object:
{"tool": "<tool_name>", "params": {<params>}, "reason": "<short explanation>"}

If the request is unclear or you cannot determine a tool, respond:
{"tool": "none", "message": "<ask the user for clarification>"}

RULES:
1. Output ONLY valid JSON. No markdown, no explanation outside JSON.
2. Always resolve relative references using the provided state.
3. For run_log updates, extract column and value from the user's message.
4. run_log supports both READ and WRITE:
   - VIEW/CHECK a log (확인, 보여줘, 읽어줘) WITHOUT a value → {"command": "read", "run_num": ...}
   - WRITE with column+value (e.g. "프로그램에 EM 추가") → {"command": "update", "run_num": ..., "<column>": "<value>"}
5. hv_read CAN read. "HV 확인" → use hv_read.
6. DAQ requires an event count. If the user says "DAQ 돌려줘" without a number, ask how many events.
7. Channel names like T1C, T1S, T2C, ..., T9S are HV channels — NOT log columns.
   "T9S 전압 100으로", "T1C 1500V로 수정" → hv_write with channels: ["T9S"] or ["T1C"].
   ONLY use channels: "all" when the input explicitly says 전체/모든/전 채널/all channels.
   A SINGLE channel name + voltage ALWAYS means channels: [that single channel].
8. For hv_write and motor_move, the system asks the user to confirm before execution — you don't need to handle confirmation in your JSON.
16. "S채널만"/"S만"/"S side"/"S 쪽만" → channels: ["T1S","T2S","T3S","T4S","T5S","T6S","T7S","T8S","T9S"]
17. "C채널만"/"C만"/"C side"/"C 쪽만"/"체렌코프만" → channels: ["T1C","T2C","T3C","T4C","T5C","T6C","T7C","T8C","T9C"]
18. "TRIG"/"트리거" without specific number → channels: ["TRIG1","TRIG2"]
    "MCP" without S/C → channels: ["MCP-S","MCP-C"]
    "TRIG1" only → channels: ["TRIG1"]   "TRIG2" only → channels: ["TRIG2"]
19. "짝수 채널"/"even channel" → channels: "0,2,4,6,8,10,12,14,16,18,20,22"
    "홀수 채널"/"odd channel" → channels: "1,3,5,7,9,11,13,15,17,19,21,23"
20. "ch0-8"/"채널 0번부터 8번" → channels: "0-8"  (use range format)
9. "플롯", "그려줘", "그래프", "확인해줘 (run)" → dqm_plot. Default type: full, default method: IntADC.
10. Specific tower/channel (T1, T1-C, T1-S, T5 etc.) → type: single, modules: [name].
11. "heatmap" or "MCPPMT" mentioned → type: heatmap, modules: ["MCPPMT"]. Always MCPPMT (SiPM not used).
12. No type/channel hint → type: full.
13. motor_move — always absolute. Extract the target position in mm from user input.
    e.g. "100mm로 이동" → {"x": 100.0}, "X축 85.5mm" → {"x": 85.5}
21. motor_alarm_reset: "모터 알람 리셋", "모터 락 풀어줘", "motor alarm reset", "모터 에러 해제",
    "모터가 안움직여" (after failed move), "범위 초과 리셋", "fault 풀어줘" → motor_alarm_reset.
14. hodoscope_hv_read: "호도스코프 HV 확인", "호도 HV 얼마야", "hodoscope HV 읽어줘" → hodoscope_hv_read.
15. hodoscope_hv_write: "호도스코프 HV X로 설정", "호도 HV X볼트로 바꿔줘", "hodoscope HV 꺼줘" → hodoscope_hv_write.
    - "꺼줘" / "off" / "0으로" → value: 0.0
    - "호도스코프 HV"는 set file의 단일 'hv' 라인이며 4채널 공통 적용.
    - hodoscope_hv_write is in TOOLS_NEED_CONFIRM — system will ask for confirmation.
"""


class BrainAgent(BaseAgent):
    """
    Lightweight agent for ad-hoc tool dispatch.
    - Stays loaded in memory (no context-manager cycling)
    - Single-turn: one request  ->  one tool call  ->  result
    - Reads scenario agent state (read-only) for context
    """

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

    # ── BaseAgent abstract methods ───────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _build_state_context(self) -> str:
        """Summarise the scenario agent's state for context."""
        s = self.shared_state
        lines = []

        if s.get("agent_type"):
            lines.append(f"Running agent: {s['agent_type']}")
        if s.get("current_run"):
            lines.append(f"Current run number: {s['current_run']}")

        # shared_state may use either 'last_run' or 'last_run_number'
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

    # ── Public API ───────────────────────────────────────────────────────────

    def handle_request(self, user_input: str, io: WebSocketIO) -> None:
        """
        Process one ad-hoc request end-to-end:
        1. Build context  (state + user input)
        2. LLM inference  (tool + params)
        3. Lock check
        4. Execute tool
        5. Send result to UI
        """
        context = self.build_full_context(current_input=user_input)

        io.send_status("BrainAgent 처리 중...")
        decision = self.decide(context)

        if "error" in decision:
            io.send_ai_message(f"요청을 이해하지 못했습니다: {decision.get('raw_output', '')[:200]}")
            io.send_status("대기 중")
            return

        tool_name = decision.get("tool", "none")
        reason = decision.get("reason", "")

        if tool_name == "none":
            msg = decision.get("message", reason or "무엇을 도와드릴까요?")
            io.send_ai_message(msg)
            io.send_status("대기 중")
            return

        params = decision.get("params", {})

        missing = self._validate_params(tool_name, params)
        if missing:
            _, question = missing
            io.send_ai_message(question)
            io.send_status("대기 중")
            return

        if tool_name in TOOLS_NEED_CONFIRM:
            preview = self._format_confirm_preview(tool_name, params)
            io.send_ai_message(f"{reason}")
            # Drain any stale confirmation responses
            while not self.confirm_queue.empty():
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
            io.send_ai_message(f"{reason}")

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
    def _format_confirm_preview(tool_name: str, params: dict) -> str:
        """Human-readable summary of the action, shown in the confirmation popup."""
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
            if float(v) == 0.0:
                return "Hodoscope HV 끄기\n  value: 0.0 V (off)"
            return f"Hodoscope HV 변경\n  value: {v} V"
        if tool_name == "motor_move":
            x = params.get("x", "?")
            return f"X축 이동\n  목표 위치: {x} mm"
        return f"{tool_name}\n  params: {params}"

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_params(tool_name: str, params: dict):
        """
        Return (field_key, question) for the first missing required param,
        or None if all required params are present.
        field_key is used to parse the clarification answer.
        """
        if tool_name == "daq_run":
            events = params.get("events")
            if not events or (isinstance(events, (int, float)) and events <= 0):
                return ("events", "몇 개의 이벤트를 수집할까요?")
        if tool_name == "dqm_plot":
            if not params.get("run_number"):
                return ("run_number", "어떤 런 번호의 DQM 플롯을 그릴까요?")
        if tool_name == "run_log":
            if not params.get("run_num"):
                return ("run_num", "어떤 런 번호의 로그를 처리할까요?")
        return None

    def _ask_clarify(self, question: str, io, timeout: int = 120) -> Optional[str]:
        """Send a clarification request to the popup and wait for the answer."""
        # Drain stale clarify replies
        while not self.clarify_queue.empty():
            try: self.clarify_queue.get_nowait()
            except queue.Empty: break
        io.output_queue.put({"type": "adhoc_clarify", "question": question})
        io.send_status("추가 정보 입력 대기 중...")
        try:
            return self.clarify_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _execute_tool(self, tool_name: str, params: dict, io: WebSocketIO, max_retries: int = 3):
        """Run the actual tool and send output to the UI. Retries on RuntimeError."""
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
                    params.setdefault("command", "status")
                    result = HVControlTool().execute(params)
                    io.send_tool_output(result)

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

                return  # 성공

            except RuntimeError as e:
                last_error = e
                self.log(f"[Retry {attempt}/{max_retries}] Tool '{tool_name}' 실패: {e}")
                if attempt < max_retries:
                    time.sleep(2)

            except Exception as e:
                io.send_ai_message(f"도구 실행 중 오류: {e}")
                return

        io.send_tool_error(tool_name, str(last_error), max_retries)


# ── Background worker loop ───────────────────────────────────────────────────

class _BrainOutputQueue:
    """Wrapper that tags every message with source='brain' before forwarding."""

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
    """
    Long-running thread that polls adhoc_queue and dispatches requests
    through BrainAgent.  Shares output_queue with the scenario agent
    so results appear in the same UI.
    """
    if confirm_queue is not None:
        brain_agent.confirm_queue = confirm_queue
    if clarify_queue is not None:
        brain_agent.clarify_queue = clarify_queue
    tagged_queue = _BrainOutputQueue(output_queue)
    io = WebSocketIO(
        input_queue=queue.Queue(),   # BrainAgent doesn't need input back
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
