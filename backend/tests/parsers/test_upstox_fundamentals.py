"""Fundamentals parser on REAL Upstox responses (2026-09-24)."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib

import pytest

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.clock import IST
from app.parsers import upstox_fundamentals as P

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_fundamentals"
MAN = json.loads((FIX / "manifest.json").read_text())
FETCHED = _dt.datetime(2026, 9, 24, 12, 0, tzinfo=IST)
V = {v.statement_type: v for v in P.VARIANTS}
D = _dt.date


def _p(name, st, data=None):
    return P.parse_fundamentals(data if data is not None else (FIX / f"{name}.json").read_bytes(),
                                http_status=200, variant=V[st], subject="INE002A01018",
                                fetched_at=FETCHED)


def test_fixture_hashes():
    for m in MAN:
        assert hashlib.sha256((FIX / m["file"]).read_bytes()).hexdigest() == m["sha256"]


def test_twelve_variants_and_paths():
    assert len(P.VARIANTS) == 12
    assert V["income:standalone:quarterly"].path("INE002A01018", "NSE_EQ|INE002A01018") == (
        "/v2/fundamentals/INE002A01018/income-statement"
        "?type=standalone&time_period=quarterly&fs=true")
    assert V["competitors"].path("INE002A01018", "NSE_EQ|INE002A01018") == \
        "/v2/fundamentals/NSE_EQ%7CINE002A01018/competitors"
    assert all(len(v.statement_type) <= 32 for v in P.VARIANTS)


@pytest.mark.parametrize("name,st,end,ptype", [
    ("RELIANCE_income_consolidated_quarterly", "income:consolidated:quarterly",
     D(2026, 6, 30), "Q"),
    ("RELIANCE_income_standalone_yearly", "income:standalone:yearly", D(2026, 3, 31), "FY"),
    ("RELIANCE_balance_sheet_consolidated", "balance_sheet:consolidated", D(2026, 3, 31), "FY"),
    ("RELIANCE_cash_flow_standalone", "cash_flow:standalone", D(2026, 3, 31), "FY"),
    ("RELIANCE_share_holdings", "share_holdings", D(2026, 6, 30), "Q"),
    ("INVIT_balance_sheet_standalone", "balance_sheet:standalone", D(2024, 3, 31), "FY"),
])
def test_statements(name, st, end, ptype):
    s = _p(name, st)
    assert not s.issues
    assert (s.period_end, s.period_type) == (end, ptype)
    assert len(s.periods) >= 4
    assert s.knowable.at == FETCHED and not s.knowable.verified


def test_payload_is_kept_verbatim():
    raw = json.loads((FIX / "RELIANCE_balance_sheet_consolidated.json").read_bytes())
    assert _p("RELIANCE_balance_sheet_consolidated", "balance_sheet:consolidated").payload == \
        raw["data"]
    assert raw["data"]["full_statement"]


def test_ratios_profile_competitors():
    r = _p("RELIANCE_key_ratios", "key_ratios")
    assert {x["name"] for x in r.payload} >= {"P/E", "P/B", "ROE", "ROCE"}
    assert r.period_end is None and r.period_type is None
    prof = _p("RELIANCE_profile", "profile")
    assert prof.payload["sector"] == "Refineries" and prof.period_end is None
    c = _p("RELIANCE_competitors", "competitors")
    assert isinstance(c.payload, list) and c.payload


def test_asked_type_must_match():
    b = json.loads((FIX / "RELIANCE_income_standalone_yearly.json").read_bytes())
    s = _p("x", "income:consolidated:yearly", json.dumps(b).encode())
    assert (AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT) in {(i.severity, i.kind)
                                                              for i in s.issues}


def test_wrong_container_is_schema_drift():
    s = _p("x", "key_ratios", b'{"status":"success","data":{"a":1}}')
    assert s.issues[0].kind is AnomalyKind.SCHEMA_DRIFT


def test_bad_period_is_rejected():
    s = _p("x", "share_holdings", b'{"status":"success","data":[{"category":"fii",'
                                  b'"history":[{"value":1,"period":"Q1 26"}]}]}')
    assert s.issues[0].kind is AnomalyKind.PARSE_REJECT


def test_empty_payload():
    assert _p("x", "profile", b'{"status":"success","data":null}').empty


def test_error_raises():
    with pytest.raises(P.FundamentalsDecodeError):
        P.parse_fundamentals((FIX / "RELIANCE_competitors_by_isin_400.json").read_bytes(),
                             http_status=400, variant=V["competitors"], subject="x",
                             fetched_at=FETCHED)


def test_period_end():
    assert P.period_end("Feb 2024") == D(2024, 2, 29)
    with pytest.raises(ValueError):
        P.period_end("2024-03")
