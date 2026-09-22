"""Bar grid and, crucially, the session date.

THE RULE THAT DEFINES V2's MARKET DATA:

    session_date is STORED, never derived from a timestamp.

V1 derived it (`timestamp::date`) and the result was 14 distinct daily anchors
in one table, 1,106,322 duplicated symbol-days, and 79,617 of those disagreeing
on the close. The fix is not a better derivation — it is to stop deriving.

The second rule: `source` participates in the primary key, so two vendors can
hold different observations of the same bar without one overwriting the other.
Conflict resolution is a Stage 2 read-time concern with an explicit precedence,
not a silent race at write time.
"""

from __future__ import annotations

import datetime as _dt

from app.core.clock import IST, to_utc

VALID_TIMEFRAMES = frozenset({"1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d", "1wk", "1mo"})

# Upstox v3 historical-candle path is /{unit}/{step}, not a query parameter.
# Verified against V1's proven caller (crawler/upstox_candles.py:43-54).
UPSTOX_INTERVAL: dict[str, tuple[str, int]] = {
    "1m": ("minutes", 1), "3m": ("minutes", 3), "5m": ("minutes", 5),
    "10m": ("minutes", 10), "15m": ("minutes", 15), "30m": ("minutes", 30),
    "1h": ("hours", 1), "1d": ("days", 1), "1wk": ("weeks", 1), "1mo": ("months", 1),
}


def upstox_interval(timeframe: str) -> tuple[str, int]:
    """Map a timeframe to Upstox's (unit, step).

    Raises on an unknown timeframe. V1 used
    `_INTERVAL_MAP.get(interval, _INTERVAL_MAP["1d"])`, so a typo silently
    returned DAILY bars labelled with the typo. A KeyError is the correct
    outcome; a wrong default is not.
    """
    try:
        return UPSTOX_INTERVAL[timeframe]
    except KeyError:
        raise ValueError(
            f"unknown timeframe {timeframe!r}; refusing to fall back to a default interval"
        ) from None


def session_date_for_intraday(bar_start: _dt.datetime) -> _dt.date:
    """The IST session an intraday bar belongs to.

    Explicit and total: the bar's IST calendar date. NSE equity sessions do not
    cross midnight IST, so this is exact for every regular and special session.
    """
    return to_utc(bar_start).astimezone(IST).date()


def validate_bar(
    open_: float, high: float, low: float, close: float, volume: float
) -> None:
    """OHLC sanity, enforced at write time AND by a table CHECK constraint."""
    if high < low:
        raise ValueError(f"high {high} < low {low}")
    if not (low <= open_ <= high):
        raise ValueError(f"open {open_} outside [{low}, {high}]")
    if not (low <= close <= high):
        raise ValueError(f"close {close} outside [{low}, {high}]")
    if volume < 0:
        raise ValueError(f"negative volume {volume}")
