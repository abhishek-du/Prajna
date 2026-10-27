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
from datetime import date as _date
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
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
        _cache["alerts_task"] = (0.0, asyncio.create_task(_alert_loop()))


# ── plans for every stock, the forward record, the watchlist and alerts ─────────────────
def _plans_all(m: dict[str, Any]) -> list[dict[str, Any]]:
    """Today's plan for every stock in the market view (stored daily bars + today's
    official close / live quote as the last bar), the same rules as the stock page."""
    from app.dashboard import analysis as A
    from app.desk import rules as RJ  # dash-plan-v2 (2026-10-27)
    out = []
    for r in m["stocks"]:
        k = r["key"]
        q = LIVE.get(k)
        hist = LIVE.history.get(k, [])
        bars = [{"high": b.high, "low": b.low} for b in hist[-260:]]
        if q and q.get("high") is not None:
            bars.append({"high": q["high"], "low": q["low"]})
        f = {**m["feat"].get(k, {}), **{x: v for x, v in (LIVE.indicators.get(k) or {}).items()
                                        if v is not None}}
        if not f or not r["close"]:
            continue
        e5 = m["e5map"].get(k)
        sig = A.research_signal(f, e5, bool(e5 and e5["selected"]))
        qq = q or {}
        plan = RJ.stock_plan(r["close"], f, A.levels(bars), {
            "median_turnover": f.get("turnover_20"), "upper_circuit": qq.get("upper_circuit"),
            "lower_circuit": qq.get("lower_circuit"), "day_high": qq.get("high")},
            {"news_24h": f.get("mnews_company_count_24h") or 0, "ret_1d": r.get("day_change")})
        out.append({**plan, "key": k, "symbol": r["symbol"], "sector": r["sector"],
                    "cap_bucket": r.get("cap_bucket"), "signal_score": sig["score"]})
    return out


@app.post("/api/signals/snapshot")
async def signals_snapshot(overwrite: bool = False) -> JSONResponse:
    from app.core.clock import IST, now
    from app.dashboard import signals_log as SL
    day = now().astimezone(IST).date()
    if not await LIVE._trading_day(day):
        return _json({"day": str(day), "skipped": "not a trading day"})
    m = await _view()
    return _json({**SL.write(day, _plans_all(m), overwrite=overwrite),
                  "official_close": LIVE.bhav_day == str(day)})


@app.get("/api/signals")
async def signals(days: int = Query(60, le=400)) -> JSONResponse:
    from sqlalchemy import text

    from app.dashboard import signals_log as SL
    recs = SL.load(days)
    if not recs:
        return _json({"stats": SL.stats([]), "records": []})
    keys = sorted({r["key"] for r in recs})
    first = min(r["day"] for r in recs)
    async with get_sessionmaker()() as s:
        await DD.read_only(s)
        rows = (await s.execute(text("""select instrument_key, market_date, open, high, low,
            close from canon_market_bar where timeframe = '1d' and instrument_key = any(:k)
              and market_date > :d order by instrument_key, market_date"""),
            {"k": keys, "d": _date.fromisoformat(first)})).all()
        await s.rollback()
    bars: dict[str, list[dict[str, Any]]] = {}
    for k, d, o, h, lo, c in rows:
        bars.setdefault(k, []).append({"date": str(d), "open": float(o), "high": float(h),
                                       "low": float(lo), "close": float(c)})
    ev = SL.evaluate(recs, bars)
    return _json({"stats": SL.stats(ev),
                  "records": sorted(ev, key=lambda x: (x["day"], -(x["signal_score"] or 0)),
                                    reverse=True)[:400]})


def _prev_plans() -> dict[str, dict[str, Any]]:
    """The latest forward-record plans before today, by instrument key."""
    from app.core.clock import IST, now
    from app.dashboard import signals_log as SL
    today = str(now().astimezone(IST).date())
    files = sorted(p for p in SL.DIR.glob("*.jsonl") if p.stem < today) if SL.DIR.exists() \
        else []
    if not files:
        return {}
    import json as _j
    return {r["key"]: r for r in (_j.loads(x) for x in files[-1].read_text().splitlines()
                                  if x.strip())}


