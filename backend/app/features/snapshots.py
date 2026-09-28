"""Snapshot instants (decision FEATURE-SNAPSHOTS), from the trading calendar.

  PRE_SESSION  as_of = pre-open start - 1 s   (08:59:59 IST on a normal session)
  PRE_OPEN     as_of = pre-open start + 8 min (09:08:00 IST): the pre-open order
               book is complete and matched; the session has not opened
A session without a pre-open window (e.g. some special sessions) has no
PRE_OPEN snapshot and its PRE_SESSION instant is the open - 1 s. A
non-trading day has no snapshot at all. Nothing here is assumed: the times
come from trading_session.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST

SNAPSHOTS = ("PRE_SESSION", "PRE_OPEN")


class NoSnapshot(ValueError):
    """The requested snapshot does not exist for that date (never guessed)."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    session_date: _dt.date
    kind: str
    as_of: _dt.datetime            # UTC, tz-aware
    previous_session: _dt.date | None


def as_of_for(session_date: _dt.date, kind: str, *, preopen_start: _dt.time | None,
              open_time: _dt.time | None) -> _dt.datetime:
    """Pure: the snapshot instant for a trading session's calendar times."""
    if kind not in SNAPSHOTS:
        raise NoSnapshot(f"unknown snapshot {kind!r}")
    if preopen_start is not None:
        base = _dt.datetime.combine(session_date, preopen_start, tzinfo=IST)
        at = base - _dt.timedelta(seconds=1) if kind == "PRE_SESSION" \
            else base + _dt.timedelta(minutes=8)
    elif kind == "PRE_OPEN":
        raise NoSnapshot(f"{session_date}: no pre-open window, so no PRE_OPEN snapshot")
    elif open_time is not None:
        at = _dt.datetime.combine(session_date, open_time, tzinfo=IST) - _dt.timedelta(seconds=1)
    else:
        raise NoSnapshot(f"{session_date}: the calendar has no open time")
    return at.astimezone(_dt.UTC)


async def resolve(s: AsyncSession, session_date: _dt.date, kind: str) -> Snapshot:
    row = (await s.execute(text("""select is_trading_day, preopen_start_ist, open_ist
        from trading_session where session_date = :d"""), {"d": session_date})).first()
    if row is None:
        raise NoSnapshot(f"{session_date}: no calendar entry")
    if not row.is_trading_day:
        raise NoSnapshot(f"{session_date}: not a trading day")
    prev = (await s.execute(text("""select max(session_date) from trading_session
        where is_trading_day and session_date < :d"""), {"d": session_date})).scalar()
    return Snapshot(session_date, kind, as_of_for(session_date, kind,
                    preopen_start=row.preopen_start_ist, open_time=row.open_ist), prev)


async def sessions_between(s: AsyncSession, start: _dt.date, end: _dt.date) -> list[_dt.date]:
    return list((await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date between :a and :b order by 1"""),
        {"a": start, "b": end})).scalars())
