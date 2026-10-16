"""Prajna Trading Intelligence Dashboard API Application."""

from __future__ import annotations

import contextlib
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.candles import router as candles_router
from app.api.features import router as features_router
from app.api.fundamentals import router as fundamentals_router
from app.api.globals import router as globals_router
from app.api.health import router as health_router
from app.api.instruments import router as instruments_router
from app.api.news import router as news_router
from app.api.ops import router as ops_router
from app.api.overview import router as overview_router
from app.api.portfolio import router as portfolio_router
from app.api.screener import router as screener_router
from app.api.signals import router as signals_router
from app.api.stages import router as stages_router
from app.api.technicals import router as technicals_router
from app.api.ws import router as ws_router

@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Stage 1 coverage takes ~13 s (canon_excluded_bar scans ohlcv_bar): compute it once
    in the background at startup so no page waits for it."""
    import asyncio

    from app.api.stages import warm_coverage
    task = asyncio.get_running_loop().create_task(warm_coverage())
    yield
    task.cancel()


app = FastAPI(
    lifespan=_lifespan,
    title="Prajna Trading Intelligence API",
    version="1.0.0",
    description="Upstox-only, provenance-bearing market intelligence and data dashboard for NSE.",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration for development frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all v1 API routers
api_v1_prefix = "/api/v1"
app.include_router(overview_router, prefix=api_v1_prefix)
app.include_router(instruments_router, prefix=api_v1_prefix)
app.include_router(candles_router, prefix=api_v1_prefix)
app.include_router(technicals_router, prefix=api_v1_prefix)
app.include_router(fundamentals_router, prefix=api_v1_prefix)
app.include_router(globals_router, prefix=api_v1_prefix)
app.include_router(news_router, prefix=api_v1_prefix)
app.include_router(screener_router, prefix=api_v1_prefix)
app.include_router(signals_router, prefix=api_v1_prefix)
app.include_router(stages_router, prefix=api_v1_prefix)
app.include_router(features_router, prefix=api_v1_prefix)
app.include_router(portfolio_router, prefix=api_v1_prefix)
app.include_router(health_router, prefix=api_v1_prefix)
app.include_router(ops_router, prefix=api_v1_prefix)
app.include_router(ws_router, prefix=api_v1_prefix)
app.include_router(ws_router)


# Mount frontend production build if it exists
frontend_dist = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "dist"
if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run("app.api.app:app", host=host, port=port, reload=False)
