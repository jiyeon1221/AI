#!/usr/bin/env python3
"""지수형 PMT 이득과 채널별 감도를 재현하는 HV ADC 시뮬레이션 모델."""

import math
import random
from typing import Dict

# 실제 HV 조정과 공유하는 수렴 허용 오차.
from tools.hv_equalization_tool import ADC_TOLERANCE

# PMT 이득 곡선의 지수 계수 범위.
B_RANGE = (0.0060, 0.0080)
# 지수 계수 A의 기준 HV.
REF_HV_RANGE = (750.0, 800.0)
# 기준 HV에서 목표 ADC 대비 초기 출력 비율.
INITIAL_FRACTION_RANGE = (0.35, 0.70)
NOISE_RANGE = (0.015, 0.040)

DEFAULT_TARGET_ADC = 1230.0


def make_channel_params(target_adc: float = DEFAULT_TARGET_ADC) -> Dict[str, Dict[str, float]]:
    """C/S 채널의 (A, B, noise) 한 세트를 뽑는다."""
    params = {}
    for ch in ("C", "S"):
        b = random.uniform(*B_RANGE)
        ref_hv = random.uniform(*REF_HV_RANGE)
        frac = random.uniform(*INITIAL_FRACTION_RANGE)
        params[ch] = {
            "A": frac * target_adc / math.exp(b * ref_hv),
            "B": b,
            "noise": random.uniform(*NOISE_RANGE),
        }
    return params


def simulate_adc(params: Dict[str, float], hv: float, iteration: int = 0) -> float:
    """한 채널의 ADC 측정값. iteration이 늘수록 노이즈가 줄어든다(수렴 흉내)."""
    base = params["A"] * math.exp(params["B"] * hv)
    effective_noise = params["noise"] / (1.0 + 0.5 * iteration)
    return max(0.0, base + random.normalvariate(0.0, base * effective_noise))


def hv_for_target(params: Dict[str, float], target_adc: float) -> int:
    """목표 ADC를 내는 HV (모델 역함수)."""
    return int(round(math.log(target_adc / params["A"]) / params["B"]))


def is_converged(adc: float, target_adc: float, tolerance: float = ADC_TOLERANCE) -> bool:
    return abs(adc - target_adc) / target_adc < tolerance
