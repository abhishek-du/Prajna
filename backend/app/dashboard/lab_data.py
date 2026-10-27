"""Strategy Lab queries for the dashboard (read only; every transaction is set read only by
the caller). The lab tables are append-only and versioned by lab_run: every query reads the
latest DAILY run of each session. Unblinded by the user's decision of 2026-10-27: per-day
P&L of every strategy is shown; the frozen tests and their looks are unchanged."""

from __future__ import annotations

import datetime as _dt
import math
import random
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.lab import registry as RG

LATEST = """with latest as (select distinct on (session_date) run_id, session_date
    from lab_run where kind = 'DAILY' order by session_date, created_at desc)"""
FEW = 30              # fewer real trades than this: the cell is shown as "too few trades"


def _n(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _row(r: Any) -> dict[str, Any]:
    out = {}
    for k, v in dict(r).items():
        out[k] = _n(v) if hasattr(v, "as_tuple") else v
    return out


async def dates(s: AsyncSession) -> list[_dt.date]:
    return list((await s.execute(text("""select distinct session_date from lab_run
        where kind = 'DAILY' order by 1 desc"""))).scalars())


async def overview(s: AsyncSession) -> dict[str, Any]:
    from app.lab import switches as SW
    sw = await SW.current(s)
    rows = (await s.execute(text(LATEST + """ select d.* from strategy_day d
        join latest l using (run_id) order by d.strategy, d.session_date"""))).mappings().all()  # noqa: S608
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["strategy"]].append(_row(r))
    out = []
    for meta in RG.STRATEGIES:
        hist = by.get(meta.name, [])
        real = [h for h in hist if h["trades"]]
        net = sum(h["net_inr"] or 0 for h in hist)
        trades = sum(h["trades"] for h in hist)
        wins = sum(h["wins"] for h in hist)
        last = hist[-1] if hist else None
        out.append({
            "strategy": meta.name, "family": meta.family, "kind": meta.kind,
            "title": meta.title, "title_hi": meta.title_hi, "tool": meta.tool,
            "look": meta.look, "switchable": meta.switchable,
            "enabled": sw[meta.name]["enabled"] if meta.switchable else None,
            "switch_reason": sw[meta.name]["reason"] if meta.switchable else None,
            "sessions": len(hist), "active_sessions": len(real), "trades": trades,
            "wins": wins, "hit_rate": wins / trades if trades else None, "net_inr": net,
            "equity_inr": last["equity_inr"] if last else None,
            "max_drawdown": max((h["drawdown"] for h in hist), default=None),
            "first": hist[0]["session_date"] if hist else None, "last": last,
            "curve": [{"d": h["session_date"], "eq": h["equity_inr"], "net": h["net_inr"]}
                      for h in hist[-120:]]})
    return {"strategies": out, "dates": [str(d) for d in (await dates(s))[:120]],
            "unblinded_from": "2026-10-28",
            "note": "Daily P&L shown by the user's decision (2026-10-27). The frozen P1/P2 "
                    "(60/250 sessions), E5 (40) and E6 (single) looks are unchanged; no rule "
                    "may change because of these numbers."}


async def day(s: AsyncSession, d: _dt.date) -> dict[str, Any]:
    run = (await s.execute(text("""select run_id, created_at, counts from lab_run
        where kind = 'DAILY' and session_date = :d order by created_at desc limit 1"""),
        {"d": d})).first()
    if run is None:
        return {"date": str(d), "available": False}
    sd = [_row(r) for r in (await s.execute(text("""select * from strategy_day
        where run_id = :r"""), {"r": run.run_id})).mappings().all()]
    tf = [_row(r) for r in (await s.execute(text("""select id, strategy, family, symbol,
        instrument_key, sector, side, is_placebo, signal_at, entry_at, exit_at, entry_px, exit_px,
        stop, target, qty, net_inr, net_r, exit_reason, outcome_class, outcome_rule, mfe_pct,
        mae_pct, mfe_r, mae_r, target_after_exit, regime_state, day_type, ai_verdict,
        first_news_lag_min, jsonb_array_length(news_before) n_before,
        jsonb_array_length(news_after) n_after from trade_forensic where run_id = :r
        order by strategy, is_placebo, entry_at nulls last"""),
        {"r": run.run_id})).mappings().all()]
    df = [_row(r) for r in (await s.execute(text("""select strategy, thought, happened, why,
        narrative from day_forensic where run_id = :r"""), {"r": run.run_id})).mappings().all()]
    order = {x.name: i for i, x in enumerate(RG.STRATEGIES)}
    sd.sort(key=lambda r: order.get(r["strategy"], 99))
    return {"date": str(d), "available": True, "built_at": run.created_at,
            "counts": run.counts, "strategies": sd, "trades": tf,
            "forensics": {f["strategy"]: f for f in df},
            "titles": {x.name: {"title": x.title, "title_hi": x.title_hi, "tool": x.tool,
                                "family": x.family} for x in RG.STRATEGIES}}


