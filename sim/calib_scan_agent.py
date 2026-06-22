#!/usr/bin/env python3
"""Calibration Scan Agent — simulation mode (no hardware)."""

from typing import Dict

from agents.calib_scan_agent import CalibScanAgent
from sim.tool_simulator import get_simulator


class CalibScanSimAgent(CalibScanAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim = get_simulator()
        self.agent_name = f"{self.agent_name} [SIM]"

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        if tool_name == "none":
            return "no_tool_executed"

        self.io.send_tool_output(self._sim.format_tool_call(tool_name, params))

        if tool_name == "motor_x_move_tool":
            tower = self._current_tower_name()
            x = self._motor_x_for_current_step()
            self.io.send_tool_output(f"[Motor] X축 이동 시작 ({tower}): {x:.3f} mm")
            result = self._sim.motor_move(x, tower)
            self.io.send_tool_output(result)
            self.state["tower_status"][tower]["x_moved"] = True
            return result

        if tool_name == "daq_run_tool":
            tower = self._current_tower_name()
            pos = self._position_for_current_step()
            self._apply_daq_params_from_state(
                params,
                events=self.state.get("target_events"),
                beam_energy=self.state.get("beam_energy"),
                program="Calibration",
                pos=pos,
            )
            result = self._sim.daq_run(params, line_callback=self.io.send_tool_output)
            run_number = self._extract_run_number(result)
            if run_number:
                self.state["last_run_number"] = run_number
                self.state["tower_status"][tower]["runs"].append(run_number)
                self.state["tower_status"][tower]["collected_events"] = params.get("events", 0)
                self.log(f"[SIM] DAQ Run {run_number} 완료: {tower}, {params.get('events', 0)} events")
            # 사용자 plot 확인 전까지 completed=True 차단 (실제 agent와 동일 부킹)
            self.state["needs_plot_confirm"] = True
            return result

        return f"Error: Unknown tool {tool_name}"
