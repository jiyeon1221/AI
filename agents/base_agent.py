#!/usr/bin/env python3
"""
Base Agent
----------
Abstract base class shared by all scenario agents (EnergyScan, CalibScan, HVEqualization).

Lifecycle:
  with agent:           → load()  : load Qwen model onto MPS / CUDA / CPU
    agent.run()         → subclass-defined experiment workflow
                        → decide(context) : LLM inference → JSON parse → action
  (exit with block)     → unload(): delete model & tokenizer, flush cache

Subclasses must implement:
  _get_system_prompt()   : step-by-step workflow instructions for the LLM
  _build_state_context() : serialize current state dict into a prompt string
  run()                  : conversation loop + tool execution logic
"""

import json
import time
import torch
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from pathlib import Path
from abc import ABC, abstractmethod

from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
)

import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import MAX_CONVERSATION_HISTORY, MAX_NEW_TOKENS


class ToolFatalError(Exception):
    """Tool이 max_retries 이후에도 실패했을 때 발생."""
    pass



class BaseAgent(ABC):
    """
    모든 Agent의 기본 클래스
    
    Features:
    - State 관리
    - Conversation history 관리 (최근 N개)
    - LLM 로드/언로드 (메모리 효율)
    - Context 생성
    """
    
    def __init__(self, model_path: str, agent_name: str, io_handler=None):
        """
        Args:
            model_path: Fine-tuned 모델 경로
            agent_name: Agent 이름 (로깅용)
            io_handler: IOHandler instance (None → TerminalIO)
        """
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
    
    # ===== Context Manager (자동 로드/언로드) =====
    
    def __enter__(self):
        """with 문 시작: 모델 로드"""
        self.load()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """with 문 종료: 모델 언로드"""
        self.unload()
        return False
    
    # ===== 모델 관리 =====
    
    def load(self):
        """모델 로드"""
        if self.model is not None:
            return
        
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
        
        self.model = AutoModelForCausalLM.from_pretrained(
            str(self.model_path),
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            device_map=self.device,
            trust_remote_code=True
        )
        
        print(f"  ✅ [{self.agent_name}] 모델 로드 완료: {self.model_path}")
    
    def unload(self):
        """모델 언로드 (메모리 해제)"""
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
    
    # ===== 대화 관리 =====
    
    def add_to_history(self, role: str, content: str, metadata: Optional[Dict] = None):
        """대화 히스토리에 추가"""
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
        """최근 N개 대화 반환"""
        if n is None:
            n = self.max_history
        return self.conversation_history[-n:]
    
    # ===== Context 생성 =====
    
    @abstractmethod
    def _build_state_context(self) -> str:
        """State를 문자열로 변환 (각 Agent가 구현)"""
        pass
    
    def _build_history_context(self) -> str:
        """대화 히스토리를 문자열로 변환 (최근 대화 우선)"""
        if not self.conversation_history:
            return "(No conversation yet)"
        
        lines = []
        recent_history = self.conversation_history[-self.max_history:]
        for msg in recent_history:
            role = "User" if msg["role"] == "user" else "Agent"
            content = msg["content"]

            if role == "Agent":
                try:
                    decision = json.loads(content)
                    if "message" in decision:
                        content = decision["message"]
                    elif "tool" in decision:
                        content = f"[Tool Call: {decision['tool']}]"
                        if "update_state" in decision:
                            content += f" (Update State: {list(decision['update_state'].keys())})"
                except:
                    pass

            lines.append(f"{role}: {content}")
        
        return "\n".join(lines)
    
    def build_full_context(self, current_input: Optional[str] = None) -> str:
        """전체 context 생성"""
        parts = []
        
        parts.append("=== Current State ===")
        parts.append(self._build_state_context())
        parts.append("")
        
        parts.append("=== Recent Conversation ===")
        parts.append(self._build_history_context())
        parts.append("")
        
        if current_input:
            parts.append("=== Current User Input ===")
            parts.append(current_input)
            parts.append("")
        
        parts.append("=== Your Task ===")
        parts.append("Based on the current state and conversation, decide the next action.")
        parts.append("Output JSON with tool name and parameters.")
        
        return "\n".join(parts)
    
    # ===== LLM 호출 =====
    
    def decide(self, context: str, max_retries: int = 3) -> Dict[str, Any]:
        """LLM에게 다음 행동 결정을 요청하고 JSON으로 반환.

        JSON 파싱 실패 시 max_retries 만큼 자동 재시도. 첫 시도는 greedy
        (do_sample=False), 재시도부터는 sampling on + 약간씩 다른 temperature
        를 적용해 모델이 같은 실수를 반복하지 않도록 유도한다."""
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
        """System prompt 반환 (Agent별로 구현)"""
        pass
    
    # ===== Tool params: state가 source of truth (LLM params 숫자는 실행 시 덮어씀) =====

    def _position_for_current_step(self) -> Optional[Dict[str, float]]:
        """현재 스캔 단계의 위치 {x, y}. 타워/에너지마다 다를 수 있음 — 서브클래스가 구현."""
        return None

    def _motor_x_for_current_step(self) -> float:
        """현재 단계 타워 위치의 X (LLM params['x'] 무시)."""
        pos = self._position_for_current_step()
        if pos is None:
            raise RuntimeError(f"[{self.agent_name}] _position_for_current_step() not implemented")
        return self._motor_x_from_state(pos["x"])

    def _motor_x_from_state(self, x_mm: float) -> float:
        """모터 X 위치 — state/config 값만 사용."""
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
    ) -> None:
        """DAQ params — update_state에 저장된 값으로 LLM 출력을 덮어씀."""
        if events is not None:
            params["events"] = events
        if beam_energy is not None:
            params["beam_energy"] = beam_energy
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
        """hv_execute voltage — last_suggested 등 state 값으로 channel_values 고정."""
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
        """hv_equalization_suggest — state에서 run/HV 주입 (LLM params 무시)."""
        params["tower"] = tower
        if run_number is not None:
            params["run_number"] = run_number
        if hv_c is not None:
            params["hv_c"] = hv_c
        if hv_s is not None:
            params["hv_s"] = hv_s

    # ===== DAQ run number =====

    def _extract_run_number(self, daq_output: Optional[str] = None) -> Optional[int]:
        """DAQ 시작 시 확정된 run number (daq_tool 마커 / Run: 줄). runnum.txt 재읽기 없음."""
        from tools.daq_tool import parse_run_number_from_daq_output

        run_number = parse_run_number_from_daq_output(daq_output)
        if run_number is None:
            self.log("WARNING: DAQ output에서 run number를 찾지 못함")
        return run_number

    # ===== Tool 재시도 =====

    def _run_tool_with_retry(self, tool_fn: Callable, tool_name: str, max_retries: int = 3) -> str:
        """tool_fn을 최대 max_retries번 자동 재시도. 모두 실패하면 에러 표시 후 사용자 '다시 시도' 대기."""
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
            action = self.io.wait_for_retry()  # blocks until retry or skip
            if action == "skip":
                return f"[SKIPPED] {tool_name} 건너뜀 (사용자 요청)"

    # ===== 로깅 =====
    # stdout only — no file I/O

    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{self.agent_name}] {message}", flush=True)
    
    # ===== 통합 실행 루프 (모든 시나리오 Agent 공용) =====
    #
    # 설계 원칙 — "code-authoritative bookkeeping":
    #   드라이버(이 루프)가 위치/확인/진행 상태(x_moved, y_confirmed, plot 확인,
    #   완료 표시, 종료)를 모두 소유한다. LLM은 message와 tool 호출만 결정한다.
    #   덕분에 "LLM이 완료/확인 플래그를 빠뜨려서" 생기던 무한 루프·조기 완료가
    #   구조적으로 사라진다. 각 Agent는 아래 hook만 구현하면 된다.

    # ---- Hooks (서브클래스가 필요 시 override) ----

    def _print_banner(self):
        print(f"\n{'='*70}\n⚡ {self.agent_name} Started\n{'='*70}")

    def _pre_iteration(self):
        """매 루프 시작에서 호출. 다음 작업 항목으로의 자동 전환 등."""
        pass

    def _is_complete(self) -> bool:
        """모든 작업이 끝났으면 True. True면 완료 메시지 후 루프 종료 → 모델 unload."""
        return bool(self.state.get("done"))

    def _completion_message(self) -> Optional[str]:
        """완료 시 사용자에게 보낼 메시지 (None이면 생략)."""
        return None

    def _completed_count(self) -> int:
        """완료된 작업 항목 수 (진행 메시지 트리거 감지용)."""
        return 0

    def _progress_message(self) -> Optional[str]:
        """작업 항목 하나가 완료될 때 보낼 진행 요약 (None이면 생략)."""
        return None

    def _on_user_input(self, user_input: str):
        """사용자 응답 직후 호출. 현재 단계에 맞는 확인 플래그를 코드가 직접 설정.
        LLM의 update_state에 의존하지 않는다."""
        pass

    def _guard_tool(self, tool_name: str, decision: Dict[str, Any]) -> Optional[str]:
        """tool 실행 전 가드. 거부 사유 문자열을 반환하면 실행을 막고
        그 문자열을 user 메시지로 히스토리에 넣어 재시도시킨다. None이면 통과."""
        return None

    # ---- 공용 메인 루프 ----

    def run(self):
        self._print_banner()
        self.log(f"{self.agent_name} 시작")

        if self.model is None:
            raise RuntimeError(f"[{self.agent_name}] Model not loaded. Use 'with agent:' statement.")

        _error_count = 0
        _MAX_ERRORS = 3

        while True:
            try:
                self._pre_iteration()

                # 모든 작업 완료 → 완료 메시지 후 종료 (with 블록 빠져나가며 unload)
                if self._is_complete():
                    msg = self._completion_message()
                    if msg:
                        self.io.send_ai_message(msg)
                    break

                context = self.build_full_context()
                decision = self.decide(context)
                print(f"\n🔍 Agent Decision:")
                print(json.dumps(decision, indent=2, ensure_ascii=False))

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
                    self.io.send_ai_message(message)
                    self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                    user_input = self.io.get_input()
                    if user_input in ["종료", "exit"]:
                        break
                    # 확인/완료 처리는 코드가 소유 (LLM update_state에 의존하지 않음)
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
                        self.log(f"tool 가드 차단 ({tool_name}): {rejection}")
                        self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                        self.add_to_history("user", rejection)
                        continue
                    print(f"\n🤖 Executing Tool: {tool_name}")
                    result = self._execute_tool(tool_name, decision.get("params", {}))
                    print(f"📝 Tool Result: {str(result)[:200]}...")
                    self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
                    if self.state.get("done"):
                        break
                    continue

                if "update_state" in decision:
                    self.add_to_history("assistant", json.dumps(decision, ensure_ascii=False))
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
                print(f"\n❌ 오류 발생: {str(e)}")
                import traceback as _tb
                _tb.print_exc()
                break

    # ===== 추상 메서드 =====

    @abstractmethod
    def _execute_tool(self, tool_name: str, params: Dict) -> str:
        """Tool 실행 (각 Agent가 구현)"""
        pass
