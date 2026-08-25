#!/usr/bin/env python3
"""AI 없이 HV·DQM 뷰어만 제공하는 최소 웹 서버."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from web import viewer_common


app = FastAPI(title="autoTB Minimal Viewers (no AI)")

# 정적 파일과 공용 HV·DQM 라우트를 등록한다.
viewer_common.mount_viewer_static(app)
app.include_router(viewer_common.router)


@app.get("/")
async def root():
    # 루트 경로에서 기본 안내를 반환한다.
    return JSONResponse({
        "ok": True,
        "message": "autoTB minimal viewers (no AI). Use /hv/check or /dqm/freeform",
        "hv_check_url": "/hv/check",
        "dqm_freeform_url": "/dqm/freeform",
    })
