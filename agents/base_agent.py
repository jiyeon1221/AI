#!/usr/bin/env python3
"""Base Agent — abstract base class for all scenario agents (EnergyScan, CalibScan, HVEqualization)."""

import json
import re
import time
from typing import Dict, Any, Optional, List, Callable, Tuple
from datetime import datetime
from pathlib import Path
from abc import ABC, abstractmethod

import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import MAX_CONVERSATION_HISTORY, MAX_NEW_TOKENS, MSG_PLOT_CONFIRM
import tools.motor_control_tool as motor

# 학습 라이브러리는 추론 시점에만 불러온다.


class ToolFatalError(Exception):
    """Tool이 max_retries 이후에도 실패했을 때 발생."""
    pass


# 런타임과 학습 데이터가 공유하는 컨텍스트 조립기.
# 학습 데이터의 무제한 대화 기록을 최근 항목으로 제한한다.
HISTORY_WINDOW = 10

NO_CONVERSATION = "(No conversation yet)"
DEFAULT_STEP_HINT = "Based on the current state and conversation, decide the next action."
OUTPUT_INSTRUCTION = "Output JSON with tool name and parameters."


def summarize_agent_content(content: Any) -> str:
    """Assistant 결정에서 다음 판단에 필요한 정보만 한 줄로 요약한다."""
    if not isinstance(content, str):
        return str(content)
    try:
        decision = json.loads(content)
    except (TypeError, ValueError):
        return content
    if not isinstance(decision, dict):
        return content

    if "message" in decision:
        return decision["message"]
    if "tool" not in decision:
        return content

    tool = decision["tool"]
    params = decision.get("params") or {}
    summary = f"[Tool Call: {tool}]"

    if tool in ("dqm_plot", "run_log"):
        run = params.get("run_number") or params.get("run_num")
        if run:
            summary += f" run={run}"
    if tool == "dqm_plot" and params.get("type"):
        summary += f" type={params['type']}"
        if params.get("modules"):
            summary += f" modules={params['modules']}"
    if tool in ("hv_write", "hodoscope_hv_write"):
        cmd = params.get("command", "")
        ch = params.get("channels", "")
        v = params.get("voltage") or params.get("value", "")
        summary += f" cmd={cmd} ch={ch}" + (f" v={v}" if v != "" else "")
    if tool in ("motor_move", "motor_x_move_tool") and params.get("x") is not None:
        summary += f" x={params['x']}mm"
    if tool == "daq_run_tool":
        if params.get("beam_energy") is not None:
            summary += f" energy={params['beam_energy']}GeV"
        if params.get("events") is not None:
            summary += f" events={params['events']}"
    if tool == "hv_suggest_tool" and params.get("tower"):
        summary += f" tower={params['tower']}"
    if tool == "hv_execute_tool":
        cmd = params.get("command", "")
        if cmd:
            summary += f" cmd={cmd}"
        cv = params.get("channel_values")
        if cv:
            summary += " " + " ".join(f"{k}={v}" for k, v in cv.items())

    if "update_state" in decision:
        summary += f" (Update State: {list(decision['update_state'].keys())})"
    return summary


def build_history_context(history: Optional[List[Dict]], window: int = HISTORY_WINDOW) -> str:
    """최근 대화를 'User: ...' / 'Agent: ...' 줄로. Agent 턴은 요약된다."""
    if not history:
        return NO_CONVERSATION
    lines = []
    for msg in history[-window:]:
        if msg["role"] == "user":
            lines.append(f"User: {msg['content']}")
        else:
            lines.append(f"Agent: {summarize_agent_content(msg['content'])}")
    return "\n".join(lines)


def split_current_input(
    history: Optional[List[Dict]],
    current_input: Optional[str] = None,
) -> Tuple[Optional[str], List[Dict]]:
    """현재 사용자 입력과 이전 대화를 분리한다."""
    history = history or []
    if current_input is None and history and history[-1]["role"] == "user":
        return history[-1]["content"], history[:-1]
    return current_input, history


def build_prompt_context(
    state_context: str,
    history: Optional[List[Dict]] = None,
    *,
    current_input: Optional[str] = None,
    step_hint: str = DEFAULT_STEP_HINT,
    window: int = HISTORY_WINDOW,
) -> str:
    """모델에 넣는 user 메시지 전체를 조립한다 (agent/data_gen 공통 형식)."""
    current_input, prior = split_current_input(history, current_input)

    parts = ["=== Current State ===", state_context, ""]
    parts += ["=== Recent Conversation ===", build_history_context(prior, window), ""]
    if current_input:
        parts += ["=== Current User Input ===", current_input, ""]
    parts += ["=== Your Task ===", step_hint, "", OUTPUT_INSTRUCTION]
    return "\n".join(parts)


