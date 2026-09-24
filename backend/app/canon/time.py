"""Stage 2 timestamp rules, in ONE place, built on the Stage 1 contracts.

Three times, never confused:
  event     when it happened in the market: a bar's [event_start, event_end),
            a pre-open frame's vendor_ts, a corporate action's announcement
            DATE, an article's published_time, a statement's period_end
  knowable  when Prajna may first USE it (contracts.knowable; B1/B2, P1,
            KN-CA, for_announced_fact). knowable_at <= fetched_at, always
  fetched   when Prajna held the bytes (local receipt)

Daily bars keep decision D4: the label is session_date 00:00 IST, the event
is the session (open..close IST from trading_session), and it is knowable
only after the session (for_daily_bar). A daily bar is never "at 09:15".
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from typing import Any

from app.contracts.knowable import BAR_WIDTH, LookAheadViolation, assert_knowable_before
from app.core.clock import IST, ist_at, to_utc

__all__ = ["DAILY", "LookAheadViolation", "assert_all_knowable", "event_window",
           "is_knowable", "market_date"]

DAILY = "1d"


def market_date(ts: _dt.datetime) -> _dt.date:
    """The NSE market date of an instant: its calendar date in IST."""
    return to_utc(ts).astimezone(IST).date()


def event_window(timeframe: str, *, session_date: _dt.date, bar_start: _dt.datetime,
                 open_ist: _dt.time | None, close_ist: _dt.time | None
                 ) -> tuple[_dt.datetime | None, _dt.datetime | None]:
    """[event_start, event_end) of a bar, the same rule as view canon_market_bar.
    Daily: the session's hours (None when unknown, e.g. a past special session).
    Intraday: bar_start + width, capped at the session close."""
    if timeframe == DAILY:
        if open_ist is None or close_ist is None:
            return None, None
        return to_utc(ist_at(session_date, open_ist)), to_utc(ist_at(session_date, close_ist))
    start = to_utc(bar_start)
    end = start + BAR_WIDTH[timeframe]
    if close_ist is not None:
        end = min(end, to_utc(ist_at(session_date, close_ist)))
    return start, end


def is_knowable(knowable_at: _dt.datetime, as_of: _dt.datetime) -> bool:
    """Strictly before: a fact knowable exactly AT T is not usable at T
    (same rule as contracts.knowable.assert_knowable_before)."""
    return to_utc(knowable_at) < to_utc(as_of)


def assert_all_knowable(rows: Iterable[Any], as_of: _dt.datetime, what: str,
                        field: str = "knowable_at") -> None:
    """Defence in depth for every point-in-time read: re-check each row."""
    for r in rows:
        k = r[field] if isinstance(r, dict) else getattr(r, field)
        assert_knowable_before(k, as_of, what)
