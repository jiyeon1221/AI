#!/usr/bin/env python3
"""
Web Server (Simulation Mode)
----------------------------
run_web_sim.py 전용. UI/웹소켓은 web/server.py와 동일, tool execution만 mock.
"""

import queue
import threading

from sim.agent_runner import AgentRunnerSim
from sim.tool_simulator import get_simulator
from web import server as _server

# 시작 전에 실제 장비 실행기를 시뮬레이션 실행기로 바꾼다.
_server.runner = AgentRunnerSim()


def _run_direct_tool_sim(cmd: dict, output_queue: queue.Queue, stop_event: threading.Event):
    """에이전트 미실행 시 직접 명령 — sim."""
    from agents.io_handler import WebSocketIO
    import queue as q

    dummy_input = q.Queue()
    io = WebSocketIO(dummy_input, output_queue, stop_event)
    sim = get_simulator()

    try:
        if cmd["tool"] == "daq_run":
            io.send_status("DAQ 실행 중... [SIM]")
            sim.daq_run({"events": cmd["events"]}, line_callback=io.send_tool_output)
            io.send_status("대기 중")
    except Exception as e:
        output_queue.put({"type": "error", "content": str(e)})
        output_queue.put({"type": "status", "content": "오류 발생"})


def _update_run_log_sim(run_number: int, column: str, value: str,
                        output_queue: queue.Queue, stop_event: threading.Event):
    from agents.io_handler import WebSocketIO
    import queue as q

    dummy_input = q.Queue()
    io = WebSocketIO(dummy_input, output_queue, stop_event)
    sim = get_simulator()

    io.send_status("로그 업데이트 중... [SIM]")
    result = sim.run_log({"command": "update", "run_num": run_number, column: value})
    io.send_tool_output(result)
    label = _server._COL_DISPLAY.get(column, column)
    io.send_ai_message(f"[SIM] Run {run_number}  {label} 열 업데이트 (mock)")
    io.send_status("대기 중")


# WebSocket의 직접 도구 호출을 시뮬레이션으로 바꾼다.
_server._run_direct_tool = _run_direct_tool_sim
_server._update_run_log = _update_run_log_sim

app = _server.app
