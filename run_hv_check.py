#!/usr/bin/env python3
"""
HV Status Check — 독립 실행 진입점
Usage: python run_hv_check.py [--port 8002] [--no-browser]

run_web.py가 꺼져 있어도, 이 스크립트 단독으로
http://localhost:<port>/hv/check 를 열어 HV 체크 별도 창을 띄웁니다.
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
    parser = argparse.ArgumentParser(description="HV Status Check Viewer")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", default=8002, type=int, help="Bind port (default: 8002)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 비활성화")
    args = parser.parse_args()

    url = f"http://localhost:{args.port}/hv/check"

    print(f"\n{'='*55}")
    print(f"  autoTB HV Check")
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

