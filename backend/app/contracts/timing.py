"""Timing finality of intraday candles (B2, revised 2026-09-25). Pure.

ORIGINAL B2 (set 2026-09-23, before measurement):
    "1m bars never change once listed; other timeframes settle inside one
    120 s completion margin."
FINDING (2026-09-25, ops/measure/candle_timing.py, archived responses):
    90 of 1,125 NSE_INDEX|Nifty 50 1m bars were revised after first listing
    (close; twice low+close), latest 95.6 s after the bar end. RELIANCE and
    HDFCBANK: none. 15m settled up to 110.9 s, 1h up to 111.0 s, 5m (out of
    scope) up to 145.9 s after the end.
REVISED B2 (user decision TIMING-B2, 2026-09-25):
    A candle is timing-final only from bar_end + completion_margin(timeframe).
    The margin is an ENGINEERING THRESHOLD - chosen from observation,
    configurable per timeframe, monitored - NOT a vendor guarantee. Any
    revision later than the margin is a LATE_REVISION: it is recorded,
    contradicts the contract (acceptance X BLOCKED) and requires an explicit
    contract review. The margin is never enlarged silently.

Timing finality is NOT point-in-time knowledge. "When may this candle be
regarded as settled?" (bar_end + margin) is a different question from "when
did Prajna know its value?" (the fetch time: contracts.knowable). A 10:00-10:01
bar is timing-final at 10:03, but if it was fetched at 16:05 its knowable_at
is 16:05. Nothing in this module produces a knowable_at.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from app.contracts.candles import bar_width

BASIS = ("engineering threshold chosen from observation (2026-09-24/25: 1m <= 95.6 s, "
         "15m <= 110.9 s, 1h <= 111.0 s after the bar end); configurable per timeframe; "
         "monitored by ops/measure/analyze_timing.py; NOT a vendor SLA")

# seconds after the bar END; in-scope timeframes only carry a validated margin
COMPLETION_MARGIN_S: dict[str, float] = {"1m": 120.0, "15m": 120.0, "1h": 120.0}
IN_SCOPE = frozenset(COMPLETION_MARGIN_S)
# 5m is OUT_OF_SCOPE (decision D2-5m). It keeps an operational margin for ad-hoc
# ingestion, explicitly NOT validated: 145.9 s was observed on 2026-09-25.
OUT_OF_SCOPE_MARGIN_S: dict[str, float] = {"5m": 120.0}


def margin(timeframe: str) -> _dt.timedelta:
    s = COMPLETION_MARGIN_S.get(timeframe, OUT_OF_SCOPE_MARGIN_S.get(timeframe))
    if s is None:
        raise ValueError(f"no completion margin for timeframe {timeframe!r}")
    return _dt.timedelta(seconds=s)


def final_at(bar_start: _dt.datetime, timeframe: str) -> _dt.datetime:
    """The instant from which the candle may be regarded as settled."""
    return bar_start + bar_width(timeframe) + margin(timeframe)


def is_final(bar_start: _dt.datetime, timeframe: str, at: _dt.datetime) -> bool:
    return at >= final_at(bar_start, timeframe)


@dataclass(frozen=True, slots=True)
class Revision:
    """A later observation of a candle that differs from an earlier one."""
    timeframe: str
    seconds_after_end: float     # when the different value was first seen

    @property
    def late(self) -> bool:
        """Revised after the margin: contradicts the contract."""
        return self.seconds_after_end >= margin(self.timeframe).total_seconds()

    @property
    def in_scope(self) -> bool:
        return self.timeframe in IN_SCOPE


def headroom_s(timeframe: str, observed_max_s: float | None) -> float | None:
    if observed_max_s is None:
        return None
    return round(margin(timeframe).total_seconds() - observed_max_s, 1)
