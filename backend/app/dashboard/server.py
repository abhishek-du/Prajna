"""Prajna research dashboard (user 2026-10-22). READ ONLY on the database; the only write
is the per-stock AI summary cache on disk. Never touches frontend/ or app/api/. PAPER
RESEARCH ONLY: nothing here places, modifies or cancels an order.

    .venv/bin/python -m app.dashboard [--host 127.0.0.1] [--port 8600]
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.dashboard import ai_summary as AIS
from app.dashboard import data as DD
from app.db.engine import get_sessionmaker

STATIC = pathlib.Path(__file__).resolve().parent / "static"
MARKET_TTL_S = 120
CAPS_TTL_S = 6 * 3600

app = FastAPI(title="Prajna research dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_cache: dict[str, tuple[float, Any]] = {}
_lock = asyncio.Lock()


def _json(x: Any) -> JSONResponse:
    return JSONResponse(x, headers={"Cache-Control": "no-store"})


async def _market() -> dict[str, Any]:
    async with _lock:
        hit = _cache.get("market")
        if hit and time.monotonic() - hit[0] < MARKET_TTL_S:
            return hit[1]
        caps = _cache.get("caps")
        async with get_sessionmaker()() as s:
            if not caps or time.monotonic() - caps[0] > CAPS_TTL_S:
                await DD.read_only(s)
                caps = (time.monotonic(), await DD.market_caps(s, await DD.last_closes(s)))
                _cache["caps"] = caps
            m = await DD.market(s, caps[1])
            await s.rollback()
        _cache["market"] = (time.monotonic(), m)
        return m


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/market")
async def market() -> JSONResponse:
    m = await _market()
    return _json({k: v for k, v in m.items() if k != "stocks"} | {"stocks": len(m["stocks"])})


@app.get("/api/movers")
async def movers(bucket: str = "ALL", period: str = "day", n: int = Query(15, le=50)
                 ) -> JSONResponse:
    m = await _market()
    rows = [r for r in m["stocks"] if bucket == "ALL" or r["cap_bucket"] == bucket]
    field = {"day": "day_change", "5d": "ret_5d", "20d": "ret_20d"}.get(period, "day_change")
    have = [r for r in rows if r[field] is not None and r["close"]]
    have.sort(key=lambda r: r[field])
    steady = sorted((r for r in rows if r["volatility_20"] is not None
                     and r["trend"] == "UPTREND" and r["cap_bucket"] in ("LARGE", "MID")),
                    key=lambda r: r["volatility_20"])[:n]
    return _json({"bucket": bucket, "period": period, "field": field,
                  "gainers": have[::-1][:n], "losers": have[:n], "steadier": steady,
                  "bullish": sorted((r for r in rows if r["signal"] == "BULLISH"),
                                    key=lambda r: -(r["signal_score"] or 0))[:n],
                  "bearish": sorted((r for r in rows if r["signal"] == "BEARISH"),
                                    key=lambda r: r["signal_score"] or 0)[:n],
                  "steadier_rule": "large/mid cap, uptrend, lowest 20-day volatility: "
                                   "steadier, not safe",
                  "features_session": m["features_session"], "as_of": m["as_of"],
                  "disclaimer": m["disclaimer"]})


@app.get("/api/sectors")
async def sectors() -> JSONResponse:
    m = await _market()
    return _json({"sectors": DD.sectors(m["stocks"]), "as_of": m["as_of"]})


@app.get("/api/stocks")
async def stocks(sector: str | None = None, bucket: str | None = None,
                 signal: str | None = None) -> JSONResponse:
    m = await _market()
    rows = [r for r in m["stocks"] if (not sector or r["sector"] == sector)
            and (not bucket or r["cap_bucket"] == bucket) and (not signal or r["signal"] == signal)]
    return _json({"rows": sorted(rows, key=lambda r: -(r["cap_cr"] or 0))[:300],
                  "count": len(rows)})


@app.get("/api/news")
async def news(hours: int = Query(24, ge=1, le=168)) -> JSONResponse:
    async with get_sessionmaker()() as s:
        out = await DD.hot_news(s, hours)
        await s.rollback()
    return _json(out)


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1, max_length=40)) -> JSONResponse:
    async with get_sessionmaker()() as s:
        out = await DD.search(s, q)
        await s.rollback()
    return _json(out)


async def _key(s, symbol: str) -> str:
    await DD.read_only(s)
    k = await DD.resolve(s, symbol)
    if not k:
        raise HTTPException(404, f"unknown symbol {symbol}")
    return k


@app.get("/api/stock/{symbol}")
async def stock(symbol: str) -> JSONResponse:
    async with get_sessionmaker()() as s:
        out = await DD.stock(s, await _key(s, symbol))
        await s.rollback()
    out["ai"] = AIS.cached(out["symbol"])
    return _json(out)


@app.get("/api/candles/{symbol}")
async def candles(symbol: str, tf: str = Query("1d", pattern="^(1d|1h|15m|5m|1m)$")
                  ) -> JSONResponse:
    async with get_sessionmaker()() as s:
        k = await _key(s, symbol)
        out = await DD.candles_for(s, k, tf)
        if tf == "1d":
            pb = await DD.provisional_daily(s, k, out["bars"][-1]["date"] if out["bars"] else None)
            if pb:
                out["bars"].append(pb)
                out["provisional_today"] = True
        await s.rollback()
    return _json(out)


@app.post("/api/ai/{symbol}")
async def ai(symbol: str) -> JSONResponse:
    from app.core.config import get_settings
    st_ = get_settings()
    if not (st_.PRAJNA_NEWS_AI_ENABLED and st_.PRAJNA_NEWS_AI_MODEL_ID):
        raise HTTPException(409, "AI is disabled (PRAJNA_NEWS_AI_ENABLED / MODEL_ID)")
    if not (os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or os.environ.get("AWS_ACCESS_KEY_ID")):
        raise HTTPException(409, "no AWS credentials in the dashboard's environment")
    async with get_sessionmaker()() as s:
        st = await DD.stock(s, await _key(s, symbol))
        await s.rollback()
    from app.news.ai import bedrock_model
    if "model" not in _cache:
        _cache["model"] = (0.0, bedrock_model(st_.PRAJNA_NEWS_AI_REGION))
    return _json(await AIS.generate(st, _cache["model"][1], st_.PRAJNA_NEWS_AI_MODEL_ID))


@app.get("/api/e5")
async def e5() -> JSONResponse:
    async with get_sessionmaker()() as s:
        out = await DD.e5_board(s)
        await s.rollback()
    return _json(out)


@app.get("/api/health")
async def health() -> JSONResponse:
    hit = _cache.get("market")
    return _json({"ok": True, "market_cached_s": None if not hit
                  else round(time.monotonic() - hit[0])})
