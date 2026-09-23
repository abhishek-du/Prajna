"""Upstox calendar payloads: the real recorded ones, plus shifted copies.

Real: tests/fixtures/upstox_calendar/*.json (see its README).
Synthetic: `timings_for(day)` takes the REAL 2026-09-24 timings payload and
shifts every timestamp to `day`. Same shape and hours as the vendor's; only
the date differs. Used for weekdays with no recording.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib

from app.core.clock import now
from app.sources.upstox_calendar import API, HOLIDAYS_PATH, TIMINGS_PATH, Fetched

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_calendar"
REAL_DAYS = {_dt.date(2026, 9, 24), _dt.date(2026, 2, 1), _dt.date(2026, 11, 8)}


def real(name: str) -> bytes:
    return (FIX / name).read_bytes()


HOLIDAYS = real("holidays_2026.json")
EMPTY = real("timings_empty.json")


def timings_for(day: _dt.date) -> bytes:
    if day in REAL_DAYS:
        return real(f"timings_{day}.json")
    base = json.loads(real("timings_2026-09-24.json"))
    shift = int((day - _dt.date(2026, 9, 24)).total_seconds() * 1000)
    for e in base["data"]:
        e["start_time"] += shift
        e["end_time"] += shift
    return json.dumps(base, separators=(",", ":")).encode()


def holidays_with(extra: list[dict] | None = None, drop: set[str] | None = None) -> bytes:
    doc = json.loads(HOLIDAYS)
    doc["data"] = [e for e in doc["data"] if e["date"] not in (drop or set())] + (extra or [])
    return json.dumps(doc).encode()


class FakeCalendar:
    """Serves the recorded holidays and, per date, real/shifted/empty timings.
    A date is closed (empty timings) if the holiday list closes NSE or it is a
    weekend with no special session."""

    def __init__(self, holidays: bytes = HOLIDAYS, overrides: dict | None = None):
        self.holidays_bytes = holidays
        self.overrides = overrides or {}
        self.calls: list[str] = []
        doc = json.loads(holidays)["data"]
        self.closed = {e["date"] for e in doc if "NSE" in e["closed_exchanges"]}
        self.special = {e["date"] for e in doc if e["holiday_type"] == "SPECIAL_TIMING"}

    async def holidays(self) -> Fetched:
        self.calls.append("holidays")
        return Fetched(API + HOLIDAYS_PATH, self.holidays_bytes, now(), 200)

    async def timings(self, day: _dt.date) -> Fetched:
        self.calls.append(day.isoformat())
        if day in self.overrides:
            data = self.overrides[day]
        elif day.isoformat() in self.closed or (day.weekday() >= 5
                                               and day.isoformat() not in self.special):
            data = EMPTY
        else:
            data = timings_for(day)
        return Fetched(API + TIMINGS_PATH.format(date=day), data, now(), 200)
