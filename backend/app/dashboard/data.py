"""Dashboard data: READ-ONLY queries on the Prajna database (every transaction is set
read only). Point in time where it matters: the market view is the latest Stage 3
PRE_SESSION snapshot (split/bonus-adjusted, knowable values), the charts are
pit.bars_adjusted as known now, news joins its AI enrichment only when that enrichment
exists. No E5 performance before its single look (pre-registration): today's predictions
only."""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST, now
from app.dashboard import analysis as A

FEATS = ("ret_1d", "ret_5d", "ret_20d", "close_to_sma_20", "close_to_sma_50",
         "close_to_sma_200", "rsi_14", "macd_histogram", "volatility_20", "atr_pct_14",
         "dist_high_252", "dist_low_252", "turnover_20", "beta_60", "pe_ttm", "pb_own",
         "mnews_company_sentiment_3d", "mnews_company_count_24h", "liabilities_to_assets",
         "pat_yoy", "pat_yoy_q", "eps_surprise_srw", "results_days_to_next",
         "analyst_upgrades_30d", "analyst_downgrades_30d", "market_regime_trend",
         "india_vix_pctile_252", "breakout_20", "breakdown_20")
INDEX_NAMES = ("Nifty 50", "Nifty Bank", "Nifty Midcap 100", "Nifty Smallcap 100",
               "Nifty IT", "Nifty Next 50", "India VIX")


async def read_only(s: AsyncSession) -> None:
    await s.rollback()
    await s.execute(text("set transaction read only"))


