#!/usr/bin/env python3
"""
Training data generator for CalibScanAgent

Code-authoritative bookkeeping (calib_scan_agent.py와 동일):
  - 위치/확인/완료 플래그(x_moved, y_confirmed, tower completed, current_tower_idx,
    종료)는 드라이버(코드)가 소유한다. 모델은 message와 tool 호출만 출력한다.
  - 따라서 예전의 y_confirmed / completed "tool:none" 턴과 최종 완료 메시지 턴은
    학습 데이터에서 제거한다 (시스템이 처리).

build_full_context / _build_state_context / _get_step_hint 포맷이
CalibScanAgent와 완전히 동일하도록 유지.
"""

import json
import random
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MSG_PLOT_CONFIRM

TOWER_ORDER = ["T1", "T2", "T3", "T6", "T5", "T4", "T7", "T8", "T9"]

MESSAGE_ENERGY_REQ = "에너지를 입력하세요."
MESSAGE_EVENTS_REQ = "이벤트를 몇개 받을까요?"
MESSAGE_Y_MOVE_REQ = "X축 자동 이동 완료 ({x:.3f} mm). Y축을 {y:.3f}으로 이동해주세요."
MESSAGE_PLOT_CONFIRM = MSG_PLOT_CONFIRM

SYSTEM_PROMPT = """You are Calibration Scan Agent for test beam experiments.

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


def random_events():
    digits = random.randint(3, 6)
    return random.randint(10 ** (digits - 1), 10 ** digits - 1)


def _build_state_context(state: Dict, tower_positions: Dict) -> str:
    lines = []
    lines.append(f"Phase: {state['phase']}")
    lines.append(f"Beam Energy: {state['beam_energy']} GeV")
    lines.append(f"Target Events: {state['target_events']}")
    lines.append(f"needs_plot_confirm: {state.get('needs_plot_confirm', False)}")
    lines.append("")
    lines.append("Tower Progress:")
    for i, tower in enumerate(TOWER_ORDER):
        status = state["tower_status"][tower]
        pos = tower_positions.get(tower, {"x": 0, "y": 0})
        if status["completed"]:
            lines.append(f"  ✅ {tower} (x:{pos['x']:.3f}, y:{pos['y']:.3f}): Completed (Runs: {status['runs']})")
        elif i == state["current_tower_idx"]:
            x_tag = " [X moved]" if status.get("x_moved") else ""
            y_tag = " [Y confirmed - proceed to DAQ]" if status.get("y_confirmed") else ""
            lines.append(
                f"  ➡️  {tower} (x:{pos['x']:.3f}, y:{pos['y']:.3f}): Pending{x_tag}{y_tag}  <- CURRENT "
                f"(target: {state['target_events']} events)"
            )
        else:
            lines.append(f"     {tower} (x:{pos['x']:.3f}, y:{pos['y']:.3f}): Pending")
    return "\n".join(lines)


def _build_history_context(history: List[Dict]) -> str:
    if not history:
        return "(No conversation yet)"
    lines = []
    for msg in history[-10:]:
        role = "User" if msg["role"] == "user" else "Agent"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def _last_user(history: List[Dict]) -> Optional[str]:
    for msg in reversed(history):
        if msg["role"] == "user":
            return msg["content"]
    return None


def _get_step_hint(state: Dict, history: List[Dict]) -> str:
    """CalibScanAgent._get_step_hint와 문자 단위로 동일해야 한다."""
    phase = state.get("phase", "config")
    lu = _last_user(history)

    if state.get("beam_energy") is None:
        if lu:
            return (f"Phase: config | User just provided beam energy: '{lu}'. "
                    "REQUIRED NEXT: parse it and output "
                    "{\"message\": \"이벤트를 몇개 받을까요?\", \"update_state\": {\"beam_energy\": <number>, \"phase\": \"config_events\"}}. "
                    "DO NOT ask for energy again.")
        return "Phase: config | REQUIRED NEXT: ask user for beam energy (STEP 0). Do NOT call motor tool yet."
    if state.get("target_events") is None:
        if lu:
            return (f"Phase: config_events | beam_energy={state['beam_energy']} | "
                    f"User just provided event count: '{lu}'. "
                    "REQUIRED NEXT: parse it and output "
                    "{\"tool\": \"none\", \"update_state\": {\"target_events\": <number>, \"phase\": \"idle\"}}. "
                    "DO NOT ask for event count again.")
        return (f"Phase: config_events | beam_energy={state['beam_energy']} | "
                "REQUIRED NEXT: ask user for event count (STEP 0). Do NOT call motor tool yet.")

    tower_idx = state.get("current_tower_idx", 0)
    total = len(TOWER_ORDER)
    if tower_idx < total:
        tower = TOWER_ORDER[tower_idx]
        status = state["tower_status"].get(tower, {})
        if not status.get("x_moved"):
            return f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | REQUIRED NEXT: motor_x_move_tool (step 1a-i)"
        elif not status.get("y_confirmed"):
            return f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | REQUIRED NEXT: Y-axis move message (step 1a-ii)"
        elif not status.get("runs"):
            return f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | REQUIRED NEXT: daq_run_tool (step 1b)"
        elif state.get("needs_plot_confirm"):
            last_run = status["runs"][-1]
            return (f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | "
                    f"DAQ done (Run {last_run}) — REQUIRED NEXT: plot confirmation message (step 1c). "
                    f"DO NOT call daq_run_tool or motor_x_move_tool. 완료 시 시스템이 자동으로 완료 처리한다.")
        return (f"Phase: {phase} | Tower: {tower} ({tower_idx+1}/{total}) | "
                f"needs_plot_confirm=False — DO NOT call any tool or send plot confirmation.")
    return f"Phase: {phase} | All towers completed — system will terminate automatically"


def build_full_context(state: Dict, history: List[Dict], tower_positions: Dict,
                       current_input: Optional[str] = None) -> str:
    if current_input is None and history and history[-1]["role"] == "user":
        current_input = history[-1]["content"]
        temp_history = history[:-1]
    else:
        temp_history = history

    parts = ["=== Current State ===", _build_state_context(state, tower_positions), ""]
    parts.append("=== Recent Conversation ===")
    parts.append(_build_history_context(temp_history))
    parts.append("")
    if current_input:
        parts.append("=== Current User Input ===")
        parts.append(current_input)
        parts.append("")
    parts.append("=== Your Task ===")
    parts.append(_get_step_hint(state, history))
    parts.append("")
    parts.append("Output JSON with tool name and parameters.")
    return "\n".join(parts)


def make_example(state, history, tower_positions, decision, current_input=None):
    ctx = build_full_context(state, history, tower_positions, current_input)
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ctx},
            {"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)},
        ]
    }


def _init_tower_status():
    return {t: {"x_moved": False, "y_confirmed": False, "collected_events": 0, "runs": [], "completed": False} for t in TOWER_ORDER}


def _random_tower_positions():
    return {
        t: {"x": round(random.uniform(70.0, 130.0), 3), "y": round(random.uniform(70.0, 130.0), 3)}
        for t in TOWER_ORDER
    }


def _emit_tower(examples, state, history, tower_positions, tower, events, run_number):
    """한 타워의 모델 결정 턴(motor → Y msg → DAQ → plot msg)을 생성.
    y_confirmed / completed 는 코드(시스템)가 소유하므로 모델 턴으로 만들지 않는다."""
    pos = tower_positions[tower]

    # 1a-i: motor X move
    dec = {"tool": "motor_x_move_tool", "params": {"x": pos["x"]}}
    examples.append(make_example(state, history, tower_positions, dec))
    history.append({"role": "assistant", "content": json.dumps(dec, ensure_ascii=False)})
    state["tower_status"][tower]["x_moved"] = True

    # 1a-ii: Y move message (update_state 없음)
    dec = {"message": MESSAGE_Y_MOVE_REQ.format(x=pos["x"], y=pos["y"])}
    examples.append(make_example(state, history, tower_positions, dec))
    history.append({"role": "assistant", "content": json.dumps(dec, ensure_ascii=False)})
    history.append({"role": "user", "content": "완료"})
    # 시스템이 Y 확인 처리 (모델 턴 없음)
    state["tower_status"][tower]["y_confirmed"] = True

    # 1b: DAQ
    dec = {"tool": "daq_run_tool", "params": {
        "events": events,
        "pos_h": pos["x"], "pos_v": pos["y"],
        "pos_rot": 0.0, "pos_tilt": 0.0, "beam_energy": state["beam_energy"],
    }}
    examples.append(make_example(state, history, tower_positions, dec))
    history.append({"role": "assistant", "content": json.dumps(dec, ensure_ascii=False)})
    state["tower_status"][tower]["collected_events"] = events
    state["tower_status"][tower]["runs"].append(run_number)
    state["needs_plot_confirm"] = True

    # 1c: plot confirm message
    dec = {"message": MESSAGE_PLOT_CONFIRM}
    examples.append(make_example(state, history, tower_positions, dec))
    history.append({"role": "assistant", "content": json.dumps(dec, ensure_ascii=False)})
    history.append({"role": "user", "content": "완료"})
    # 시스템이 완료 처리 + idx 갱신 (모델 턴 없음)
    state["needs_plot_confirm"] = False
    state["tower_status"][tower]["completed"] = True
    state["current_tower_idx"] = sum(1 for s in state["tower_status"].values() if s["completed"])


def generate_workflow_normal(energy: float, events: int) -> List[Dict[str, Any]]:
    examples = []
    history = []
    tower_positions = _random_tower_positions()
    state = {
        "phase": "config",
        "beam_energy": None,
        "target_events": None,
        "current_tower_idx": 0,
        "tower_status": _init_tower_status(),
        "needs_plot_confirm": False,
    }

    # --- STEP 0 (config, model-owned) ---
    # 0a: ask energy
    dec = {"message": MESSAGE_ENERGY_REQ}
    examples.append(make_example(state, history, tower_positions, dec))
    history.append({"role": "assistant", "content": json.dumps(dec, ensure_ascii=False)})
    history.append({"role": "user", "content": str(int(energy))})

    # 0b: parse energy → ask events (state.beam_energy still None at decision time)
    dec = {"message": MESSAGE_EVENTS_REQ, "update_state": {"beam_energy": energy, "phase": "config_events"}}
    examples.append(make_example(state, history, tower_positions, dec))
    history.append({"role": "assistant", "content": json.dumps(dec, ensure_ascii=False)})
    state["beam_energy"] = energy
    state["phase"] = "config_events"
    history.append({"role": "user", "content": f"{events}개"})

    # 0c: parse events → idle (state.target_events still None at decision time)
    dec = {"tool": "none", "update_state": {"target_events": events, "phase": "idle"}}
    examples.append(make_example(state, history, tower_positions, dec))
    history.append({"role": "assistant", "content": json.dumps(dec, ensure_ascii=False)})
    state["target_events"] = events
    state["phase"] = "idle"

    # --- STEP 1 ---
    run_number = 100
    for i, tower in enumerate(TOWER_ORDER):
        _emit_tower(examples, state, history, tower_positions, tower, events, run_number)
        run_number += 1

    # STEP 2 완료 메시지는 시스템이 보낸다 — 모델 턴으로 만들지 않는다.
    return examples


def generate_workflow_from_mid(energy: float, events: int, start_idx: int) -> List[Dict[str, Any]]:
    """후반 타워부터 시작하는 partial 워크플로우."""
    examples = []
    tower_positions = _random_tower_positions()

    state = {
        "phase": "idle",
        "beam_energy": energy,
        "target_events": events,
        "current_tower_idx": start_idx,
        "tower_status": {
            t: {
                "x_moved": j < start_idx,
                "y_confirmed": j < start_idx,
                "collected_events": events if j < start_idx else 0,
                "runs": [1000 + j] if j < start_idx else [],
                "completed": j < start_idx,
            }
            for j, t in enumerate(TOWER_ORDER)
        },
        "needs_plot_confirm": False,
    }

    # 직전 1-2개 타워의 모델 결정 턴만 히스토리로 미리 채운다
    # (y_confirmed/completed 턴은 시스템 소유라 히스토리에도 넣지 않는다).
    history = []
    for j in range(max(0, start_idx - 2), start_idx):
        prev_tower = TOWER_ORDER[j]
        prev_pos = tower_positions[prev_tower]
        history.append({"role": "assistant", "content": json.dumps(
            {"tool": "motor_x_move_tool", "params": {"x": prev_pos["x"]}}, ensure_ascii=False)})
        history.append({"role": "assistant", "content": json.dumps(
            {"message": MESSAGE_Y_MOVE_REQ.format(x=prev_pos["x"], y=prev_pos["y"])}, ensure_ascii=False)})
        history.append({"role": "user", "content": "완료"})
        history.append({"role": "assistant", "content": json.dumps(
            {"tool": "daq_run_tool", "params": {"events": events,
             "pos_h": prev_pos["x"], "pos_v": prev_pos["y"],
             "pos_rot": 0.0, "pos_tilt": 0.0, "beam_energy": energy}}, ensure_ascii=False)})
        history.append({"role": "assistant", "content": json.dumps(
            {"message": MESSAGE_PLOT_CONFIRM}, ensure_ascii=False)})
        history.append({"role": "user", "content": "완료"})

    run_number = 1000 + start_idx
    for i in range(start_idx, len(TOWER_ORDER)):
        tower = TOWER_ORDER[i]
        state["current_tower_idx"] = i
        _emit_tower(examples, state, history, tower_positions, tower, events, run_number)
        run_number += 1

    return examples


def main():
    output_file = Path(__file__).parent / "data" / "calib_scan_data.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    all_ex = []

    ENERGIES = [1, 2, 5, 10, 20, 50, 100, 200]

    for energy in ENERGIES:
        for _ in range(4):
            events = random_events()
            all_ex.extend(generate_workflow_normal(energy, events))

    for _ in range(10):
        energy = random.choice(ENERGIES)
        events = random_events()
        all_ex.extend(generate_workflow_normal(energy, events))

    for energy in random.choices(ENERGIES, k=20):
        events = random_events()
        start_idx = random.choice([1, 2, 3, 4, 5, 6, 7])
        all_ex.extend(generate_workflow_from_mid(energy, events, start_idx))

    for _ in range(15):
        energy = random.choice(ENERGIES)
        events = random_events()
        start_idx = random.choice([1, 2, 3, 4, 5, 6, 7])
        all_ex.extend(generate_workflow_from_mid(energy, events, start_idx))

    with open(output_file, "w", encoding="utf-8") as f:
        for ex in all_ex:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    lengths = [sum(len(m["content"]) for m in ex["messages"]) for ex in all_ex]
    print(f"Generated {len(all_ex)} samples → {output_file}")
    print(f"   char len  max={max(lengths):,}  avg={sum(lengths)/len(lengths):,.0f}")


if __name__ == "__main__":
    main()
