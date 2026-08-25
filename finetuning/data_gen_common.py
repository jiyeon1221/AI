#!/usr/bin/env python3
"""학습 데이터 생성기가 공유하는 컨텍스트와 출력 함수."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List

# 보정과 HV 데이터 생성이 공유하는 타워 순서.
TOWER_ORDER = ["T1", "T2", "T3", "T6", "T5", "T4", "T7", "T8", "T9"]

DATA_DIR = Path(__file__).parent / "data"


def random_events() -> int:
    """3~6자리에서 자릿수별로 균등하게 이벤트 수를 고른다."""
    digits = random.randint(3, 6)
    return random.randint(10 ** (digits - 1), 10 ** digits - 1)


def make_example(system_prompt: str, context: str, decision: Dict) -> Dict:
    """학습용 3-message 샘플."""
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
            {"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)},
        ]
    }


def write_dataset(filename: str, examples: List[Dict]) -> List[int]:
    """샘플을 JSONL로 저장하고 문자 길이 통계를 반환한다."""
    output_file = DATA_DIR / filename
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    lengths = [sum(len(m["content"]) for m in ex["messages"]) for ex in examples]
    print(f"Generated {len(examples)} samples -> {output_file}")
    if lengths:
        print(f"   char len  max={max(lengths):,}  avg={sum(lengths) / len(lengths):,.0f}")
    return lengths
