#!/usr/bin/env python3
"""Configuration Loader — config_general.yml 파싱 유틸리티"""

import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional


PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "config_general.yml"

_config_cache: Optional[Dict[str, Any]] = None


def load_config() -> Dict[str, Any]:
    """config_general.yml 파일을 읽어서 딕셔너리로 반환"""
    global _config_cache
    
    if _config_cache is not None:
        return _config_cache
    
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"설정 파일을 찾을 수 없습니다: {CONFIG_FILE}\n"
            f"config_general.yml 파일이 존재하는지 확인하세요."
        )
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            _config_cache = yaml.safe_load(f) or {}
        return _config_cache
    except Exception as e:
        raise RuntimeError(f"설정 파일 읽기 실패: {e}")


def get_data_directory() -> str:
    """데이터 디렉토리 경로 반환 (BaseDirectory 사용)"""
    config = load_config()
    base_dir = config.get("BaseDirectory")
    if not base_dir:
        raise ValueError(
            "설정 파일에 'BaseDirectory'가 없습니다.\n"
            f"config_general.yml 파일에 다음을 추가하세요:\n"
            f"  BaseDirectory: \"/path/to/data\""
        )
    return str(base_dir)


def get_mapping_root_path() -> str:
    """매핑 ROOT 파일 경로 반환"""
    config = load_config()
    mapping = config.get("Mapping")
    if not mapping:
        raise ValueError(
            "설정 파일에 'Mapping'이 없습니다.\n"
            f"config_general.yml 파일에 다음을 추가하세요:\n"
            f"  Mapping: \"/path/to/mapping_KEK.root\""
        )

    if not os.path.isabs(mapping):
        dqm_dir = PROJECT_ROOT / "DQM"
        mapping_path = (dqm_dir / mapping).resolve()
    else:
        mapping_path = Path(mapping)

    return str(mapping_path)


def get_path_config(key: str) -> str:
    """설정 파일의 Paths 섹션에서 경로를 가져옴"""
    config = load_config()
    paths = config.get("Paths", {})
    val = paths.get(key)
    if not val:
        raise ValueError(f"설정 파일의 Paths 섹션에 '{key}'가 정의되지 않았습니다.")
    
    # 스프레드시트 ID는 경로 변환에서 제외한다.
    if key == "SpreadsheetId":
        return str(val)
        
    # 상대 경로를 프로젝트 기준 절대 경로로 바꾼다.
    if not os.path.isabs(str(val)):
        return str((PROJECT_ROOT / str(val)).resolve())
        
    return str(val)


def get_hv_config() -> Dict[str, Any]:
    """HV 설정 반환"""
    config = load_config()
    return config.get("HV", {})


def get_run_log_fixed_hv_path() -> Path:
    """런 로그의 DRC HV 비교 기준 파일 경로 반환 (RunLog.FixedHvFile).

    실험 시기에 따라 기준을 fixed_hv_v1/v2 등으로 바꿔 끼울 수 있도록 config에서 지정한다.
    HV Equalization이 기록하는 대상(항상 fixed_hv.txt)과는 별개 — 비교 전용이다.
    미지정이면 fixed_hv.txt. 상대 경로는 프로젝트 루트 기준으로 해석한다."""
    config = load_config()
    val = str((config.get("RunLog") or {}).get("FixedHvFile") or "fixed_hv.txt")
    path = Path(val)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def get_run_log_beam_type() -> str:
    """새 Run 로그 작성 시 사용할 기본 Beam Type 반환 (RunLog.BeamType)"""
    config = load_config()
    return str(config.get("RunLog", {}).get("BeamType", "e-"))


def get_dqm_dir() -> Path:
    """DQM 소스 디렉터리 (Paths.DqmDir). monit 바이너리·jsroot·config가 여기 있다."""
    return Path(get_path_config("DqmDir"))


def get_dqm_output_dir() -> Path:
    """monit이 ROOT/JSON canvas를 떨어뜨리는 디렉터리."""
    out = get_dqm_dir() / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_studio_ssh() -> Dict[str, str]:
    """Mac Studio SSH 접속 정보 — 키 이름 표기 흔들림(User/Username)을 흡수한다."""
    cfg = load_config().get("StudioSSH", {}) or {}
    return {
        "host": str(cfg.get("Host", "")),
        "user": str(cfg.get("User") or cfg.get("Username") or ""),
        "password": str(cfg.get("Password", "")),
    }


def get_last_finished_run_number() -> Optional[int]:
    """방금 종료된 run number.

    DAQ가 종료되면 runnum.txt는 '다음' 번호로 갱신되므로 -1 한다.
    DAQ 실행 중에 얻은 번호를 쓸 수 있다면 daq_tool이 출력에 심는 마커
    (parse_run_number_from_daq_output)를 쓰는 쪽이 정확하다 — 이 함수는
    그 경로가 없을 때의 fallback이다.
    """
    try:
        with open(get_path_config("RunNumberFile"), "r") as f:
            return int(f.read().strip()) - 1
    except Exception:
        return None

