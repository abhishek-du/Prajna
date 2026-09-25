"""Targeted warm-up planning (hardening: live first, warm-up on a feature contract).

The historical intraday backfill (~293k requests) is DEFERRED_FOR_STAGE_1.
When a later stage fixes a feature contract - "N completed sessions of
timeframe T" - only that depth is fetched, and only for the ACTIVE instruments
that do not already hold it. This module plans that fetch; it never calls the
vendor and never writes. The fetch itself is the ordinary, resumable

    prajna ingest candles --timeframe T --from F --to L --keys-file K --commit

(historical endpoint: the bars are VENDOR_ADJUSTED as of the fetch date and are
recorded so in ohlcv_payload_basis; the live closes keep adding RAW_OBSERVED
sessions).

Sessions come from trading_session (NORMAL / SPECIAL), never from a calendar
assumption. Request windows come from contracts.candles.plan_windows (the
measured vendor limits: one calendar month per request for minutes <= 15, three
consecutive calendar months for hours). Cost uses the documented 2,000 requests
/ 30 min per user.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.candles import plan_windows
from app.vendor.upstox.rest import DOCUMENTED_LIMITS

PER_30_MIN = next(n for n, s in DOCUMENTED_LIMITS if s == 1800.0)
SESSION_TYPES = ("NORMAL", "SPECIAL")


def window_for(sessions_desc: list[_dt.date], n: int) -> tuple[_dt.date, _dt.date]:
    """Pure. The first and last of the n most recent completed sessions."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if len(sessions_desc) < n:
        raise ValueError(f"only {len(sessions_desc)} completed sessions are known, {n} asked")
    return sessions_desc[n - 1], sessions_desc[0]


def cost(timeframe: str, start: _dt.date, end: _dt.date, instruments: int,
         fraction: float) -> dict[str, Any]:
    """Pure. Requests and wall-clock hours for one timeframe."""
    plan = plan_windows(timeframe, start, end)
    requests = instruments * len(plan.windows)
    per_hour = PER_30_MIN * 2 * fraction
    return {"windows": [[str(w.from_date), str(w.to_date)] for w in plan.windows],
            "windows_per_instrument": len(plan.windows), "instruments": instruments,
            "requests": requests, "hours_at_fraction": round(requests / per_hour, 2)}


async def plan(s: AsyncSession, *, sessions: int, timeframes: list[str], fraction: float,
               through: _dt.date | None = None) -> dict[str, Any]:
    """Read-only plan for 'N completed sessions of each timeframe'."""
    through = through or (await s.execute(text(
        "select max(session_date) from trading_session where session_type = any(:t) and "
        "session_date < (now() at time zone 'Asia/Kolkata')::date"),
        {"t": list(SESSION_TYPES)})).scalar()
    days = [d for (d,) in (await s.execute(text(
        "select session_date from trading_session where session_type = any(:t) and "
        "session_date <= :th order by session_date desc limit :n"),
        {"t": list(SESSION_TYPES), "th": through, "n": sessions})).all()]
    start, end = window_for(days, sessions)
    active = (await s.execute(text(
        "select count(*) from instrument where valid_to = 'infinity' and lifecycle_status = "
        "'ACTIVE' and segment in ('NSE_EQ', 'NSE_INDEX')"))).scalar()
    out: dict[str, Any] = {"sessions": sessions, "from": str(start), "to": str(end),
                           "active_instruments": active, "fraction": fraction,
                           "timeframes": {}, "vendor_calls": 0, "writes": 0}
    total = 0
    for tf in timeframes:
        # instruments that already hold a bar on every one of the N sessions
        held = (await s.execute(text("""
            select count(*) from (
              select b.instrument_id from ohlcv_bar b
              join instrument i on i.instrument_id = b.instrument_id
              where i.valid_to = 'infinity' and i.lifecycle_status = 'ACTIVE'
                and i.segment in ('NSE_EQ', 'NSE_INDEX') and b.timeframe = :tf
                and b.session_date = any(:days)
              group by b.instrument_id
              having count(distinct b.session_date) = :n) x"""),
            {"tf": tf, "days": days, "n": len(days)})).scalar()
        need = active - held
        c = cost(tf, start, end, need, fraction)
        c.update({"already_complete": held,
                  "command": (f"prajna ingest candles --timeframe {tf} --from {start} --to {end} "
                              f"--keys-file <ACTIVE keys lacking {tf}> --commit  "
                              f"(PRAJNA_UPSTOX_RATE_FRACTION={fraction}; outside 06:50-16:00 "
                              "on trading days; under the candles lock)")})
        out["timeframes"][tf] = c
        total += c["requests"]
    out["total_requests"] = total
    out["total_hours_at_fraction"] = round(total / (PER_30_MIN * 2 * fraction), 2)
    out["deferred_full_backfill_requests"] = "~293k (DEFERRED_FOR_STAGE_1; not planned here)"
    return out
