#!/usr/bin/env python3
"""Calibration Scan Agent — 모든 타워(T1-T9)를 돌며 데이터 수집 자동화"""

import json
import sys
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from tools.daq_tool import DAQRunTool
import tools.motor_control_tool as motor

from .base_agent import BaseAgent
sys.path.append(str(Path(__file__).parent.parent))
from config import AGENT_MODELS, MSG_PLOT_CONFIRM


class CalibScanAgent(BaseAgent):
    def __init__(
        self,
        tower_order: Optional[list] = None,
        beam_energy: Optional[float] = None,
        target_events: Optional[int] = None,
        daq_config: str = "setup",
        use_base_model: bool = True,
        io_handler=None,
    ):
        model_config = AGENT_MODELS["calibration"]
        if use_base_model:
            model_path = model_config["base_model"]
            print(f"⚠️  Base model 사용 ({model_path})")
        else:
            fine_tuned_path = Path(model_config["fine_tuned_path"])
            if fine_tuned_path.exists() and (fine_tuned_path / "config.json").exists():
                model_path = str(fine_tuned_path)
                print(f"✅ Fine-tuned model 사용 ({model_path})")
            else:
                model_path = model_config["base_model"]
                print(f"⚠️  Fine-tuned 모델 없음. Base model 사용 ({model_path})")

        super().__init__(
            model_path=model_path,
            agent_name="Calibration",
            io_handler=io_handler,
        )

        self.daq_tool = DAQRunTool()

        # 타워 순서는 agent_runner에서 전달 — fallback으로 기본 지그재그 사용
        self.tower_order = tower_order if tower_order is not None else ["T1", "T2", "T3", "T6", "T5", "T4", "T7", "T8", "T9"]
        
        # Calibration은 rot=0, tilt=0 고정
        self.tower_positions = {}
        from tools.position_calculator_tool import get_calculator
        calc = get_calculator()
        for tower in self.tower_order:
            pos = calc.calculate_tower_position(tower, rotation=0.0, tilting=0.0)
            if pos:
                self.tower_positions[tower] = pos
            else:
                print(f"⚠️  Warning: {tower} 위치 계산 실패")

        self.state = {
            "phase": "config" if beam_energy is None or target_events is None else "idle",
            "beam_energy": beam_energy,
            "target_events": target_events,
            "daq_config": daq_config,
            
            "tower_order": self.tower_order,
            "current_tower_idx": 0,
            
            "tower_status": {
                tower: {
                    "collected_events": 0,
                    "runs": [],
                    "completed": False,
                    "completed_at": None,
                    "x_moved": False,
                    "y_confirmed": False,
                }
                for tower in self.tower_order
            },
            
            "start_time": datetime.now().isoformat(),
            "plot_method": "PeakADC",
            "needs_plot_confirm": False,
        }
        
        self.log(f"Calibration Scan Agent 초기화: Energy={beam_energy}, Events={target_events}")

    def _get_system_prompt(self) -> str:
        """System prompt (workflow 정의 - EnergyScanAgent와 통일)"""
        return """You are Calibration Scan Agent for test beam experiments.

Follow these steps EXACTLY:

=== STEP 0: Configuration ===
- If 'beam_energy' is null: Request energy from user.
  Output: {"message": "에너지를 입력하세요."}
- After energy is provided: Update 'beam_energy' and request event count.
  CRITICAL: beam_energy is in GeV. Store the number exactly as user inputs. (e.g. user inputs "2" → beam_energy: 2, NOT 2000)
  Output: {"message": "이벤트를 몇개 받을까요?", "update_state": {"beam_energy": <number in GeV>, "phase": "config_events"}}
- After event count is provided: Update 'target_events' and set phase to 'idle'.
  Output: {"tool": "none", "update_state": {"target_events": <number>, "phase": "idle"}}

=== STEP 1: For Each Tower in tower_order (REPEAT for T1-T9) ===
Repeat steps 1a-1c for each tower in tower_order until all towers are completed.

1a-i. Move X-axis automatically (no user input needed):
  Output: {"tool": "motor_x_move_tool", "params": {"x": <x from state>}}

1a-ii. After motor tool completes, ask user to move Y-axis manually:
  Output: {"message": "X축 자동 이동 완료 (<x> mm). Y축을 <y>으로 이동해주세요."}
  (Replace <x>, <y> with the CURRENT tower's position from state)

After user says "완료" to the Y-axis message:
The SYSTEM marks Y-axis confirmed automatically — you do NOT output any state update.
Just proceed to STEP 1b (the step hint will say "daq_run_tool").

1b. Execute DAQ
Tool: "daq_run_tool"
Params: {
    "events": <target_events from state>,
    "pos_h": <x>,
    "pos_v": <y>,
    "pos_rot": 0.0,
    "pos_tilt": 0.0,
    "beam_energy": <beam_energy from state>
}
(Plot is auto-rendered by DQM live during DAQ — never call any plot tool.)

1c. Request Plot Confirmation (only AFTER the DAQ tool has run):
Output: {"message": "데이터 수집 및 Plot 생성이 완료되었습니다. 결과를 확인해주세요."}

After user says "완료" to the plot message:
The SYSTEM marks the current tower completed and advances to the next tower automatically — you do NOT output any state update.
Proceed to the next tower's STEP 1a-i (or, if all done, the SYSTEM ends the session).

=== STEP 2: Completion ===
When ALL towers are completed, the SYSTEM sends the completion message and ends the session automatically.

=== CRITICAL RULES ===
1. Follow steps STRICTLY in order. Do NOT skip or reorder steps.
2. Step 1a-i ALWAYS comes before 1a-ii for every tower.
3. The SYSTEM (not you) owns all bookkeeping: x_moved, y_confirmed, tower "completed", current_tower_idx, and session termination. NEVER output update_state for these — only the step hint tells you the next action.
4. Output JSON format (CHOOSE ONE, NEVER BOTH "tool" and "message"):
   - {"tool": "...", "params": {...}}        (tool execution)
   - {"message": "..."}                        (user message)
   - {"tool": "none", "update_state": {...}}   (ONLY for STEP 0 config: beam_energy / target_events / phase)
5. When the step hint says a user already answered during config, parse it immediately — do NOT re-ask.
"""

    def _get_step_hint(self) -> str:
        """현재 상태 요약 - AI가 학습을 통해 다음 단계를 스스로 결정"""
        phase = self.state.get("phase", "config")

        # STEP 0: beam_energy/target_events가 설정 안 됐으면 사용자에게 먼저 물어야 한다.
        # phase 무시하고 STEP 1로 가버리는 것을 막기 위해 명시적으로 안내.
        # 마지막 대화가 user 응답인지 확인 — 이미 답한 경우엔 parse 지시
        _last_user = None
        for _msg in reversed(self.conversation_history):
            if _msg["role"] == "user":
                _last_user = _msg["content"]
                break

        if self.state.get("beam_energy") is None:
            if _last_user:
                return (f"Phase: config | User just provided beam energy: '{_last_user}'. "
                        "REQUIRED NEXT: parse it and output "
                        "{\"message\": \"이벤트를 몇개 받을까요?\", \"update_state\": {\"beam_energy\": <number>, \"phase\": \"config_events\"}}. "
                        "DO NOT ask for energy again.")
            return "Phase: config | REQUIRED NEXT: ask user for beam energy (STEP 0). Do NOT call motor tool yet."
        if self.state.get("target_events") is None:
            if _last_user:
                return (f"Phase: config_events | beam_energy={self.state['beam_energy']} | "
                        f"User just provided event count: '{_last_user}'. "
                        "REQUIRED NEXT: parse it and output "
                        "{\"tool\": \"none\", \"update_state\": {\"target_events\": <number>, \"phase\": \"idle\"}}. "
                        "DO NOT ask for event count again.")
            return (f"Phase: config_events | beam_energy={self.state['beam_energy']} | "
                    "REQUIRED NEXT: ask user for event count (STEP 0). Do NOT call motor tool yet.")

        # STEP 1+: config 끝난 경우만 진입
        tower_idx = self.state.get("current_tower_idx", 0)
        total = len(self.tower_order)
        if tower_idx < total:
            tower = self.tower_order[tower_idx]
            status = self.state["tower_status"].get(tower, {})
            if not status.get("x_moved"):
                return f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | REQUIRED NEXT: motor_x_move_tool (step 1a-i)"
            elif not status.get("y_confirmed"):
                # Y축 확인은 사용자 '완료' 시 코드가 처리. 모델은 Y 이동 메시지만 출력.
                return f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | REQUIRED NEXT: Y-axis move message (step 1a-ii)"
            elif not status.get("runs"):
                return f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | REQUIRED NEXT: daq_run_tool (step 1b)"
            elif self.state.get("needs_plot_confirm"):
                last_run = status["runs"][-1]
                return (f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | "
                        f"DAQ done (Run {last_run}) — REQUIRED NEXT: plot confirmation message (step 1c). "
                        f"DO NOT call daq_run_tool or motor_x_move_tool. 완료 시 시스템이 자동으로 완료 처리한다.")
            # runs exist + needs_plot_confirm=False → should already be completed; guard prevents loops
            return (f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | "
                    f"needs_plot_confirm=False — DO NOT call any tool or send plot confirmation.")
        return f"Phase: {phase} | All towers completed — system will terminate automatically"

    # Fields that can never be overwritten by the LLM under any circumstances.
    # (init-only config + code-owned bookkeeping)
    _ALWAYS_PROTECTED = frozenset({
        "tower_order", "start_time", "plot_method", "daq_config",
        "needs_plot_confirm", "last_run_number",
    })
    # Fields that become read-only once set (not None/0).
    # During STEP 0 config phase they're None → LLM is allowed to initialise them.
    # After STEP 0 they hold real values → any further LLM change is rejected.
    _ONCE_SET_PROTECTED = frozenset({"beam_energy", "target_events"})

    def _recompute_tower_idx(self):
        """current_tower_idx = 완료된 타워 수 (tower_status 기준 자동 관리)."""
        completed_count = sum(
            1 for s in self.state["tower_status"].values() if s.get("completed")
        )
        self.state["current_tower_idx"] = completed_count

    def _update_state(self, updates: Dict[str, Any]):
        """State 업데이트"""
        for key, value in updates.items():
            if key == "tower_status" and isinstance(value, dict):
                for t, v in value.items():
                    if t in self.state["tower_status"]:
                        # completed/runs/collected_events/x_moved/y_confirmed는 코드 소유.
                        # 완료 표시는 _on_user_input(plot 확인)에서만 일어난다.
                        safe_v = {
                            k: val for k, val in v.items()
                            if k not in ("completed", "completed_at", "runs",
                                         "collected_events", "x_moved", "y_confirmed")
                        }
                        if any(k in v for k in ("completed", "y_confirmed", "x_moved")):
                            self.log(f"WARNING: LLM tried to set code-owned field on {t} — rejected")
                        self.state["tower_status"][t].update(safe_v)
                        self.log(f"State updated: tower_status[{t}] = {safe_v}")
                self._recompute_tower_idx()
            elif key == "current_tower_idx":
                # tower_status 기반 자동 관리 — LLM 직접 설정 무시
                self.log(f"current_tower_idx 직접 설정 무시 (tower_status 기반 자동 관리)")
            elif key in self._ALWAYS_PROTECTED:
                self.log(f"WARNING: LLM tried to update protected field '{key}' = {value} — rejected")
            elif key in self._ONCE_SET_PROTECTED and self.state.get(key) is not None:
                # Already initialised → reject mid-scan changes
                self.log(f"WARNING: LLM tried to overwrite already-set '{key}' = {value} — rejected")
            else:
                self.state[key] = value
                self.log(f"State updated: {key} = {value}")

    def _position_for_current_step(self) -> Optional[Dict[str, float]]:
        """current_tower_idx 기준 — 타워마다 x/y가 다름."""
        tower = self.tower_order[self.state["current_tower_idx"]]
        return self.tower_positions.get(tower)

    def _current_tower_name(self) -> str:
        return self.tower_order[self.state["current_tower_idx"]]

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        """Tool 실행"""
        if tool_name == "none":
            return "no_tool_executed"

        elif tool_name == "motor_x_move_tool":
            tower = self._current_tower_name()
            x = self._motor_x_for_current_step()
            self.io.send_tool_output(f"[Motor] X축 이동 시작 ({tower}): {x:.3f} mm")
            def _do_move():
                ok, msg = motor.move_x(x)
                if not ok:
                    raise RuntimeError(msg)
                return msg
            result = self._run_tool_with_retry(_do_move, "motor_x_move_tool")
            self.io.send_tool_output(f"[Motor] {result}")
            self.state["tower_status"][tower]["x_moved"] = True
            return result

        elif tool_name == "daq_run_tool":
            tower = self._current_tower_name()
            pos = self._position_for_current_step()
            self._apply_daq_params_from_state(
                params,
                events=self.state.get("target_events"),
                beam_energy=self.state.get("beam_energy"),
                program="Calibration",
                pos=pos,
            )

            # DAQ 실행. daq_tool 내부에서 dqm_session.start()이 monit --LIVE를 띄워
            # DAQ 동안 우측 하단 DQM 패널이 실시간 갱신된다 — 여기가 유일한 플롯 경로.
            result = self._run_tool_with_retry(
                lambda: self.daq_tool.execute(params, line_callback=self.io.send_tool_output),
                "daq_run_tool",
            )

            run_number = self._extract_run_number(result)
            if run_number:
                self.state['last_run_number'] = run_number
                self.state['tower_status'][tower]['runs'].append(run_number)
                self.state['tower_status'][tower]['collected_events'] = params.get('events', 0)
                self.log(f"DAQ Run {run_number} 완료: {tower} 타워, {params.get('events', 0)} events")
            # 사용자 plot 확인 전까지 completed=True 차단
            self.state['needs_plot_confirm'] = True
            return result

        return f"Error: Unknown tool {tool_name}"

    def _guard_tool(self, tool_name: str, decision) -> Optional[str]:
        # 1. plot confirm 필요 시 모든 tool 차단
        if self.state.get("needs_plot_confirm"):
            return (
                f"needs_plot_confirm=True — DO NOT call {tool_name}. "
                f'Send: {{"message": "{MSG_PLOT_CONFIRM}"}}'
            )
        idx = self.state.get("current_tower_idx", 0)
        if idx >= len(self.tower_order):
            return None
        tower = self.tower_order[idx]
        st = self.state["tower_status"].get(tower, {})
        # 2. motor 이미 완료된 타워에 재호출 차단
        if tool_name == "motor_x_move_tool" and st.get("x_moved"):
            return f"{tower} X-axis already moved. Send Y-axis move message. {self._get_step_hint()}"
        # 3. Y축 미확인 시 DAQ 차단
        if tool_name == "daq_run_tool" and not st.get("y_confirmed"):
            return f"{tower} Y-axis not confirmed. Send Y-axis move message first. {self._get_step_hint()}"
        return None

    def _guard_ai_message(self, message: str) -> Optional[str]:
        if MSG_PLOT_CONFIRM in message and not self.state.get("needs_plot_confirm"):
            return f"needs_plot_confirm=False — DO NOT send plot confirmation. {self._get_step_hint()}"
        return None

    def _format_progress(self) -> str:
        """현재 진행 상황을 문자열로 반환 (AI 메시지용)"""
        done = sum(1 for s in self.state['tower_status'].values() if s.get('completed'))
        total = len(self.tower_order)
        lines = [
            f"📊 Calibration Scan  —  {done} / {total} 타워 완료",
            "─" * 36,
        ]
        for i, tower in enumerate(self.tower_order):
            status = self.state['tower_status'][tower]
            if status['completed']:
                runs_str = ', '.join(str(r) for r in status['runs']) if status['runs'] else '-'
                lines.append(f"  ✅  {tower}   Run {runs_str}")
            else:
                lines.append(f"       {tower}")
        lines.append("─" * 36)
        return "\n".join(lines)

    # ===== 공용 드라이버 hooks (run()은 BaseAgent에서 제공) =====

    def _print_banner(self):
        print(f"\n{'='*70}\n⚡ Calibration Scan Agent Started\n{'='*70}")

    def _print_summary(self):
        """현재 진행 상황 요약 출력 (CLI용)"""
        print(f"\n📊 Calibration Progress Summary:")
        print("-" * 70)
        print(f"Energy: {self.state['beam_energy']} GeV | Target: {self.state['target_events']} events/tower")
        print("-" * 70)
        for i, tower in enumerate(self.tower_order):
            status = self.state['tower_status'][tower]
            pos = self.tower_positions.get(tower, {'x': 0, 'y': 0})
            mark = "✅" if status['completed'] else ("➡️ " if i == self.state['current_tower_idx'] else "  ")
            run_info = f" (Runs: {status['runs']})" if status['runs'] else ""
            print(f"  {mark} {tower} (x:{pos['x']:.3f}, y:{pos['y']:.3f}): {'Completed' if status['completed'] else 'Pending'}{run_info}")
        print("-" * 70)

    def _pre_iteration(self):
        self._print_summary()

    def _is_complete(self) -> bool:
        # config가 끝나야(=energy/events 설정) 완료 판정. 그 전엔 모두 미완료라 자동 False.
        if self.state.get("beam_energy") is None or self.state.get("target_events") is None:
            return False
        return all(s.get("completed", False) for s in self.state["tower_status"].values())

    def _completion_message(self) -> Optional[str]:
        return "모든 타워에 대한 스캔이 완료되었습니다."

    def _completed_count(self) -> int:
        return sum(1 for s in self.state["tower_status"].values() if s.get("completed"))

    def _progress_message(self) -> Optional[str]:
        return self._format_progress()

    def _on_user_input(self, user_input: str):
        idx = self.state.get("current_tower_idx", 0)
        if idx >= len(self.tower_order):
            return
        tower = self.tower_order[idx]
        st = self.state["tower_status"][tower]
        # 1) Y축 이동 확인 → 코드가 직접 처리
        if st.get("x_moved") and not st.get("y_confirmed"):
            st["y_confirmed"] = True
            self.log(f"{tower} Y-axis confirmed by user")
            return
        # 2) DAQ 후 plot 확인 → 현재 타워 완료 처리 (코드가 소유)
        if self.state.get("needs_plot_confirm"):
            self.state["needs_plot_confirm"] = False
            if st.get("runs"):
                st["completed"] = True
                st.setdefault("completed_at", datetime.now().strftime("%H:%M:%S"))
                self._recompute_tower_idx()
                self.log(f"{tower} plot 확인 완료 → completed")

    def build_full_context(self, current_input: Optional[str] = None) -> str:
        """전체 context 생성 (EnergyScanAgent와 통일)"""
        if current_input is None and self.conversation_history:
            if self.conversation_history[-1]["role"] == "user":
                current_input = self.conversation_history[-1]["content"]
                temp_history = self.conversation_history[:-1]
            else:
                temp_history = self.conversation_history
        else:
            temp_history = self.conversation_history

        parts = []
        parts.append("=== Current State ===")
        parts.append(self._build_state_context())
        parts.append("")
        parts.append("=== Recent Conversation ===")
        history_lines = []
        if not temp_history:
            history_lines.append("(No conversation yet)")
        else:
            for msg in temp_history[-10:]:
                role = "User" if msg["role"] == "user" else "Agent"
                history_lines.append(f"{role}: {msg['content']}")
        parts.append("\n".join(history_lines))
        parts.append("")
        
        if current_input:
            parts.append("=== Current User Input ===")
            parts.append(current_input)
            parts.append("")
        
        parts.append("=== Your Task ===")
        parts.append(self._get_step_hint())
        parts.append("")
        parts.append("Output JSON with tool name and parameters.")
        return "\n".join(parts)

    def _build_state_context(self) -> str:
        """State를 문자열로 변환 (EnergyScanAgent와 통일)"""
        lines = []
        lines.append(f"Phase: {self.state['phase']}")
        lines.append(f"Beam Energy: {self.state['beam_energy']} GeV")
        lines.append(f"Target Events: {self.state['target_events']}")
        lines.append(f"needs_plot_confirm: {self.state.get('needs_plot_confirm', False)}")
        lines.append("")
        lines.append("Tower Progress:")
        for i, tower in enumerate(self.tower_order):
            status = self.state['tower_status'][tower]
            pos = self.tower_positions.get(tower, {'x': 0, 'y': 0})
            if status['completed']:
                lines.append(f"  ✅ {tower} (x:{pos['x']:.3f}, y:{pos['y']:.3f}): Completed (Runs: {status['runs']})")
            elif i == self.state['current_tower_idx']:
                x_tag = " [X moved]" if status.get("x_moved") else ""
                y_tag = " [Y confirmed - proceed to DAQ]" if status.get("y_confirmed") else ""
                lines.append(f"  ➡️  {tower} (x:{pos['x']:.3f}, y:{pos['y']:.3f}): Pending{x_tag}{y_tag}  <- CURRENT (target: {self.state['target_events']} events)")
            else:
                lines.append(f"     {tower} (x:{pos['x']:.3f}, y:{pos['y']:.3f}): Pending")
        return "\n".join(lines)
