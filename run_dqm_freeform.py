#!/usr/bin/env python3
"""
DQM Freeform Viewer — 독립 실행 진입점
Usage: python run_dqm_freeform.py [--port 8001] [--run 12345]

run_web.py와 동시에 실행해도 되고, 단독으로 실행해도 됩니다.
기본 포트(8001)는 run_web.py(8000)와 겹치지 않습니다.
"""
import sys
import argparse
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn


def _open_browser(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    webbrowser.open(url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DQM Freeform Viewer")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", default=8001, type=int, help="Bind port (default: 8001)")
    parser.add_argument("--run", default=None, type=int, help="미리 채울 Run 번호 (예: --run 12345)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 비활성화")
    args = parser.parse_args()

    url = f"http://localhost:{args.port}/dqm/freeform"
    if args.run:
        url += f"?run={args.run}"

    print(f"\n{'='*55}")
    print(f"  DQM Freeform Viewer")
    print(f"  {url}")
    print(f"{'='*55}\n")

    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    uvicorn.run(
        "web.min_server:app",
        host=args.host,
        port=args.port,
        log_level="warning",
    )