@app.get("/api/watchlist")
async def watch_get() -> JSONResponse:
    from app.core.clock import IST, now
    from app.dashboard import alerts as AL
    m = await _view()
    by_sym = {r["symbol"]: r for r in m["stocks"]}
    prev = _prev_plans()
    rows = []
    for sym in AL.watchlist():
        r = by_sym.get(sym)
        if r:
            rows.append({**r, "plan": prev.get(r["key"])})
    return _json({"rows": rows, "alerts": AL.history(now().astimezone(IST).date()),
                  "plans_from": next(iter(prev.values()))["day"] if prev else None})


@app.post("/api/watchlist/{symbol}")
async def watch_set(symbol: str, on: bool = True) -> JSONResponse:
    from app.dashboard import alerts as AL
    async with get_sessionmaker()() as s:
        await _key(s, symbol)                          # 404 for an unknown symbol
        await s.rollback()
    return _json({"watchlist": AL.set_watch(symbol, on)})


async def _alert_loop() -> None:
    """In market hours: watchlist prices vs the previous session's plan levels, and
    HIGH-impact news on watched stocks; each event once a day to Telegram."""
    import datetime as _dt

    from sqlalchemy import text

    from app.core.clock import IST, now
    from app.dashboard import alerts as AL
    seen_cycle, news_since = -1, None
    while True:
        await asyncio.sleep(20)
        try:
            t = now().astimezone(IST)
            if not (_dt.time(9, 15) <= t.time() <= _dt.time(15, 35)) or LIVE.cycles == seen_cycle:
                continue
            if not await LIVE._trading_day(t.date()):
                continue
            seen_cycle = LIVE.cycles
            watch = AL.watchlist()
            if not watch:
                continue
            m = await _view()
            by_sym = {r["symbol"]: r for r in m["stocks"]}
            prev = _prev_plans()
            cands = []
            for sym in watch:
                r = by_sym.get(sym)
                q = LIVE.get(r["key"]) if r else None
                if not r or not q:
                    continue
                for ev, txt in AL.events(prev.get(r["key"]), q["ltp"]):
                    cands.append((f"{t.date()}|{sym}|{ev}", f"{sym} {q['ltp']:,.2f}: {txt}"))
            keys = [by_sym[s]["key"] for s in watch if s in by_sym]
            since = news_since or (now() - _dt.timedelta(hours=1))
            news_since = now()
            async with get_sessionmaker()() as s:
                await DD.read_only(s)
                rows = (await s.execute(text("""select i.id, c.trading_symbol, i.title,
                    e.output->>'impact_direction' d from news_ai_enrichment e
                    join news_item i on i.id = e.item_id
                    join news_entity_link l on l.item_id = i.id and l.confidence >= 0.8
                    join canon_instrument c on c.instrument_key = l.instrument_key
                    where e.status = 'OK' and e.output->>'potential_impact' = 'HIGH'
                      and e.knowable_at > :t and l.instrument_key = any(:k)"""),
                    {"t": since, "k": keys})).all()
                await s.rollback()
            for i, sym, title, d in rows:
                cands.append((f"news|{i}", f"{sym} HIGH-impact news ({d or 'direction n/a'}): "
                                           f"{title[:160]}"))
            await asyncio.to_thread(AL.send, NOTIFY, t.date(), AL.due(t.date(), cands))
        except asyncio.CancelledError:
            raise
        except Exception as e:                        # an alert failure never stops the app
            import logging
            logging.getLogger("dashboard.alerts").warning("alerts: %s", e)


