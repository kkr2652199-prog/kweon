"""4군 전용 FastAPI: lotto4 API + 독립 정적 페이지."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.lotto4.v13_routes import router as lotto4_v13_router
from app.hyodo.routes import router as hyodo_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(title="나의 지식 도서관 — 4군 AI 예측", version="0.1.0")

_ALLOW_ORIGIN_REGEX = (
    r"https?://("
    r"localhost|127\.0\.0\.1|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}"
    r")(?::\d+)?$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(lotto4_v13_router)
app.include_router(hyodo_router)


@app.get("/")
async def root():
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.on_event("startup")
async def startup():
    from app.lotto.models import init_lotto_db
    from app.lotto2.models import init_lotto2_db
    from app.lotto4.models import init_lotto4_db
    from app.lotto4.v13_weights_v2 import init_v13_v2_seeds

    init_lotto_db()
    init_lotto2_db()
    init_lotto4_db()
    init_v13_v2_seeds()
    from app.hyodo.models import init_hyodo_db

    init_hyodo_db()
    from app.lotto.draw_scheduler import start_draw_collect_scheduler

    start_draw_collect_scheduler()
