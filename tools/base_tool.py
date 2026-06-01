#!/usr/bin/env python3
"""
Base Tool 클래스

모든 Tool이 상속받아야 하는 기본 클래스
Tool Manager가 일관된 방식으로 Tool을 호출할 수 있도록 표준 인터페이스 제공
"""

from typing import Dict, Any, Tuple
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """모든 Tool의 기본 클래스"""
    
    def __init__(self, name: str, description: str):
        """
        Args:
            name: Tool 이름
            description: Tool 설명
        """
        self.name = name
        self.description = description
    
    @abstractmethod
    def execute(self, params: Dict[str, Any]) -> str:
        """
        Tool 실행 메서드 (각 Tool에서 반드시 구현해야 함)
        
        Args:
            params: Tool 실행에 필요한 파라미터 (dict)
        
        Returns:
            실행 결과 문자열 (프로그램 출력 그대로)
        """
        raise NotImplementedError("execute() 메서드를 구현해야 합니다")
    
    def validate_params(self, params: Dict[str, Any], required_keys: list) -> Tuple[bool, str]:
        """
        파라미터 검증
        
        Args:
            params: 검증할 파라미터
            required_keys: 필수 키 리스트
        
        Returns:
            (성공 여부, 에러 메시지)
        """
        if not isinstance(params, dict):
            return False, "파라미터는 dict 형식이어야 합니다"
        
        for key in required_keys:
            if key not in params:
                return False, f"필수 파라미터 누락: {key}"
            if params[key] is None:
                return False, f"파라미터 값이 None입니다: {key}"
        
        return True, ""
    
    def __str__(self):
        return f"{self.name}: {self.description}"
