#!/usr/bin/env python3
"""
autoTB Web UI — Simulation Mode
Usage: python run_web_sim.py [--host 0.0.0.0] [--port 8000]

DAQ/HV/Motor/Google Sheets 등 하드웨어·원격 연결 없이
finetuned agent의 tool calling·인자·워크플로우를 검증합니다.

실제 run_web.py와 동일한 UI를 사용하며, tool은 호출되지만 mock 응답만 반환합니다.

개인 맥북에서 접속:
  맥미니: python run_web_sim.py
  맥북: ssh -L 8000:localhost:8000 PA353 -N
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="autoTB Web UI (Simulation)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", default=8000, type=int, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code change (dev only)")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  autoTB Control Panel  [SIMULATION MODE]")
    print(f"  http://localhost:{args.port}")
    print(f"  ⚠️  No DAQ / HV / Motor — tool calls are mocked")
    print(f"{'='*55}\n")

    uvicorn.run(
        "sim.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
