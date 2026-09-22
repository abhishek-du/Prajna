"""One source of 'now', and one definition of the IST market day.

V1 read the clock in at least four different ways (`datetime.now()`,
`datetime.utcnow()`, `datetime.now(_IST)`, and a DB `now()`), which is how a
UTC column came to be compared against an IST wall clock in the Step-2C audit
and produced a wrong conclusion about which writer created a row.

Everything here is tz-aware. This module never returns a naive datetime.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = _dt.timezone.utc

# NSE regular equity session, IST. Muhurat and Budget-day sessions differ and
# are carried per-session in the trading_session table, never assumed here.
REGULAR_PREOPEN_START = _dt.time(9, 0)
REGULAR_PREOPEN_END = _dt.time(9, 15)
REGULAR_OPEN = _dt.time(9, 15)
REGULAR_CLOSE = _dt.time(15, 30)

_frozen: _dt.datetime | None = None


def now() -> _dt.datetime:
    """Current instant, tz-aware UTC. The only clock read in the application."""
    return _frozen if _frozen is not None else _dt.datetime.now(UTC)


def now_ist() -> _dt.datetime:
    return now().astimezone(IST)


def freeze(at: _dt.datetime) -> None:
    """Pin the clock. Tests only; refuses a naive datetime."""
    global _frozen
    if at.tzinfo is None:
        raise ValueError("freeze() requires a tz-aware datetime")
    _frozen = at.astimezone(UTC)


def unfreeze() -> None:
    global _frozen
    _frozen = None


def to_utc(value: _dt.datetime) -> _dt.datetime:
    """Normalise to tz-aware UTC. A naive input is an error, never an assumption.

    V1 stored every market timestamp as TIMESTAMP WITHOUT TIME ZONE and then
    disagreed with itself about what zone they were in.
    """
    if value.tzinfo is None:
        raise ValueError(f"naive datetime rejected: {value!r} (declare its zone)")
    return value.astimezone(UTC)


def ist_date_of(value: _dt.datetime) -> _dt.date:
    """The IST calendar date an instant falls on."""
    return to_utc(value).astimezone(IST).date()


def epoch_ms_to_utc(ms: int) -> _dt.datetime:
    """Upstox feed timestamps (FeedResponse.currentTs, LTPC.ltt) are epoch ms."""
    return _dt.datetime.fromtimestamp(ms / 1000.0, tz=UTC)


def ist_at(day: _dt.date, at: _dt.time) -> _dt.datetime:
    """Build a tz-aware IST instant from an NSE session date and a wall time."""
    return _dt.datetime.combine(day, at, tzinfo=IST)
