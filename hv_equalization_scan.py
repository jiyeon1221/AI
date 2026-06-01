#!/usr/bin/env python3
"""
HV Equalization Scan Controller
config를 Python에서 한 번만 받고, 타워를 순서대로 돌며 HVEqualizationTowerAgent를 호출.
"""

import os
from pathlib import Path

from tools.hv_equalization_tool import hv_equalization_start
from agents.hv_equalization_agent import HVEqualizationAgent

FIXED_HV_PATH = Path(__file__).parent / "fixed_hv.txt"


def _write_fixed_hv():
    """모든 타워 equalization 완료 후 현재 V0Set을 fixed_hv.txt에 저장 (read-only 보호)"""
    from tools.hv_control_tool import HVControlTool
    hv = HVControlTool()
    try:
        if not hv._ensure_connection():
            print("⚠️ HV 연결 실패 — fixed_hv.txt 업데이트 스킵")
            return

        rows = hv._read_config_rows()
        name_to_vset = {}
        for row in rows:
            name = str(row.get("name", "")).strip()
            if not name or name.lower() == "none":
                continue
            name_to_vset[name.upper()] = str(row.get("V0Set", "")).strip()

        drc_channels = [f"T{i}{s}" for i in range(1, 10) for s in ("S", "C")]
        lines = ["# Fixed HV reference — DO NOT MODIFY (edit manually with chmod 644 first)"]
        for ch in drc_channels:
            val = name_to_vset.get(ch, "")
            if val:
                lines.append(f"{ch}:{val}")

        if FIXED_HV_PATH.exists():
            os.chmod(FIXED_HV_PATH, 0o644)

        with open(FIXED_HV_PATH, "w") as f:
            f.write("\n".join(lines) + "\n")

        os.chmod(FIXED_HV_PATH, 0o444)
        print(f"✅ fixed_hv.txt 업데이트 완료 ({len(lines) - 1}개 채널)")

    except Exception as e:
        print(f"⚠️ fixed_hv.txt 업데이트 실패: {e}")
    finally:
        try:
            if hv.ssh_client:
                hv.ssh_client.close()
        except Exception:
            pass

TOWER_ORDER = ["T1", "T2", "T3", "T6", "T5", "T4", "T7", "T8", "T9"]


def main():
    print("\n" + "=" * 60)
    print("⚡ HV Equalization Scan")
    print("=" * 60)

    # Config 수집 (한 번만)
    beam_energy = float(input("빔 에너지 (GeV): ").strip())
    target_events = int(input("이벤트 수: ").strip())
    target_adc = float(input("목표 peakADC: ").strip())

    # HV Equalization 세션 초기화 (한 번만)
    result = hv_equalization_start.invoke({
        "target_c": target_adc,
        "target_s": target_adc,
        "tower": TOWER_ORDER[0],
    }) if hasattr(hv_equalization_start, "invoke") else hv_equalization_start(
        target_c=target_adc, target_s=target_adc, tower=TOWER_ORDER[0]
    )
    print(result)

    # 타워 루프
    for i, tower in enumerate(TOWER_ORDER):
        print(f"\n[{i + 1}/{len(TOWER_ORDER)}] {tower} 타워 시작")
        agent = HVEqualizationAgent(
            tower=tower,
            beam_energy=beam_energy,
            target_events=target_events,
            target_adc=target_adc,
            use_base_model=False,
        )
        with agent:
            agent.run()
        print(f"✅ {tower} 완료")

    print("\n🎉 모든 타워 HV Equalization 완료!")
    _write_fixed_hv()


if __name__ == "__main__":
    main()
