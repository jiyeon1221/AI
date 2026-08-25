#!/usr/bin/env python3
"""인접 타워의 가우시안 응답을 재현하는 Position Scan peakADC 모델."""

import math
import random
from typing import Optional


class PositionScanPeakADCSimMixin:
    """PositionScanAgent의 peakADC 측정을 시뮬레이션으로 대체한다."""

    def _init_peakadc_sim_model(self):
        interval = self.state["interval"]
        # 시뮬레이션용 타워 간격.
        self._sim_pitch = 46.333 if self.state["direction"] == "horizontal" else 50.0
        # 양방향 스윕이 공유할 실제 중심을 추정값 근처에 정한다.
        base = self.state["est_center"][self._axis_key()]
        self._sim_true_center = base + random.uniform(-0.4, 0.4) * interval
        self._sim_peak = random.uniform(1000.0, 1500.0)
        self._sim_sigma = self._sim_pitch * 0.7
        self._sim_noise = 0.01  # 1% 가우시안 노이즈.
        self.log(
            f"[SIM] peakADC model: true_center({self._axis_key()})={self._sim_true_center:.3f}, "
            f"pitch={self._sim_pitch}, peak={self._sim_peak:.1f}, sigma={self._sim_sigma:.2f}"
        )

    def _measure_peakadc(self, run_number: int, tower: str, channel: str) -> Optional[float]:
        coord = self._current_axis_coord()
        if tower == self.state["center_tower"]:
            mu = self._sim_true_center
        else:
            # 이웃 타워 중심은 스윕 방향으로 한 간격 떨어져 있다.
            mu = self._sim_true_center + self._current_sign() * self._sim_pitch
        base = self._sim_peak * math.exp(-((coord - mu) ** 2) / (2.0 * self._sim_sigma ** 2))
        val = base + random.normalvariate(0.0, self._sim_peak * self._sim_noise)
        return max(0.0, val)