async def trade(s: AsyncSession, trade_id: int) -> dict[str, Any] | None:
    r = (await s.execute(text("select * from trade_forensic where id = :i"),
                         {"i": trade_id})).mappings().first()
    if r is None:
        return None
    t = _row(r)
    bars = (await s.execute(text("""select bar_start_utc, open, high, low, close, volume
        from canon_market_bar where timeframe = '1m' and market_date = :d
          and instrument_key = :k order by bar_start_utc"""),
        {"d": t["session_date"], "k": t["instrument_key"]})).all()
    ist = 5 * 3600 + 1800          # the chart library shows UTC: shift to IST wall time
    t["candles"] = [{"time": int(b.bar_start_utc.timestamp()) + ist, "open": _n(b.open),
                     "high": _n(b.high), "low": _n(b.low), "close": _n(b.close)}
                    for b in bars]
    t["chart_offset_s"] = ist
    t["title"] = (RG.BY_NAME.get(t["strategy"]).title if t["strategy"] in RG.BY_NAME else None)
    return t


def _ci(x: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float] | None:
    if len(x) < 5:
        return None
    rng = random.Random(seed)  # noqa: S311 - a seeded bootstrap, not security
    means = sorted(sum(rng.choice(x) for _ in x) / len(x) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


async def regime(s: AsyncSession, a: _dt.date | None = None, b: _dt.date | None = None
                 ) -> dict[str, Any]:
    """Strategy x regime and strategy x day type, on real filled trades."""
    rows = (await s.execute(text(LATEST + """ select t.strategy, t.family, t.regime_state,
            t.day_type, t.net_inr, t.net_r, t.session_date, d.regime_pre, d.day_type d_type
        from trade_forensic t join latest l using (run_id)
        left join strategy_day d on d.run_id = t.run_id and d.strategy = t.strategy
        where not t.is_placebo and t.exit_reason is distinct from 'NOT_FILLED'
          and (cast(:a as date) is null or t.session_date >= :a)
          and (cast(:b as date) is null or t.session_date <= :b)"""),  # noqa: S608
        {"a": a, "b": b})).mappings().all()
    # paper / E5 rows carry no regime of their own: use the day's P1 regime when present
    days = {r["session_date"]: (r["regime_pre"], r["d_type"]) for r in rows
            if r["family"] == "P1" and r["regime_pre"]}
    cells: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        st = r["regime_state"] or (days.get(r["session_date"]) or (None, None))[0] or "UNKNOWN"
        dt = r["day_type"] or (days.get(r["session_date"]) or (None, None))[1] or "UNKNOWN"
        cells[(r["strategy"], "regime", st)].append(r)
        cells[(r["strategy"], "day_type", dt)].append(r)
    out = []
    for (strat, axis, val), xs in sorted(cells.items()):
        nets = [_n(x["net_inr"]) or 0.0 for x in xs]
        rs = [x["net_r"] for x in xs if x["net_r"] is not None]
        ci = _ci(nets)
        out.append({"strategy": strat, "axis": axis, "value": val, "trades": len(xs),
                    "hit_rate": sum(1 for v in nets if v > 0) / len(nets),
                    "net_inr": sum(nets), "avg_net_inr": sum(nets) / len(nets),
                    "avg_r": sum(rs) / len(rs) if rs else None,
                    "ci95_avg_net": ci, "too_few": len(xs) < FEW})
    return {"cells": out, "few": FEW,
            "note": f"Cells with fewer than {FEW} trades are noise-dominated; read them as "
                    "counts, not evidence."}


async def history(s: AsyncSession, strategy: str) -> list[dict[str, Any]]:
    return [_row(r) for r in (await s.execute(text(LATEST + """ select d.* from strategy_day d
        join latest l using (run_id) where d.strategy = :s order by d.session_date desc"""),  # noqa: S608
        {"s": strategy})).mappings().all()]


async def brief(s: AsyncSession, d: _dt.date) -> dict[str, Any]:
    r = (await s.execute(text("""select b.*, r.created_at, r.counts from daily_brief b
        join lab_run r using (run_id) where b.session_date = :d
        order by r.created_at desc limit 1"""), {"d": d})).mappings().first()
    prev = (await s.execute(text("""select session_date from daily_brief where session_date < :d
        order by session_date desc limit 1"""), {"d": d})).scalar()
    grade = None
    if prev is not None:
        g = (await s.execute(text(LATEST + """ select f.why, f.happened from day_forensic f
            join latest l using (run_id) where f.session_date = :p and f.strategy = '_BRIEF'"""),  # noqa: S608
            {"p": prev})).mappings().first()
        grade = {"date": str(prev), **dict(g)} if g else None
    if r is None:
        return {"date": str(d), "available": False, "previous_grade": grade}
    return {"date": str(d), "available": True, **_row(r), "previous_grade": grade}


async def health(s: AsyncSession) -> dict[str, Any]:
    q = {
        "lab_daily": "select max(created_at) from lab_run where kind = 'DAILY'",
        "lab_brief": "select max(created_at) from lab_run where kind = 'BRIEF'",
        "p1_shadow": "select max(created_at) from shadow_run",
        "p1_last_session": "select max(market_date) from shadow_run",
        "p2_review": "select max(created_at) from llm_review",
        "paper": "select max(created_at) from paper_run",
        "paper_last_session": "select max(session_date) from paper_run",
        "e5_predict": "select max(predicted_at) from model_prediction",
        "stage3_snapshot": "select max(session_date) from feature_value "
                           "where snapshot = 'PRE_SESSION'",
        "daily_bars": "select max(market_date) from canon_market_bar where timeframe = '1d' "
                      "and instrument_key = 'NSE_INDEX|Nifty 50'",
        "news_last": "select max(knowable_at) from news_item",
    }
    out = {}
    for k, sql in q.items():
        out[k] = (await s.execute(text(sql))).scalar()
    reviews = (await s.execute(text("""select status, count(*) from llm_review
        group by 1"""))).all()
    out["p2_status_mix"] = {r[0]: r[1] for r in reviews}
    return out


async def buylist(s: AsyncSession, d: _dt.date | None) -> dict[str, Any]:
    """The Buy List of a session (the latest brief of that day, else the latest brief), its
    end-of-day grade when built, and the score cards of the recent days."""
    q = """select b.session_date, b.regime, b.events, b.candidates, r.created_at
        from daily_brief b join lab_run r using (run_id) {w}
        order by b.session_date desc, r.created_at desc limit 1"""
    r = (await s.execute(text(q.format(w="where b.session_date = :d")), {"d": d})).mappings() \
        .first() if d else None
    if r is None:
        r = (await s.execute(text(q.format(w="")))).mappings().first()
    if r is None:
        return {"available": False}
    day = r["session_date"]
    g = (await s.execute(text(LATEST + """ select f.happened from day_forensic f
        join latest l using (run_id) where f.session_date = :d and f.strategy = '_BUYLIST'"""),  # noqa: S608
        {"d": day})).scalar()
    hist = [{"date": str(x.session_date), **(x.happened or {}).get("summary", {})}
            for x in (await s.execute(text(LATEST + """ select f.session_date, f.happened
                from day_forensic f join latest l using (run_id)
                where f.strategy = '_BUYLIST' order by f.session_date desc limit 20""")))  # noqa: S608
            .all()]
    dates = [str(x) for x in (await s.execute(text("""select distinct session_date
        from daily_brief order by 1 desc limit 30"""))).scalars()]
    return {"available": True, "date": str(day), "built_at": r["created_at"],
            "regime": r["regime"], "events": r["events"],
            "items": (r["candidates"] or {}).get("BUYLIST") or [],
            "grade": g, "history": hist, "dates": dates}
