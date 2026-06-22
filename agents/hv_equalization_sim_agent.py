#!/usr/bin/env python3
"""
HV Equalization Simulation Agent (Sim-ADC)
HV/motor/DAQ는 실제 하드웨어, peakADC 측정만 시뮬레이션한다.

설계 원칙: 찐(HVEqualizationAgent)과 "ADC를 실제로 가져오느냐(_measure_adc)"만
다르고 나머지 워크플로우(hv_execute_tool / motor / daq / suggest 계산 / plot 확인 /
state 부킹)는 부모 로직을 그대로 공유한다.
"""

import math
import random
from typing import Optional, Tuple

from .hv_equalization_agent import HVEqualizationAgent


class HVEqualizationSimAgent(HVEqualizationAgent):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_name = f"HV Equalization Sim-ADC [{self.tower}]"

        # 지수함수 PMT 모델: ADC = A * exp(B * HV). 실제 HV는 하드웨어에서 읽으므로
        # ref_hv는 ADC 파라미터 산정 기준으로만 사용.
        B_c = random.uniform(0.0060, 0.0080)
        B_s = random.uniform(0.0060, 0.0080)
        ref_hv_c = random.uniform(750.0, 800.0)
        ref_hv_s = random.uniform(750.0, 800.0)
        ref_target = float(self.state.get("target_adc_c") or 1230)
        frac_c = random.uniform(0.35, 0.70)
        frac_s = random.uniform(0.35, 0.70)
        A_c = frac_c * ref_target / math.exp(B_c * ref_hv_c)
        A_s = frac_s * ref_target / math.exp(B_s * ref_hv_s)
        self._sim_params = {
            "C": {"A": A_c, "B": B_c, "noise": random.uniform(0.015, 0.040)},
            "S": {"A": A_s, "B": B_s, "noise": random.uniform(0.015, 0.040)},
        }
        self.log(f"Sim-ADC 초기화: {self.tower} (HV는 실제 하드웨어, ADC만 시뮬레이션)")

    def _simulate_adc(self, channel: str, hv: float) -> float:
        p = self._sim_params[channel]
        base = p["A"] * math.exp(p["B"] * hv)
        # iteration이 늘수록 노이즈 감쇠
        itr = self.state.get("iterations", 0)
        effective_noise = p["noise"] / (1.0 + 0.5 * itr)
        return max(0.0, base + random.normalvariate(0.0, base * effective_noise))

    def _measure_adc(self, hv_c: float, hv_s: float, run_number: int) -> Tuple[Optional[float], Optional[float]]:
        """실제 run 데이터 대신 시뮬레이션 ADC를 반환 (유일한 차이점)."""
        return self._simulate_adc("C", hv_c), self._simulate_adc("S", hv_s)
