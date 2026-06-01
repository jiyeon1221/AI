#!/usr/bin/env python3
"""
HV Equalization Sim Agent (Web)
모든 tool calling을 시뮬레이션 (DAQ/HV/Motor/ADC — 하드웨어 없음).
"""

import json
from typing import Dict

from agents.hv_equalization_agent import HVEqualizationAgent
from sim.tool_simulator import get_simulator


class HVEqualizationSimAgent(HVEqualizationAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim = get_simulator()
        self.agent_name = f"HV Equalization Sim [{self.tower}]"

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        try:
            if tool_name == "none":
                return "no_tool_executed"

            self.io.send_tool_output(self._sim.format_tool_call(tool_name, params))

            if tool_name == "motor_x_move_tool":
                x = self._motor_x_for_current_step()
                self.io.send_tool_output(f"[Motor] X축 이동 시작 ({self.tower}): {x:.3f} mm")
                result = self._sim.motor_move(x, self.tower)
                self.io.send_tool_output(result)
                self.state["x_moved"] = True
                return result

            if tool_name == "daq_run_tool":
                self._apply_daq_params_from_state(
                    params,
                    events=self.state.get("target_events"),
                    beam_energy=self.state.get("beam_energy"),
                    program="HV Equalization",
                    pos=self._position_for_current_step(),
                )
                result = self._sim.daq_run(params, line_callback=self.io.send_tool_output)
                run_number = self._extract_run_number(result)
                if run_number:
                    self.state["last_run_number"] = run_number
                    self.state["iterations"] = self.state.get("iterations", 0) + 1
                    self.log(f"[SIM] DAQ Run {run_number} 완료: {self.tower}, {params.get('events', 0)} events")
                self.state["needs_suggest"] = True
                return result

            if tool_name == "hv_execute_tool":
                cmd = params.get("command", "").lower()

                if cmd == "voltage":
                    if self.state.get("last_suggested_hv_c") is not None:
                        cv = {}
                        if not self.state.get("channel_done_c", False):
                            cv["MCP-C"] = self.state["last_suggested_hv_c"]
                        if not self.state.get("channel_done_s", False):
                            cv["MCP-S"] = self.state["last_suggested_hv_s"]
                        if cv:
                            self._apply_hv_voltage_params_from_state(params, cv)

                if cmd == "status":
                    result = self._sim.hv_status(params.get("channels", ["MCP-C", "MCP-S"]))
                elif cmd == "voltage":
                    result = self._sim.hv_voltage(params.get("channel_values", {}))
                else:
                    result = self._sim.hv_on_off(cmd, params.get("channels", []))

                self.io.send_tool_output(result)

                if cmd == "status":
                    v_c, v_s = self._extract_voltages(result)
                    if v_c is not None:
                        self.state["last_hv_c"], self.state["last_hv_s"] = v_c, v_s
                        self.log(f"[SIM] HV Status: C={v_c}V, S={v_s}V")
                elif cmd == "voltage":
                    if self.state.get("last_suggested_hv_c") is not None:
                        self.state["last_hv_c"] = self.state["last_suggested_hv_c"]
                        self.state["last_hv_s"] = self.state["last_suggested_hv_s"]
                    self.state["last_suggested_hv_c"] = None
                    self.state["last_suggested_hv_s"] = None

                    self.io.send_tool_output(f"🔍 [SIM] HV 적용 확인 중 ({self.tower})...")
                    verify = self._sim.hv_status(["MCP-C", "MCP-S"])
                    self.io.send_tool_output(verify)
                    v_c, v_s = self._extract_voltages(verify)
                    if v_c is not None:
                        self.state["last_hv_c"] = v_c
                        self.state["last_hv_s"] = v_s
                        self.log(f"[SIM] HV Verified: C={v_c}V, S={v_s}V")
                return result

            if tool_name == "hv_equalization_suggest":
                self._apply_hv_suggest_params_from_state(
                    params,
                    tower=self.tower,
                    run_number=self.state.get("last_run_number"),
                    hv_c=self.state.get("last_hv_c"),
                    hv_s=self.state.get("last_hv_s"),
                )
                hv_c = float(self.state.get("last_hv_c") or 775.0)
                hv_s = float(self.state.get("last_hv_s") or 775.0)
                run_number = int(params.get("run_number") or self.state.get("last_run_number") or 0)
                result_dict = self._sim.hv_suggest(
                    tower=self.tower,
                    run_number=run_number,
                    hv_c=hv_c,
                    hv_s=hv_s,
                    target_adc_c=float(self.state.get("target_adc_c") or 1230),
                    target_adc_s=float(self.state.get("target_adc_s") or 1230),
                    iteration=self.state.get("iterations", 0),
                )

                cur = result_dict.get("current", {})
                sug = result_dict.get("suggested", {})
                self.state["last_adc_c"] = cur.get("C", {}).get("adc")
                self.state["last_adc_s"] = cur.get("S", {}).get("adc")
                raw_hv_c = sug.get("C", {}).get("hv")
                raw_hv_s = sug.get("S", {}).get("hv")
                self.state["last_suggested_hv_c"] = int(round(raw_hv_c)) if raw_hv_c is not None else None
                self.state["last_suggested_hv_s"] = int(round(raw_hv_s)) if raw_hv_s is not None else None
                self.state["channel_done_c"] = bool(sug.get("C", {}).get("done", False))
                self.state["channel_done_s"] = bool(sug.get("S", {}).get("done", False))
                self.state["needs_suggest"] = False

                adc_c = self.state["last_adc_c"]
                adc_s = self.state["last_adc_s"]
                summary = (
                    f"🔬 [SIM] HV Suggest — {self.tower} | "
                    f"ADC(sim): C={adc_c:.1f if adc_c else 'N/A'}, S={adc_s:.1f if adc_s else 'N/A'} | "
                    f"HV: C={hv_c:.0f}V→{self.state['last_suggested_hv_c']}V, "
                    f"S={hv_s:.0f}V→{self.state['last_suggested_hv_s']}V | "
                    f"Done: C={self.state['channel_done_c']}, S={self.state['channel_done_s']}"
                )
                self.io.send_tool_output(summary)
                self.log(summary)
                self.io.send_tool_output(
                    f"── [SIM] HV Fitting History ({self.tower}) ──\n"
                    f"(fitting plot skipped in sim mode)"
                )
                return json.dumps(result_dict, ensure_ascii=False, indent=2)

            if tool_name == "hv_equalization_done_channel":
                result = self._sim.hv_done_channel(self.tower)
                itr = self.state.get("iterations", 0)
                done_msg = f"{self.tower} HV Equalization 완료 ({itr}회 반복) [SIM]"
                self.io.send_tool_output(result)
                self.io.send_ai_message(done_msg)
                self.state["done"] = True
                self.log(f"[SIM] HV Equalization Done: {self.tower}")
                return result

            self.log(f"Unknown tool: {tool_name}")
            return f"Error: Unknown tool {tool_name}"
        except Exception as e:
            self.log(f"Tool 실행 오류 ({tool_name}): {str(e)}")
            return f"Error: {str(e)}"
