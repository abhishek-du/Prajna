"""Event features (diagram group 4). Only events knowable before the snapshot.

  ca_days_since_{any,dividend,split,bonus}   session - latest ex-date <= session (days)
  ca_days_to_{any,dividend,split,bonus}      next ex-date > session - session (days)
  news_count_24h, news_count_7d              linked news published in the window before as_of
  news_hours_since_last                      as_of - latest publication (hours)
News sentiment, analyst up/downgrades and earnings dates: UNSUPPORTED (no data
source). Counts and recency are not sentiment and are not labelled as such.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.features.compute import MISSING_INPUT, Result, miss, ok

TYPES = {"any": None, "dividend": "DIVIDEND", "split": "SPLIT", "bonus": "BONUS"}


def ca_days_since(actions: list[dict[str, Any]], session: date, kind: str) -> Result:
    t = TYPES[kind]
    past = [a["ex_date"] for a in actions if a.get("ex_date") and a["ex_date"] <= session
            and (t is None or a.get("action_type") == t)]
    return ok(float((session - max(past)).days)) if past else miss(MISSING_INPUT)


def ca_days_to(actions: list[dict[str, Any]], session: date, kind: str) -> Result:
    t = TYPES[kind]
    fut = [a["ex_date"] for a in actions if a.get("ex_date") and a["ex_date"] > session
           and (t is None or a.get("action_type") == t)]
    return ok(float((min(fut) - session).days)) if fut else miss(MISSING_INPUT)


def news_count(published: list[datetime], as_of: datetime, hours: int) -> Result:
    lo = as_of - timedelta(hours=hours)
    return ok(float(sum(1 for p in published if lo <= p < as_of)))


def news_hours_since(published: list[datetime], as_of: datetime) -> Result:
    past = [p for p in published if p < as_of]
    return ok((as_of - max(past)).total_seconds() / 3600) if past else miss(MISSING_INPUT)
