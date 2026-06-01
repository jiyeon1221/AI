#!/usr/bin/env python3
"""
Calibration Scan Agent 실행
"""

from agents import CalibScanAgent

def main():
    print("\n" + "="*70)
    print("⚡ Calibration Scan Agent")
    print("="*70)

    agent = CalibScanAgent(
        beam_energy=None,       # 대화에서 입력받도록 None
        target_events=None,
        use_base_model=False,
    )

    with agent:
        agent.run()

if __name__ == "__main__":
    main()
