"""M4.0 — the candle contract. PURE: no network, no database.

Everything here is either MEASURED (2026-09-23, archived probes under
var/archive/UPSTOX_REST_V3/2026/09/23, see docs) or a DECISION recorded with
its date. It builds on contracts.timeframe (VALID_TIMEFRAMES, upstox_interval,
session_date_for_intraday, validate_bar) and contracts.knowable
(for_intraday_bar, for_daily_bar) instead of redefining them.

1. REQUEST WINDOWS: how a date range must be split for
   GET /v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}.
2. COMPLETENESS: which returned candles may ever be persisted.
3. DAILY LABEL: session_date and the D4 key for 1D candles.
4. COVERAGE: every (instrument, timeframe, window) ends in exactly one named
   outcome; nothing is skipped silently.
5. IDENTITY / CONFLICT: when two observations of a bar are the same.
6. CHECKPOINT NAMING: the watermark stream for resumable runs.
"""

from __future__ import annotations

import datetime as _dt
import enum
from dataclasses import dataclass
from decimal import Decimal

from app.contracts.identity import GLOBAL_SEGMENTS
from app.contracts.knowable import BAR_WIDTH
from app.contracts.timeframe import VALID_TIMEFRAMES, session_date_for_intraday, upstox_interval
from app.core.clock import IST, ist_at, to_utc

# The M4 timeframes. D2 (vendor-fetched vs derived 5m/15m/1h) is undecided, so
# this lists what the vendor serves and the contract can validate, not what M4
# will fetch.
DAILY = "1d"
INTRADAY = ("1m", "5m", "15m", "1h")
M4_TIMEFRAMES = (*INTRADAY, DAILY)
assert set(M4_TIMEFRAMES) <= VALID_TIMEFRAMES

# ── 1. request windows ──────────────────────────────────────────────────────
class Span(str, enum.Enum):
    MONTH = "month"      # one calendar month
    QUARTER = "quarter"  # three consecutive calendar months
    DECADE = "decade"    # ten calendar years


@dataclass(frozen=True, slots=True)
class RequestLimit:
    span: Span
    earliest: _dt.date   # first date the vendor serves for this unit
    basis: str


# Measured 2026-09-23 against Upstox's own docs (upstox.com/developer/
# api-documentation/v3/get-historical-candle-data):
#   minutes 1..15: Jan-2022 served, Dec-2021 empty; 1 calendar month accepted,
#                  2 months -> 400 UDAPI1148
#   minutes >15:   a 3-month span (Jun..Aug) accepted
#   hours:         Jan-2022 served, Dec-2021 empty; Jun..Aug accepted,
#                  May..Aug -> 400 UDAPI1148
#   days:          2000-01-03 is the first bar, 1990s empty; 2000..2009 and a
#                  rolling 2016-09-24..2026-09-23 accepted; 2000..2026 -> 400
# Windows use only the SHAPES that were accepted: calendar months, three
# calendar months, ten calendar years.
_MINUTE_EARLIEST = _dt.date(2022, 1, 1)
_DAY_EARLIEST = _dt.date(2000, 1, 1)


def request_limit(timeframe: str) -> RequestLimit:
    unit, step = upstox_interval(timeframe)
    if unit == "minutes":
        span = Span.MONTH if step <= 15 else Span.QUARTER
        return RequestLimit(span, _MINUTE_EARLIEST, f"measured 2026-09-23: minutes/{step}")
    if unit == "hours":
        return RequestLimit(Span.QUARTER, _MINUTE_EARLIEST, f"measured 2026-09-23: hours/{step}")
    if unit == "days":
        return RequestLimit(Span.DECADE, _DAY_EARLIEST, "measured 2026-09-23: days/1")
    raise ValueError(f"{timeframe!r} ({unit}) is not an M4 timeframe")


@dataclass(frozen=True, slots=True)
class Window:
    from_date: _dt.date   # inclusive
    to_date: _dt.date     # inclusive

    def __post_init__(self) -> None:
        if self.to_date < self.from_date:
            raise ValueError(f"window ends before it starts: {self}")


def _month_start(d: _dt.date) -> _dt.date:
    return d.replace(day=1)


def _add_months(d: _dt.date, n: int) -> _dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return _dt.date(d.year + y, m + 1, 1)


def _span_end(start: _dt.date, span: Span) -> _dt.date:
    """Last date of the span that starts on the aligned `start`."""
    if span is Span.MONTH:
        return _add_months(start, 1) - _dt.timedelta(days=1)
    if span is Span.QUARTER:
        return _add_months(start, 3) - _dt.timedelta(days=1)
    return _dt.date(start.year + 10, 1, 1) - _dt.timedelta(days=1)


def _span_start(d: _dt.date, span: Span) -> _dt.date:
    if span is Span.DECADE:
        return _dt.date(d.year - d.year % 10, 1, 1)
    return _month_start(d)


