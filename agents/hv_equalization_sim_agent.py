#!/usr/bin/env python3
"""
HV Equalization Simulation Agent (Sim-ADC)
HV/motor/DAQ는 실제 하드웨어, peakADC 측정만 시뮬레이션한다.

설계 원칙: 찐(HVEqualizationAgent)과 "ADC를 실제로 가져오느냐(_measure_adc)"만
다르고 나머지 워크플로우(hv_execute_tool / motor / daq / suggest 계산 / plot 확인 /
state 부킹)는 부모 로직을 그대로 공유한다.
"""

from typing import Optional, Tuple

from sim.adc_sim_model import DEFAULT_TARGET_ADC, make_channel_params, simulate_adc

from .hv_equalization_agent import HVEqualizationAgent


class HVEqualizationSimAgent(HVEqualizationAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_name = f"HV Equalization Sim-ADC [{self.tower}]"
        self._sim_params = make_channel_params(
            float(self.state.get("target_adc_c") or DEFAULT_TARGET_ADC)
        )
        self.log(f"Sim-ADC 초기화: {self.tower} (HV는 실제 하드웨어, ADC만 시뮬레이션)")

    def _measure_adc(self, hv_c: float, hv_s: float, run_number: int) -> Tuple[Optional[float], Optional[float]]:
        """실제 run 데이터 대신 시뮬레이션 ADC를 반환 (유일한 차이점)."""
        itr = self.state.get("iterations", 0)
        return (
            simulate_adc(self._sim_params["C"], hv_c, itr),
            simulate_adc(self._sim_params["S"], hv_s, itr),
        )
