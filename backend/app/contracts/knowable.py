"""When did a fact become knowable?

This is the single most important contract in V2. It is promoted from V1's
`scripts/phase5_causality.py`, where it existed only inside a research script
and therefore protected nothing in production.

The insight it encodes, restated:

    A bar's LABEL is not when the bar became known.

An NSE daily bar labelled 2026-09-01 describes the whole session. It cannot be
acted on at 09:15; it is complete only at the close. Comparing the label against
a decision time T and concluding "label < T, therefore safe" is exactly the
look-ahead that put the next session's close into V1's beta, Sharpe, Treynor and
Jensen figures across 2,276 symbol/date pairs.

THE FOUR TIMES — every ingested row must be able to answer all four:

    event_time   the instant the fact refers to        (session date, bar start, ex-date)
    vendor_time  the instant the vendor reports        (currentTs, ISO string, lastUpdateTime)
    fetched_at   the instant we received it            (our wall clock)
    knowable_at  the earliest instant it could be acted on

CONSTRAINT #9 — knowable_at is NEVER INVENTED. Where it cannot be derived from
evidence, `verified=False` is returned with the conservative bound (fetched_at,
which can never be too early), and the gap is reported as an open unknown. A
conservative bound loses opportunities; an optimistic one fabricates profit.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from app.core.clock import IST, ist_at, to_utc

# ── NSE regular session geometry ────────────────────────────────────────────
SESSION_CLOSE_IST = _dt.time(15, 30)
SESSION_OPEN_IST = _dt.time(9, 15)

BAR_WIDTH: dict[str, _dt.timedelta] = {
    "1m": _dt.timedelta(minutes=1),
    "3m": _dt.timedelta(minutes=3),
    "5m": _dt.timedelta(minutes=5),
    "10m": _dt.timedelta(minutes=10),
    "15m": _dt.timedelta(minutes=15),
    "30m": _dt.timedelta(minutes=30),
    "1h": _dt.timedelta(hours=1),
}

# A price must also be recent enough to mean anything. V1 learned this the hard
# way: an unbounded "latest bar before T" search returned a bar from days
# earlier for a symbol with no intraday coverage. Not look-ahead, but just as
# wrong. Readers bound their searches by this.
MAX_PRICE_AGE = _dt.timedelta(days=5)


@dataclass(frozen=True, slots=True)
class Knowable:
    """A knowable_at decision, with its provenance.

    `verified` False means: this is a conservative fallback, not a measurement.
    It is persisted alongside the row so downstream code can tell the difference
    instead of assuming.
    """

    at: _dt.datetime
    verified: bool
    basis: str

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("Knowable.at must be tz-aware")


# ── Per-datatype rules ──────────────────────────────────────────────────────

def for_preopen_tick(vendor_ts: _dt.datetime) -> Knowable:
    """Pre-open WebSocket frame.

    VERIFIED. This is a live push stream: Upstox stamps FeedResponse.currentTs
    at emission and we hold the frame immediately after. There is no
    publication lag to measure — the vendor time IS the knowable time.
    """
    return Knowable(to_utc(vendor_ts), True, "upstox_ws_v3.currentTs (live push)")


def for_preopen_status(vendor_updated_at: _dt.datetime) -> Knowable:
    """MarketInfo.preOpenSessionStatus transition. Same reasoning as above."""
    return Knowable(to_utc(vendor_updated_at), True, "upstox_ws_v3.StatusInfo.updatedTime")


def for_daily_bar(
    session_date: _dt.date,
    fetched_at: _dt.datetime,
    *,
    close_ist: _dt.time = SESSION_CLOSE_IST,
    settlement_lag_verified: bool = False,
) -> Knowable:
    """NSE daily OHLCV bar.

    V1 asserted the bar is complete at the close (15:30 IST / 10:00 UTC). That
    is the right SHAPE — it is emphatically not the bar's own label — but the
    exact instant is UNMEASURED (open blocker B1): we have not established
    whether Upstox finalises the daily bar at the close or revises it after
    post-close settlement.

    So until the M4 measurement harness settles it, this returns the
    conservative bound (fetched_at, never earlier than the close) with
    verified=False. It refuses to pretend to a precision we have not earned.
    """
    at_close = to_utc(ist_at(session_date, close_ist))
    fetched = to_utc(fetched_at)
    if settlement_lag_verified:
        return Knowable(at_close, True, f"session close {close_ist} IST (measured)")
    return Knowable(
        max(at_close, fetched),
        False,
        "UNVERIFIED (B1): conservative max(session_close, fetched_at); "
        "settlement finalisation lag not yet measured",
    )


def for_intraday_bar(
    bar_start: _dt.datetime,
    timeframe: str,
    fetched_at: _dt.datetime,
    *,
    publication_lag_verified: bool = False,
) -> Knowable:
    """Intraday OHLCV bar.

    Lower bound is bar_start + bar_width: a 1m bar labelled 09:15 is not
    complete until 09:16. The vendor's publication lag ON TOP of that is
    UNMEASURED (open blocker B2), so unverified rows take the conservative
    bound.
    """
    width = BAR_WIDTH.get(timeframe)
    if width is None:
        raise ValueError(f"unknown timeframe {timeframe!r}; refusing to guess its width")
    bar_end = to_utc(bar_start) + width
    if publication_lag_verified:
        return Knowable(bar_end, True, f"bar_start + {timeframe} (lag measured)")
    return Knowable(
        max(bar_end, to_utc(fetched_at)),
        False,
        f"UNVERIFIED (B2): conservative max(bar_end, fetched_at) for {timeframe}; "
        "vendor publication lag not yet measured",
    )


def for_snapshot_download(fetched_at: _dt.datetime) -> Knowable:
    """A dump that carries no publication time of its own.

    The Upstox instrument master is the case in point: NSE.json.gz has no
    valid_from and no generated-at header, so the earliest instant we can
    honestly claim to know it is when we downloaded it. Documented limitation,
    not an assumption.
    """
    return Knowable(to_utc(fetched_at), False,
                    "no vendor publication time in payload; fetched_at is the honest bound")


def for_announced_fact(
    announced_at: _dt.datetime | None, fetched_at: _dt.datetime, *, what: str
) -> Knowable:
    """Corporate actions, fundamentals, news, calendar — anything published.

    If the vendor supplies a publication/announcement instant we use it and mark
    it verified. If it does not, we fall back to fetched_at and say so. We never
    substitute the EVENT time (ex-date, period_end) for the KNOWABLE time: a
    result for the quarter ending 30-Jun is not knowable on 30-Jun.
    """
    if announced_at is not None:
        return Knowable(to_utc(announced_at), True, f"{what}: vendor announcement time")
    return Knowable(to_utc(fetched_at), False,
                    f"{what}: vendor supplied no announcement time; fetched_at used")


def for_announcement_date(
    announced_on: _dt.date, fetched_at: _dt.datetime, *, what: str
) -> Knowable:
    """A fact whose vendor announcement is a DATE without a time (Upstox
    corporate actions). Decision KN-CA (user, 2026-09-24): knowable at the END
    of that IST day, 23:59:59.999, a conservative upper bound (the announcement
    happened at some instant of that day), never later than when we held it.
    Unverified: the vendor date itself is not independently confirmed."""
    end_of_day = to_utc(ist_at(announced_on, _dt.time(23, 59, 59, 999000)))
    fetched = to_utc(fetched_at)
    if end_of_day <= fetched:
        return Knowable(end_of_day, False,
                        f"{what}: announcement DATE only; end of that IST day (KN-CA)")
    return Knowable(fetched, False,
                    f"{what}: announcement DATE is the fetch day or later; fetched_at used")


# ── Read-side guard ─────────────────────────────────────────────────────────

class LookAheadViolation(Exception):
    """A read asked for a fact that was not knowable at the decision time."""


def assert_knowable_before(
    knowable_at: _dt.datetime, decision_time: _dt.datetime, what: str
) -> None:
    """Strictly `<`.

    A fact knowable exactly at T is not usable AT T. V1's guard made the same
    choice and it is the correct one — the alternative silently admits the
    boundary case, which is where most look-ahead lives.
    """
    k, t = to_utc(knowable_at), to_utc(decision_time)
    if k >= t:
        raise LookAheadViolation(
            f"LOOK-AHEAD: {what} became knowable at {k.astimezone(IST)} IST "
            f"but the decision time is {t.astimezone(IST)} IST"
        )