def _num(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


async def latest_session(s: AsyncSession) -> _dt.date | None:
    return (await s.execute(text("""select max(session_date) from feature_value
        where snapshot = 'PRE_SESSION'"""))).scalar()


async def features(s: AsyncSession, day: _dt.date, keys: list[str] | None = None
                   ) -> dict[str, dict[str, float | None]]:
    rows = (await s.execute(text("""select instrument_key, feature_id, value from feature_value
        where session_date = :d and snapshot = 'PRE_SESSION' and feature_id = any(:f)
          and (cast(:k as text[]) is null or instrument_key = any(cast(:k as text[])))"""),
        {"d": day, "f": list(FEATS), "k": keys})).all()
    out: dict[str, dict[str, float | None]] = {}
    for k, f, v in rows:
        out.setdefault(k, {})[f] = _num(v)
    return out


async def instruments(s: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = (await s.execute(text("""select instrument_key, trading_symbol, name, segment,
        sector from canon_instrument where included and lifecycle_status = 'ACTIVE'
          and segment in ('NSE_EQ', 'NSE_INDEX')"""))).mappings().all()
    return {r["instrument_key"]: dict(r) for r in rows}


async def last_closes(s: AsyncSession) -> dict[str, dict[str, Any]]:
    """The two latest daily bars of every NSE instrument (close, previous close)."""
    rows = (await s.execute(text("""
        select instrument_key, market_date, close, rn from (
          select instrument_key, market_date, close,
                 row_number() over (partition by instrument_key order by market_date desc) rn
          from canon_market_bar where timeframe = '1d' and segment in ('NSE_EQ', 'NSE_INDEX')
            and market_date > current_date - 20) x where rn <= 2"""))).all()
    out: dict[str, dict[str, Any]] = {}
    for k, d, c, rn in rows:
        e = out.setdefault(k, {})
        if rn == 1:
            e.update(date=d, close=_num(c))
        else:
            e["prev_close"] = _num(c)
    return out


async def intraday_last(s: AsyncSession, day: _dt.date) -> dict[str, dict[str, Any]]:
    """The latest stored 1m bar of `day` per instrument (stored after each session)."""
    rows = (await s.execute(text("""select distinct on (instrument_key) instrument_key,
        bar_start_utc, close from canon_market_bar where timeframe = '1m' and market_date = :d
        order by instrument_key, bar_start_utc desc"""), {"d": day})).all()
    return {k: {"at": t, "close": _num(c)} for k, t, c in rows}


async def market_caps(s: AsyncSession, closes: dict[str, dict[str, Any]]) -> dict[str, float]:
    """close x shares (FY profit after tax / FY basic EPS, app.fundamentals.ratios), crore."""
    from app.fundamentals import ratios as RT
    types = ["income:standalone:yearly", "income:consolidated:yearly",
             "income:standalone:quarterly", "income:consolidated:quarterly"]
    rows = (await s.execute(text("""select instrument_key, statement_type, knowable_at, payload
        from canon_fundamental where statement_type = any(:t) and instrument_key like 'NSE_EQ|%%'
        order by instrument_key, knowable_at"""), {"t": types})).all()
    snaps: dict[str, dict[str, list]] = {}
    for k, st, kn, p in rows:
        snaps.setdefault(k, {}).setdefault(st, []).append((kn, p))
    caps = {}
    for k, sn in snaps.items():
        c = (closes.get(k) or {}).get("close")
        try:
            f = RT.build(sn)
        except (KeyError, TypeError, ValueError, AttributeError):
            f = None                           # one malformed vendor payload: no cap
        n = RT.shares(f)[0] if f else None
        if c and n and n > 0:
            caps[k] = c * n / 1e7
    return caps


async def e5_today(s: AsyncSession, day: _dt.date) -> dict[str, dict[str, Any]]:
    """Today's E5 outputs only - never a past session's (no look before session 40)."""
    rows = (await s.execute(text("""select instrument_key, prob_up, exp_return, range_lo,
        range_hi, volatility, confidence, score, rank, selected, predicted_at, model_sha256
        from model_prediction where session_date = :d"""), {"d": day})).mappings().all()
    return {r["instrument_key"]: dict(r) for r in rows}


async def market(s: AsyncSession, caps: dict[str, float] | None = None) -> dict[str, Any]:
    """The whole market view, one pass (the server caches it)."""
    await read_only(s)
    day = await latest_session(s)
    ins = await instruments(s)
    feat = await features(s, day) if day else {}
    closes = await last_closes(s)
    today = now().astimezone(IST).date()
    intra = await intraday_last(s, today)
    if caps is None:
        caps = await market_caps(s, closes)
    bucket = A.cap_buckets(caps)
    e5 = await e5_today(s, today)
    stocks, indices = [], []
    for k, i in ins.items():
        c = closes.get(k, {})
        f = feat.get(k, {})
        last = c.get("close")
        live = intra.get(k)
        newer = bool(live and live["close"] and last and c.get("date") and c["date"] < today)
        prev = last if newer else c.get("prev_close")
        price = live["close"] if newer else last
        rec = {"key": k, "symbol": i["trading_symbol"], "name": i["name"], "sector": i["sector"],
               "close": price,
               "close_date": str(today) if newer else (str(c["date"]) if c.get("date") else None),
               "price_basis": "intraday (latest stored 1m bar)" if newer else "daily close",
               "price_at": live["at"].isoformat() if newer else None,
               "day_change": (price / prev - 1) if price and prev else None,
               "ret_5d": f.get("ret_5d"), "ret_20d": f.get("ret_20d"),
               "volatility_20": f.get("volatility_20"), "rsi_14": f.get("rsi_14"),
               "dist_high_252": f.get("dist_high_252"),
               "news_24h": f.get("mnews_company_count_24h"),
               "sentiment_3d": f.get("mnews_company_sentiment_3d")}
        if i["segment"] == "NSE_INDEX":
            indices.append(rec)
            continue
        rec["cap_cr"] = caps.get(k)
        rec["cap_bucket"] = bucket.get(k, "UNCLASSIFIED")
        ek = e5.get(k)
        sig = A.research_signal(f, ek, bool(ek and ek["selected"])) if f else None
        rec["signal"] = sig["label"] if sig else None
        rec["action"] = A.ACTIONS.get(sig["label"]) if sig else None
        rec["signal_score"] = sig["score"] if sig else None
        rec["trend"] = sig["trend"] if sig else None
        rec["e5_pick"] = bool(ek and ek["selected"])
        stocks.append(rec)
    ups = sum(1 for r in stocks if (r["day_change"] or 0) > 0)
    downs = sum(1 for r in stocks if (r["day_change"] or 0) < 0)
    nifty = next((x for x in indices if x["name"] and x["name"].lower() == "nifty 50"), None)
    regime = feat.get(nifty["key"], {}).get("market_regime_trend") if nifty else None
    vix = next((x for x in indices if x["name"] and "vix" in x["name"].lower()), None)
    return {"as_of": now().isoformat(), "features_session": str(day) if day else None,
            "breadth": {"advances": ups, "declines": downs,
                        "unchanged": len(stocks) - ups - downs},
            "regime": {"nifty_trend": regime,
                       "label": {1.0: "UPTREND", -1.0: "DOWNTREND", 0.0: "MIXED"}.get(regime),
                       "vix": vix},
            "indices": sorted(indices, key=lambda r: (r["name"] or "") not in INDEX_NAMES),
            "stocks": stocks, "e5_session": str(today) if e5 else None,
            "feat": feat, "e5map": e5,                      # internal (never returned)
            "disclaimer": A.DISCLAIMER}


def sectors(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in stocks:
        if r["sector"]:
            by.setdefault(r["sector"], []).append(r)

    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        return xs[len(xs) // 2] if xs else None
    out = []
    for sec, rs in by.items():
        out.append({"sector": sec, "stocks": len(rs),
                    "day": med([r["day_change"] for r in rs]),
                    "ret_5d": med([r["ret_5d"] for r in rs]),
                    "ret_20d": med([r["ret_20d"] for r in rs]),
                    "bullish": sum(r["signal"] == "BULLISH" for r in rs),
                    "bearish": sum(r["signal"] == "BEARISH" for r in rs),
                    "news_24h": sum(int(r["news_24h"] or 0) for r in rs),
                    "leaders": [r["symbol"] for r in sorted(
                        (r for r in rs if r["day_change"] is not None),
                        key=lambda r: -r["day_change"])[:3]]})
    return sorted(out, key=lambda r: -(r["day"] or -9))


MEDIA_EXCLUDE = ("NSE_ANNOUNCEMENTS", "SEBI_RSS")       # filings / regulator, not media


async def hot_news(s: AsyncSession, hours: int = 24, limit: int = 150,
                   source: str | None = None) -> dict[str, Any]:
    """Every item first seen in the window (all sources) for the topic / stock / source
    counts, with its AI enrichment when it exists; the list is filtered by `source`
    (a source key, MEDIA = every source except exchange filings and the regulator, or
    None = all) and capped at `limit`. Each item carries its delay: published -> seen."""
    await read_only(s)
    since = now() - _dt.timedelta(hours=hours)
    items = (await s.execute(text("""
        select i.id, i.title, i.summary, i.publisher, i.url, i.knowable_at, i.published_at,
               i.discovered_at, i.source, i.backlog, e.output as ai
        from news_item i
        left join lateral (select output from news_ai_enrichment x
                           where x.item_id = i.id and x.status = 'OK'
                           order by x.id desc limit 1) e on true
        where i.knowable_at > :t order by i.knowable_at desc"""),
        {"t": since})).mappings().all()
    ids = [r["id"] for r in items]
    links = (await s.execute(text("""select l.item_id, c.trading_symbol
        from news_entity_link l join canon_instrument c using (instrument_key)
        where l.item_id = any(:i) and l.confidence >= 0.8"""), {"i": ids})).all()
    by: dict[int, list[str]] = {}
    for i, sym in links:
        by.setdefault(i, []).append(sym)
    topics: dict[str, int] = {}
    stocks: dict[str, dict[str, int]] = {}
    sources: dict[str, dict[str, Any]] = {}
    out = []
    for r in items:
        ai = r["ai"] or {}
        src = sources.setdefault(r["source"], {"items": 0, "ai": 0, "linked": 0, "delays": []})
        src["items"] += 1
        src["ai"] += bool(ai)
        src["linked"] += bool(by.get(r["id"]))
        delay = None
        if r["published_at"] and not r["backlog"]:
            delay = (r["discovered_at"] - r["published_at"]).total_seconds() / 60
            if delay >= 0:
                src["delays"].append(delay)
        et = (ai.get("event_type") or "").strip().lower().replace(" ", "_").replace("-", "_") \
            or None
        if et:
            topics[et] = topics.get(et, 0) + 1
        for sym in by.get(r["id"], []):
            d = stocks.setdefault(sym, {"items": 0, "positive": 0, "negative": 0})
            d["items"] += 1
            if ai.get("impact_direction") == "POSITIVE":
                d["positive"] += 1
            elif ai.get("impact_direction") == "NEGATIVE":
                d["negative"] += 1
        if source == "MEDIA" and r["source"] in MEDIA_EXCLUDE:
            continue
        if source and source != "MEDIA" and r["source"] != source:
            continue
        if len(out) < limit:
            out.append({"title": r["title"], "summary": (r["summary"] or "")[:300],
                        "publisher": r["publisher"], "url": r["url"],
                        "at": r["knowable_at"].isoformat(), "source": r["source"],
                        "published_at": r["published_at"].isoformat() if r["published_at"]
                        else None,
                        "delay_min": None if delay is None or delay < 0 else round(delay, 1),
                        "stocks": by.get(r["id"], []),
                        "ai": None if not ai else {k: ai.get(k) for k in (
                            "summary", "event_type", "market_scope", "potential_impact",
                            "impact_direction", "confidence", "entities")}})

    def med(xs):
        xs = sorted(xs)
        return round(xs[len(xs) // 2], 1) if xs else None
    src_out = sorted(({"source": k, "items": v["items"], "ai": v["ai"], "linked": v["linked"],
                       "median_delay_min": med(v["delays"])} for k, v in sources.items()),
                     key=lambda x: -x["items"])
    last_poll = (await s.execute(text("""select max(finished_at) from news_poll
        where mode = 'PRODUCTION'"""))).scalar()
    return {"hours": hours, "source": source, "items": out, "total": len(items),
            "sources": src_out, "last_poll": last_poll.isoformat() if last_poll else None,
            "topics": sorted(topics.items(), key=lambda x: -x[1])[:25],
            "stocks": sorted(stocks.items(), key=lambda x: -x[1]["items"])[:30],
            "ai_note": "AI enrichment (Bedrock Nova Pro): a description of the text, never "
                       "a fact or a price prediction"}


async def resolve(s: AsyncSession, q: str) -> str | None:
    q = q.strip().upper()
    return (await s.execute(text("""select instrument_key from canon_instrument
        where included and segment in ('NSE_EQ', 'NSE_INDEX')
          and (upper(trading_symbol) = :q or instrument_key = :raw)
        order by segment limit 1"""), {"q": q, "raw": q})).scalar()


async def search(s: AsyncSession, q: str, limit: int = 15) -> list[dict[str, Any]]:
    await read_only(s)
    return [dict(r) for r in (await s.execute(text("""select trading_symbol as symbol, name,
        segment, sector from canon_instrument where included and lifecycle_status = 'ACTIVE'
          and segment in ('NSE_EQ', 'NSE_INDEX')
          and (trading_symbol ilike :p or name ilike :p2)
        order by (trading_symbol ilike :p) desc, length(trading_symbol) limit :n"""),
        {"p": q.strip() + "%", "p2": "%" + q.strip() + "%", "n": limit})).mappings().all()]


async def candles_for(s: AsyncSession, key: str, tf: str) -> dict[str, Any]:
    from app.canon import pit
    if tf == "1d":
        r = await pit.bars_adjusted(s, key, "1d", now(), allow_low_confidence=True)
        rows = r["rows"]
        low = sum(1 for x in rows if x.get("basis_confidence") == "LOW")
    else:
        start = now().astimezone(IST).date() - _dt.timedelta(days={"1h": 120, "15m": 30,
                                                                     "5m": 10, "1m": 3}[tf])
        rows = (await s.execute(text("""select bar_start_utc, market_date, open, high, low,
            close, volume from canon_market_bar where instrument_key = :k and timeframe = :tf
              and market_date >= :a order by bar_start_utc"""),
            {"k": key, "tf": tf, "a": start})).mappings().all()
        low = 0
    bars = [{"time": int(x["bar_start_utc"].timestamp()) if tf != "1d" else
             str(x["market_date"]), "date": str(x["market_date"]),
             "open": _num(x["open"]), "high": _num(x["high"]), "low": _num(x["low"]),
             "close": _num(x["close"]), "volume": _num(x["volume"])} for x in rows]
    return {"timeframe": tf, "bars": bars, "low_confidence_bars": low}


async def provisional_daily(s: AsyncSession, key: str, last_daily: str | None
                            ) -> dict[str, Any] | None:
    """Today's candle from today's stored 1m bars, when the daily bar is not stored yet
    (it arrives with the next morning's job). Marked provisional."""
    today = now().astimezone(IST).date()
    if last_daily and last_daily >= str(today):
        return None
    r = (await s.execute(text("""select (array_agg(open order by bar_start_utc))[1] o,
        max(high) h, min(low) l, (array_agg(close order by bar_start_utc desc))[1] c,
        sum(volume) v, max(bar_start_utc) at, count(*) n from canon_market_bar
        where instrument_key = :k and timeframe = '1m' and market_date = :d"""),
        {"k": key, "d": today})).one()
    if not r.n:
        return None
    return {"time": str(today), "date": str(today), "open": _num(r.o), "high": _num(r.h),
            "low": _num(r.l), "close": _num(r.c), "volume": _num(r.v), "provisional": True,
            "last_at": r.at.isoformat(), "minutes": r.n}


async def stock(s: AsyncSession, key: str) -> dict[str, Any]:
    await read_only(s)
    info = (await s.execute(text("""select instrument_key, trading_symbol, name, segment, sector,
        isin from canon_instrument where instrument_key = :k"""), {"k": key})).mappings().one()
    day = await latest_session(s)
    f = (await features(s, day, [key])).get(key, {}) if day else {}
    daily = await candles_for(s, key, "1d")
    bars = daily["bars"]
    today_bar = await provisional_daily(s, key, bars[-1]["date"] if bars else None)
    prev_close = bars[-1]["close"] if bars else None
    if today_bar:
        bars = [*bars, today_bar]
    an = A.candles(bars[-120:])
    close = bars[-1]["close"] if bars else None
    today = now().astimezone(IST).date()
    e5 = (await e5_today(s, today)).get(key)
    sig = A.research_signal(f, e5, bool(e5 and e5["selected"]))
    kr = (await s.execute(text("""select payload from canon_fundamental where instrument_key = :k
        and statement_type = 'key_ratios' order by knowable_at desc limit 1"""),
        {"k": key})).scalar() or []
    ratios = {}
    for x in kr if isinstance(kr, list) else []:
        n = (x.get("name") or "").upper()
        cv = _num(str(x.get("company_value", "")).rstrip("%").replace(",", ""))
        sv = _num(str(x.get("sector_value", "")).rstrip("%").replace(",", ""))
        if n == "P/E":
            ratios.update(pe_company=cv, pe_sector=sv)
        elif n == "P/B":
            ratios.update(pb_company=cv, pb_sector=sv)
        elif n in ("ROE", "ROCE", "ROA"):
            ratios[n.lower()] = cv
            ratios[n.lower() + "_sector"] = sv
        elif n == "EV/EBITDA":
            ratios["ev_ebitda"] = cv
    holdings = (await s.execute(text("""select payload from canon_fundamental
        where instrument_key = :k and statement_type = 'share_holdings'
        order by knowable_at desc limit 1"""), {"k": key})).scalar() or []
    profile = (await s.execute(text("""select payload from canon_fundamental
        where instrument_key = :k and statement_type = 'profile'
        order by knowable_at desc limit 1"""), {"k": key})).scalar() or {}
    results = [dict(r) for r in (await s.execute(text("""select kind, meeting_date, period_end,
        verdict, event_at from results_event where instrument_key = :k
        order by coalesce(meeting_date, event_at::date) desc limit 8"""),
        {"k": key})).mappings().all()]
    actions = [dict(r) for r in (await s.execute(text("""select action_type, ex_date, details
        from canon_corporate_action where instrument_key = :k order by ex_date desc nulls last
        limit 10"""), {"k": key})).mappings().all()] if await _has_col(
        s, "canon_corporate_action", "details") else [dict(r) for r in (await s.execute(text(
            """select action_type, ex_date from canon_corporate_action where instrument_key = :k
            order by ex_date desc nulls last limit 10"""), {"k": key})).mappings().all()]
    news = (await s.execute(text("""
        select i.title, i.summary, i.publisher, i.url, i.knowable_at, e.output as ai
        from news_entity_link l join news_item i on i.id = l.item_id
        left join lateral (select output from news_ai_enrichment x where x.item_id = i.id
                           and x.status = 'OK' order by x.id desc limit 1) e on true
        where l.instrument_key = :k and l.confidence >= 0.8
          and i.knowable_at > now() - interval '30 days'
        order by i.knowable_at desc limit 40"""), {"k": key})).mappings().all()
    ret = {}
    closes = [b["close"] for b in bars if b["close"]]
    for name, n in (("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252), ("3y", 756)):
        if len(closes) > n:
            ret[name] = closes[-1] / closes[-1 - n] - 1
    return {"key": key, "symbol": info["trading_symbol"], "name": info["name"],
            "segment": info["segment"], "sector": info["sector"], "isin": info["isin"],
            "profile": (profile or {}).get("company_profile"),
            "close": close, "close_date": bars[-1]["date"] if bars else None,
            "price_basis": ("intraday: today's 1m bars so far (the official daily bar arrives "
                            "with the next morning's job)") if today_bar else "daily close",
            "price_at": today_bar["last_at"] if today_bar else None,
            "day_change": (close / (prev_close if today_bar else (bars[-2]["close"]
                           if len(bars) > 1 else None)) - 1)
            if close and (prev_close if today_bar else len(bars) > 1) else None,
            "returns": ret, "features_session": str(day) if day else None, "features": f,
            "trend": A.trend(f), "signal": sig,
            "levels": A.levels(bars),
            "plan": A.trade_plan(close, f, A.levels(bars), sig),
            "candle_read": A.candle_read(an, A.trend(f)["trend"]),
            "ranges": A.ranges(close, f.get("atr_pct_14"), e5),
            "candles": an[-60:], "low_confidence_bars": daily["low_confidence_bars"],
            "e5_today": None if not e5 else {k: (v.isoformat() if hasattr(v, "isoformat")
                                                 else v) for k, v in e5.items()},
            "ratios": ratios,
            "holdings": holdings if isinstance(holdings, list) else [],
            "forensic": A.forensic(ratios, holdings if isinstance(holdings, list) else [], f),
            "results": [{k: str(v) if v is not None else None for k, v in r.items()}
                        for r in results],
            "actions": [{k: str(v) if v is not None else None for k, v in r.items()}
                        for r in actions],
            "news": [{"title": n["title"], "summary": (n["summary"] or "")[:300],
                      "publisher": n["publisher"], "url": n["url"],
                      "at": n["knowable_at"].isoformat(),
                      "ai": None if not n["ai"] else {k: n["ai"].get(k) for k in (
                          "summary", "event_type", "potential_impact", "impact_direction")}}
                     for n in news],
            "disclaimer": A.DISCLAIMER}


async def _has_col(s: AsyncSession, table: str, col: str) -> bool:
    return bool((await s.execute(text("""select 1 from information_schema.columns
        where table_name = :t and column_name = :c"""), {"t": table, "c": col})).first())


async def e5_board(s: AsyncSession) -> dict[str, Any]:
    """Today's predictions of the forward-test model. No past session, no outcome."""
    await read_only(s)
    today = now().astimezone(IST).date()
    rows = (await s.execute(text("""select p.instrument_key, c.trading_symbol, c.sector,
        p.prob_up, p.exp_return, p.range_lo, p.range_hi, p.volatility, p.confidence, p.score,
        p.rank, p.selected, p.predicted_at, p.model_sha256 from model_prediction p
        join canon_instrument c using (instrument_key) where p.session_date = :d
        order by p.rank limit 100"""), {"d": today})).mappings().all()
    days = (await s.execute(text("select count(distinct session_date) from model_prediction"))
            ).scalar()
    return {"session": str(today), "rows": [{k: (v.isoformat() if hasattr(v, "isoformat")
                                                 else v) for k, v in r.items()} for r in rows],
            "forward_day": days, "forward_needed": 40,
            "note": "E5 forward test: today's outputs only. Past picks and their returns stay "
                    "hidden until the single look after 40 sessions (pre-registration)."}


async def fii_dii(s: AsyncSession, days: int = 5) -> list[dict[str, Any]]:
    """Cash-market net flows (buy - sell, vendor crore) for the latest sessions."""
    await read_only(s)
    rows = (await s.execute(text("""select observation_date, series_code, value
        from canon_macro_observation where series_code like any (array[
          'FII|NSE_EQ|CASH|1D|%', 'DII|NSE_EQ|CASH|1D|%'])
          and observation_date >= current_date - 20 order by observation_date desc"""))).all()
    by: dict[Any, dict[str, float]] = {}
    for d, code, v in rows:
        who, side = code.split("|")[0], code.rsplit("|", 1)[1]
        by.setdefault(d, {})[f"{who}_{side}"] = _num(v)
    out = []
    for d in sorted(by, reverse=True)[:days]:
        x = by[d]
        out.append({"date": str(d),
                    "fii_net": (x.get("FII_buy_amt") or 0) - (x.get("FII_sell_amt") or 0)
                    if "FII_buy_amt" in x else None,
                    "dii_net": (x.get("DII_buy_amt") or 0) - (x.get("DII_sell_amt") or 0)
                    if "DII_buy_amt" in x else None})
    return out


async def results_today(s: AsyncSession, day: _dt.date) -> list[dict[str, Any]]:
    """Results outcomes announced today, with the parsed street verdict when known."""
    await read_only(s)
    rows = (await s.execute(text("""select c.trading_symbol, r.kind, r.verdict, r.period_end
        from results_event r join canon_instrument c using (instrument_key)
        where (r.event_at at time zone 'Asia/Kolkata')::date = :d and r.kind = 'OUTCOME'
        order by c.trading_symbol"""), {"d": day})).mappings().all()
    return [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in rows]
