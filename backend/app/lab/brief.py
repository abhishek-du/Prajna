"""The admin's morning brief for a session, built before the open from data knowable then:
the P1 regime call (PRE, from the frozen regime engine), the event calendar and today's
results, the stocks that fit each strategy's setup with their present condition (trend,
ATR%, RSI, support/resistance distance, liquidity), what would trigger and what would
invalidate each one, the E5 picks once made (09:06), and the high-impact news.

These are UNVALIDATED research signals, not advice: no strategy has passed its forward
test, and nothing here places an order."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST, now
from app.lab import compute as C
from app.shadow import indicators as I
from app.shadow import regime as RGM
from app.shadow import spec as SP

DISCLAIMER = ("Unvalidated research signals, not investment advice. No strategy has passed "
              "its forward test; every figure is from stored data before the open. Paper "
              "only: nothing here places an order.")
TOP = 10


def _pct(a: float | None, b: float | None) -> float | None:
    return None if a is None or b in (None, 0) else a / b - 1


def watch(k: str, sym: dict[str, Any], c: float, ctx: dict[str, Any], rsi: float | None
          ) -> list[dict[str, Any]]:
    """The setups a name fits before the open (pure). S1 = trend breakout, S2 = range
    reversion; the thresholds are the frozen P1 ones (app/shadow/spec.py)."""
    s1, s2 = SP.STRAT[SP.S1], SP.STRAT[SP.S2]
    ema, adx, atrp, zs = ctx.get("ema50"), ctx.get("adx14"), ctx.get("atr_pct_1d"), \
        ctx.get("sr_zones") or []
    base = {"key": k, "symbol": sym.get("symbol"), "sector": sym.get("sector"), "close": c,
            "ema50": ema, "adx14": adx, "atr_pct": atrp, "rsi14": rsi}
    out = []
    above = [z for z in zs if z > c]
    below = [z for z in zs if z < c]
    res = min(above) if above else None
    sup = max(below) if below else None
    if ema and adx is not None and adx >= s1["ind_adx_min"] and atrp is not None \
            and atrp <= s1["max_atr_pct_1d"]:
        side = 1 if c > ema else -1
        zone = res if side > 0 else sup
        out.append({**base, "strategy": "S1", "side": side, "zone": zone,
                    "zone_dist": None if zone is None else abs(zone / c - 1),
                    "score": adx,
                    "why": [f"daily trend {'up' if side > 0 else 'down'}: close "
                            f"{'above' if side > 0 else 'below'} the 50-day EMA",
                            f"ADX {adx:.0f} >= {s1['ind_adx_min']:.0f} (strong trend)",
                            f"ATR {atrp:.1%} <= {s1['max_atr_pct_1d']:.0%} (moderate volatility)"]
                    + ([f"next {'resistance' if side > 0 else 'support'} zone ₹{zone:,.1f} "
                        f"({abs(zone / c - 1):.1%} away)"] if zone else
                       ["no S/R zone in the way"]),
                    "trigger": (f"after 09:45, a strong 15-min candle closing "
                                f"{'above' if side > 0 else 'below'} the 09:15-09:30 range "
                                f"{'high' if side > 0 else 'low'} on above-average volume, "
                                f"with > 60 % of stocks and Nifty "
                                f"{'above' if side > 0 else 'below'} their open"),
                    "invalidate": (f"price back inside the opening range, or Nifty "
                                   f"{'below' if side > 0 else 'above'} its open; no entry "
                                   f"after 11:00")})
    if adx is not None and adx < s2["stock_adx_max"]:
        near_sup = sup is not None and (c - sup) / c <= SP.SR["near_pct"]
        near_res = res is not None and (res - c) / c <= SP.SR["near_pct"]
        if near_sup and (rsi is None or rsi < 50):
            out.append({**base, "strategy": "S2", "side": 1, "zone": sup,
                        "zone_dist": (c - sup) / c, "score": -((c - sup) / c),
                        "why": [f"no trend (ADX {adx:.0f} < {s2['stock_adx_max']:.0f})",
                                f"support zone ₹{sup:,.1f} only {(c - sup) / c:.1%} below"]
                        + ([f"RSI {rsi:.0f}: already weak"] if rsi is not None else []),
                        "trigger": ("10:00-14:00: price below the lower Bollinger band, RSI(15m) "
                                    "< 30 and below VWAP, then a hammer or bullish engulfing "
                                    "near the support"),
                        "invalidate": ("a move of more than 3 % from yesterday's close (news-"
                                       "like), or a close below the support zone")})
        if near_res and (rsi is None or rsi > 50):
            out.append({**base, "strategy": "S2", "side": -1, "zone": res,
                        "zone_dist": (res - c) / c, "score": -((res - c) / c),
                        "why": [f"no trend (ADX {adx:.0f} < {s2['stock_adx_max']:.0f})",
                                f"resistance zone ₹{res:,.1f} only {(res - c) / c:.1%} above"]
                        + ([f"RSI {rsi:.0f}: already stretched"] if rsi is not None else []),
                        "trigger": ("10:00-14:00: price above the upper Bollinger band, RSI(15m) "
                                    "> 70 and above VWAP, then a shooting star or bearish "
                                    "engulfing near the resistance"),
                        "invalidate": ("a move of more than 3 % from yesterday's close, or a "
                                       "close above the resistance zone")})
    return out


def preopen_eligible(series: dict[str, dict], d: int, suspect: dict[str, set[int]]
                     ) -> list[str]:
    """app/training/e4.eligible before the open: the same history, price, suspect-session
    and turnover rules at d - 1, ranked by turnover, without the 09:15 gap check (the
    gap is not known yet; P1 applies it at the open)."""
    from app.training import e3 as E3
    from app.training import e4 as E4
    rows = []
    for k, sr in series.items():
        pc = sr["close"][d - 1] if d >= 1 else None
        if not pc or pc < E4.MIN_PRICE:
            continue
        if sum(1 for x in sr["close"][:d] if x is not None and x > 0) < E3.MIN_HISTORY:
            continue
        if any(d - E3.LOOKBACK < x < d for x in suspect.get(k, ())):
            continue
        t, v = E3.median_turnover(sr, d - 1), E3.volatility(sr, d - 1)
        if t is not None and v is not None:
            rows.append((k, t))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return [k for k, _ in rows[:E4.UNIVERSE_TOP]]


async def latest_desk(s: AsyncSession, keys: list[str], day: _dt.date) -> dict[str, dict]:
    """The Research Desk's latest valid verdict per stock made before `day`'s open."""
    try:
        rows = (await s.execute(text("""select distinct on (instrument_key) instrument_key,
                decision, score, entry_lo, entry_hi, stop, t1, t2, why_moved, thesis,
                created_at from desk_verdict where instrument_key = any(:k)
              and status = 'OK' and created_at < :o and created_at > :o - interval '4 days'
            order by instrument_key, created_at desc"""),
            {"k": keys, "o": C.ist_at(day, "09:15")})).mappings().all()
    except Exception:
        await s.rollback()
        return {}
    return {r["instrument_key"]: dict(r) for r in rows}


async def buy_list(s: AsyncSession, day: _dt.date, m, d: int, uni: list[str],
                   meta: dict[str, dict], excluded: set[str]) -> list[dict[str, Any]]:
    """The intraday Buy List for `day` (app/lab/buylist): rules (dash-plan-v2) and the
    Research Desk, every liquid stock except today's results / corporate actions."""
    from app.desk import dossier as DS
    from app.desk import rules as RJ
    from app.lab import buylist as BL
    from app.training import e3 as E3
    keys = [k for k in uni if k not in excluded]
    desk = await latest_desk(s, keys, day)
    rows = []
    for k in keys:
        f = DS.price_facts(m.series[k], d - 1)
        if not f:
            continue
        rule = RJ.judge(f, {"median_turnover": E3.median_turnover(m.series[k], d - 1)},
                        {"news_24h": 0})
        rows.append(BL.item(k, meta.get(k) or {}, f, rule, desk.get(k)))
    return BL.rank_items([r for r in rows if r])


