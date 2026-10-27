"""The dossier agent: for every stock, the evidence a detective would want, each item with an
id the LLM must cite. Deterministic; reads stored Upstox bars, the news Prajna collects, the
results/corporate-action/fundamental records, the P1 regime engine and (for circuit limits
and intraday prices) an Upstox market quote.

Evidence ids: px (price facts), lvl (levels), attr (move attribution), rule (dash-plan-v2),
exec (liquidity, circuits, costs), ctx (market context), fund (fundamentals), news:<id>,
res:<id>, ca:<n>.

Modes (the last completed bar):
  EVENING   day T, T's candle from the stored 1m bars when its daily bar is not stored yet
  MORNING   day T before the open: the bars through T-1 (overnight news and events added)
  INTRADAY  day T in session: T-1's bars plus T's quote so far as the provisional bar
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.desk import config as K
from app.desk import rules as RJ
from app.lab import compute as LC
from app.shadow import indicators as I
from app.shadow import patterns as PT


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


LEVEL_KEYS = ("support_20", "resistance_20", "swing_low_60", "swing_high_60", "high_252",
              "low_252", "zone_below", "zone_above")


# ── pure: facts from a daily series ─────────────────────────────────────────────────
def price_facts(sr: dict[str, list], last: int) -> dict[str, Any] | None:
    """Price, momentum, volatility and levels from the daily series through index `last`."""
    rows = [(sr["open"][i], sr["high"][i], sr["low"][i], sr["close"][i], sr["volume"][i])
            for i in range(0, last + 1)]
    rows = [r for r in rows if None not in r[:4] and r[3] > 0]
    if len(rows) < 30:
        return None
    o, h, lo, c, v = (list(x) for x in zip(*rows, strict=True))
    v = [x or 0.0 for x in v]
    close = c[-1]

    def ret(n: int) -> float | None:
        return c[-1] / c[-1 - n] - 1 if len(c) > n and c[-1 - n] else None

    def dist(n: int) -> float | None:
        s = I.sma(c, n)[-1] if len(c) >= n else None
        return close / s - 1 if s else None

    atr = I.atr(h, lo, c, 14)[-1] if len(c) > 15 else None
    e12, e26 = I.ema(c, 12), I.ema(c, 26)
    macd = [a - b if a is not None and b is not None else None
            for a, b in zip(e12, e26, strict=True)]
    mv = [x for x in macd if x is not None]
    sig = I.ema(mv, 9)[-1] if len(mv) >= 9 else None
    vol20 = statistics.mean(v[-21:-1]) if len(v) > 21 else None
    zs = PT.zones(h, lo)
    return {
        "close": close, "open": o[-1], "high": h[-1], "low": lo[-1], "prev_close": c[-2],
        "ret_1d": ret(1), "ret_5d": ret(5), "ret_20d": ret(20), "ret_60d": ret(60),
        "gap": o[-1] / c[-2] - 1 if c[-2] else None,
        "intraday": close / o[-1] - 1 if o[-1] else None,
        "volume": v[-1], "volume_x20": v[-1] / vol20 if vol20 else None,
        "atr_pct": atr / close if atr else None, "rsi_14": I.rsi(c, 14)[-1],
        "close_to_sma_20": dist(20), "close_to_sma_50": dist(50), "close_to_sma_200": dist(200),
        "macd_histogram": mv[-1] - sig if mv and sig is not None else None,
        "support_20": min(lo[-20:]), "resistance_20": max(h[-20:]),
        "swing_low_60": min(lo[-60:]), "swing_high_60": max(h[-60:]),
        "high_252": max(h[-252:]), "low_252": min(lo[-252:]),
        "from_high_252": close / max(h[-252:]) - 1, "sessions": len(c),
        "zone_below": max((z for z in zs if z < close), default=None),
        "zone_above": min((z for z in zs if z > close), default=None),
    }


def beta(sr: list, ix: list, last: int, n: int = 60) -> float | None:
    a, b = [], []
    for i in range(max(1, last - n + 1), last + 1):
        if None in (sr[i], sr[i - 1], ix[i], ix[i - 1]) or not sr[i - 1] or not ix[i - 1]:
            continue
        a.append(sr[i] / sr[i - 1] - 1)
        b.append(ix[i] / ix[i - 1] - 1)
    if len(a) < n // 2:
        return None
    mb = sum(b) / len(b)
    var = sum((y - mb) ** 2 for y in b)
    if not var:
        return None
    ma = sum(a) / len(a)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / var


def attribution(ret: float | None, b: float | None, nifty_ret: float | None,
                sector_ret: float | None) -> dict[str, Any]:
    """The day's move split: market (beta x Nifty), sector excess and stock-specific."""
    if ret is None:
        return {}
    mkt = (b if b is not None else 1.0) * (nifty_ret or 0.0)
    sec = (sector_ret - mkt) if sector_ret is not None else 0.0
    own = ret - mkt - sec
    parts = {"market": mkt, "sector": sec, "stock_specific": own}
    main = max(parts, key=lambda k: abs(parts[k]))
    return {"ret": _r(ret), "beta_60": _r(b, 2), "nifty_ret": _r(nifty_ret),
            "sector_ret": _r(sector_ret), "market_part": _r(mkt), "sector_part": _r(sec),
            "stock_part": _r(own), "main_driver": main}


