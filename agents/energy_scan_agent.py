#!/usr/bin/env python3
"""Energy Scan Agent — 다양한 빔 에너지에서 데이터 수집 자동화"""

import json
import re
import sys
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from tools.daq_tool import DAQRunTool

from .base_agent import BaseAgent, format_event_count, extract_number_tokens, _normalize_thousands_commas
sys.path.append(str(Path(__file__).parent.parent))
from config import AGENT_MODELS, MSG_PLOT_CONFIRM


class EnergyScanAgent(BaseAgent):
    def __init__(
        self,
        energy_config: Dict[float, int],
        tower: str = "T5",
        position: Optional[Dict[str, float]] = None,
        daq_config: str = "setup",
        use_base_model: bool = True,  # 기본 모델 사용 여부.
        io_handler=None,
    ):
        model_config = AGENT_MODELS["energy_scan"]
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
            agent_name="EnergyScan",
            io_handler=io_handler,
        )
        
        self._init_energy_config = energy_config if energy_config else {}
        self.daq_tool = DAQRunTool()
        
        from tools.position_calculator_tool import get_calculator
        # 선택한 타워의 이동 위치를 계산한다.
        t5_pos = get_calculator().calculate_tower_position(tower, rotation=1.5, tilting=1.0)
        self.t5_x = t5_pos['x']
        self.t5_y = t5_pos['y']
        
        self.state = {
            "phase": "config" if not self._init_energy_config else "idle",
            "tower": tower,
            # DQM 실시간 캔버스가 참조하는 현재 타워.
            "current_tower": tower,
            "position": position,
            "daq_config": daq_config,
            "t5_x": self.t5_x,
            "t5_y": self.t5_y,

            "energy_config": {
                energy: {
                    "target_events": events,
                    "collected_events": 0,
                    "runs": [],
                    "completed": False,
                    "completed_at": None
                }
                for energy, events in self._init_energy_config.items()
            },

            "scan_order": sorted(list(self._init_energy_config.keys())),
            "current_energy": None,
            "current_energy_idx": 0,

            "start_time": datetime.now().isoformat(),
            "plot_method": "PeakADC",
            "plot_max_event": None,
            "x_moved": False,
            "y_confirmed": False,
            "needs_plot_confirm": False,
        }
        
        self.log(f"Energy Scan Agent 초기화: {list(self._init_energy_config.keys())} GeV")
    
    # 시스템 프롬프트.
    
    def _get_system_prompt(self) -> str:
        """System prompt (workflow 정의)"""
        return """You are Energy Scan Agent for test beam experiments.

Follow these steps EXACTLY:

=== STEP 0: Get Energy Config (only when phase is "config") ===
0a. Ask user for energy settings:
  {"message": "에너지 설정을 입력해주세요.\n예) 1GeV 50000개 2GeV 200000개 5GeV 100000개  또는  1GeV 80000 3GeV 500000 5GeV 300000"}

After user responds, parse their input:
0b. Update state with parsed config:
  {"tool": "none", "update_state": {"energy_config": {<energy_int>: {"target_events": <n>, "collected_events": 0, "runs": [], "completed": false, "completed_at": null}, ...}, "scan_order": [<sorted ints>], "phase": "idle"}}
  CRITICAL: energy keys must be INTEGERS (e.g., 1, 2, 3). scan_order must be sorted ascending.
  CRITICAL: beam_energy in GeV → store as number (integer if whole: "2GeV" → 2; float if decimal: "2.5GeV" → 2.5). NEVER convert to MeV.
  CRITICAL: If user says "모두", "각각", or "씩" with one number (e.g., "모두 500개"), apply that number to ALL energies.
  CRITICAL: If the user names a DAQ config for an energy (e.g. "3GeV setup1로 200000"),
  add "config": "<name>" to THAT energy's entry ONLY (copy the name EXACTLY as written).
  If a config name appears before ALL energies, apply it to every energy.
  OMIT "config" when the user does not name one — the default ("setup") applies.

=== STEP 1: Move to T5 ===
CRITICAL RULE: After STEP 0, when phase is "idle" and energy_config is NOT empty, start STEP 1.
DO NOT repeat STEP 0. DO NOT skip to phase "scanning".

1a-i. Move X-axis automatically (no user input needed):
  Output: {"tool": "motor_x_move_tool", "params": {"x": <x from state>}}

1a-ii. After motor tool completes, ask user to move Y-axis manually:
  Output: {"message": "X축 자동 이동 완료 (<x> mm). Y축을 <y>으로 이동해주세요."}
  (Replace <x>, <y> with T5 Position values from state)

After user says "완료" to the Y-axis message:
The SYSTEM marks Y-axis confirmed and switches to scanning automatically — you do NOT output any state update.
Just proceed to STEP 2 (the step hint will say "set-beam message").

=== STEP 2: For Each Energy in scan_order (REPEAT for ALL energies) ===
Repeat steps 2a-2c for each energy in scan_order until all energies are completed.

2a. Request Energy Setting
Output: {"message": "빔 에너지를 {energy} GeV로 설정해주세요."} (replace {energy} with number, e.g., "빔 에너지를 10 GeV로 설정해주세요.")

After user says "완료":
2b. Execute DAQ immediately:
Tool: "daq_run_tool"
Params: {
    "events": <target_events from energy_config>,
    "pos_h": <x_from_state>,
    "pos_v": <y_from_state>,
    "pos_rot": 1.5,
    "pos_tilt": 1.0,
    "beam_energy": <energy>
}
(If energy_config[energy] has "config", also include "config": <that name> in Params. Omit otherwise.)
(Plot is auto-rendered by DQM live during DAQ — never call any plot tool.)

2c. Request Plot Confirmation (only AFTER the DAQ tool has run):
Output: {"message": "데이터 수집 및 Plot 생성이 완료되었습니다. 결과를 확인해주세요."}

After user says "완료" to the plot message:
The SYSTEM marks the current energy completed and advances automatically — you do NOT output any state update.
Proceed to the next energy's STEP 2a (or, if all done, the SYSTEM ends the session).

=== STEP 3: Completion ===
When ALL energies are completed, the SYSTEM sends the completion message and ends the session automatically.

=== CRITICAL RULES ===
1. Follow steps STRICTLY in order. Do NOT skip or reorder steps.
2. Use EXACT messages above. DO NOT change or paraphrase.
3. The SYSTEM (not you) owns all bookkeeping: x_moved, y_confirmed, phase→scanning, energy "completed", and session termination. NEVER output update_state for these — only the step hint tells you the next action.
4. Output JSON format (CHOOSE ONE, NEVER BOTH):
   - {"tool": "...", "params": {...}}  (for tool execution)
   - {"message": "..."}  (for user message)
   - {"tool": "none", "update_state": {...}}  (ONLY for STEP 0b config parsing)
   CRITICAL: NEVER output both "tool" and "message" in the same JSON. NEVER put "message" inside "update_state".
5. Use energy_config[energy].target_events for DAQ events
6. STEP TRANSITION RULES:
   - phase="config", no history → output STEP 0a (ask message). DO NOT skip to parse.
   - phase="config", user just answered → output STEP 0b (parse + update_state). DO NOT ask again.
   - After STEP 0b (energy_config parsed, phase="idle"): go to STEP 1 (motor_x_move_tool). DO NOT repeat STEP 0.
   - After STEP 1a-i (motor done): send Y-axis message. After user "완료", the system advances — go to STEP 2a.
   - After DAQ tool runs: send STEP 2c plot message. DO NOT call daq_run_tool again for the same energy.
   - NEVER skip STEP 1. NEVER output the same message twice in a row.
7. All "message" field values MUST be written in Korean (한국어) only. Never use Chinese characters (한자).
"""
    
    # 상태 컨텍스트.
    
    def _build_state_context(self) -> str:
        """State를 문자열로 변환"""
        lines = []
        lines.append(f"Phase: {self.state['phase']}")
        lines.append(f"Tower: {self.state['tower']}")
        lines.append(f"T5 Position: x={self.t5_x:.3f}, y={self.t5_y:.3f}, rot=1.5, tilt=1.0")
        lines.append(f"x_moved: {self.state.get('x_moved', False)}")
        lines.append(f"y_confirmed: {self.state.get('y_confirmed', False)}")
        lines.append(f"needs_plot_confirm: {self.state.get('needs_plot_confirm', False)}")
        if self.state['position']:
            lines.append(f"Position: {self.state['position']}")
        lines.append("")

        ec = self.state.get("energy_config", {})
        so = self.state.get("scan_order", [])
        if ec:
            lines.append("Energy Config:")
            for e in so:
                cfg = ec.get(e, {})
                status = "✅" if cfg.get("completed") else "➡️" if e == self.state.get("current_energy") else "  "
                cfg_suffix = f" config={cfg['config']}" if cfg.get("config") else ""
                lines.append(
                    f"  {status} {e} GeV: target={cfg.get('target_events', '?')} "
                    f"collected={cfg.get('collected_events', 0)} "
                    f"runs={cfg.get('runs', [])} completed={cfg.get('completed', False)}{cfg_suffix}"
                )

        return "\n".join(lines)
    
    def _get_step_hint(self) -> str:
        """현재 상태 요약 - AI가 학습을 통해 다음 단계를 스스로 결정"""
        phase = self.state.get("phase", "config")
        if phase == "config":
            if self.conversation_history:
                return "Phase: config | REQUIRED NEXT: parse user input and update state (step 0b)"
            return "Phase: config | REQUIRED NEXT: ask for energy settings (step 0a)"
        if phase == "idle":
            if not self.state.get("x_moved"):
                return f"Phase: idle | REQUIRED NEXT: motor_x_move_tool (step 1a-i, x={self.t5_x:.3f})"
            # Y축 이동 완료 여부는 사용자 응답으로 처리한다.
            return f"Phase: idle | REQUIRED NEXT: Y-axis move message (step 1a-ii, y={self.t5_y:.3f})"
        current_energy = self.state.get("current_energy")
        scan_order = self.state.get("scan_order", [])
        idx = scan_order.index(current_energy) + 1 if current_energy in scan_order else 0
        total = len(scan_order)
        ec = self.state.get("energy_config", {})
        if ec and all(c.get("completed", False) for c in ec.values()):
            return f"Phase: {phase} | ALL ENERGIES COMPLETE — system will terminate automatically"
        cfg = ec.get(current_energy, {})
        if cfg.get("runs") and not cfg.get("completed"):
            last_run = cfg["runs"][-1]
            return (
                f"Phase: {phase} | Energy: {current_energy} GeV ({idx}/{total}) | "
                f"DAQ done (Run {last_run}) — "
                f"REQUIRED NEXT: plot confirmation message (step 2c). DO NOT call daq_run_tool again. "
                f"완료 시 시스템이 자동으로 완료 처리한다."
            )
        return (
            f"Phase: {phase} | Energy: {current_energy} GeV ({idx}/{total}) | "
            f"needs_plot_confirm=False — DO NOT output plot confirmation. "
            f"REQUIRED NEXT: set-beam message (step 2a) then daq_run_tool (step 2b)"
        )

    # BaseAgent 실행 루프용 훅.

    def _print_banner(self):
        print(f"\n{'='*70}\n⚡ Energy Scan Agent Started\n{'='*70}")

    def _print_summary(self):
        """현재 진행 상황 요약 출력 (Dash보드 스타일)"""
        print(f"\n📊 Energy Scan Progress Summary:")
        print("-" * 70)
        tower = self.state.get('tower', 'T5')
        print(f"Tower: {tower} | Position: x={self.t5_x:.3f}, y={self.t5_y:.3f}")
        print("-" * 70)

        for energy in self.state['scan_order']:
            if energy is None: continue
            config = self.state['energy_config'][energy]
            completed = config.get('completed', False)
            collected = config.get('collected_events', 0)
            target = config.get('target_events', 0)
            mark = "✅" if completed else ("➡️ " if energy == self.state['current_energy'] else "  ")
            status_text = "Completed" if completed else f"{format_event_count(collected)}/{format_event_count(target)} events"
            run_info = f" (Runs: {config['runs']})" if config['runs'] else ""
            cfg_info = f" [config: {config['config']}]" if config.get('config') else ""
            print(f"  {mark} {energy} GeV: {status_text}{run_info}{cfg_info}")
        print("-" * 70)

    def _pre_iteration(self):
        self._print_summary()
        # 다음 미완료 에너지로 이동한다.
        if self.state.get('phase') == 'scanning':
            _cur = self.state.get('current_energy')
            _cur_done = _cur is not None and self.state['energy_config'].get(_cur, {}).get('completed', False)
            if _cur is None or _cur_done:
                for _e in self.state['scan_order']:
                    if not self.state['energy_config'][_e].get('completed', False):
                        self.state['current_energy'] = _e
                        self.state['current_energy_idx'] = self.state['scan_order'].index(_e)
                        break

    def _is_complete(self) -> bool:
        ec = self.state.get("energy_config", {})
        return bool(ec) and self.state.get("phase") == "scanning" and all(
            c.get("completed", False) for c in ec.values()
        )

    def _completion_message(self) -> Optional[str]:
        return "모든 에너지 스캔이 완료되었습니다."

    def _completed_count(self) -> int:
        return sum(1 for c in self.state.get("energy_config", {}).values() if c.get("completed"))

    def _progress_message(self) -> Optional[str]:
        return self._format_progress()

    def _on_user_input(self, user_input: str):
        # Y축 이동 확인을 기록한다.
        if self.state.get("x_moved") and not self.state.get("y_confirmed"):
            self.state["y_confirmed"] = True
            self.state["phase"] = "scanning"
            self.log("Y-axis confirmed by user → phase=scanning")
            return
        # 플롯 확인 후 현재 에너지를 완료 처리한다.
        if self.state.get("needs_plot_confirm"):
            self.state["needs_plot_confirm"] = False
            e = self.state.get("current_energy")
            cfg = self.state.get("energy_config", {}).get(e)
            if cfg is not None and cfg.get("runs"):
                cfg["completed"] = True
                cfg.setdefault("completed_at", datetime.now().strftime("%H:%M:%S"))
                self.log(f"{e} GeV plot 확인 완료 → completed")

    def _position_for_current_step(self) -> Optional[Dict[str, float]]:
        """EM Scan은 T5 고정 위치."""
        return {"x": self.t5_x, "y": self.t5_y}

    def _daq_config_for(self, energy_key) -> str:
        """해당 에너지의 DAQ config 이름 — 에너지별 지정이 없으면 기본 daq_config("setup")."""
        cfg = self.state.get("energy_config", {}).get(energy_key, {}) if energy_key is not None else {}
        return cfg.get("config") or self.state.get("daq_config", "setup")

    def _resolve_daq_energy_key(self):
        """DAQ용 에너지 — state/scan_order 기준 (LLM params 무시)."""
        energy_key = self.state.get("current_energy")
        ec = self.state.get("energy_config", {})
        if energy_key is not None and energy_key in ec:
            if not ec[energy_key].get("completed", False):
                return energy_key
        for e in self.state.get("scan_order", []):
            if not ec.get(e, {}).get("completed", False):
                return e
        return None

    # 도구 실행.

    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        """Tool 실행"""
        print(f"\n🤖 Agent Decision:")
        print(f"   Tool: {tool_name}")
        print(f"   Params: {json.dumps(params, ensure_ascii=False)}")
        print()
        
        if tool_name == "none":
            return "no_tool_executed"

        elif tool_name == "motor_x_move_tool":
            result = self._run_motor_x_move("T5")
            self.state["x_moved"] = True
            return result

        elif tool_name == "daq_run_tool":
            energy_key = self._resolve_daq_energy_key()
            events = None
            if energy_key is not None and energy_key in self.state['energy_config']:
                events = self.state['energy_config'][energy_key]['target_events']
            result, run_number = self._run_daq_from_state(
                params,
                events=events,
                beam_energy=energy_key,
                program="EM Scan",
                pos=self._position_for_current_step(),
                pos_rot=1.5,
                pos_tilt=1.0,
                config=self._daq_config_for(energy_key),
            )
            if run_number:
                if energy_key is not None and energy_key in self.state['energy_config']:
                    self.state['current_energy'] = energy_key
                    self.state['energy_config'][energy_key]['runs'].append(run_number)
                    self.state['energy_config'][energy_key]['collected_events'] = params.get('events', 0)
                    self.log(f"DAQ Run {run_number} 완료: {energy_key} GeV, {params.get('events', 0)} events")
            return result

        else:
            print(f"⚠️  Unknown tool: {tool_name}")
            self.log(f"Unknown tool: {tool_name}")
            return f"Error: Unknown tool {tool_name}"
    
    # 보조 함수.
    
    def _guard_tool(self, tool_name: str, params) -> Optional[str]:
        if tool_name == "daq_run_tool" and self.state.get("needs_plot_confirm"):
            return (
                f'needs_plot_confirm=True — DAQ already ran. '
                f'Send: {{"message": "{MSG_PLOT_CONFIRM}"}}'
            )
        return None

    # 플롯 확인은 BaseAgent에서 검사한다.

    # 코드에서만 관리하는 상태 필드.
    _PROTECTED_FIELDS = frozenset({
        "tower", "current_tower", "daq_config", "start_time", "plot_method",
        "plot_max_event", "x_moved", "y_confirmed", "needs_plot_confirm",
        "current_energy_idx", "last_run_number",
    })

    # 목록 구분자로 연결된 숫자를 같은 에너지 그룹으로 묶는다.
    _ENUM_SEP = re.compile(r'^\s*(?:[,·、/&]|와|과|및|그리고|and)\s*$', re.IGNORECASE)
    # 이벤트 수와 구분하기 위한 에너지 상한.
    _MAX_ENUM_ENERGY = 1000

    # 문자로 시작하는 DAQ 설정 이름.
    _RE_CONFIG_TOKEN = re.compile(r'(?<![0-9A-Za-z_])([A-Za-z][A-Za-z0-9_-]*)')
    # DAQ 설정 이름에서 제외할 일반 단어.
    _CONFIG_TOKEN_STOPWORDS = {
        "gev", "mev", "tev", "and", "all", "events", "event", "evt", "evts",
        "run", "daq", "k",
    }

    def _parse_config_pairs(self, text: str) -> Optional[Dict[float, tuple]]:
        """에너지별 이벤트 수와 DAQ 설정 이름을 사용자 입력에서 파싱한다."""
        normalized = _normalize_thousands_commas(text) if isinstance(text, str) else ""

        # 설정 이름 영역을 공백으로 바꿔 숫자 분석에서 제외한다.
        config_tokens: list = []  # (이름, 시작 위치)
        def _blank(m):
            tok = m.group(1)
            if tok.lower() in self._CONFIG_TOKEN_STOPWORDS:
                return tok
            config_tokens.append((tok, m.start(1)))
            return " " * len(tok)
        blanked = self._RE_CONFIG_TOKEN.sub(_blank, normalized)

        tokens = extract_number_tokens(blanked)  # 위치는 치환된 문자열 기준이다.
        normalized = blanked

        # GeV로 끝나는 숫자 목록을 에너지 그룹으로 묶는다.
        groups: list = []   # [(에너지 값, 위치), ...]
        plains: list = []   # (값, 위치)
        chain: list = []    # 연결 중인 일반 숫자 목록
        prev_end = None
        for v, s, e, is_energy in tokens:
            linked = bool(chain) and prev_end is not None and bool(self._ENUM_SEP.match(normalized[prev_end:s]))
            if is_energy:
                if linked and all(cv < self._MAX_ENUM_ENERGY for cv, _ in chain):
                    groups.append(chain + [(v, s)])
                else:
                    plains.extend(chain)
                    groups.append([(v, s)])
                chain = []
            else:
                if linked:
                    chain.append((v, s))
                else:
                    plains.extend(chain)
                    chain = [(v, s)]
            prev_end = e
        plains.extend(chain)

        if not groups:
            return None
        all_energies = [ev for g in groups for ev, _ in g]
        if len(set(all_energies)) != len(all_energies):
            return None  # 중복 에너지는 확정할 수 없다.

        # 에너지 그룹별 이벤트 수를 연결한다.
        events_map: Optional[Dict[float, int]] = None
        # 공통 이벤트 수 표현은 모든 에너지에 적용한다.
        if len(plains) == 1 and re.search(r'모두|각각|씩|전부|다\s|all', text):
            events_map = {ev: int(plains[0][0]) for ev in all_energies}
        else:
            # 첫 에너지 앞의 숫자는 용도를 확정할 수 없다.
            if any(p_pos < groups[0][0][1] for _, p_pos in plains):
                return None
            # 각 그룹 뒤의 단일 숫자를 그룹 전체의 이벤트 수로 사용한다.
            bounds = [g[0][1] for g in groups] + [float('inf')]
            events_map = {}
            for i, g in enumerate(groups):
                last_pos = g[-1][1]
                seg = [v for v, p in plains if last_pos < p < bounds[i + 1]]
                if len(seg) != 1:
                    return None
                for ev, _ in g:
                    events_map[ev] = int(seg[0])

        # DAQ 설정 이름을 전체 또는 개별 에너지 그룹에 배정한다.
        group_starts = [g[0][1] for g in groups]
        global_cfg: Optional[str] = None
        seg_cfgs: Dict[int, str] = {}
        for name, pos in config_tokens:
            if pos < group_starts[0]:
                if global_cfg is not None:
                    return None  # 전역 설정 이름은 하나만 허용한다.
                global_cfg = name
            else:
                gi = max(i for i, s in enumerate(group_starts) if s <= pos)
                if gi in seg_cfgs:
                    return None  # 그룹별 설정 이름은 하나만 허용한다.
                seg_cfgs[gi] = name

        pairs: Dict[float, tuple] = {}
        for i, g in enumerate(groups):
            cfg_name = seg_cfgs.get(i, global_cfg)
            for ev, _ in g:
                pairs[ev] = (events_map[ev], cfg_name)
        return pairs

    def _guard_update_state(self, updates: Dict[str, Any]) -> Optional[str]:
        """STEP 0b config 파싱 방어 (2단계):
        1) 코드가 GeV 앵커로 짝을 확정할 수 있으면 → LLM 파싱을 코드 값으로 자동 교정
           (자릿수 오류·짝 뒤바뀜 모두 결정론적으로 해소, state-source-of-truth 패턴)
        2) 애매해서 짝을 못 지으면 → 출처 검증(입력에 없는 숫자 거부)으로 폴백"""
        if self.state.get("phase") != "config" or "energy_config" not in updates:
            return None
        ec = updates.get("energy_config")
        if not isinstance(ec, dict):
            return None

        # 확정 가능한 에너지와 이벤트 쌍으로 상태를 교정한다.
        pairs = self._parse_config_pairs(self._last_user_input)
        if pairs:
            corrected = {}
            for e, (n, cfg_name) in pairs.items():
                key = int(e) if e == int(e) else e
                corrected[key] = {
                    "target_events": n, "collected_events": 0,
                    "runs": [], "completed": False, "completed_at": None,
                }
                if cfg_name:
                    corrected[key]["config"] = cfg_name
            llm_pairs = {}
            for k, v in ec.items():
                try:
                    f = float(k)
                    llm_pairs[int(f) if f == int(f) else f] = (v or {}).get("target_events") if isinstance(v, dict) else None
                except (TypeError, ValueError):
                    pass
            code_pairs = {k: v["target_events"] for k, v in corrected.items()}
            if llm_pairs != code_pairs:
                self.log(f"energy_config 자동 교정(입력 짝 기준): LLM {llm_pairs} → {code_pairs}")
            updates["energy_config"] = corrected
            updates.pop("scan_order", None)  # 상태 반영 시 다시 계산한다.
            return None

        # 자동 확정이 불가능하면 입력 원문과 숫자를 대조한다.
        allowed = self._numbers_in_last_input()
        if not allowed:
            return None  # 비교할 입력이 없으면 검증을 생략한다.
        for energy_key, cfg in ec.items():
            try:
                e = float(energy_key)
            except (TypeError, ValueError):
                return f"REJECTED: energy key {energy_key!r} is not a number. Re-parse the user input."
            if e not in allowed:
                return (f"REJECTED: energy {energy_key} does not appear in the user's input. "
                        f"Numbers in input: {sorted(allowed)}. Re-parse exactly — do not invent or drop digits.")
            if isinstance(cfg, dict) and "target_events" in cfg:
                try:
                    n = float(cfg["target_events"])
                except (TypeError, ValueError):
                    return f"REJECTED: target_events {cfg['target_events']!r} is not a number. Re-parse the user input."
                if n not in allowed:
                    return (f"REJECTED: target_events {cfg['target_events']} does not appear in the user's input. "
                            f"Numbers in input: {sorted(allowed)}. Re-parse exactly — do not invent or drop digits.")
        return None

    def _echo_parsed_config(self):
        """config 파싱 직후, 코드가 state 진짓값으로 설정 내용을 echo (사용자 이중 확인용)."""
        lines = ["설정을 다음과 같이 확인했습니다:"]
        for energy in self.state.get("scan_order", []):
            if energy is None:
                continue
            cfg = self.state["energy_config"].get(energy, {})
            cfg_suffix = f" (config: {cfg['config']})" if cfg.get("config") else ""
            lines.append(f"  • {energy} GeV — {format_event_count(cfg.get('target_events', 0))} events{cfg_suffix}")
        self.io.send_ai_message("\n".join(lines))

    def _update_state(self, updates: Dict[str, Any]):
        """State 업데이트 (energy_config는 deep merge로 기존 필드 보존)"""
        _was_config = self.state.get("phase") == "config"
        for key, value in updates.items():
            if key == "energy_config" and isinstance(value, dict):
                for energy_key, config_value in value.items():
                    try:
                        f = float(energy_key)
                        int_key = int(f) if f == int(f) else f
                    except (ValueError, TypeError):
                        int_key = energy_key
                    if int_key in self.state['energy_config'] and isinstance(config_value, dict):
                        # 이벤트 수와 진행 상태는 코드에서 관리한다.
                        safe_update = {
                            k: v for k, v in config_value.items()
                            if k not in ('target_events', 'completed', 'completed_at', 'runs', 'collected_events')
                        }
                        if 'completed' in config_value:
                            self.log(f"WARNING: LLM tried to set completed for {int_key} GeV — rejected (code-owned)")
                        self.state['energy_config'][int_key].update(safe_update)

                    else:
                        self.state['energy_config'][int_key] = config_value
                self.state['scan_order'] = sorted(
                    [e for e in self.state['energy_config'].keys() if e is not None],
                    key=lambda x: float(x)
                )
                self.log(f"State updated: energy_config (deep merge), scan_order={self.state['scan_order']}")

            elif key == "current_energy" and value is not None:
                try:
                    f = float(value)
                    self.state[key] = int(f) if f == int(f) else f
                except:
                    self.state[key] = value
                self.log(f"State updated: {key} = {self.state[key]}")

            elif key in self._PROTECTED_FIELDS:
                self.log(f"WARNING: LLM tried to update protected field '{key}' = {value} — rejected")
            else:
                self.state[key] = value
                self.log(f"State updated: {key} = {value}")

        # 설정 완료 시 확정된 값을 사용자에게 알린다.
        if _was_config and self.state.get("phase") == "idle" and self.state.get("energy_config"):
            self._echo_parsed_config()

    def _format_progress(self) -> str:
        """현재 진행 상황을 문자열로 반환 (AI 메시지용)"""
        total = len(self.state['scan_order'])
        done = sum(1 for c in self.state['energy_config'].values() if c.get('completed'))
        lines = [
            f"📊 Energy Scan  —  {done} / {total} 완료",
            f"T5 위치:  x = {self.t5_x:.3f},  y = {self.t5_y:.3f}",
            "─" * 36,
        ]
        for energy in self.state['scan_order']:
            if energy is None:
                continue
            config = self.state['energy_config'].get(energy, {})
            cfg_suffix = f"   [{config['config']}]" if config.get('config') else ""
            if config.get('completed'):
                runs_str = ', '.join(str(r) for r in config['runs']) if config['runs'] else '-'
                lines.append(f"  ✅  {energy} GeV   {format_event_count(config['target_events'])} events   Run {runs_str}{cfg_suffix}")
            else:
                lines.append(f"       {energy} GeV   {format_event_count(config.get('target_events',0))} events{cfg_suffix}")
        lines.append("─" * 36)
        return "\n".join(lines)
