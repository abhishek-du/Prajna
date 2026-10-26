"""The P1 shadow job: load one session's inputs, run the regime engine, both strategies,
the guards and the placebos, and return the rows (store.py records them).

A session T is ready when its 1d bars are stored (the next morning, as the paper job)
and its 1m bars are complete (>= 90 % of the universe with >= 370 bars). Prices:
  daily context   pit.bars_adjusted at the run's cutoff (app.paper.strategies.load_market)
  intraday        raw canonical 15m / 1m bars; a name with a non-dividend corporate action
                  ex-dated inside the 15m history window (11 sessions) is excluded, so
                  raw intraday prices never straddle an adjustment
Universe: the E4 eligible top-500 restricted to security class STOCK (no fund units or
ETFs) with a median daily turnover >= Rs 5 crore. Exclusions decided before 09:15 of T: results intimated for T - 1 or T, or a results
outcome knowable in [T - 1 09:15, T 09:15); the CA window above.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import pathlib
from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.core.clock import IST
from app.core.errors import PrajnaError
from app.paper import strategies as PS
from app.shadow import book as BK
from app.shadow import indicators as I
from app.shadow import regime as RG
from app.shadow import spec as SP
from app.shadow import strategies as STG
from app.shadow.bars import IBar, NameDay, at
from app.training import e3 as E3
from app.training import e4 as E4

NIFTY, BANK, VIX = "NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank", "NSE_INDEX|India VIX"
MIN_TURNOVER_INR = 5e7                       # app/paper/risk.py Limits.min_turnover_inr
CALENDAR = pathlib.Path(__file__).with_name("event_calendar.csv")


class ShadowRefused(PrajnaError):
    """The session cannot be run (yet), or a stored run would be contradicted."""


def calendar() -> tuple[dict[_dt.date, list[str]], str]:
    raw = CALENDAR.read_bytes()
    out: dict[_dt.date, list[str]] = defaultdict(list)
    for r in csv.DictReader(raw.decode().splitlines()):
        out[_dt.date.fromisoformat(r["date"])].append(r["event"])
    return dict(out), hashlib.sha256(raw).hexdigest()


def _bars(rows) -> dict[str, list[tuple[_dt.date, IBar]]]:
    out: dict[str, list[tuple[_dt.date, IBar]]] = defaultdict(list)
    for r in rows:
        if None in (r.open, r.high, r.low, r.close):
            continue
        out[r.instrument_key].append((r.market_date, IBar(
            r.bar_start_utc, r.event_end, float(r.open), float(r.high), float(r.low),
            float(r.close), float(r.volume or 0))))
    return out


async def _intraday(s: AsyncSession, tf: str, days: list[_dt.date], keys: list[str],
                    cutoff: _dt.datetime):
    return _bars((await s.execute(text("""
        select instrument_key, market_date, bar_start_utc, event_end, open, high, low, close,
               volume from canon_market_bar
        where timeframe = :tf and market_date = any(:d) and instrument_key = any(:k)
          and knowable_at <= :c
        order by instrument_key, bar_start_utc"""),
        {"tf": tf, "d": days, "k": keys, "c": cutoff})).all())


async def _index_series(s: AsyncSession, key: str, m: PS.Market,
                        cutoff: _dt.datetime) -> dict[str, list]:
    r = await pit.bars_adjusted(s, key, "1d", cutoff, start=m.days[0], end=m.days[-1],
                                allow_low_confidence=True)
    cols = {f: [None] * len(m.days) for f in PS.FIELDS}
    for b in r["rows"]:
        i = m.index.get(b["market_date"])
        if i is not None:
            for f in PS.FIELDS:
                cols[f][i] = None if b.get(f) is None else float(b[f])
    return cols


def _daily_context(sr: dict[str, list], d: int) -> dict[str, float | None]:
    t = RG._tail(sr, d)
    c = t["close"]
    e = I.ema(c, 50)[-1] if len(c) >= 50 else None
    a = I.adx(t["high"], t["low"], c, 14)[-1] if len(c) >= 29 else None
    vols = [v for v in sr["volume"][max(0, d - 20):d] if v is not None and v >= 0]
    return {"ema50": e, "adx14": a,
            "median_volume_20d": float(np.median(vols)) if len(vols) >= 10 else None}


async def ready(s: AsyncSession, session: _dt.date) -> str | None:
    """None when the session can run; else why not."""
    if not (await s.execute(text("""select exists(select 1 from canon_market_bar
            where instrument_key = :k and timeframe = '1d' and market_date = :d)"""),
            {"k": NIFTY, "d": session})).scalar():
        return "the session's 1d bars are not stored yet"
    if not (await s.execute(text("""select exists(select 1 from canon_market_bar
            where instrument_key = :k and timeframe = '1m' and market_date = :d)"""),
            {"k": NIFTY, "d": session})).scalar():
        return "the session's 1m bars are not stored yet"
    return None


async def load(s: AsyncSession, session: _dt.date, cutoff: _dt.datetime) -> dict[str, Any]:
    why = await ready(s, session)
    if why:
        raise ShadowRefused(f"{session}: {why}")
    ts = (await s.execute(text("""select session_type, open_ist, close_ist from trading_session
        where session_date = :d and is_trading_day"""), {"d": session})).first()
    if ts is None:
        raise ShadowRefused(f"{session} is not a trading session")
    if ts.session_type != "NORMAL" or str(ts.open_ist)[:5] != "09:15" \
            or str(ts.close_ist)[:5] != "15:30":
        return {"skipped": f"{ts.session_type} session {ts.open_ist}-{ts.close_ist}"}
    m = await PS.load_market(s, session, session, cutoff=cutoff)
    d = m.d(session)
    if d < 1:
        raise ShadowRefused(f"{session}: no previous session loaded")
    stocks = set((await s.execute(text("""select instrument_key from (
        select distinct on (instrument_key) instrument_key, security_class
        from instrument_security_class order by instrument_key, classified_at desc) x
        where security_class = 'STOCK'"""))).scalars())
    uni = [r[0] for r in E4.eligible(m.series, d, m.suspect)
           if r[0] in stocks
           and (E3.median_turnover(m.series[r[0]], d - 1) or 0) >= MIN_TURNOVER_INR]
    idx = {"nifty": await _index_series(s, NIFTY, m, cutoff),
           "bank": await _index_series(s, BANK, m, cutoff),
           "vix": await _index_series(s, VIX, m, cutoff)}
    if idx["nifty"]["close"][d - 1] is None:
        raise ShadowRefused(f"{session}: the Nifty 50 1d bar of the previous session is missing")
    prev = m.days[d - 1]
    open_t = at(session, "09:15")
    prev_open = at(prev, "09:15")
    res = (await s.execute(text("""select distinct instrument_key from results_event
        where instrument_key = any(:k) and knowable_at < :o and (
              (kind = 'INTIMATION' and meeting_date in (:p, :d))
           or (kind = 'OUTCOME' and event_at >= :po and event_at < :o))"""),
        {"k": uni, "o": open_t, "p": prev, "d": session, "po": prev_open})).scalars().all()
    res_t = (await s.execute(text("""select count(distinct instrument_key) from results_event
        where instrument_key = any(:k) and knowable_at < :o and kind = 'INTIMATION'
          and meeting_date = :d"""), {"k": uni, "o": open_t, "d": session})).scalar()
    h15 = m.days[max(0, d - SP.DATA["history_15m_sessions"]):d + 1]
    ca = (await s.execute(text("""select distinct instrument_key from canon_corporate_action
        where instrument_key = any(:k) and action_type <> 'DIVIDEND'
          and ex_date > :a and ex_date <= :b"""),
        {"k": uni, "a": h15[0], "b": session})).scalars().all()
    m15 = await _intraday(s, "15m", h15, uni, cutoff)
    m1 = await _intraday(s, "1m", [session], uni + [NIFTY], cutoff)
    full = sum(1 for k in uni if len(m1.get(k, ())) >= SP.DATA["min_1m_bars"])
    if not uni or full / len(uni) < SP.DATA["min_universe_share_1m"]:
        raise ShadowRefused(f"{session}: 1m bars incomplete ({full}/{len(uni)} names with "
                            f">= {SP.DATA['min_1m_bars']} bars)")
    names: dict[str, NameDay] = {}
    for k in uni:
        ctx = _daily_context(m.series[k], d)
        names[k] = NameDay(
            k, [b for _, b in m1.get(k, [])], [b for _, b in m15.get(k, [])],
            [dt for dt, _ in m15.get(k, [])], m.series[k]["close"][d - 1],
            ctx["ema50"], ctx["adx14"], ctx["median_volume_20d"], m.sectors.get(k))
    cal, cal_sha = calendar()
    near = (await s.execute(text("""select session_date, session_type from trading_session
        where session_date between :a and :b"""),
        {"a": session - _dt.timedelta(days=4), "b": session + _dt.timedelta(days=4)})).all()
    kinds = {r.session_date: r.session_type for r in near}

    def _adjacent(step: int) -> bool:
        x = session + _dt.timedelta(days=step)
        while kinds.get(x) == "WEEKEND":
            x += _dt.timedelta(days=step)
        return kinds.get(x) == "HOLIDAY"

    thin = _adjacent(-1) or _adjacent(1) or (session.month == 12 and session.day >= 24)
    sha = hashlib.sha256()
    for k in sorted(names):
        nd = names[k]
        sha.update(json.dumps([k, nd.prev_close, nd.ema50_1d, nd.adx14_1d,
                               nd.median_volume_20d, nd.sector,
                               [(b.start.isoformat(), b.open, b.high, b.low, b.close, b.volume)
                                for b in nd.m1 + nd.m15]], default=str).encode())
    sha.update(json.dumps([[(b.start.isoformat(), b.open, b.close) for _, b in m1.get(NIFTY, [])],
                           {k: v[max(0, d - 300):d] for k, v in
                            {n: idx[n]["close"] for n in idx}.items()},
                           sorted(res), sorted(ca), cal_sha, thin], default=str).encode())
    return {"session": session, "m": m, "d": d, "universe": uni, "idx": idx,
            "names": names, "nifty_1m": [b for _, b in m1.get(NIFTY, [])],
            "excluded_results": sorted(res), "excluded_ca": sorted(ca),
            "results_share": (res_t or 0) / len(uni), "calendar": cal.get(session, []),
            "calendar_sha256": cal_sha, "holiday_thin": thin, "inputs_sha256": sha.hexdigest()}


def _cp(hhmm: str) -> str:
    return hhmm.replace(":", "")


def compute(inp: dict[str, Any], prior_daily_net: dict[str, list[float]]) -> dict[str, Any]:
    """The rows of one session (pure given the loaded inputs)."""
    session, d, names = inp["session"], inp["d"], inp["names"]
    eq = {k: inp["m"].series[k] for k in inp["universe"]}
    pre = RG.pre_features(inp["idx"], eq, inp["universe"], d,
                          results_share=inp["results_share"],
                          calendar_events=inp["calendar"], holiday_thin=inp["holiday_thin"])
    state, rule, mult = RG.classify(pre)
    snaps = [{"checkpoint": "PRE", "features": pre, "state": state, "rule_fired": rule,
              "risk_mult": mult, "day_type": None}]
    of = RG.open_features(inp["nifty_1m"], inp["idx"]["nifty"]["close"][d - 1],
                          pre["nifty_sigma20"])
    if of["shock_open"] and state != "SHOCK":
        state, rule = "SHOCK", "open:|nifty_gap|>=2sigma20"
        mult = SP.REGIME["mult"]["SHOCK"] * (SP.REGIME["holiday_thin_mult"]
                                             if pre["holiday_thin"] else 1.0)
    snaps.append({"checkpoint": "OPEN", "features": of, "state": state, "rule_fired": rule,
                  "risk_mult": mult, "day_type": None})
    day_types: list[tuple[_dt.datetime, str]] = []
    for hhmm in SP.REGIME["checkpoints_ist"]:
        f = RG.intraday_features(session, hhmm, inp["nifty_1m"], names)
        dt_ = RG.day_type(f)
        day_types.append((at(session, hhmm), dt_))
        snaps.append({"checkpoint": _cp(hhmm), "features": f, "state": state,
                      "rule_fired": rule, "risk_mult": mult, "day_type": dt_})
    excluded = set(inp["excluded_results"]) | set(inp["excluded_ca"])
    pool = [k for k in inp["universe"] if k not in excluded]
    s1 = SP.STRAT[SP.S1]
    ends = []
    t = at(session, s1["signal_from"])
    while t <= at(session, s1["signal_to"]):
        ends.append(t)
        t += _dt.timedelta(minutes=15)
    breadth = {e: RG.breadth_at(names, e)["breadth_above_open"] for e in ends}
    trades: list[dict] = []
    skips: list[dict] = []
    counts: dict[str, Any] = {"universe": len(inp["universe"]), "pool": len(pool),
                              "excluded_results": len(inp["excluded_results"]),
                              "excluded_ca": len(inp["excluded_ca"])}
    for strat in SP.STRATEGIES:
        cands: list[STG.Candidate] = []
        sk: list[STG.Skip] = []
        for k in pool:
            r = STG.orb_breadth(names[k], session, inp["nifty_1m"], breadth) \
                if strat == SP.S1 else STG.vwap_revert(names[k], session)
            if isinstance(r, STG.Candidate):
                cands.append(r)
            elif isinstance(r, STG.Skip):
                sk.append(r)
        taken, gs, flags = BK.run(cands, names, prior_daily_net=prior_daily_net.get(strat, []))
        plc = BK.placebo(taken, names, pool, strat, session)
        m_state = SP.REGIME["mult"]["SHOCK_REVERSION"] if (state == "SHOCK" and strat == SP.S2) \
            else mult
        for x in taken + plc:
            dts = [v for tt, v in day_types if tt <= x["entry_at"]]
            x.update(regime_state=state, risk_mult=m_state, day_type=dts[-1] if dts else None)
        trades += taken + plc
        skips += [{"strategy": z.strategy, "instrument_key": z.key, "reason": z.reason,
                   "signal_at": z.signal_at, "detail": z.detail} for z in sk + gs]
        counts[strat] = {"candidates": len(cands), "taken": len(taken), "placebo": len(plc),
                         "skips": len(sk) + len(gs), "guard_flags": flags}
    return {"snapshots": snaps, "trades": trades, "skips": skips, "counts": counts,
            "state": state}


def rows_sha256(out: dict[str, Any]) -> str:
    body = {k: out[k] for k in ("snapshots", "trades", "skips")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def mechanics(out: dict[str, Any]) -> dict[str, Any]:
    """The smoke-run summary: counts, exit-reason mix and fill-inside-bar checks. No P&L
    is computed or printed (pre-registration §9)."""
    reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    skips: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    bad = []
    for x in out["trades"]:
        reasons[x["strategy"] + (":placebo" if x["is_placebo"] else "")][x["exit_reason"]] += 1
        if not (x["entry_at"] < x["exit_at"] <= x["time_stop"]):
            bad.append((x["instrument_key"], "times"))
        if x["side"] * (x["entry_raw"] - x["stop"]) <= 0:
            bad.append((x["instrument_key"], "stop_side"))
        if x["rrr"] < SP.BOOK["rrr_min"] and not x["is_placebo"]:
            bad.append((x["instrument_key"], "rrr"))
    for z in out["skips"]:
        skips[z["strategy"]][z["reason"]] += 1
    return {"state": out["state"],
            "snapshots": [(z["checkpoint"], z["state"], z["day_type"]) for z in out["snapshots"]],
            "counts": out["counts"], "exit_reasons": {k: dict(v) for k, v in reasons.items()},
            "skip_reasons": {k: dict(v) for k, v in skips.items()}, "violations": bad}


def _ist(t: _dt.datetime) -> str:
    return t.astimezone(IST).strftime("%H:%M")