def rank_universe(series: dict[str, dict], last: int, stocks: set[str],
                  top: int = K.UNIVERSE_TOP) -> list[str]:
    from app.training import e3 as E3
    rows = []
    for k, sr in series.items():
        if k not in stocks:
            continue
        c = sr["close"][last]
        if not c or c < K.MIN_PRICE:
            continue
        if sum(1 for x in sr["close"][:last + 1] if x) < 60:
            continue
        t = E3.median_turnover(sr, last)
        if t:
            rows.append((k, t))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return [k for k, _ in rows[:top]]


# ── loaders ───────────────────────────────────────────────────────────────────────
async def one_minute_day(s: AsyncSession, keys: list[str], day: _dt.date
                         ) -> dict[str, dict[str, float]]:
    """Day T's candle from its stored 1m bars (before the daily bar arrives)."""
    rows = (await s.execute(text("""select instrument_key,
            (array_agg(open order by bar_start_utc))[1] o, max(high) h, min(low) l,
            (array_agg(close order by bar_start_utc desc))[1] c, sum(volume) v, count(*) n
        from canon_market_bar where timeframe = '1m' and market_date = :d
          and instrument_key = any(:k) group by 1"""), {"d": day, "k": keys})).all()
    return {r.instrument_key: {"open": _f(r.o), "high": _f(r.h), "low": _f(r.l),
                               "close": _f(r.c), "volume": _f(r.v), "minutes": r.n}
            for r in rows if r.c is not None}


async def quotes(keys: list[str]) -> dict[str, dict[str, Any]]:
    """Upstox market quotes (circuit limits, today's price so far). {} if unavailable."""
    import json as _json

    from app.dashboard import live as LV
    from app.vendor.upstox.auth import load_cached
    from app.vendor.upstox.rest import QUOTE_MAX_KEYS, RateLimiter, UpstoxRestClient, quotes_path
    rec = load_cached()
    if rec is None:
        return {}
    c = UpstoxRestClient(rec.access_token, limiter=LV._limiter(RateLimiter))
    out: dict[str, dict[str, Any]] = {}
    try:
        for i in range(0, len(keys), QUOTE_MAX_KEYS):
            r = await c.get(quotes_path(keys[i:i + QUOTE_MAX_KEYS]))
            d = _json.loads(r.data)
            if r.status != 200 or d.get("status") != "success":
                return out
            for v in (d.get("data") or {}).values():
                q = LV.parse(v)
                if q:
                    out[q["key"]] = q
    finally:
        await c.aclose()
    return out


async def fii_dii(s: AsyncSession, days: int = 3) -> list[dict[str, Any]]:
    """Cash-market net flows (Rs crore) of the latest sessions (as app/dashboard/data.fii_dii,
    without its read-only transaction)."""
    rows = (await s.execute(text("""select observation_date, series_code, value
        from canon_macro_observation where series_code like any (array[
          'FII|NSE_EQ|CASH|1D|%', 'DII|NSE_EQ|CASH|1D|%'])
          and observation_date >= current_date - 20 order by observation_date desc"""))).all()
    by: dict[Any, dict[str, float]] = {}
    for d, code, v in rows:
        by.setdefault(d, {})[f"{code.split('|')[0]}_{code.rsplit('|', 1)[1]}"] = _f(v) or 0.0
    return [{"date": str(d),
             "fii_net": _r(x.get("FII_buy_amt", 0) - x.get("FII_sell_amt", 0), 0),
             "dii_net": _r(x.get("DII_buy_amt", 0) - x.get("DII_sell_amt", 0), 0)}
            for d, x in sorted(by.items(), reverse=True)[:days]]


