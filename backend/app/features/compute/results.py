"""Results-calendar and street-verdict features (features-v5; docs/STAGE3_FEATURES_V5.md).
Pure: events in (app.canon.results_pit, all knowable before as_of), results out.

  results_days_to_next   calendar days from the session to the next results board meeting
                         known at as_of (>= the session); per period only the LATEST
                         intimation counts (a postponed meeting replaces the earlier date)
  results_today          1 if such a meeting is on the session's date, else 0
  results_days_since     calendar days from the latest results dissemination (OUTCOME) to
                         the session
  street_verdict_90d     the latest street verdict of the 90 days before as_of: BEAT +1,
                         MISS -1, INLINE / MIXED 0
No coverage at as_of (the announcements source never ran before it) -> MISSING_INPUT.
With coverage, "nothing known" is NOT_APPLICABLE (no meeting scheduled, no verdict) - except
results_days_since inside its first 120 days of coverage, when an earlier dissemination may
simply predate the source: MISSING_INPUT.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Sequence
from typing import Any

from app.core.clock import IST
from app.features.compute import MISSING_INPUT, NOT_APPLICABLE, Result, miss, ok

SINCE_MIN_COVERAGE = _dt.timedelta(days=120)
VERDICT_WINDOW = _dt.timedelta(days=90)
VERDICT_SCORE = {"BEAT": 1.0, "MISS": -1.0, "INLINE": 0.0, "MIXED": 0.0}


def _covered(coverage_from: _dt.datetime | None, as_of: _dt.datetime) -> bool:
    return coverage_from is not None and coverage_from < as_of


def scheduled_meetings(events: Sequence[Any]) -> list[_dt.date]:
    """The meeting date of the latest-known intimation per period (period None: per date)."""
    latest: dict[Any, Any] = {}
    for e in events:
        if e.kind != "INTIMATION" or e.meeting_date is None:
            continue
        key = e.period_end or ("date", e.meeting_date)
        if key not in latest or (e.knowable_at, e.news_id) > (latest[key].knowable_at,
                                                             latest[key].news_id):
            latest[key] = e
    return sorted({e.meeting_date for e in latest.values()})


def days_to_next(events: Sequence[Any], session: _dt.date, coverage_from, as_of) -> Result:
    if not _covered(coverage_from, as_of):
        return miss(MISSING_INPUT)
    nxt = [d for d in scheduled_meetings(events) if d >= session]
    return ok(float((nxt[0] - session).days)) if nxt else miss(NOT_APPLICABLE)


def today(events: Sequence[Any], session: _dt.date, coverage_from, as_of) -> Result:
    if not _covered(coverage_from, as_of):
        return miss(MISSING_INPUT)
    return ok(1.0 if session in scheduled_meetings(events) else 0.0)


def days_since(events: Sequence[Any], session: _dt.date, coverage_from, as_of) -> Result:
    if not _covered(coverage_from, as_of):
        return miss(MISSING_INPUT)
    past = [e.event_at.astimezone(IST).date() for e in events if e.kind == "OUTCOME"]
    past = [d for d in past if d <= session]
    if past:
        return ok(float((session - max(past)).days))
    return miss(MISSING_INPUT if as_of - coverage_from < SINCE_MIN_COVERAGE else NOT_APPLICABLE)


def street_verdict(events: Sequence[Any], coverage_from, as_of) -> Result:
    if not _covered(coverage_from, as_of):
        return miss(MISSING_INPUT)
    recent = [e for e in events if e.kind == "ESTIMATE_NEWS" and e.verdict in VERDICT_SCORE
              and as_of - e.event_at <= VERDICT_WINDOW]
    if not recent:
        return miss(NOT_APPLICABLE)
    last = max(recent, key=lambda e: (e.event_at, e.news_id))
    return ok(VERDICT_SCORE[last.verdict])
