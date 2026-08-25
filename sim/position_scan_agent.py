#!/usr/bin/env python3
"""모터, DAQ, peakADC 측정을 모의 실행하는 Position Scan Agent."""

from typing import Dict

from agents.position_scan_agent import PositionScanAgent
from sim.position_scan_sim_model import PositionScanPeakADCSimMixin
from sim.sim_base import SimExecMixin
from sim.tool_simulator import get_simulator


class PositionScanSimAgent(SimExecMixin, PositionScanPeakADCSimMixin, PositionScanAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim = get_simulator()
        self.agent_name = f"{self.agent_name} [SIM]"
        self._init_peakadc_sim_model()

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        if tool_name == "none":
            return "no_tool_executed"

        if tool_name == "motor_x_move_tool":
            x = self._motor_x_for_current_step()
            # 상태의 X 좌표로 시뮬레이션 매개변수를 확정한다.
            self._sim_emit_tool_call(tool_name, {"x": x})
            self.io.send_tool_output(f"[Motor] X축 이동 시작 (Position Scan): {x:.3f} mm")
            result = self._sim.motor_move(x, self.state["center_tower"])
            self.io.send_tool_output(result)
            self.state["x_moved"] = True
            return result

        if tool_name == "daq_run_tool":
            # 공통 시뮬레이션 경로로 DAQ를 실행하고 플롯 확인을 기다린다.
            result, run_number = self._sim_run_daq(
                params,
                events=self.state.get("target_events"),
                beam_energy=self.state.get("beam_energy"),
                program="Position Scan",
                pos=self._position_for_current_step(),
            )
            if run_number:
                self.state["last_run_number"] = run_number
                self.log(f"[SIM] DAQ Run {run_number} 완료: {self._position_for_current_step()}, "
                         f"{params.get('events', 0)} events")
            return result

        self._sim_emit_tool_call(tool_name, params)
        return f"Error: Unknown tool {tool_name}"
