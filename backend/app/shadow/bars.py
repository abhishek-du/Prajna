"""Intraday bar containers shared by the shadow modules (pure)."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from app.core.clock import IST


@dataclass(frozen=True)
class IBar:
    start: _dt.datetime          # UTC, aware
    end: _dt.datetime            # UTC, aware (event_end): knowable from this instant
    open: float
    high: float
    low: float
    close: float
    volume: float

    def ist_end(self) -> _dt.time:
        return self.end.astimezone(IST).time().replace(tzinfo=None)

    def ist_start(self) -> _dt.time:
        return self.start.astimezone(IST).time().replace(tzinfo=None)


@dataclass
class NameDay:
    """One instrument on session T: its 1m bars of T, its 15m bars of the previous
    sessions + T (oldest first), and its daily context (sessions <= T - 1)."""
    key: str
    m1: list[IBar]
    m15: list[IBar]
    m15_dates: list[_dt.date]                 # market date of each m15 bar
    prev_close: float | None
    ema50_1d: float | None = None
    adx14_1d: float | None = None
    median_volume_20d: float | None = None
    sector: str | None = None
    extra: dict = field(default_factory=dict)


def at(session: _dt.date, hhmm: str) -> _dt.datetime:
    """IST wall time on the session, as an aware UTC datetime."""
    h, m = (int(x) for x in hhmm.split(":"))
    return _dt.datetime.combine(session, _dt.time(h, m), tzinfo=IST).astimezone(_dt.timezone.utc)


def last_until(bars: list[IBar], t: _dt.datetime) -> IBar | None:
    """The last bar knowable at t (end <= t)."""
    out = None
    for b in bars:
        if b.end <= t:
            out = b
        else:
            break
    return out