async def build(s: AsyncSession, day: _dt.date) -> dict[str, Any]:
    from app.paper import strategies as PS
    from app.shadow import job as SJ
    from app.training import e3 as E3
    cutoff = min(now(), C.ist_at(day, "09:14"))
    m = await PS.load_market(s, day, day, cutoff=cutoff)
    d = m.d(day)
    stocks = set((await s.execute(text("""select instrument_key from (
        select distinct on (instrument_key) instrument_key, security_class
        from instrument_security_class order by instrument_key, classified_at desc) x
        where security_class = 'STOCK'"""))).scalars())
    uni = [k for k in preopen_eligible(m.series, d, m.suspect) if k in stocks
           and (E3.median_turnover(m.series[k], d - 1) or 0) >= SJ.MIN_TURNOVER_INR]
    idx = {"nifty": await SJ._index_series(s, SJ.NIFTY, m, cutoff),
           "bank": await SJ._index_series(s, SJ.BANK, m, cutoff),
           "vix": await SJ._index_series(s, SJ.VIX, m, cutoff)}
    open_t = C.ist_at(day, "09:15")
    res_today = (await s.execute(text("""select distinct instrument_key from results_event
        where instrument_key = any(:k) and knowable_at < :o and kind = 'INTIMATION'
          and meeting_date = :d"""), {"k": uni, "o": open_t, "d": day})).scalars().all()
    ca_today = (await s.execute(text("""select instrument_key, action_type from
        canon_corporate_action where instrument_key = any(:k) and ex_date = :d"""),
        {"k": uni, "d": day})).all()
    cal, _ = SJ.calendar()
    pre = RGM.pre_features(idx, {k: m.series[k] for k in uni}, uni, d,
                           results_share=len(res_today) / len(uni) if uni else 0.0,
                           calendar_events=cal.get(day, []), holiday_thin=False)
    state, rule, mult = RGM.classify(pre)
    fo, _ = await SJ.fo_underlyings(s, open_t)
    excluded = set(res_today) | {r.instrument_key for r in ca_today}
    pool = [k for k in uni if k in fo and k not in excluded]
    meta = await C.names(s, sorted(set(uni) | set(res_today)))
    cands: list[dict] = []
    for k in pool:
        c = m.series[k]["close"][d - 1]
        if not c:
            continue
        ctx = SJ._daily_context(m.series[k], d)
        closes = [x for x in m.series[k]["close"][max(0, d - 60):d] if x]
        r = I.rsi(closes, 14)[-1] if len(closes) > 15 else None
        cands += watch(k, meta.get(k) or {}, c, ctx, r)
    by: dict[str, list[dict]] = {"S1": [], "S2": []}
    for x in cands:
        by[x["strategy"]].append(x)
    for k in by:
        by[k] = sorted(by[k], key=lambda x: -x["score"])[:TOP]
    e5 = [dict(r._mapping) for r in (await s.execute(text("""select p.instrument_key,
            i.trading_symbol, p.rank, p.prob_up, p.exp_return, p.confidence from model_prediction p
        left join canon_instrument i using (instrument_key)
        where p.session_date = :d and p.selected order by p.rank"""), {"d": day})).all()]
    hot = await C.news(s, pool, open_t - _dt.timedelta(hours=24), open_t, by_knowable=False)
    seen: set[str] = set()
    news = []
    for n in sorted(({"symbol": (meta.get(k) or {}).get("symbol"), **n}
                     for k, items in hot.items() for n in items if n.get("impact") == "HIGH"),
                    key=lambda n: n["knowable_at"], reverse=True):
        if n["title"] in seen:
            continue
        seen.add(n["title"])
        news.append(n)
    news = news[:20]
    events = {"calendar": cal.get(day, []),
              "results_today": sorted((meta.get(k) or {}).get("symbol") or k for k in res_today),
              "corporate_actions": [{"symbol": (meta.get(r.instrument_key) or {}).get("symbol"),
                                     "type": r.action_type} for r in ca_today]}
    regime = {"state": state, "rule": rule, "risk_mult": mult,
              "features": {k: pre.get(k) for k in ("nifty_adx14", "breadth_50dma",
                                                  "vix_close", "vix_pct252", "nifty_ret_1d",
                                                  "nifty_sigma20")},
              "tools": {"S1": state in ("TREND_UP", "TREND_DOWN"), "S2": state == "RANGE"},
              "note": {"TREND_UP": "trend day expected: S1 longs fit, S2 does not",
                       "TREND_DOWN": "down-trend: S1 shorts fit, avoid buying dips",
                       "RANGE": "sideways: S2 reversion fits, breakouts often fail",
                       "SHOCK": "shock: stand aside or minimum size",
                       "EVENT_WAIT": "event day: half size, wait for the event",
                       "MIXED": "unclear: no trade is a valid choice"}.get(state)}
    buylist = await buy_list(s, day, m, d, uni, meta, excluded)
    body = {"session": day, "regime": regime, "events": events,
            "candidates": {"S1": by["S1"], "S2": by["S2"], "E5": e5, "BUYLIST": buylist,
                           "gap_fade": "chosen at 09:15 from the 10 largest gap-downs in the "
                                       "top 500 (see Today after the open)"},
            "news": news}
    sha = hashlib.sha256(json.dumps(body, default=str, sort_keys=True).encode()).hexdigest()
    return {**body, "disclaimer": DISCLAIMER, "inputs_sha256": sha,
            "counts": {"universe": len(uni), "pool": len(pool), "S1": len(by["S1"]),
                       "buylist": len(buylist),
                       "S2": len(by["S2"]), "E5": len(e5), "news": len(news),
                       "as_of": cutoff.astimezone(IST).isoformat()}}
