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
from app.dashboard import live as LV
from app.db.engine import get_sessionmaker

STATIC = pathlib.Path(__file__).resolve().parent / "static"
NOTIFY = str(pathlib.Path(__file__).resolve().parents[2] / "ops/runbooks/telegram_notify.sh")
MARKET_TTL_S = 120
CAPS_TTL_S = 6 * 3600

app = FastAPI(title="Prajna research dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_cache: dict[str, tuple[float, Any]] = {}
_lock = asyncio.Lock()
LIVE = LV.LiveQuotes()


@app.on_event("startup")
async def _start_live() -> None:
    if os.environ.get("PRAJNA_DASHBOARD_LIVE", "1") == "1":
        LIVE.start()


def _live_row(m: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    """A market row with the live quote and the live indicators / signal applied."""
    from app.dashboard import analysis as A
    out = LV.overlay(r, LIVE.get(r["key"]))
    ind = LIVE.indicators.get(r["key"])
    if ind and "cap_bucket" in r:
        f = {**m["feat"].get(r["key"], {}), **{k: v for k, v in ind.items() if v is not None}}
        e5 = m["e5map"].get(r["key"])
        sig = A.research_signal(f, e5, bool(e5 and e5["selected"]))
        out.update(signal=sig["label"], signal_score=sig["score"], trend=sig["trend"],
                   action=A.ACTIONS.get(sig["label"]), ret_5d=f.get("ret_5d"),
                   ret_20d=f.get("ret_20d"), rsi_14=f.get("rsi_14"),
                   volatility_20=f.get("volatility_20"), dist_high_252=f.get("dist_high_252"),
                   indicators_basis="live")
    return out


async def _view() -> dict[str, Any]:
    """The cached market view with the live quotes, indicators and signals applied
    (computed once per live cycle)."""
    m = await _market()
    memo = _cache.get("view")
    if memo and memo[0] == (id(m), LIVE.cycles):
        return memo[1]
    stocks = [_live_row(m, r) for r in m["stocks"]]
    ups = sum(1 for r in stocks if (r["day_change"] or 0) > 0)
    downs = sum(1 for r in stocks if (r["day_change"] or 0) < 0)
    v = {**m, "stocks": stocks,
            "indices": [LV.overlay(r, LIVE.get(r["key"])) for r in m["indices"]],
            "breadth": {"advances": ups, "declines": downs,
                        "unchanged": len(stocks) - ups - downs},
            "live": LIVE.summary()}
    _cache["view"] = ((id(m), LIVE.cycles), v)
    return v


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
    m = await _view()
    return _json({k: v for k, v in m.items() if k not in ("stocks", "feat", "e5map")}
                 | {"stocks": len(m["stocks"])})


@app.get("/api/movers")
async def movers(bucket: str = "ALL", period: str = "day", n: int = Query(15, le=50)
                 ) -> JSONResponse:
    m = await _view()
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
    m = await _view()
    return _json({"sectors": DD.sectors(m["stocks"]), "as_of": m["as_of"]})


@app.get("/api/stocks")
async def stocks(sector: str | None = None, bucket: str | None = None,
                 signal: str | None = None) -> JSONResponse:
    m = await _view()
    rows = [r for r in m["stocks"] if (not sector or r["sector"] == sector)
            and (not bucket or r["cap_bucket"] == bucket) and (not signal or r["signal"] == signal)]
    return _json({"rows": sorted(rows, key=lambda r: -(r["cap_cr"] or 0))[:300],
                  "count": len(rows)})


@app.get("/api/news")
async def news(hours: int = Query(24, ge=1, le=168), source: str | None = None,
               limit: int = Query(150, ge=1, le=500)) -> JSONResponse:
    async with get_sessionmaker()() as s:
        out = await DD.hot_news(s, hours, limit, source)
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
    q = LIVE.get(out["key"])
    if q:
        out.update(LV.overlay({k: out[k] for k in ("close", "day_change", "close_date")}, q))
        out["live"] = q
    ind = LIVE.indicators.get(out["key"])
    if ind:
        from app.dashboard import analysis as A
        f = {**out["features"], **{k: v for k, v in ind.items() if v is not None}}
        e5 = out["e5_today"]
        sig = A.research_signal(f, e5, bool(e5 and e5.get("selected")))
        lv = dict(out["levels"])
        if q and q.get("low") is not None:
            lv["support_20"] = min(x for x in (lv["support_20"], q["low"]) if x is not None)
            lv["resistance_20"] = max(x for x in (lv["resistance_20"], q["high"]) if x is not None)
        out.update(features=f, trend=A.trend(f), signal=sig, levels=lv,
                   ranges=A.ranges(out["close"], f.get("atr_pct_14"), e5),
                   plan=A.trade_plan(out["close"], f, lv, sig),
                   indicators_basis="live: Stage 3 price definitions on stored daily bars "
                                    "plus today's live bar")
    out["live_status"] = LIVE.summary()
    out["ai"] = AIS.cached(out["symbol"])
    return _json(out)


@app.get("/api/quote/{symbol}")
async def quote(symbol: str) -> JSONResponse:
    """The cached live quote of one stock (no vendor call per request)."""
    async with get_sessionmaker()() as s:
        k = await _key(s, symbol)
        await s.rollback()
    return _json({"symbol": symbol, "quote": LIVE.get(k), "live": LIVE.summary()})


@app.get("/api/candles/{symbol}")
async def candles(symbol: str, tf: str = Query("1d", pattern="^(1d|1h|15m|5m|1m)$")
                  ) -> JSONResponse:
    async with get_sessionmaker()() as s:
        k = await _key(s, symbol)
        out = await DD.candles_for(s, k, tf)
        if tf == "1d":
            last = out["bars"][-1]["date"] if out["bars"] else None
            q = LIVE.get(k)
            if q and (not last or last < q["date"]) and q["open"] is not None:
                pb = {"time": q["date"], "date": q["date"], "open": q["open"],
                      "high": q["high"], "low": q["low"], "close": q["ltp"],
                      "volume": q["volume"], "provisional": True, "source": "live quote"}
            else:
                pb = await DD.provisional_daily(s, k, last)
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
    if "model_note" not in _cache:
        _cache["model_note"] = (0.0, bedrock_model(st_.PRAJNA_NEWS_AI_REGION, max_tokens=1200))
    return _json(await AIS.generate(st, _cache["model_note"][1], st_.PRAJNA_NEWS_AI_MODEL_ID))


@app.get("/api/global")
async def global_() -> JSONResponse:
    async with get_sessionmaker()() as s:
        flows = await DD.fii_dii(s)
        await s.rollback()
    m = await _view()
    return _json({"india": m["indices"], "global": LIVE.global_view(), "flows": flows,
                  "not_available": ["KOSPI", *LIVE.ext_missing], "live": LIVE.summary(),
                  "note": "Global indices and Sensex: Upstox live quotes; Brent, WTI and USD/INR: "
                          "Upstox intraday 30-minute candles (every 5 min); US 10Y: US Treasury "
                          "and dollar index: FRED (daily, about a day behind); FII/DII: NSE "
                          "cash market, published the next morning. Display only."})


@app.get("/api/report")
async def report_list() -> JSONResponse:
    from app.dashboard import report as RP
    return _json({"reports": RP.latest(10)})


@app.post("/api/report/generate")
async def report_generate(telegram: bool = False) -> JSONResponse:
    from app.core.config import get_settings
    from app.dashboard import report as RP
    st_ = get_settings()
    if not (st_.PRAJNA_NEWS_AI_ENABLED and st_.PRAJNA_NEWS_AI_MODEL_ID):
        raise HTTPException(409, "AI is disabled (PRAJNA_NEWS_AI_ENABLED / MODEL_ID)")
    m = await _view()
    from app.core.clock import IST, now
    today = now().astimezone(IST)
    async with get_sessionmaker()() as s:
        news_ = await DD.hot_news(s, max(6, today.hour + 1), 300, "MEDIA")
        flows = await DD.fii_dii(s)
        res = await DD.results_today(s, today.date())
        await s.rollback()
    glob = LIVE.global_view()
    india = m["indices"] + [g for g in glob if g["key"] in ("BSE_INDEX|SENSEX",
                                                           "GLOBAL_INDEX|SGX NIFTY")]
    india = [{"name": x.get("name"), "close": x.get("close", x.get("ltp")),
              "day_change": x.get("day_change", x.get("change")), "price_at": x.get("price_at",
                                                                                   x.get("at"))}
             for x in india]
    fx = RP.facts({**m, "indices": india}, [g for g in glob if g["key"] not in (
        "BSE_INDEX|SENSEX", "GLOBAL_INDEX|SGX NIFTY")], news_, DD.sectors(m["stocks"]), flows, res)
    from app.news.ai import bedrock_model
    if "model_long" not in _cache:                 # a report needs more than 600 tokens
        _cache["model_long"] = (0.0, bedrock_model(st_.PRAJNA_NEWS_AI_REGION, max_tokens=3000))
    fx["not_available"] = ["KOSPI", *LIVE.ext_missing]
    rec = await RP.generate(fx, _cache["model_long"][1], st_.PRAJNA_NEWS_AI_MODEL_ID)
    if telegram:
        rec["telegram_sent"] = await asyncio.to_thread(RP.send_telegram, rec, NOTIFY)
    return _json(rec)


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
                  else round(time.monotonic() - hit[0]), "live": LIVE.summary()})
