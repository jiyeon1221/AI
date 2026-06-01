#!/usr/bin/env python3
"""autoTB Configuration"""

from pathlib import Path

# ===== 프로젝트 경로 =====
PROJECT_ROOT = Path(__file__).parent
MODELS_DIR = PROJECT_ROOT / "models"

MODELS_DIR.mkdir(exist_ok=True)

# ===== 모델 설정 =====
AGENT_MODELS = {
    "energy_scan": {
        "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "fine_tuned_path": str(MODELS_DIR / "energy_scan_agent" / "final"),
        "memory_mb": 3000,
        "description": "Energy Scan Agent (에너지 스캔)"
    },
    
    "calibration": {
        "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "fine_tuned_path": str(MODELS_DIR / "calibration_agent" / "final"),
        "memory_mb": 3000,
        "description": "Calibration Agent (캘리브레이션)"
    },
    
    "position_scan": {
        "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "fine_tuned_path": str(MODELS_DIR / "position_scan_agent" / "final"),
        "memory_mb": 3000,
        "description": "Position Scan Agent (위치 스캔)"
    },
    
    "hv_equalization": {
        "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "fine_tuned_path": str(MODELS_DIR / "hv_equalization_agent" / "final"),
        "memory_mb": 3000,
        "description": "HV Equalization Agent (HV 조정)"
    },

    "brain": {
        "base_model": "Qwen/Qwen2.5-3B-Instruct",
        "fine_tuned_path": str(MODELS_DIR / "brain_agent" / "final"),
        "memory_mb": 6000,
        "description": "Brain Agent (범용 도구 호출)"
    }
}

# ===== Agent 설정 =====
MAX_CONVERSATION_HISTORY = 20
MAX_NEW_TOKENS = 512
TEMPERATURE = 0.0
