#!/usr/bin/env python3
"""
autoTB Web UI Entry Point
Usage: python run_web.py [--host 0.0.0.0] [--port 8000]

개인 맥북에서 접속하려면 
맥미니: python run_web.py
맥북: ssh -L 8000:localhost:8000 PA353 -N

"""
import sys
import argparse
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="autoTB Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", default=8000, type=int, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code change (dev only)")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  autoTB Control Panel")
    print(f"  http://localhost:{args.port}")
    print(f"{'='*55}\n")

    uvicorn.run(
        "web.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
