#!/usr/bin/env python3
"""Agent 입출력을 터미널과 WebSocket 환경에 맞게 연결한다."""

import queue
import threading
from abc import ABC, abstractmethod
from typing import List, Optional
from pathlib import Path


class IOHandler(ABC):
    @abstractmethod
    def get_input(self) -> str:
        """Block until user provides input. Returns stripped string."""
        pass

    @abstractmethod
    def send_ai_message(self, message: str, requires_confirm: bool = False):
        """AI 메시지를 보내고 필요하면 완료 확인을 요청한다."""
        pass

    @abstractmethod
    def send_tool_output(self, text: str):
        """Send tool stdout → right panel."""
        pass

    @abstractmethod
    def send_plots(self, file_paths: List[str]):
        """Send plot image paths → right panel."""
        pass

    @abstractmethod
    def send_status(self, text: str):
        """Update status bar."""
        pass

    @abstractmethod
    def send_tool_error(self, tool_name: str, error_msg: str, attempts: int):
        """Tool 최종 실패 알림 → 왼쪽 패널 빨간 버블."""
        pass

    @abstractmethod
    def wait_for_retry(self):
        """사용자가 '다시 시도' 버튼을 클릭할 때까지 블로킹."""
        pass


class TerminalIO(IOHandler):
    """Default: same behavior as before (print / input)."""

    def get_input(self) -> str:
        return input("👤 You: ").strip()

    def send_ai_message(self, message: str, requires_confirm: bool = False):
        print(f"\n💬 Agent: {message}")

    def send_tool_output(self, text: str):
        print(text, flush=True)

    def send_plots(self, file_paths: List[str]):
        for f in file_paths:
            print(f"   📊 Plot saved → {Path(f).name}")

    def send_status(self, text: str):
        print(f"[Status] {text}")

    def send_tool_error(self, tool_name: str, error_msg: str, attempts: int):
        print(f"\n❌ [Tool Error] {tool_name} ({attempts}회 시도 모두 실패): {error_msg}")

    def wait_for_retry(self):
        input("다시 시도하려면 Enter를 누르세요...")


class WebSocketIO(IOHandler):
    """WebSocket-backed I/O for the web UI."""

    # 물리 작업이 필요한 메시지에는 완료 버튼을 표시한다.
    _CONFIRM_KEYWORDS = [
        "이동해주세요",       # 스테이지 또는 타워 이동.
        "설정해주세요",       # 빔 에너지 설정.
        "확인해주세요",       # 결과 확인.
        "다음 DAQ를 시작합니다",  # 다음 DAQ 준비.
        "전압이 변경되었습니다",  # HV 변경 확인.
    ]

    # HV 승인 메시지에는 완료와 수정 버튼을 표시한다.
    _HV_CONFIRM_KEYWORDS = [
        "적용하시겠습니까",
    ]

    def __init__(self, input_queue: queue.Queue, output_queue: queue.Queue,
                 stop_event: Optional[threading.Event] = None,
                 waiting_flag: Optional[threading.Event] = None):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.stop_event = stop_event
        self.waiting_flag = waiting_flag      # 입력 대기 상태.
        self._last_needs_confirm = False      # 일반 완료 버튼 표시 여부.
        self._last_needs_hv_confirm = False   # HV 승인 버튼 표시 여부.

    def send_ai_message(self, message: str, requires_confirm: bool = False):
        self._last_needs_hv_confirm = any(kw in message for kw in self._HV_CONFIRM_KEYWORDS)
        self._last_needs_confirm = (
            not self._last_needs_hv_confirm
            and (requires_confirm or any(kw in message for kw in self._CONFIRM_KEYWORDS))
        )
        self.output_queue.put({"type": "ai_message", "content": message})

    def get_input(self) -> str:
        from agents.agent_runner import StopAgentException
        # HV 승인은 완료와 수정, 일반 작업은 완료 버튼만 사용한다.
        if self._last_needs_hv_confirm:
            self.output_queue.put({"type": "awaiting_hv_confirm"})
        elif self._last_needs_confirm:
            self.output_queue.put({"type": "awaiting_input"})
        self._last_needs_confirm = False   # 다음 입력을 위해 초기화한다.
        self._last_needs_hv_confirm = False
        # 시나리오 에이전트의 입력 대기 상태를 알린다.
        if self.waiting_flag is not None:
            self.waiting_flag.set()
        try:
            # 입력 대기 중에도 중지 요청을 확인한다.
            while True:
                if self.stop_event and self.stop_event.is_set():
                    raise StopAgentException()
                try:
                    value = self.input_queue.get(timeout=0.2)
                    return value.strip()
                except queue.Empty:
                    continue
        finally:
            if self.waiting_flag is not None:
                self.waiting_flag.clear()

    def send_tool_output(self, text: str):
        if text and text.strip():
            self.output_queue.put({"type": "tool_output", "content": text})

    def send_plots(self, file_paths: List[str]):
        for path in file_paths:
            # 서버가 제공할 플롯 파일명만 전송한다.
            self.output_queue.put({"type": "plot", "filename": Path(path).name})

    def send_status(self, text: str):
        self.output_queue.put({"type": "status", "content": text})

    def send_tool_error(self, tool_name: str, error_msg: str, attempts: int):
        self.output_queue.put({
            "type": "tool_error",
            "tool_name": tool_name,
            "error": error_msg,
            "attempts": attempts,
        })

    def wait_for_retry(self) -> str:
        from agents.agent_runner import StopAgentException
        self.output_queue.put({"type": "awaiting_retry"})
        if self.waiting_flag is not None:
            self.waiting_flag.set()
        try:
            while True:
                if self.stop_event and self.stop_event.is_set():
                    raise StopAgentException()
                try:
                    val = self.input_queue.get(timeout=0.2)
                    return val
                except queue.Empty:
                    continue
        finally:
            if self.waiting_flag is not None:
                self.waiting_flag.clear()
