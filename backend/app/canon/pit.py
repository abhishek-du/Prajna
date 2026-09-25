"""Stage 2 point-in-time read API: the contract Stage 3 consumes.

Every read takes `as_of` and returns ONLY rows knowable strictly before it
(`knowable_at < as_of`, the rule of contracts.knowable.assert_knowable_before),
and each returned row is re-checked in Python. Reads go through the
canonical views, so only NSE-universe instruments are visible (global
instruments only through `global_bars` / `macro`). Nothing is filled in: a
missing bar is absent; `coverage()` says why (DATA / EMPTY / QUARANTINED /
VENDOR_ERROR / PENDING_BACKFILL / MISSING; 5m is OUT_OF_SCOPE), as of the
same instant.

Two things here are NOT point-in-time and must never feed a historical
decision: `current_coverage()` (what Stage 1 holds now, for live/ops) and
the columns canon_instrument.sector / sector_knowable_at (the LATEST profile
snapshot, i.e. today's sector). Historical sector: `sector(key, as_of)`.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import coverage as COV
from app.canon.process import _stage1_inputs, depth_start, session_cutoff
from app.canon.time import assert_all_knowable, market_date
from app.canon.validate import CANON_TIMEFRAMES
from app.core.clock import IST, now, to_utc


class OutOfScope(ValueError):
    """The timeframe is not part of the canonical layer (5m: D2-5m)."""


async def _rows(s: AsyncSession, sql: str, what: str, as_of: _dt.datetime, **kw) -> list[dict]:
    rows = [dict(r) for r in (await s.execute(text(sql), {"as_of": to_utc(as_of), **kw}))
            .mappings().all()]
    assert_all_knowable(rows, as_of, what)
    return rows


async def bars(s: AsyncSession, instrument_key: str, timeframe: str, as_of: _dt.datetime, *,
               start: _dt.date | None = None, end: _dt.date | None = None,
               limit: int | None = None) -> list[dict]:
    """Bars of one NSE instrument knowable before as_of, oldest first. `limit`
    keeps the LAST n bars."""
    if timeframe not in CANON_TIMEFRAMES:
        raise OutOfScope(f"timeframe {timeframe!r} is not canonical (in scope: "
                         f"{', '.join(CANON_TIMEFRAMES)})")
    lim = f"limit {int(limit)}" if limit else ""
    rows = await _rows(s, f"""
        select * from (select * from canon_market_bar
          where instrument_key = :k and timeframe = :tf and knowable_at < :as_of
            and (cast(:a as date) is null or market_date >= :a)
            and (cast(:b as date) is null or market_date <= :b)
          order by bar_start_utc desc {lim}) x order by bar_start_utc""",   # noqa: S608
                       f"bar {instrument_key} {timeframe}", as_of, k=instrument_key,
                       tf=timeframe, a=start, b=end)
    return rows


async def corporate_actions(s: AsyncSession, as_of: _dt.datetime,
                            instrument_key: str | None = None) -> list[dict]:
    return await _rows(s, """
        select * from canon_corporate_action where knowable_at < :as_of
          and (cast(:k as text) is null or instrument_key = :k)
        order by knowable_at, id""", "corporate action", as_of, k=instrument_key)


async def news(s: AsyncSession, as_of: _dt.datetime, instrument_key: str | None = None,
               since: _dt.datetime | None = None) -> list[dict]:
    """Per instrument: the (article, instrument) association must be knowable
    (greatest of article and vendor-link knowable_at)."""
    return await _rows(s, """
        select * from canon_news where knowable_at < :as_of
          and (cast(:k as text) is null or instrument_key = :k)
          and (cast(:since as timestamptz) is null or published_at >= :since)
        order by published_at, news_id""", "news", as_of, k=instrument_key,
                       since=to_utc(since) if since else None)


async def fundamentals(s: AsyncSession, instrument_key: str, as_of: _dt.datetime,
                       statement_type: str | None = None) -> list[dict]:
    """The LATEST snapshot per statement type among those knowable before as_of."""
    return await _rows(s, """
        select distinct on (statement_type) * from canon_fundamental
        where instrument_key = :k and knowable_at < :as_of
          and (cast(:st as text) is null or statement_type = :st)
        order by statement_type, knowable_at desc""", "fundamentals", as_of,
                       k=instrument_key, st=statement_type)


async def sector(s: AsyncSession, instrument_key: str, as_of: _dt.datetime) -> str | None:
    """The sector of the latest profile snapshot knowable before as_of. The only
    historical access path: canon_instrument.sector is today's sector."""
    rows = await fundamentals(s, instrument_key, as_of, "profile")
    return (rows[0]["payload"] or {}).get("sector") or None if rows else None


