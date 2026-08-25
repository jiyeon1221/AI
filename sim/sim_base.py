#!/usr/bin/env python3
"""Simulation Agent가 공유하는 도구 호출과 DAQ 실행 로직."""

from typing import Any, Dict, Optional, Tuple


class SimExecMixin:
    """sim agent 공통 tool 실행 헬퍼. self._sim / self.io / self.state 를 가진
    sim agent에 믹스인한다."""

    def _sim_emit_tool_call(self, tool_name: str, params: Dict[str, Any]) -> None:
        """확정된 params로 tool-call 헤더 출력 (우측 패널 표시용)."""
        self.io.send_tool_output(self._sim.format_tool_call(tool_name, params))

    def _sim_run_daq(
        self,
        params: Dict[str, Any],
        *,
        events: Any,
        beam_energy: Any,
        program: str,
        pos: Optional[Dict[str, float]] = None,
        pos_rot: float = 0.0,
        pos_tilt: float = 0.0,
        daq_config: Optional[str] = None,
    ) -> Tuple[str, Optional[int]]:
        """DAQ 공통 실행: params override → 표시 → 실행 → run# 추출 → plot 대기.
        (result, run_number)를 반환. agent별 부킹은 호출부에서 run_number로 처리."""
        self._apply_daq_params_from_state(
            params,
            events=events,
            beam_energy=beam_energy,
            program=program,
            pos=pos,
            pos_rot=pos_rot,
            pos_tilt=pos_tilt,
            config=daq_config,
        )
        # 확정된 시뮬레이션 매개변수를 표시한다.
        self._sim_emit_tool_call("daq_run_tool", params)
        result = self._sim.daq_run(params, line_callback=self.io.send_tool_output)
        run_number = self._extract_run_number(result)
        # 플롯 확인 전에는 완료 상태 변경을 막는다.
        self.state["needs_plot_confirm"] = True
        return result, run_number
