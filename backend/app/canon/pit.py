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


async def bars_adjusted(s: AsyncSession, instrument_key: str, timeframe: str,
                        as_of: _dt.datetime, *, start: _dt.date | None = None,
                        end: _dt.date | None = None, allow_reconstructed: bool = False,
                        allow_low_confidence: bool = False) -> dict[str, Any]:
    """Split/bonus-adjusted bars AS A TRADER KNEW THEM at as_of (phase 7).

    For each bar knowable before as_of (the same rows as bars()):
      target = product of EXACT factors F (canon_ca_factor) with  bar_date <
               ex_date <= market date of as_of  AND  knowable_at < as_of, where a
               factor is knowable when Prajna OBSERVED its action (CA-OBSERVED,
               migration 0018: greatest(announcement end of day, fetched_at))
      baked  = product of F the vendor already applied to the stored value
               (vendor_applied = APPLIED, bar_date < ex_date <= the payload's
               basis_as_of), EXCEPT in a payload of which the vendor later re-served a
               bar adjusted by exactly F (a CA_ADJUSTMENT observation naming the
               action): that payload was fetched before the vendor applied F, so F is
               in none of its bars (F3-PAYLOAD-BASIS: BLSE's history, fetched on the
               ex-date morning; only its last 4 bars were later re-served);
               RAW_OBSERVED payloads bake nothing
      net    = target / baked:   1 -> as stored (AS_STORED)
                                >1 -> price / net, volume * net (ADJUSTED, exact)
                                <1 -> the stored value contains an action NOT yet
                                      knowable at as_of: undoing it multiplies a
                                      rounded vendor value (RECONSTRUCTED,
                                      approximate) -> refused unless
                                      allow_reconstructed
    LOW confidence (refused unless allow_low_confidence): a vendor-adjusted row
    older than the corporate-action horizon (the earliest ex-date among actions
    knowable before as_of; earlier events are unknown; no action knowable at all:
    every vendor-adjusted row), an
    UNKNOWN vendor treatment inside (bar, basis_as_of], or no recorded basis.
    A future corporate action can never change what an earlier as_of sees.
    """
    from decimal import Decimal

    rows = await bars(s, instrument_key, timeframe, as_of, start=start, end=end)
    as_of_u = to_utc(as_of)
    day = market_date(as_of_u)
    basis = {r[0]: (r[1], r[2]) for r in (await s.execute(text(
        "select payload_sha256, price_basis, basis_as_of from ohlcv_payload_basis "
        "where payload_sha256 = any(:h)"),
        {"h": list({r["payload_sha256"] for r in rows})})).all()}
    events = [dict(e) for e in (await s.execute(text("""
        select ca_id, ex_date, factor_price, knowable_at, vendor_applied from canon_ca_factor
        where instrument_key = :k and status = 'EXACT' and ex_date is not null
        order by ex_date"""), {"k": instrument_key})).mappings().all()]
    horizon = (await s.execute(text("""select min(ex_date) from canon_corporate_action
        where knowable_at < :a"""), {"a": as_of_u})).scalar()
    # (payload, action) pairs: the vendor later re-served a bar of that stored payload
    # adjusted by the action's factor, so when the payload was fetched the vendor had
    # not applied the action yet - every bar of that payload is raw for it
    raw_for = {(r[0], int(r[1])) for r in (await s.execute(text("""
        select distinct b.payload_sha256,
               jsonb_array_elements_text(o.explained_by -> 'ca_ids')
        from ohlcv_observation o
        join ohlcv_bar b on b.instrument_id = o.instrument_id and b.timeframe = o.timeframe
         and b.bar_start_utc = o.bar_start_utc and o.fetched_at > b.fetched_at
        where o.instrument_key = :k and o.timeframe = :tf
          and o.classification = 'CA_ADJUSTMENT'"""),
        {"k": instrument_key, "tf": timeframe})).all()}
    known = [e for e in events if e["ex_date"] <= day and e["knowable_at"] < as_of_u]
    out, refused = [], {"reconstructed": 0, "low_confidence": 0}
    for r in rows:
        bd = r["market_date"]
        pb, bas = basis.get(r["payload_sha256"], (None, None))
        target = Decimal(1)
        used = [e["ca_id"] for e in known if bd < e["ex_date"]]
        for e in known:
            if bd < e["ex_date"]:
                target *= Decimal(e["factor_price"])
        baked, low = Decimal(1), pb is None
        if pb == "VENDOR_ADJUSTED":
            for e in events:
                if bd < e["ex_date"] <= bas:
                    if e["vendor_applied"] == "APPLIED":
                        if (r["payload_sha256"], e["ca_id"]) not in raw_for:
                            baked *= Decimal(e["factor_price"])
                    elif e["vendor_applied"] == "UNKNOWN":
                        low = True
            low = low or horizon is None or bd < horizon
        net = target / baked
        status = "AS_STORED" if net == 1 else ("ADJUSTED" if net > 1 else "RECONSTRUCTED")
        if low and not allow_low_confidence:
            refused["low_confidence"] += 1
            continue
        if status == "RECONSTRUCTED" and not allow_reconstructed:
            refused["reconstructed"] += 1
            continue
        adj = dict(r)
        for f in ("open", "high", "low", "close"):
            adj[f] = (Decimal(str(r[f])) / net).quantize(Decimal("0.000001"))
        adj["volume"] = Decimal(str(r["volume"])) * net
        adj.update(adjustment_status=status, factor_applied=net, ca_ids_known=used,
                   price_basis=pb, basis_as_of=bas, basis_confidence="LOW" if low else "HIGH")
        out.append(adj)
    return {"as_of": as_of_u.isoformat(), "instrument_key": instrument_key,
            "timeframe": timeframe, "rows": out, "refused": refused,
            "events_known": [e["ca_id"] for e in known], "horizon": horizon}


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
    """The global labels that were FINAL at as_of, oldest first - the rules of the
    global_bar_finality view (migration 0010), each evaluated with only what was
    observed before as_of (F-GLOBAL-FINALITY, 2026-09-29):

      bar          first observation knowable before as_of
      REVISED      a GLOBAL_REVISION observation fetched before as_of -> withheld
                   (a revision seen later does not rewrite what as_of saw)
      PLACEHOLDER  flat and equal to the previous label's close with no volume,
                   the previous label among those knowable before as_of -> withheld
      CONFIRMED    an unchanged re-observation >= confirm_hours after the first,
                   fetched before as_of; knowable from that re-observation
      CONFIRMED_BY_AGE  first observed >= 4 days after the label date

    canon_global_bar is the same rules evaluated NOW (current state, for live use);
    it must not be filtered by knowable_at for a past as_of: a label revised after
    as_of would vanish from a past view (measured: DJI 2026-09-25, revised at
    2026-09-29 12:40 IST, changed a recompute of that morning's snapshot)."""
    return await _rows(s, """
        with g as (
          select b.instrument_id, i.instrument_key, i.trading_symbol, i.name, i.segment,
                 b.timeframe, b.session_date, b.bar_start_utc, b.open, b.high, b.low, b.close,
                 b.volume, b.knowable_at, b.knowable_at_verified, b.knowable_at_basis,
                 b.fetched_at, b.source, b.run_id, b.payload_sha256,
                 coalesce(c.confirm_hours, 6) as confirm_hours,
                 lag(b.close) over (partition by b.instrument_id order by b.session_date)
                   as prev_close
          from ohlcv_bar b
          join instrument i on i.instrument_id = b.instrument_id
          left join global_instrument_contract c on c.instrument_key = i.instrument_key
          where i.instrument_key = :k and i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR')
            and i.valid_to = 'infinity' and b.timeframe = '1d' and b.knowable_at < :as_of),
        f as (
          select g.*,
            exists (select 1 from ohlcv_observation o
                    where o.instrument_id = g.instrument_id and o.timeframe = '1d'
                      and o.bar_start_utc = g.bar_start_utc
                      and o.classification = 'GLOBAL_REVISION' and o.fetched_at < :as_of)
              as revised,
            (select min(o.fetched_at) from ohlcv_observation o
             where o.instrument_id = g.instrument_id and o.timeframe = '1d'
               and o.bar_start_utc = g.bar_start_utc and o.classification = 'REOBSERVED'
               and o.fetched_at >= g.fetched_at + make_interval(hours => g.confirm_hours)
               and o.fetched_at < :as_of) as conf_at,
            g.fetched_at >= ((g.session_date + 4)::timestamp at time zone 'Asia/Kolkata')
              as by_age,
            (g.open = g.high and g.high = g.low and g.low = g.close
             and g.close = g.prev_close and g.volume = 0) as placeholder
          from g)
        select instrument_id, instrument_key, trading_symbol, name, segment, timeframe,
               session_date as label_date, bar_start_utc, open, high, low, close, volume,
               greatest(knowable_at, coalesce(conf_at, fetched_at)) as knowable_at,
               knowable_at_verified,
               case when conf_at is not null
                    then 'confirmed by an unchanged re-observation; ' || knowable_at_basis
                    else knowable_at_basis end as knowable_at_basis,
               greatest(fetched_at, coalesce(conf_at, fetched_at)) as fetched_at,
               source, run_id, payload_sha256,
               case when conf_at is not null then 'CONFIRMED' else 'CONFIRMED_BY_AGE' end
                 as finality,
               coalesce(conf_at, fetched_at) as confirmed_at, fetched_at as first_fetched_at
        from f
        where not revised and not coalesce(placeholder, false)
          and (conf_at is not null or by_age)
          and greatest(knowable_at, coalesce(conf_at, fetched_at)) < :as_of
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
