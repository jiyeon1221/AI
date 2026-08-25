#!/usr/bin/env python3
"""
HV Equalization Web-Sim Agent
run_web_sim.py 전용 — 하드웨어/SSH 없이 motor/DAQ/HV를 전부 mock.

설계: ADC-sim agent(agents.hv_equalization_sim_agent)를 상속해
peakADC 시뮬레이션(_measure_adc)과 suggest 계산(_do_suggest, 부모)을 그대로 공유하고,
하드웨어 호출(motor/daq/hv_execute)만 ToolSimulator로 mock한다.
채널명은 항상 현재 타워 기준({tower}C/{tower}S) — MCP 하드코딩 없음.
"""

from typing import Dict

from agents.hv_equalization_sim_agent import HVEqualizationSimAgent as _ADCSimAgent
from sim.sim_base import SimExecMixin
from sim.tool_simulator import get_simulator


class HVEqualizationSimAgent(SimExecMixin, _ADCSimAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim = get_simulator()
        self.agent_name = f"HV Equalization Web-Sim [{self.tower}]"

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        try:
            if tool_name == "none":
                return "no_tool_executed"

            if tool_name == "motor_x_move_tool":
                x = self._motor_x_for_current_step()
                # 상태의 X 좌표로 시뮬레이션 매개변수를 확정한다.
                self._sim_emit_tool_call(tool_name, {"x": x})
                self.io.send_tool_output(f"[Motor] X축 이동 시작 ({self.tower}): {x:.3f} mm")
                result = self._sim.motor_move(x, self.tower)
                self.io.send_tool_output(result)
                self.state["x_moved"] = True
                return result

            if tool_name == "daq_run_tool":
                result, run_number = self._sim_run_daq(
                    params,
                    events=self.state.get("target_events"),
                    beam_energy=self.state.get("beam_energy"),
                    program="HV Equalization",
                    pos=self._position_for_current_step(),
                )
                if run_number:
                    self.state["last_run_number"] = run_number
                    self.state["iterations"] = self.state.get("iterations", 0) + 1
                    self.log(f"[SIM] DAQ Run {run_number} 완료: {self.tower}, {params.get('events', 0)} events")
                self.state["needs_suggest"] = False   # HV 제안 대기 상태.
                return result

            if tool_name == "hv_execute_tool":
                return self._mock_hv_execute(params)

            # HV 제안과 채널 완료는 부모의 ADC 시뮬레이션을 사용한다.
            self._sim_emit_tool_call(tool_name, params)
            return super()._execute_tool(tool_name, params)

        except Exception as e:
            self.log(f"Tool 실행 오류 ({tool_name}): {str(e)}")
            return f"Error: {str(e)}"

    def _mock_hv_execute(self, params: Dict) -> str:
        """HV status/voltage를 sim으로 mock — 채널명은 {tower}C/{tower}S."""
        cmd = params.get("command", "").lower()

        if cmd == "voltage":
            # 미완료 채널에 마지막 제안 전압을 적용한다.
            if self.state.get("last_suggested_hv_c") is not None:
                cv = {}
                if not self.state.get("channel_done_c", False):
                    cv[f"{self.tower}C"] = self.state["last_suggested_hv_c"]
                if not self.state.get("channel_done_s", False):
                    cv[f"{self.tower}S"] = self.state["last_suggested_hv_s"]
                if cv:
                    self._apply_hv_voltage_params_from_state(params, cv)
            # 확정된 인가 전압을 표시한다.
            self._sim_emit_tool_call("hv_execute_tool", params)
            result = self._sim.hv_voltage(params.get("channel_values", {}))
            self.io.send_tool_output(result)

            if self.state.get("last_suggested_hv_c") is not None:
                self.state["last_hv_c"] = self.state["last_suggested_hv_c"]
                self.state["last_hv_s"] = self.state["last_suggested_hv_s"]
            self.state["last_suggested_hv_c"] = None
            self.state["last_suggested_hv_s"] = None
            self.state["last_adc_c"] = None
            self.state["last_adc_s"] = None
            self.state["approval_confirmed"] = False  # 다음 승인을 기다린다.

            self.io.send_tool_output(f"🔍 [SIM] HV 적용 확인 중 ({self.tower})...")
            verify = self._sim.hv_status([f"{self.tower}C", f"{self.tower}S"])
            self.io.send_tool_output(verify)
            v_c, v_s = self._extract_voltages(verify)
            if v_c is not None:
                self.state["last_hv_c"] = v_c
                self.state["last_hv_s"] = v_s
                self.log(f"[SIM] HV Verified: C={v_c}V, S={v_s}V")
            return result

        if cmd == "status":
            self._sim_emit_tool_call("hv_execute_tool", params)
            channels = params.get("channels") or [f"{self.tower}C", f"{self.tower}S"]
            result = self._sim.hv_status(channels)
            self.io.send_tool_output(result)
            v_c, v_s = self._extract_voltages(result)
            if v_c is not None:
                self.state["last_hv_c"], self.state["last_hv_s"] = v_c, v_s
                self.log(f"[SIM] HV Status: C={v_c}V, S={v_s}V")
            return result

        self._sim_emit_tool_call("hv_execute_tool", params)
        result = self._sim.hv_on_off(cmd, params.get("channels", []))
        self.io.send_tool_output(result)
        return result
