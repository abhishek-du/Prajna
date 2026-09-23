"""Calendar decisions, first on REAL recorded Upstox payloads, then on the
contradictions the two endpoints must never be allowed to hide."""

from __future__ import annotations

import datetime as _dt
import json

import pytest

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.contracts.session import SessionType
from app.parsers.upstox_calendar import (
    CalendarDecodeError,
    decide,
    parse_holidays,
    parse_timings,
)
from tests.support.upstox_calendar import EMPTY, HOLIDAYS, holidays_with, real, timings_for

D = _dt.date
T = _dt.time
HOL, HOL_ISSUES = parse_holidays(HOLIDAYS)
COVER = (D(2026, 1, 1), D(2026, 12, 31))


def _decide(day, timings=None, hol=HOL):
    return decide(day, hol, parse_timings(timings if timings is not None else timings_for(day),
                                          day), holidays_cover=COVER)


class TestRealPayloads:
    def test_holiday_list_parses_as_recorded(self):
        assert HOL_ISSUES == [] and len(HOL) == 22
        types = sorted(e.holiday_type for es in HOL.values() for e in es)
        assert types.count("TRADING_HOLIDAY") == 16 and types.count("SETTLEMENT_HOLIDAY") == 4

    def test_normal_thursday(self):
        d = _decide(D(2026, 9, 24)).decision
        assert (d.is_trading_day, d.session_type) == (True, SessionType.NORMAL)
        assert (d.open_ist, d.close_ist) == (T(9, 15), T(15, 30))
        assert (d.preopen_start_ist, d.preopen_end_ist) == (T(9, 0), T(9, 15))
        assert "derived" in d.note["preopen_basis"]

    def test_budget_sunday_is_a_special_session_with_vendor_hours(self):
        d = _decide(D(2026, 2, 1)).decision
        assert (d.session_type, d.open_ist, d.close_ist) == (SessionType.SPECIAL, T(9, 15),
                                                             T(15, 30))
        assert d.preopen_start_ist is None and "UNKNOWN" in d.note["preopen_basis"]

    def test_muhurat_is_evening_not_0915(self):
        d = _decide(D(2026, 11, 8)).decision
        assert (d.session_type, d.open_ist, d.close_ist) == (SessionType.SPECIAL, T(18, 0),
                                                             T(19, 0))
        assert d.preopen_start_ist is None

    def test_trading_holiday(self):
        d = _decide(D(2026, 10, 2), EMPTY).decision
        assert (d.is_trading_day, d.session_type, d.open_ist) == (False, SessionType.HOLIDAY,
                                                                  None)
        assert d.note["description"] == "Gandhi Jayanti"

    def test_weekend(self):
        d = _decide(D(2026, 9, 26), EMPTY).decision
        assert (d.is_trading_day, d.session_type) == (False, SessionType.WEEKEND)

    def test_settlement_holiday_is_a_trading_day(self):
        """B9: Upstox lists it as a holiday; NSE trades."""
        d = _decide(D(2026, 2, 19)).decision
        assert (d.is_trading_day, d.session_type) == (True, SessionType.NORMAL)
        assert d.note["holiday_type"] == "SETTLEMENT_HOLIDAY"


class TestContradictionsFail:
    def _fails(self, res, text):
        assert res.decision is None
        assert any(i.severity is AnomalySeverity.FAIL and text in i.detail["reason"]
                   for i in res.issues)

    def test_weekday_with_no_hours_and_no_holiday(self):
        self._fails(_decide(D(2026, 9, 25), EMPTY), "weekday with no NSE timings")

    def test_holiday_list_closed_but_timings_open(self):
        self._fails(_decide(D(2026, 10, 2), timings_for(D(2026, 10, 2))),
                    "closes NSE but timings opens")

    def test_special_session_hours_disagree(self):
        self._fails(_decide(D(2026, 11, 8), _shifted_hours(D(2026, 11, 8))),
                    "disagree on NSE hours")

    def test_special_session_missing_from_timings(self):
        self._fails(_decide(D(2026, 11, 8), EMPTY), "SPECIAL_TIMING says NSE is open")

    def test_settlement_holiday_missing_from_timings(self):
        self._fails(_decide(D(2026, 2, 19), EMPTY), "SETTLEMENT_HOLIDAY says NSE is open")

    def test_outside_holiday_coverage_is_not_guessed(self):
        self._fails(_decide(D(2027, 1, 4), EMPTY), "does not cover this date")

    def test_hours_on_another_date(self):
        self._fails(_decide(D(2026, 9, 25), timings_for(D(2026, 9, 24))), "another IST date")

    def test_duplicate_holiday_entries(self):
        dup = json.loads(HOLIDAYS)["data"][0]
        hol, _ = parse_holidays(holidays_with(extra=[dup]))
        self._fails(_decide(D(2026, 1, 15), EMPTY, hol=hol), "several holiday entries")


class TestEdges:
    def test_unlisted_weekend_session_is_special_and_flagged(self):
        res = _decide(D(2026, 9, 27))           # Sunday, synthetic hours
        assert res.decision.session_type is SessionType.SPECIAL
        assert res.issues and res.issues[0].severity is AnomalySeverity.WARN

    def test_unknown_holiday_type_is_schema_drift(self):
        _, issues = parse_holidays(holidays_with(extra=[{
            "date": "2026-12-31", "description": "x", "holiday_type": "NEW_KIND",
            "closed_exchanges": [], "open_exchanges": []}]))
        assert issues[0].kind is AnomalyKind.SCHEMA_DRIFT

    @pytest.mark.parametrize("data", [b"[]", b'{"status":"error","errors":[]}', b"<html>"])
    def test_bad_envelope_is_refused(self, data):
        with pytest.raises(CalendarDecodeError):
            parse_timings(data, D(2026, 9, 24))

    def test_market_status_fixture_is_the_real_shape(self):
        doc = json.loads(real("market_status_NSE.json"))
        assert doc["data"]["exchange"] == "NSE" and doc["data"]["status"] == "NORMAL_OPEN"


def _shifted_hours(day: _dt.date) -> bytes:
    """Muhurat timings with NSE moved an hour later than the holiday list says."""
    doc = json.loads(real(f"timings_{day}.json"))
    for e in doc["data"]:
        if e["exchange"] == "NSE":
            e["start_time"] += 3_600_000
            e["end_time"] += 3_600_000
    return json.dumps(doc).encode()