@dataclass(frozen=True, slots=True)
class WindowPlan:
    timeframe: str
    windows: tuple[Window, ...]
    # the part of the requested range before the vendor's earliest date: never
    # requested, but still reported (outcome BEFORE_AVAILABILITY)
    unavailable: Window | None


def plan_windows(timeframe: str, start: _dt.date, end: _dt.date) -> WindowPlan:
    """Split [start, end] into request windows of an accepted shape.

    Deterministic, contiguous, non-overlapping, oldest first. Month and
    quarter windows begin on the 1st of a month; decade windows on a year
    ending in 0. The first and last windows are clipped to the range.
    """
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    lim = request_limit(timeframe)
    unavailable = None
    if start < lim.earliest:
        unavailable = Window(start, min(end, lim.earliest - _dt.timedelta(days=1)))
        start = lim.earliest
    windows: list[Window] = []
    cur = start
    while cur <= end:
        aligned = _span_start(cur, lim.span)
        stop = min(_span_end(aligned, lim.span), end)
        windows.append(Window(cur, stop))
        cur = stop + _dt.timedelta(days=1)
    return WindowPlan(timeframe, tuple(windows), unavailable)


# ── 2. completeness ─────────────────────────────────────────────────────────
# Measured 2026-09-23 (3,117 polls, 3 instruments, 14:34-15:40 IST):
#   1m   never served while forming; a closed bar appears 6-36 s after its end
#        and never changed afterwards (177 bars)
#   5m   SERVED WHILE FORMING; 2 of 42 bars still changed up to 30.9 s after
#        their end (they are built from 1m bars that arrive late)
#   15m, 1h served while forming; none changed after their end
# So a bar is persistable only once its end is behind us by a margin. 120 s is
# about 3x the largest lag seen. ONE session: UNVERIFIED (B2).
COMPLETION_MARGIN = _dt.timedelta(seconds=120)
COMPLETION_MARGIN_BASIS = "UNVERIFIED (B2): 3x the 36 s max lag seen on 2026-09-23, one session"


class BarState(str, enum.Enum):
    COMPLETE = "COMPLETE"       # may be persisted
    FORMING = "FORMING"         # archived only; a later fetch will persist it
    SETTLING = "SETTLING"       # ended, but within COMPLETION_MARGIN: archived only


def bar_width(timeframe: str) -> _dt.timedelta:
    if timeframe == DAILY:
        raise ValueError("a daily bar has no fixed width; use daily_state()")
    try:
        return BAR_WIDTH[timeframe]
    except KeyError:
        raise ValueError(f"unknown intraday timeframe {timeframe!r}") from None


def intraday_state(bar_start: _dt.datetime, timeframe: str,
                   fetched_at: _dt.datetime) -> BarState:
    end = to_utc(bar_start) + bar_width(timeframe)
    fetched = to_utc(fetched_at)
    if end > fetched:
        return BarState.FORMING
    if end + COMPLETION_MARGIN > fetched:
        return BarState.SETTLING
    return BarState.COMPLETE


# B1, measured 2026-09-23: the historical endpoint did not serve the session's
# daily bar at all up to 17:30 IST. The intraday endpoint's daily bar kept
# changing until ~16:02 IST (close adjusted at 15:52, volume growing). So a
# daily bar is complete only if fetched on a LATER IST date than its session,
# and only from the historical endpoint. ONE session: UNVERIFIED (B1).
DAILY_COMPLETION_BASIS = ("UNVERIFIED (B1): only when fetched on a later IST date than the "
                          "session; 2026-09-23 daily bar changed until ~16:02 IST")


# Global instruments (GLOBAL_INDEX / GLOBAL_INDICATOR) are labelled with their
# own trading date, but their sessions end after NSE's day: US indices close
# ~01:30-02:30 IST on D+1, and oil/FX/Dow futures trade until ~03:30 IST.
# "Fetched on a later IST date" would call a still-open US bar complete at
# 00:30 IST. So a global daily bar is complete only from D+1 12:00 IST,
# 8.5 h after the latest listed close (global.json.gz end_time values).
GLOBAL_DAILY_COMPLETE_AT = _dt.time(12, 0)
GLOBAL_DAILY_COMPLETION_BASIS = ("global instrument: complete only from D+1 12:00 IST "
                                 "(latest listed close ~03:30 IST)")


def daily_state(session_date: _dt.date, fetched_at: _dt.datetime,
                segment: str | None = None) -> BarState:
    fetched_ist = to_utc(fetched_at).astimezone(IST)
    if segment in GLOBAL_SEGMENTS:
        cutoff = ist_at(session_date + _dt.timedelta(days=1), GLOBAL_DAILY_COMPLETE_AT)
        return BarState.COMPLETE if fetched_ist >= cutoff else BarState.FORMING
    return BarState.COMPLETE if fetched_ist.date() > session_date else BarState.FORMING


# ── 3. timestamps ───────────────────────────────────────────────────────────
class CandleTimestampError(ValueError):
    pass


