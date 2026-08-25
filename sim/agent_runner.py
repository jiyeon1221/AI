#!/usr/bin/env python3
"""공통 실행 흐름에 모의 Agent와 도구를 연결하는 Simulation Runner."""

import threading

from agents.agent_runner import (
    AgentFactory,
    AgentRunner,
    shared_locks,
    shared_state,
)
from agents.brain_agent import run_brain_thread
from sim.tool_simulator import get_simulator


class SimFactory(AgentFactory):
    """모든 도구를 모의 구현으로 제공하는 Agent Factory."""

    tag = "[SIM] "

    def energy_agent(self):
        from sim.energy_scan_agent import EnergyScanSimAgent
        return EnergyScanSimAgent

    def calib_agent(self):
        from sim.calib_scan_agent import CalibScanSimAgent
        return CalibScanSimAgent

    def hv_agent(self, agent_name: str):
        from sim.hv_equalization_agent import HVEqualizationSimAgent
        return HVEqualizationSimAgent

    def position_agent(self, agent_name: str):
        from sim.position_scan_agent import PositionScanSimAgent
        return PositionScanSimAgent

    def hv_start(self, io, target_adc, tower):
        result = get_simulator().hv_equalization_start(
            target_c=target_adc, target_s=target_adc, tower=tower,
        )
        io.send_tool_output(result)

    def finalize_hv(self, io):
        io.send_ai_message("모든 타워 HV Equalization이 완료되었습니다. [SIM]")
        io.send_status("✅ [SIM] fixed_hv.txt 업데이트 건너뜀 (sim mode)")


class AgentRunnerSim(AgentRunner):
    """Web simulation runner — AgentRunner와 동일한 API/orchestration, mock tools only."""

    factory = SimFactory()

    def start_brain(self, use_base_model: bool = False):
        if self.brain_ready:
            return

        from sim.brain_agent import BrainAgentSim

        self._brain_stop.clear()
        self._brain_agent = BrainAgentSim(
            shared_state=shared_state,
            shared_locks=shared_locks,
            use_base_model=use_base_model,
        )
        self._brain_agent.load()

        self._brain_thread = threading.Thread(
            target=run_brain_thread,
            args=(
                self._brain_agent,
                self.adhoc_queue,
                self.output_queue,
                self._brain_stop,
                self.confirm_queue,
                self.clarify_queue,
            ),
            daemon=True,
        )
        self._brain_thread.start()

    def stop(self):
        """Sim mode — DAQ KILLME 없이 agent thread만 중지."""
        self.stop_event.set()
        self.input_queue.put("종료")