# 사용자 메시지의 이벤트 수를 상태값과 일치시킨다.

_EVENT_KEYWORD = r'(?:이벤트|events?|evt)'
# 숫자가 이벤트 단위 앞에 오는 표현.
_RE_NUM_BEFORE_EVENT = re.compile(r'([\d,]+)(\s*개?\s*' + _EVENT_KEYWORD + r')', re.IGNORECASE)
# 이벤트 단위가 숫자 앞에 오는 표현.
_RE_NUM_AFTER_EVENT = re.compile(r'(' + _EVENT_KEYWORD + r'\s*수?\s*[:：]?\s*)([\d,]+)', re.IGNORECASE)


def format_event_count(n) -> str:
    """이벤트 개수를 천 단위 콤마 문자열로. 정수화 불가하면 원본을 문자열로."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


_RE_NUMBER = re.compile(r'\d+(?:\.\d+)?')
_RE_GEV_SUFFIX = re.compile(r'\s*(?:GeV|기가)', re.IGNORECASE)


# 천 단위 쉼표가 포함된 숫자.
_RE_COMMA_GROUP = re.compile(r'\d{1,3}(?:,\d{3})+(?!\d)')


def _normalize_thousands_commas(text: str) -> str:
    """"10,000" → "10000" (천 단위 콤마 제거 — 나열 구분 콤마는 보존).
    그룹 전체가 GeV/기가로 끝나면 에너지 나열("50,100,120GeV")이므로 병합하지 않는다
    (빔 에너지는 최대 수백 GeV라 천 단위 콤마가 필요한 경우가 없음)."""
    def _repl(m):
        if _RE_GEV_SUFFIX.match(text, m.end()):
            return m.group()  # 에너지 목록의 구분 쉼표는 유지한다.
        return m.group().replace(',', '')
    return _RE_COMMA_GROUP.sub(_repl, text)


def extract_number_tokens(text: str) -> List[tuple]:
    """텍스트의 숫자 토큰을 (값, 시작위치, 끝위치, 에너지단위 여부) 리스트로 반환.
    위치는 천 단위 콤마 정규화 후 텍스트 기준. 에너지단위 여부 = 숫자 바로 뒤에
    GeV/기가가 붙는지 (예: '3GeV' → (3.0, s, e, True)).
    코드가 LLM 파싱의 짝(에너지↔이벤트 수)을 결정론적으로 재구성/교정할 때 사용."""
    if not isinstance(text, str):
        return []
    normalized = _normalize_thousands_commas(text)
    tokens = []
    for m in _RE_NUMBER.finditer(normalized):
        is_energy = bool(_RE_GEV_SUFFIX.match(normalized, m.end()))
        tokens.append((float(m.group()), m.start(), m.end(), is_energy))
    return tokens


def extract_numbers_from_text(text: str) -> set:
    """텍스트에 등장하는 모든 숫자를 float 집합으로 추출 (천 단위 콤마 정규화).
    LLM이 파싱해 state에 넣는 숫자가 사용자 입력에 실제로 존재하는지(지어낸/자릿수
    틀린 숫자가 아닌지) 검증하는 데 사용한다. 형식이 어떻게 섞여 있어도 동작."""
    return {v for v, _, _, _ in extract_number_tokens(text)}


def correct_event_count_in_text(text: str, n) -> str:
    """LLM이 문장에 쓴 이벤트 개수를 state 진짓값(콤마 포맷)으로 교정.
    이벤트 키워드에 인접한 숫자만 대상으로 하여 전압/에너지/ADC 등은 건드리지 않는다."""
    if not isinstance(text, str) or not text:
        return text
    try:
        target = int(n)
    except (TypeError, ValueError):
        return text
    if target <= 0:
        return text
    formatted = f"{target:,}"
    text = _RE_NUM_BEFORE_EVENT.sub(lambda m: formatted + m.group(2), text)
    text = _RE_NUM_AFTER_EVENT.sub(lambda m: m.group(1) + formatted, text)
    return text



class BaseAgent(ABC):

    def __init__(self, model_path: str, agent_name: str, io_handler=None):
        self.model_path = Path(model_path)
        self.agent_name = agent_name

        if io_handler is None:
            from agents.io_handler import TerminalIO
            self.io = TerminalIO()
        else:
            self.io = io_handler
        
        self.model = None
        self.tokenizer = None
        self.device = None
        self.state = {}
        self.conversation_history: List[Dict[str, Any]] = []
        self.max_history = MAX_CONVERSATION_HISTORY
        # 상태 업데이트의 숫자를 검증할 원문 입력.
        self._last_user_input: str = ""
    
    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
        return False

    def load(self):
        if self.model is not None:
            return

        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        if torch.backends.mps.is_available():
            self.device = "mps"
            print(f"  ✅ [{self.agent_name}] MPS 사용")
        elif torch.cuda.is_available():
            self.device = "cuda"
            print(f"  ✅ [{self.agent_name}] CUDA 사용")
        else:
            self.device = "cpu"
            print(f"  ✅ [{self.agent_name}] CPU 사용")
        
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_path),
            trust_remote_code=True
        )
        
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.truncation_side = "left"
        
        self.model = AutoModelForCausalLM.from_pretrained(
            str(self.model_path),
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            device_map=self.device,
            trust_remote_code=True
        )
        
        print(f"  ✅ [{self.agent_name}] 모델 로드 완료: {self.model_path}")

    def unload(self):
        import torch

        if self.model is not None:
            del self.model
            self.model = None
        
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif torch.backends.mps.is_available():
            torch.mps.empty_cache()
        
        print(f"  🗑️  [{self.agent_name}] 모델 언로드 완료")

    def add_to_history(self, role: str, content: str, metadata: Optional[Dict] = None):
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        if metadata:
            entry.update(metadata)
        
        self.conversation_history.append(entry)
        
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]
    
    def get_recent_history(self, n: Optional[int] = None) -> List[Dict]:
        if n is None:
            n = self.max_history
        return self.conversation_history[-n:]
    
    @abstractmethod
    def _build_state_context(self) -> str:
        pass

    def _get_step_hint(self) -> str:
        """'=== Your Task ===' 아래 들어갈 한 줄. 시나리오 agent가 현재 단계를 알린다."""
        return DEFAULT_STEP_HINT

    def build_full_context(self, current_input: Optional[str] = None) -> str:
        return build_prompt_context(
            self._build_state_context(),
            self.conversation_history,
            current_input=current_input,
            step_hint=self._get_step_hint(),
        )

    
    def decide(self, context: str, max_retries: int = 3) -> Dict[str, Any]:
        """LLM inference → JSON. 첫 시도 greedy, 재시도 sampling."""
        import torch

        if self.model is None:
            raise RuntimeError(f"[{self.agent_name}] Model not loaded. Use with statement or call load().")

        system_prompt = self._get_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context}
        ]
        formatted_prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(
            formatted_prompt,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=2048,
        ).to(self.device)

        last_err: Optional[str] = None
        last_raw: Optional[str] = None

        for attempt in range(max_retries):
            gen_kwargs = dict(do_sample=False) if attempt == 0 else dict(do_sample=True, temperature=0.7, top_p=0.9)

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    repetition_penalty=1.1,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                    **gen_kwargs,
                )

            generated_text = self.tokenizer.decode(
                outputs[0][inputs['input_ids'].shape[1]:],
                skip_special_tokens=True,
            )

            try:
                text = generated_text.strip()
                if '{' not in text:
                    raise json.JSONDecodeError("No JSON found", text, 0)

                decoder = json.JSONDecoder()
                start = text.index('{')
                decision, _ = decoder.raw_decode(text, start)
                if attempt > 0:
                    self.log(f"JSON 파싱 재시도 성공 (attempt {attempt + 1}/{max_retries})")
                return decision

            except (json.JSONDecodeError, ValueError) as e:
                last_err = str(e)
                last_raw = generated_text
                self.log(f"JSON 파싱 실패 (attempt {attempt + 1}/{max_retries}): {e}")
                continue

        return {
            "error": f"JSON parsing failed after {max_retries} attempts: {last_err}",
            "raw_output": last_raw,
        }
    
    @abstractmethod
    def _get_system_prompt(self) -> str:
        pass

    # 도구 매개변수는 상태값을 기준으로 확정한다.

    def _position_for_current_step(self) -> Optional[Dict[str, float]]:
        return None

    def _motor_x_for_current_step(self) -> float:
        pos = self._position_for_current_step()
        if pos is None:
            raise RuntimeError(f"[{self.agent_name}] _position_for_current_step() not implemented")
        return self._motor_x_from_state(pos["x"])

    def _motor_x_from_state(self, x_mm: float) -> float:
        return float(x_mm)

    def _apply_daq_params_from_state(
        self,
        params: Dict[str, Any],
        *,
        events: Optional[int] = None,
        beam_energy: Any = None,
        program: str,
        pos: Optional[Dict[str, float]] = None,
        pos_rot: float = 0.0,
        pos_tilt: float = 0.0,
        config: Optional[str] = None,
    ) -> None:
        if events is not None:
            params["events"] = events
        if beam_energy is not None:
            params["beam_energy"] = beam_energy
        if config is not None:
            params["config"] = config
        params["program"] = program
        if pos is not None:
            params["pos_h"] = pos["x"]
            params["pos_v"] = pos["y"]
        params["pos_rot"] = pos_rot
        params["pos_tilt"] = pos_tilt

    def _apply_hv_voltage_params_from_state(
        self,
        params: Dict[str, Any],
        channel_values: Dict[str, float],
    ) -> None:
        params["channel_values"] = channel_values

    def _apply_hv_suggest_params_from_state(
        self,
        params: Dict[str, Any],
        *,
        tower: str,
        run_number: Optional[int] = None,
        hv_c: Optional[float] = None,
        hv_s: Optional[float] = None,
    ) -> None:
        params["tower"] = tower
        if run_number is not None:
            params["run_number"] = run_number
        if hv_c is not None:
            params["hv_c"] = hv_c
        if hv_s is not None:
            params["hv_s"] = hv_s

    def _extract_run_number(self, daq_output: Optional[str] = None) -> Optional[int]:
        from tools.daq_tool import parse_run_number_from_daq_output

        run_number = parse_run_number_from_daq_output(daq_output)
        if run_number is None:
            self.log("WARNING: DAQ output에서 run number를 찾지 못함")
        return run_number

    # 시나리오 에이전트가 공유하는 모터·DAQ 실행 순서.

    def _run_motor_x_move(self, label: str) -> str:
        """현재 단계의 X 좌표로 모터를 옮긴다. x_moved 부킹은 호출자 몫."""
        x = self._motor_x_for_current_step()
        self.io.send_tool_output(f"[Motor] X축 이동 시작 ({label}): {x:.3f} mm")

        def _do_move():
            ok, msg = motor.move_x(x)
            if not ok:
                raise RuntimeError(msg)
            return msg

        result = self._run_tool_with_retry(_do_move, "motor_x_move_tool")
        self.io.send_tool_output(f"[Motor] {result}")
        return result

    def _run_daq_from_state(self, params: Dict[str, Any], **daq_kwargs):
        """state를 진짓값으로 DAQ를 돌리고 (출력, run number)를 돌려준다.

        DAQ 직후에는 항상 사용자 plot 확인이 필요하므로 needs_plot_confirm을 세운다.
        daq_tool 내부의 dqm_session.start()이 monit --LIVE를 띄워 DAQ 동안 우측 하단
        DQM 패널이 갱신된다 — 여기가 유일한 플롯 경로다.
        """
        self._apply_daq_params_from_state(params, **daq_kwargs)
        result = self._run_tool_with_retry(
            lambda: self.daq_tool.execute(params, line_callback=self.io.send_tool_output),
            "daq_run_tool",
        )
        run_number = self._extract_run_number(result)
        if run_number:
            self.state["last_run_number"] = run_number
        self.state["needs_plot_confirm"] = True
        return result, run_number

    def _run_tool_with_retry(self, tool_fn: Callable, tool_name: str, max_retries: int = 3) -> str:
        while True:
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return tool_fn()
                except RuntimeError as e:
                    last_error = e
                    self.log(f"[Retry {attempt}/{max_retries}] Tool '{tool_name}' 실패: {e}")
                    if attempt < max_retries:
                        time.sleep(2)
            self.io.send_tool_error(tool_name, str(last_error), max_retries)
            action = self.io.wait_for_retry()
            if action == "skip":
                return f"[SKIPPED] {tool_name} 건너뜀 (사용자 요청)"

    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{self.agent_name}] {message}", flush=True)
    
    # 서브클래스용 실행 루프 훅.

    def _print_banner(self):
        print(f"\n{'='*70}\n⚡ {self.agent_name} Started\n{'='*70}")

    def _pre_iteration(self): pass
    def _is_complete(self) -> bool: return bool(self.state.get("done"))
    def _completion_message(self) -> Optional[str]: return None
    def _completed_count(self) -> int: return 0
    def _progress_message(self) -> Optional[str]: return None
    def _on_user_input(self, user_input: str): pass

    def _guard_tool(self, tool_name: str, decision: Dict[str, Any]) -> Optional[str]:
        """거부 사유 반환 → 실행 차단 후 재시도. None이면 통과."""
        return None

    def _guard_ai_message(self, message: str) -> Optional[str]:
        """거부 사유 반환 → 출력 차단 후 재시도. None이면 통과.

        기본 동작: DAQ가 돌기도 전에 plot 확인 메시지를 내보내는 것을 막는다.
        서브클래스는 super()를 먼저 호출하고, 통과했을 때만 자기 검사를 이어갈 것.
        """
        if MSG_PLOT_CONFIRM in message and not self.state.get("needs_plot_confirm"):
            return f"needs_plot_confirm=False — DO NOT send plot confirmation. {self._get_step_hint()}"
        return None

    def _plot_confirm_pending_rejection(self, tool_name: str) -> Optional[str]:
        """plot 확인 대기 중 tool 호출을 막는 표준 사유. 통과면 None."""
        if self.state.get("needs_plot_confirm"):
            return (
                f"needs_plot_confirm=True — DO NOT call {tool_name}. "
                f'Send: {{"message": "{MSG_PLOT_CONFIRM}"}}'
            )
        return None

    def _guard_update_state(self, updates: Dict[str, Any]) -> Optional[str]:
        """update_state 적용 직전 검증. 거부 사유 반환 → 적용 차단 후 재시도. None이면 통과.
        서브클래스가 LLM이 파싱한 숫자(이벤트 수·에너지 등)의 출처를
        _last_user_input과 대조할 때 사용 (자릿수 오류 방어)."""
        return None

    def _numbers_in_last_input(self) -> set:
        return extract_numbers_from_text(self._last_user_input)

    def _finalize_ai_message(self, message: str) -> str:
        """전송 직전 메시지를 보정할 기회.
        기본 동작: state의 target_events를 진짓값으로 삼아, 모델이 문장에 쓴
        이벤트 개수의 자릿수를 교정하고 콤마 포맷으로 통일한다.
        서브클래스가 오버라이드할 땐 super()를 호출해 이 교정을 유지할 것."""
        corrected = correct_event_count_in_text(message, self.state.get("target_events"))
        if corrected != message:
            self.log(f"이벤트 개수 표시 교정(state 기준): {message!r} → {corrected!r}")
        return corrected

    def _stop_requested(self) -> bool:
        """WebSocketIO의 stop_event가 set이면 True (TerminalIO는 항상 False)."""
        ev = getattr(self.io, "stop_event", None)
        return ev is not None and ev.is_set()

    def run(self):
        self._print_banner()
        self.log(f"{self.agent_name} 시작")

        if self.model is None:
            raise RuntimeError(f"[{self.agent_name}] Model not loaded. Use 'with agent:' statement.")

        _error_count = 0
        _MAX_ERRORS = 3
        # 상태 업데이트만 반복하는 무진행 루프를 감지한다.
        _no_progress = 0
        _MAX_NO_PROGRESS = 5
        # 가드가 같은 결정을 반복 거부하는 경우도 감지한다.
        _guard_reject = 0
        _MAX_GUARD_REJECT = 6

        while True:
            try:
                # 입력 대기 없이도 중지 요청을 확인한다.
                if self._stop_requested():
                    self.log("Stop 요청 감지 — 종료합니다.")
                    break

                self._pre_iteration()

                if self._is_complete():
                    msg = self._completion_message()
                    if msg:
                        self.io.send_ai_message(msg)
                    break

                context = self.build_full_context()
                decision = self.decide(context)
                print(f"\n🔍 Decision: {json.dumps(decision, ensure_ascii=False)}")

                if "error" in decision:
                    _error_count += 1
                    self.log(f"Agent error ({_error_count}/{_MAX_ERRORS}): {decision['error']}")
                    if _error_count >= _MAX_ERRORS:
                        print(f"\n❌ 연속 오류 {_MAX_ERRORS}회 — 종료합니다.")
                        break
                    self.add_to_history("user", "Output valid JSON only. No other text.")
                    continue

                _error_count = 0

                if "update_state" in decision:
                    # 검증되지 않은 값은 상태에 반영하지 않는다.
                    rejection = self._guard_update_state(decision["update_state"])
                    if rejection:
                        self.log(f"update_state guard blocked: {rejection}")
                        self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                        self.add_to_history("user", rejection)
                        _guard_reject += 1
                        if _guard_reject >= _MAX_GUARD_REJECT:
                            self.log(f"Guard-reject 워치독 발동 ({_guard_reject}회 연속 거부) — 종료")
                            self.io.send_ai_message(
                                "에이전트가 올바른 다음 단계를 내지 못하고 같은 응답을 반복하고 있습니다. "
                                "세션을 종료합니다. 다시 시작해주세요."
                            )
                            break
                        continue
                    _guard_reject = 0  # 상태가 진행되면 거부 횟수를 초기화한다.
                    before = self._completed_count()
                    self._update_state(decision["update_state"])
                    after = self._completed_count()
                    if after > before:
                        prog = self._progress_message()
                        if prog:
                            self.io.send_ai_message(prog)

                message = decision.get("message")
                tool_name = decision.get("tool")

                if message:
                    message = self._finalize_ai_message(message)
                    decision["message"] = message
                    rejection = self._guard_ai_message(message)
                    if rejection:
                        self.log(f"message guard blocked: {rejection}")
                        self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                        self.add_to_history("user", rejection)
                        _guard_reject += 1
                        if _guard_reject >= _MAX_GUARD_REJECT:
                            self.log(f"Guard-reject 워치독 발동 ({_guard_reject}회 연속 거부) — 종료")
                            self.io.send_ai_message(
                                "에이전트가 올바른 다음 단계를 내지 못하고 같은 응답을 반복하고 있습니다. "
                                "세션을 종료합니다. 다시 시작해주세요."
                            )
                            break
                        continue
                    _guard_reject = 0
                    _no_progress = 0
                    self.io.send_ai_message(message)
                    self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                    user_input = self.io.get_input()
                    self._last_user_input = user_input
                    if user_input in ["종료", "exit"]:
                        break
                    before = self._completed_count()
                    self._on_user_input(user_input)
                    after = self._completed_count()
                    if after > before:
                        prog = self._progress_message()
                        if prog:
                            self.io.send_ai_message(prog)
                    self.add_to_history("user", user_input)
                    continue

                if tool_name and tool_name != "none":
                    rejection = self._guard_tool(tool_name, decision)
                    if rejection:
                        self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                        self.add_to_history("user", rejection)
                        _guard_reject += 1
                        if _guard_reject >= _MAX_GUARD_REJECT:
                            self.log(f"Guard-reject 워치독 발동 ({_guard_reject}회 연속 거부) — 종료")
                            self.io.send_ai_message(
                                "에이전트가 올바른 다음 단계를 내지 못하고 같은 응답을 반복하고 있습니다. "
                                "세션을 종료합니다. 다시 시작해주세요."
                            )
                            break
                        continue
                    _guard_reject = 0
                    _no_progress = 0
                    result = self._execute_tool(tool_name, decision.get("params", {}))
                    self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                    if self.state.get("done"):
                        break
                    continue

                if "update_state" in decision:
                    # 상태 업데이트만 반복되면 워치독으로 종료한다.
                    self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                    _no_progress += 1
                    if _no_progress >= _MAX_NO_PROGRESS:
                        self.log(f"No-progress 워치독 발동 ({_no_progress}회 연속 update_state-only) — 종료")
                        self.io.send_ai_message(
                            "에이전트가 다음 단계를 진행하지 못하고 있습니다. 세션을 종료합니다. "
                            "다시 시작해주세요."
                        )
                        break
                    continue

                _error_count += 1
                self.log(f"Unrecognized decision ({_error_count}/{_MAX_ERRORS}): {decision}")
                if _error_count >= _MAX_ERRORS:
                    print(f"\n❌ 연속 인식 불가 응답 {_MAX_ERRORS}회 — 종료합니다.")
                    break
                self.add_to_history("user", "Output valid JSON only. No other text.")

            except KeyboardInterrupt:
                break
            except Exception as e:
                # 중지 요청으로 발생한 예외는 정상 종료로 처리한다.
                if self._stop_requested():
                    self.log("Stop 요청 감지 — 종료합니다.")
                    break
                print(f"\n❌ 오류 발생: {str(e)}")
                import traceback as _tb
                _tb.print_exc()
                break

    @abstractmethod
    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        pass