def _parse_vendor_ts(raw: str) -> _dt.datetime:
    try:
        ts = _dt.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        raise CandleTimestampError(f"not an ISO-8601 timestamp: {raw!r}") from None
    if ts.tzinfo is None:
        raise CandleTimestampError(f"timestamp without an offset: {raw!r}")
    return ts


def intraday_bar_start(raw: str) -> tuple[_dt.datetime, _dt.date]:
    """(bar_start_utc, session_date) for an intraday candle. Upstox stamps the
    START of the bar (its docs; consistent with 1m->5m->1h aggregation)."""
    start = to_utc(_parse_vendor_ts(raw))
    return start, session_date_for_intraday(start)


# D4, decided 2026-09-23: a daily candle's bar_start_utc is its session_date at
# 00:00 IST. It is a KEY, never an instant anything became knowable
# (knowable_at comes from knowable.for_daily_bar). The vendor's label is kept
# verbatim in vendor_ts_raw: usually '<date>T00:00:00+05:30', but a listing day
# was seen as '2018-07-18T09:45:00+05:30'.
D4_DAILY_KEY_BASIS = "D4 (2026-09-23): session_date 00:00 IST as key; label kept verbatim"


def daily_session_date(raw: str) -> _dt.date:
    """The session a daily label names: its calendar date in IST."""
    return _parse_vendor_ts(raw).astimezone(IST).date()


def daily_bar_start(session_date: _dt.date) -> _dt.datetime:
    return to_utc(ist_at(session_date, _dt.time(0, 0)))


def aligned(bar_start: _dt.datetime, timeframe: str, session_open_ist: _dt.time) -> bool:
    """Does the bar start on the session's grid (open + k * width)?"""
    start = to_utc(bar_start).astimezone(IST)
    opened = ist_at(start.date(), session_open_ist)
    offset = (start - opened).total_seconds()
    return offset >= 0 and offset % bar_width(timeframe).total_seconds() == 0


# ── 4. coverage ─────────────────────────────────────────────────────────────
class WindowOutcome(str, enum.Enum):
    DATA = "DATA"                                # >= 1 candle returned
    EMPTY = "EMPTY"                              # 200 OK, zero candles: not listed / no
                                                 # trades / holiday / not yet published
    BEFORE_AVAILABILITY = "BEFORE_AVAILABILITY"  # never requested: older than the vendor serves
    VENDOR_ERROR = "VENDOR_ERROR"                # non-200, with the vendor's error code
    NOT_ATTEMPTED = "NOT_ATTEMPTED"              # run stopped (rate limit, crash) before it


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    """One per (instrument, timeframe, window). The sum over records accounts
    for every window a run planned, so an absence is always explainable."""

    instrument_key: str
    timeframe: str
    window: Window
    outcome: WindowOutcome
    returned: int = 0
    complete: int = 0
    forming: int = 0
    settling: int = 0
    invalid: int = 0
    payload_sha256: str | None = None
    vendor_error_code: str | None = None
    quarantined: int = 0            # Q1: value-insane vendor bars, never stored

    def __post_init__(self) -> None:
        n = self.complete + self.forming + self.settling + self.invalid + self.quarantined
        if n != self.returned:
            raise ValueError(f"coverage does not add up: {n} classified != {self.returned}")
        if (self.outcome is WindowOutcome.DATA) != (self.returned > 0):
            raise ValueError(f"outcome {self.outcome.value} with {self.returned} candles")
        if (self.outcome is WindowOutcome.VENDOR_ERROR) != (self.vendor_error_code is not None):
            raise ValueError("a VENDOR_ERROR carries an error code, and only it does")


# ── 5. identity and conflict ────────────────────────────────────────────────
# The observation key is ohlcv_bar's PK: (instrument_id, timeframe,
# session_date, bar_start_utc, source). Two observations with the same key are
# the same bar. They are the same OBSERVATION iff these values are equal;
# otherwise it is a conflict, which fails the run (the M1/M2 rule). Revisions
# are not stored until D3 is decided.
BAR_VALUE_FIELDS = ("open", "high", "low", "close", "volume", "open_interest")


def _n(v) -> Decimal | None:
    return None if v is None else Decimal(repr(v) if isinstance(v, float) else str(v)).normalize()


def same_observation(a: dict, b: dict) -> bool:
    return all(_n(a.get(f)) == _n(b.get(f)) for f in BAR_VALUE_FIELDS)


# ── 6. checkpoint naming ────────────────────────────────────────────────────
STREAM_MAX = 64   # ingest_watermark.stream varchar(64)


def watermark_stream(timeframe: str, instrument_key: str) -> str:
    """One watermark per (timeframe, instrument): a resumed backfill skips
    exactly the windows that instrument already completed."""
    if timeframe not in M4_TIMEFRAMES:
        raise ValueError(f"{timeframe!r} is not an M4 timeframe")
    s = f"ohlcv.{timeframe}.{instrument_key}"
    if len(s) > STREAM_MAX:
        raise ValueError(f"stream name {len(s)} > {STREAM_MAX}: {s!r}")
    return s