async def _events(s: AsyncSession, keys: list[str], day: _dt.date) -> tuple[dict, dict]:
    a, b = day - _dt.timedelta(days=K.EVENT_WINDOW_D), day + _dt.timedelta(days=K.EVENT_WINDOW_D)
    res: dict[str, list] = defaultdict(list)
    for r in (await s.execute(text("""select id, instrument_key, kind, meeting_date,
            period_end, verdict, event_at, knowable_at, source from results_event
        where instrument_key = any(:k) and kind <> 'HISTORICAL_FILING'
          and coalesce(meeting_date, event_at::date) between :a and :b
          and knowable_at <= now() order by coalesce(meeting_date, event_at::date) desc"""),
            {"k": keys, "a": a, "b": b})).mappings().all():
        res[r["instrument_key"]].append(dict(r))
    ca: dict[str, list] = defaultdict(list)
    for r in (await s.execute(text("""select instrument_key, action_type, ex_date
        from canon_corporate_action where instrument_key = any(:k)
          and ex_date between :a and :b order by ex_date"""),
            {"k": keys, "a": a, "b": b})).mappings().all():
        ca[r["instrument_key"]].append(dict(r))
    return res, ca


async def _fundamentals(s: AsyncSession, keys: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in (await s.execute(text("""select distinct on (instrument_key) instrument_key,
            payload from canon_fundamental where instrument_key = any(:k)
              and statement_type = 'key_ratios' order by instrument_key, knowable_at desc"""),
            {"k": keys})).all():
        for x in r.payload if isinstance(r.payload, list) else []:
            n = (x.get("name") or "").upper().replace(" ", "")
            cv = _f(str(x.get("company_value", "")).rstrip("%").replace(",", ""))
            sv = _f(str(x.get("sector_value", "")).rstrip("%").replace(",", ""))
            if n in ("P/E", "P/B", "ROE", "ROCE", "EV/EBITDA", "DIVIDENDYIELD"):
                out[r.instrument_key][n.lower()] = cv
                out[r.instrument_key][n.lower() + "_sector"] = sv
    for r in (await s.execute(text("""select distinct on (instrument_key, feature_id)
            instrument_key, feature_id, value from feature_value
        where instrument_key = any(:k) and snapshot = 'PRE_SESSION'
          and feature_id in ('pat_yoy', 'pat_yoy_q', 'eps_surprise_srw', 'pe_ttm', 'pb_own',
                             'liabilities_to_assets', 'results_days_to_next')
        order by instrument_key, feature_id, session_date desc"""), {"k": keys})).all():
        out[r.instrument_key][r.feature_id] = _f(r.value)
    for f in out.values():
        flags = []
        pe, pes = f.get("p/e"), f.get("p/e_sector")
        if pes is not None and (pes > 150 or pes <= 0):
            flags.append(f"sector P/E {pes} looks implausible (vendor value)")
        if pe is not None and f.get("pe_ttm") is not None and pe > 0 and \
                abs(pe / f["pe_ttm"] - 1) > 0.25:
            flags.append(f"vendor P/E {pe} and Prajna's TTM P/E {f['pe_ttm']:.1f} disagree")
        f["sanity_flags"] = flags
    return out


async def build(s: AsyncSession, session: _dt.date, mode: str, *,
                keys: list[str] | None = None, live: dict[str, dict] | None = None,
                fetch_quotes: bool = True, extra: list[str] | tuple = (),
                regime_override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dossiers for `keys` (default: the top-500 universe plus the watchlist)."""
    from app.paper import strategies as PS
    from app.shadow import job as SJ
    nxt = (await s.execute(text("""select min(session_date) from trading_session
        where is_trading_day and session_date > :d"""), {"d": session})).scalar()
    cutoff = LC.ist_at(session, "23:59") if mode == "EVENING" else None
    from app.core.clock import now
    cutoff = min(now(), cutoff) if cutoff else now()
    m = await PS.load_market(s, session, nxt if mode == "EVENING" and nxt else session,
                             cutoff=cutoff, keys=keys)
    d = m.d(session)
    stocks = set((await s.execute(text("""select instrument_key from (
        select distinct on (instrument_key) instrument_key, security_class
        from instrument_security_class order by instrument_key, classified_at desc) x
        where security_class = 'STOCK'"""))).scalars())
    nifty = await SJ._index_series(s, SJ.NIFTY, m, cutoff)
    # the last completed bar for each mode
    if mode == "EVENING":
        if m.series and all(sr["close"][d] is None for sr in list(m.series.values())[:50]):
            day_bars = await one_minute_day(s, list(m.series), session)
            for k, b in day_bars.items():
                for f in ("open", "high", "low", "close", "volume"):
                    m.series[k][f][d] = b[f]
            nb = (await one_minute_day(s, [SJ.NIFTY], session)).get(SJ.NIFTY)
            if nb:
                nifty["close"][d] = nb["close"]
        last = d
    elif mode == "INTRADAY":
        for k, q in (live or {}).items():
            if k in m.series and q.get("ltp"):
                sr = m.series[k]
                sr["open"][d], sr["high"][d], sr["low"][d] = q["open"], q["high"], q["low"]
                sr["close"][d], sr["volume"][d] = q["ltp"], q.get("volume")
        nq = (live or {}).get(SJ.NIFTY)
        if nq and nq.get("ltp"):
            nifty["close"][d] = nq["ltp"]
        last = d
    else:
        last = d - 1
    if keys is None:
        keys = rank_universe(m.series, last, stocks)
        keys += [k for k in extra if k not in keys]
    keys = [k for k in keys if k in m.series]
    names = await LC.names(s, keys)
    qx = live if live is not None else (await quotes([*keys, SJ.NIFTY]) if fetch_quotes
                                        else {})
    if nifty["close"][last] is None and (qx.get(SJ.NIFTY) or {}).get("ltp"):
        nifty["close"][last] = qx[SJ.NIFTY]["ltp"]        # index 1m bars are not stored
    # market context
    nret = (nifty["close"][last] / nifty["close"][last - 1] - 1) \
        if nifty["close"][last] and nifty["close"][last - 1] else None
    facts = {k: price_facts(m.series[k], last) for k in keys}
    by_sec: dict[str, list[float]] = defaultdict(list)
    for k, f in facts.items():
        if f and f["ret_1d"] is not None:
            by_sec[m.sectors.get(k) or "?"].append(f["ret_1d"])
    sec_med = {sct: statistics.median(v) for sct, v in by_sec.items() if len(v) >= 3}
    cal, _ = SJ.calendar()
    reg_day = d + 1 if mode == "EVENING" and nxt and nxt in m.index else d
    reg_on = m.days[reg_day] if reg_day < len(m.days) else session
    if regime_override:
        regime = regime_override
    else:
        regime = await _regime(s, m, keys, facts, nifty, cutoff, reg_day, reg_on, cal)
    fii = await fii_dii(s)
    ctx = {"session": str(session), "mode": mode, "nifty_ret_1d": _r(nret),
           "regime": regime, "calendar": cal.get(reg_on, []), "fii_dii": fii}
    return await _assemble(s, m, keys, names, qx, facts, nifty, nret, sec_med, ctx, cutoff,
                           session, last, mode)


async def _regime(s, m, keys, facts, nifty, cutoff, reg_day, reg_on, cal) -> dict[str, Any]:
    from app.shadow import job as SJ
    from app.shadow import regime as RGM
    try:
        idx = {"nifty": nifty, "bank": await SJ._index_series(s, SJ.BANK, m, cutoff),
               "vix": await SJ._index_series(s, SJ.VIX, m, cutoff)}
        uni = [k for k in keys if facts.get(k)]
        pre = RGM.pre_features(idx, {k: m.series[k] for k in uni}, uni, reg_day,
                               results_share=0.0, calendar_events=cal.get(reg_on, []),
                               holiday_thin=False)
        state, rule, _ = RGM.classify(pre)
        regime = {"for_session": str(reg_on), "state": state, "rule": rule,
                  "nifty_adx14": _r(pre.get("nifty_adx14"), 1),
                  "breadth_50dma": _r(pre.get("breadth_50dma"), 3),
                  "vix": pre.get("vix_close"), "vix_pct252": _r(pre.get("vix_pct252"), 2)}
    except Exception as e:
        regime = {"error": f"{type(e).__name__}: {e}"[:200]}
    return regime


async def _assemble(s, m, keys, names, qx, facts, nifty, nret, sec_med, ctx, cutoff,
                    session, last, mode) -> dict[str, Any]:
    from app.core.clock import now
    t_last = cutoff
    news = await LC.news(s, keys, t_last - _dt.timedelta(hours=K.NEWS_WINDOW_H), t_last,
                         by_knowable=False)
    res, ca = await _events(s, keys, session)
    fund = await _fundamentals(s, keys)
    from app.training import e3 as E3
    out = {}
    for k in keys:
        f = facts.get(k)
        if not f:
            continue
        sr = m.series[k]
        b = beta(sr["close"], nifty["close"], last)
        sct = m.sectors.get(k)
        attr = attribution(f["ret_1d"], b, nret, sec_med.get(sct or "?"))
        q = qx.get(k) or {}
        tv = E3.median_turnover(sr, last)
        ex = {"median_turnover": tv, "upper_circuit": q.get("upper_circuit"),
              "lower_circuit": q.get("lower_circuit"), "quote_ltp": q.get("ltp"),
              "quote_at": q.get("at"), "round_trip_cost": K.ROUND_TRIP_COST,
              "half_spread": K.HALF_SPREAD}
        items = news.get(k, [])[:K.MAX_NEWS]
        last_close_t = LC.ist_at(m.days[last], "15:30")
        for n in items:
            t = n["published_at"] or n["knowable_at"]
            n["hours_before_last_close"] = _r((last_close_t - t).total_seconds() / 3600, 1) \
                if t else None
        today_res = any(r["kind"] == "INTIMATION" and r["meeting_date"] in (
            m.days[min(last + 1, len(m.days) - 1)], session) for r in res.get(k, []))
        bad = []
        if f["sessions"] < 120:
            bad.append(f"only {f['sessions']} sessions of history (recent listing)")
        bad += fund.get(k, {}).get("sanity_flags", [])
        news_24h = sum(1 for n in items if n["hours_before_last_close"] is not None
                       and n["hours_before_last_close"] <= 24)
        rule = RJ.judge(f, ex, {"news_24h": news_24h, "results_today": today_res,
                                "bad_data": bad})
        packet = {
            "stock": {"key": k, "symbol": (names.get(k) or {}).get("symbol"),
                      "name": (names.get(k) or {}).get("name"), "sector": sct},
            "as_of": {"mode": mode, "last_bar": str(m.days[last]), "built_at": str(now())},
            "evidence": {
                "px": {x: _r(v) if isinstance(v, float) else v for x, v in f.items()
                       if x not in LEVEL_KEYS},
                "lvl": {x: _r(f[x], 2) for x in LEVEL_KEYS if f.get(x) is not None},
                "attr": attr,
                "exec": {x: (_r(v, 5) if isinstance(v, float) else v) for x, v in ex.items()},
                "ctx": ctx,
                "fund": {x: v for x, v in fund.get(k, {}).items()},
                "rule": rule,
                "news": [{"id": f"news:{n['id']}", "source": n["source"], "title": n["title"],
                          "published_at": str(n["published_at"]), "hours_before_last_close":
                          n["hours_before_last_close"], "event_type": n["event_type"],
                          "impact": n["impact"], "direction": n["direction"],
                          "summary": (n["summary"] or "")[:300], "url": n["url"]} for n in items],
                "res": [{"id": f"res:{r['id']}", "kind": r["kind"], "meeting_date":
                         str(r["meeting_date"]), "period_end": str(r["period_end"]),
                         "verdict": r["verdict"], "event_at": str(r["event_at"])}
                        for r in res.get(k, [])[:6]],
                "ca": [{"id": f"ca:{i}", "type": r["action_type"], "ex_date": str(r["ex_date"])}
                       for i, r in enumerate(ca.get(k, []))],
            }}
        sha = hashlib.sha256(json.dumps(packet["evidence"], default=str, sort_keys=True)
                             .encode()).hexdigest()
        out[k] = {"packet": packet, "sha": sha, "symbol": packet["stock"]["symbol"]}
    return {"session": session, "mode": mode, "dossiers": out, "context": ctx,
            "universe": len(keys)}


def evidence_ids(packet: dict[str, Any]) -> set[str]:
    ev = packet["evidence"]
    ids = {k for k in ("px", "lvl", "attr", "exec", "ctx", "fund", "rule") if ev.get(k)}
    for sect in ("news", "res", "ca"):
        ids |= {x["id"] for x in ev.get(sect) or []}
    return ids
