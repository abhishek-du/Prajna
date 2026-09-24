"""Corporate-actions parser on REAL Upstox responses (2026-09-23/24), plus mutations."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
from decimal import Decimal

import pytest

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.clock import IST
from app.parsers import upstox_corporate_actions as P

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_corporate_actions"
MAN = {m["file"][:-5]: m for m in json.loads((FIX / "manifest.json").read_text())}
FETCHED = _dt.datetime(2026, 9, 24, 12, 30, tzinfo=IST)
D = _dt.date


def _raw(name):
    return (FIX / f"{name}.json").read_bytes()


def _parse(name, data=None, isin=None):
    return P.parse_corporate_actions(data if data is not None else _raw(name), http_status=200,
                                     isin=isin or MAN[name]["isin"] or "INE000000000",
                                     fetched_at=FETCHED)


def _kinds(p):
    return {(i.severity, i.kind) for i in p.issues}


def test_fixture_hashes():
    for m in MAN.values():
        assert hashlib.sha256((FIX / m["file"]).read_bytes()).hexdigest() == m["sha256"]


def test_dividend():
    (e,) = _parse("dividend_RELIANCE_INE002A01018").events
    assert (e.action_type, e.ex_date, e.record_date, e.announcement_date, e.amount) == (
        "DIVIDEND", D(2026, 6, 5), D(2026, 6, 5), D(2026, 4, 24), Decimal("6.0"))
    assert e.ratio_from is None and e.face_value_before is None


def test_split_and_bonus_same_day():
    p = _parse("split_bonus_INE838B01021")
    assert not [i for i in p.issues if i.severity is AnomalySeverity.FAIL]
    by = {e.action_type: e for e in p.events}
    s, b = by["SPLIT"], by["BONUS"]
    assert (s.ex_date, s.ratio_from, s.ratio_to) == (D(2025, 12, 12), Decimal(5), Decimal(10))
    assert (s.face_value_before, s.face_value_after) == (Decimal("10.0"), Decimal("5.0"))
    assert (b.ratio_from, b.ratio_to, b.amount) == (Decimal(1), Decimal(1), None)


def test_rights():
    (e,) = _parse("rights_INE741L01018").events
    assert (e.action_type, e.ex_date, e.ratio_from, e.ratio_to) == (
        "RIGHTS", D(2026, 8, 25), Decimal(10), Decimal(13))


def test_two_dividends_on_one_ex_date_are_two_events():
    p = _parse("dup_same_ex_INE572G01025")
    assert len(p.events) == 2
    assert len({e.content_sha256 for e in p.events}) == 2
    assert {e.ex_date for e in p.events} == {D(2026, 9, 21)}
    assert {e.amount for e in p.events} == {Decimal("0.2"), Decimal("0.1")}


def test_knowable_is_end_of_the_announcement_day_ist_kn_ca():
    (e,) = _parse("dividend_RELIANCE_INE002A01018").events       # announced 24 Apr 2026
    assert e.knowable.at == _dt.datetime(2026, 4, 24, 23, 59, 59, 999000, tzinfo=IST)
    assert not e.knowable.verified and "KN-CA" in e.knowable.basis
    for name in MAN:
        for e in _parse(name).events:
            assert e.knowable.at <= FETCHED and not hasattr(e, "announced_at")


def test_announced_on_the_fetch_day_is_bounded_by_fetch():
    b = json.loads(_raw("dividend_RELIANCE_INE002A01018"))
    b["data"][0]["event_details"][0]["value"] = "24 Sep 2026"      # the fetch day
    (e,) = _parse("dividend_RELIANCE_INE002A01018", json.dumps(b).encode()).events
    assert e.knowable.at == FETCHED


def test_no_announcement_date_falls_back_to_fetch():
    b = json.loads(_raw("dividend_RELIANCE_INE002A01018"))
    b["data"][0]["event_details"] = [x for x in b["data"][0]["event_details"]
                                     if x["name"] != "Announcement date"]
    (e,) = _parse("dividend_RELIANCE_INE002A01018", json.dumps(b).encode()).events
    assert e.knowable.at == FETCHED and e.announcement_date is None


def test_empty_is_valid():
    p = _parse("empty")
    assert not p.issues and not p.events


def test_unknown_event_type_is_other_with_warn():
    b = json.loads(_raw("dividend_RELIANCE_INE002A01018"))
    b["data"][0]["name"] = "Buyback"
    p = _parse("dividend_RELIANCE_INE002A01018", json.dumps(b).encode())
    assert p.events[0].action_type == "OTHER"
    assert (AnomalySeverity.WARN, AnomalyKind.SCHEMA_DRIFT) in _kinds(p)


def test_unknown_event_key_is_schema_drift_fail():
    b = json.loads(_raw("dividend_RELIANCE_INE002A01018"))
    b["data"][0]["event_id"] = 7
    assert (AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT) in _kinds(
        _parse("dividend_RELIANCE_INE002A01018", json.dumps(b).encode()))


@pytest.mark.parametrize("field,value", [("amount", "abc"), ("ratio", "1-1")])
def test_bad_numbers_are_rejected(field, value):
    b = json.loads(_raw("dividend_RELIANCE_INE002A01018"))
    b["data"][0][field] = value
    p = _parse("dividend_RELIANCE_INE002A01018", json.dumps(b).encode())
    assert (AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT) in _kinds(p) and not p.events


def test_bad_date_is_rejected():
    b = json.loads(_raw("dividend_RELIANCE_INE002A01018"))
    b["data"][0]["event_details"][1]["value"] = "2026-06-05"
    p = _parse("dividend_RELIANCE_INE002A01018", json.dumps(b).encode())
    assert (AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT) in _kinds(p)


def test_identity_is_content_not_type_and_date():
    a = {"name": "Dividend", "amount": 1}
    assert P.content_sha256(a) == P.content_sha256({"amount": 1, "name": "Dividend"})
    assert P.content_sha256(a) != P.content_sha256({"name": "Dividend", "amount": 2})


def test_non_success_raises():
    with pytest.raises(P.CorporateActionDecodeError):
        P.parse_corporate_actions(b"{}", http_status=400, isin="X", fetched_at=FETCHED)