async def preopen(s: AsyncSession, instrument_key: str, as_of: _dt.datetime,
                  market_date: _dt.date | None = None) -> list[dict]:
    return await _rows(s, """
        select * from canon_preopen where instrument_key = :k and knowable_at < :as_of
          and (cast(:d as date) is null or market_date = :d)
        order by event_ts, tick_id""", "pre-open", as_of, k=instrument_key, d=market_date)


async def macro(s: AsyncSession, as_of: _dt.datetime, series_prefix: str = "") -> list[dict]:
    return await _rows(s, """
        select * from canon_macro_observation where knowable_at < :as_of
          and series_code like :p order by observation_date, series_code""",
                       "macro observation", as_of, p=series_prefix + "%")


async def global_bars(s: AsyncSession, instrument_key: str, as_of: _dt.datetime) -> list[dict]:
    return await _rows(s, """
        select * from canon_global_bar where instrument_key = :k and knowable_at < :as_of
        order by bar_start_utc""", "global bar", as_of, k=instrument_key)


async def coverage(s: AsyncSession, instrument_key: str, timeframe: str,
                   as_of: _dt.datetime) -> list[dict]:
    """Data-availability ranges AS THEY STOOD strictly before as_of: the
    materialized rules (coverage.session_state) applied only to Stage 1 facts
    that existed then — bars knowable before as_of (exactly what bars() returns),
    quarantines/windows of runs finished before as_of, the checkpoint of the
    latest run finished before as_of — over sessions dated before as_of's market
    date. So a backtest cannot learn from coverage that a later session traded,
    how many bars exist, or how a later ingestion ended. Meta data, no values."""
    if timeframe not in CANON_TIMEFRAMES:
        return [{"state": "OUT_OF_SCOPE", "timeframe": timeframe}]
    included = (await s.execute(text(
        "select 1 from canon_instrument where instrument_key = :k and included"),
        {"k": instrument_key})).first()
    if not included:
        return []
    as_of = to_utc(as_of)
    before = market_date(as_of)
    # the listing state in force at as_of, as far as it was knowable then: a
    # delisting known only later must not shorten a historical view
    life = (await s.execute(text("""
        select p.status, p.valid_from from instrument_lifecycle_period p
        join instrument i using (instrument_id)
        where i.instrument_key = :k and p.valid_from < :a and p.knowable_at < :a
        order by p.valid_from desc limit 1"""), {"k": instrument_key, "a": as_of})).first()
    end = session_cutoff(*life) if life else None
    if end is not None:
        before = min(before, end)
    sessions = list((await s.execute(text(
        "select session_date from trading_session where is_trading_day "
        "and session_date >= :a and session_date < :b order by 1"),
        {"a": depth_start(timeframe, now().astimezone(IST).date()), "b": before})).scalars())
    bars_, quar, wins, cps = await _stage1_inputs(s, timeframe, {instrument_key}, as_of)
    out = [{"instrument_key": instrument_key, "timeframe": timeframe, "as_of": as_of,
            "from_date": r.from_date, "to_date": r.to_date, "state": r.state,
            "sessions": r.sessions, "bars": r.bars, "quarantined": r.quarantined}
           for r in COV.ranges(sessions, bars=bars_.get(instrument_key, {}),
                               quarantined=quar.get(instrument_key, {}),
                               windows=wins.get(instrument_key, []),
                               checkpoint=cps.get(instrument_key))]
    if any(r["to_date"] >= before for r in out):          # defence in depth
        raise AssertionError(f"coverage {instrument_key} {timeframe} reaches {before}")
    return out


async def current_coverage(s: AsyncSession, instrument_key: str,
                           timeframe: str) -> list[dict]:
    """What Stage 1 holds NOW (the materialized canon_coverage), for live use
    and operations. NOT point-in-time: it reflects ingestion done after any
    historical instant, so a backtest must use coverage(..., as_of)."""
    if timeframe not in CANON_TIMEFRAMES:
        return [{"state": "OUT_OF_SCOPE", "timeframe": timeframe}]
    return [dict(r) for r in (await s.execute(text("""
        select c.* from canon_coverage c join canon_instrument ci using (instrument_id)
        where ci.instrument_key = :k and c.timeframe = :tf order by c.from_date"""),
        {"k": instrument_key, "tf": timeframe})).mappings().all()]


async def context(s: AsyncSession, instrument_key: str, as_of: _dt.datetime, *,
                  last_daily: int = 250) -> dict[str, Any]:
    """Everything knowable about one instrument at as_of (no indicators)."""
    return {
        "as_of": to_utc(as_of).isoformat(), "instrument_key": instrument_key,
        "daily_bars": await bars(s, instrument_key, "1d", as_of, limit=last_daily),
        "corporate_actions": await corporate_actions(s, as_of, instrument_key),
        "news": await news(s, as_of, instrument_key),
        "fundamentals": await fundamentals(s, instrument_key, as_of),
        "sector": await sector(s, instrument_key, as_of),
    }