def _live_row(m: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    """A market row with the live quote and the live indicators / signal applied."""
    from app.dashboard import analysis as A
    out = LV.overlay(r, LIVE.get(r["key"]))
    ind = LIVE.indicators.get(r["key"])
    if ind and "cap_bucket" in r:
        f = {**m["feat"].get(r["key"], {}), **{k: v for k, v in ind.items() if v is not None}}
        e5 = m["e5map"].get(r["key"])
        sig = A.research_signal(f, e5, bool(e5 and e5["selected"]))
        from app.desk import rules as RJ
        act, guards = RJ.list_action(out.get("close"), f, LIVE.get(r["key"]),
                                     out.get("day_change"))
        out.update(signal=sig["label"], signal_score=sig["score"], trend=sig["trend"],
                   action=act, guards=guards, ret_5d=f.get("ret_5d"),
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
    return _json(await _stock_view(symbol))


async def _stock_view(symbol: str) -> dict[str, Any]:
    """The stock page's data: stored facts, the live quote and indicators, dash-plan-v2."""
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
    _stock_v2(out, q)
    return out


def _stock_v2(out: dict[str, Any], q: dict[str, Any] | None) -> None:
    """dash-plan-v2 on the stock page (user 2026-10-27): returns at the price shown, the
    rule guards (circuit, extension, liquidity, news move, results, data), AI staleness."""
    import datetime as _dt

    from app.core.clock import IST, now
    from app.desk import rules as RJ
    closes = out.pop("_closes", [])
    if closes and out.get("close") and out.get("close_date") and \
            str(out["close_date"]) > str(closes[-1][0]):
        closes = [*closes, (str(out["close_date"]), out["close"])]
    cs = [c for _, c in closes]
    out["returns"] = {n: cs[-1] / cs[-1 - k] - 1 for n, k in (
        ("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252), ("3y", 756))
        if len(cs) > k and cs[-1 - k]}
    out["returns_basis"] = f"from the price shown ({out.get('close_date')})"
    today = now().astimezone(IST)
    news_24h = sum(1 for n in out.get("news") or []
                   if n.get("at") and today - _dt.datetime.fromisoformat(n["at"])
                   <= _dt.timedelta(hours=24))
    results_today = any(r.get("meeting_date") == str(today.date())
                        for r in out.get("results") or [])
    bad = []
    if (out.get("low_confidence_bars") or 0) > 0:
        bad.append(f"{out['low_confidence_bars']} low-confidence daily bars")
    bad += [x for x in out["forensic"]["red_flags"] if "implausible" in x]
    # the averages and RSI from the closes through the price shown, so the plan never mixes
    # today's price with an older snapshot's indicators (e.g. before the live cycle)
    from app.shadow import indicators as IND
    f = dict(out.get("features") or {})
    for n in (20, 50, 200):
        if len(cs) >= n:
            f[f"close_to_sma_{n}"] = cs[-1] / (sum(cs[-n:]) / n) - 1
    if len(cs) > 15:
        f["rsi_14"] = IND.rsi(cs, 14)[-1]
    out["features"] = f
    from app.dashboard import analysis as A
    e5 = out.get("e5_today")
    out["trend"] = A.trend(f)
    out["signal"] = A.research_signal(f, e5, bool(e5 and e5.get("selected")))
    ex = {"median_turnover": f.get("turnover_20"),
          "upper_circuit": (q or {}).get("upper_circuit"),
          "lower_circuit": (q or {}).get("lower_circuit"), "day_high": (q or {}).get("high")}
    out["plan"] = RJ.stock_plan(out.get("close"), f, out.get("levels") or {}, ex,
                                {"news_24h": news_24h, "results_today": results_today,
                                 "bad_data": bad, "ret_1d": out.get("day_change")})
    ai = out.get("ai") or {}
    out["ai_stale"] = bool(ai.get("facts_close_date") and out.get("close_date")
                           and str(ai["facts_close_date"]) != str(out["close_date"]))


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
    st = await _stock_view(symbol)        # the facts as shown: live price, v2 plan
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


# ── Strategy Lab (user 2026-10-27): per-day performance, forensics, regime, brief ────────
# Reads only, except POST /api/lab/switch, which needs the write token (X-Prajna-Token).
def _lab_json(x: Any) -> JSONResponse:
    from fastapi.encoders import jsonable_encoder
    return _json(jsonable_encoder(x))


async def _lab_read(fn, *a):
    async with get_sessionmaker()() as s:
        await DD.read_only(s)
        out = await fn(s, *a)
        await s.rollback()
    return out


def _day(d: str | None) -> _date | None:
    try:
        return _date.fromisoformat(d) if d else None
    except ValueError:
        raise HTTPException(400, f"bad date {d!r} (YYYY-MM-DD)") from None


@app.get("/api/lab/overview")
async def lab_overview() -> JSONResponse:
    from app.dashboard import lab_data as LD
    return _lab_json(await _lab_read(LD.overview))


@app.get("/api/lab/day")
async def lab_day(date: str | None = None) -> JSONResponse:
    from app.dashboard import lab_data as LD
    d = _day(date)
    if d is None:
        ds = await _lab_read(LD.dates)
        if not ds:
            return _lab_json({"available": False, "date": None})
        d = ds[0]
    return _lab_json(await _lab_read(LD.day, d))


@app.get("/api/lab/trade/{trade_id}")
async def lab_trade(trade_id: int) -> JSONResponse:
    from app.dashboard import lab_data as LD
    t = await _lab_read(LD.trade, trade_id)
    if t is None:
        raise HTTPException(404, f"no trade {trade_id}")
    return _lab_json(t)


@app.get("/api/lab/regime")
async def lab_regime(start: str | None = None, end: str | None = None) -> JSONResponse:
    from app.dashboard import lab_data as LD
    return _lab_json(await _lab_read(LD.regime, _day(start), _day(end)))


@app.get("/api/lab/history/{strategy}")
async def lab_history(strategy: str) -> JSONResponse:
    from app.dashboard import lab_data as LD
    return _lab_json(await _lab_read(LD.history, strategy))


@app.get("/api/lab/brief")
async def lab_brief(date: str | None = None) -> JSONResponse:
    from app.core.clock import IST, now
    from app.dashboard import lab_data as LD
    return _lab_json(await _lab_read(LD.brief, _day(date) or now().astimezone(IST).date()))


@app.get("/api/lab/health")
async def lab_health() -> JSONResponse:
    from app.dashboard import lab_data as LD
    return _lab_json(await _lab_read(LD.health))


@app.get("/api/lab/switches")
async def lab_switches() -> JSONResponse:
    from app.lab import switches as SW

    async def _both(s):
        return {"current": await SW.current(s), "history": await SW.history(s, 50)}
    return _lab_json(await _lab_read(_both))


@app.post("/api/lab/switch")
async def lab_switch(body: dict[str, Any], x_prajna_token: str | None = Header(None)
                     ) -> JSONResponse:
    from app.core.errors import AuthorizationError
    from app.lab import switches as SW
    try:
        async with get_sessionmaker()() as s:
            out = await SW.set_switch(s, str(body.get("strategy", "")), bool(body.get("on")),
                                      str(body.get("reason", "")), x_prajna_token)
    except AuthorizationError as e:
        raise HTTPException(403, str(e)) from None
    except SW.SwitchRefused as e:
        raise HTTPException(400, str(e)) from None
    return _lab_json(out)


# ── Research Desk (user 2026-10-27): LLM-led investigation, auto-watchlist, live tracking ─
@app.on_event("startup")
async def _start_desk() -> None:
    if os.environ.get("PRAJNA_DASHBOARD_LIVE", "1") == "1":
        _cache["desk_task"] = (0.0, asyncio.create_task(_desk_loop()))


async def _desk_loop() -> None:
    """In market hours, after every live cycle: the desk watchlist's suggestions against the
    live quote (entry, T1, T2, stop, expiry), written once each, sent to Telegram."""
    import datetime as _dt

    from app.core.clock import IST, now
    from app.dashboard import alerts as AL
    from app.desk import track as TR
    seen = -1
    while True:
        await asyncio.sleep(15)
        try:
            t = now().astimezone(IST)
            if not (_dt.time(9, 15) <= t.time() <= _dt.time(15, 30)) or LIVE.cycles == seen:
                continue
            if not await LIVE._trading_day(t.date()):
                continue
            seen = LIVE.cycles
            async with get_sessionmaker()() as s:
                new = await TR.tick(s, LIVE.get, LIVE.fetched_at or now())
            if new:
                items = [(f"{t.date()}|desk|{e['verdict']['verdict_id']}|{e['kind']}",
                          TR.message(e)) for e in new]
                await asyncio.to_thread(AL.send, NOTIFY, t.date(), AL.due(t.date(), items))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            import logging
            logging.getLogger("dashboard.desk").warning("desk tracker: %s", e)


@app.get("/api/desk/watch")
async def desk_watch() -> JSONResponse:
    from app.dashboard import desk_data as DK
    out = await _lab_read(DK.watch)
    for r in out["watchlist"]:
        q = LIVE.get(r["key"])
        r["live"] = None if not q else {"ltp": q["ltp"], "change": q.get("change"),
                                        "at": q.get("at"), "high": q.get("high"),
                                        "low": q.get("low")}
    out["live_status"] = LIVE.summary()
    return _lab_json(out)


@app.get("/api/desk/verdicts")
async def desk_verdicts(decision: str | None = None) -> JSONResponse:
    from app.dashboard import desk_data as DK
    return _lab_json(await _lab_read(DK.verdicts, decision))


@app.get("/api/desk/stock/{symbol}")
async def desk_stock(symbol: str) -> JSONResponse:
    from app.dashboard import desk_data as DK
    async with get_sessionmaker()() as s:
        key = await _key(s, symbol)
        await s.rollback()
    out = await _lab_read(DK.stock, key)
    if out is None:
        raise HTTPException(404, f"no desk verdict for {symbol} yet")
    q = LIVE.get(key)
    out["live"] = q
    return _lab_json(out)


@app.get("/api/desk/log")
async def desk_log() -> JSONResponse:
    from app.dashboard import desk_data as DK
    return _lab_json(await _lab_read(DK.log))


@app.get("/api/desk/accuracy")
async def desk_accuracy() -> JSONResponse:
    from app.dashboard import desk_data as DK
    return _lab_json(await _lab_read(DK.accuracy))


@app.get("/api/buylist")
async def buylist_view(date: str | None = None) -> JSONResponse:
    """The intraday Buy List with the live quote of each pick (Strategy Lab brief)."""
    from app.dashboard import lab_data as LD
    out = await _lab_read(LD.buylist, _day(date))
    for it in out.get("items") or []:
        q = LIVE.get(it["key"])
        if not q:
            continue
        from app.lab import buylist as BL
        o, hi, lo, ltp = q.get("open"), q.get("high"), q.get("low"), q.get("ltp")
        il = BL.intraday_levels(o, it.get("atr_pct")) if o else {}   # anchored at today's open
        st = "WAITING"
        if lo is not None and il.get("stop") is not None and lo <= il["stop"]:
            st = "STOP_TOUCHED"
        if hi is not None and il.get("t1") is not None and hi >= il["t1"]:
            st = "T1_TOUCHED" if st == "WAITING" else "BOTH_TOUCHED"
        it["live"] = {"ltp": ltp, "open": o, "high": hi, "low": lo, "change": q.get("change"),
                      "from_open": (ltp / o - 1) if ltp and o else None,
                      "open_to_high": (hi / o - 1) if hi and o else None,
                      "at": q.get("at"), "status": st, "levels_today": il,
                      "date": q.get("date")}
    out["live_status"] = LIVE.summary()
    return _lab_json(out)
