"""News acceptance gate: evidence of a full market session, politeness, health,
human-reviewed mapping, terms - a PASS needs all; tests alone never pass."""

from __future__ import annotations

import datetime as _dt
import json

import pytest

from app.acceptance import news as NA
from app.core.clock import IST

D = _dt.date(2026, 9, 29)


def poll(h, m, outcome="OK"):
    t = _dt.datetime.combine(D, _dt.time(h, m), tzinfo=IST).isoformat()
    return {"type": "poll", "started_at": t, "finished_at": t, "outcome": outcome,
            "http_status": 200, "bytes": 1, "items_seen": 0, "items_new": 0, "items_changed": 0,
            "backlog": False, "issues": []}


def session(step=5):
    return [poll(9 + (m // 60), m % 60) for m in range(10, 6 * 60 + 35, step)]


def test_full_market_session_is_required():
    assert NA.market_sessions(session(), 300) == ["2026-09-29"]
    gappy = [p for p in session() if "11:" not in p["started_at"][11:14]]
    assert NA.market_sessions(gappy, 300) == []           # a 1 h hole is not coverage
    assert NA.market_sessions(session(), 300) and NA.market_sessions([], 300) == []


def test_mapping_needs_a_human_judged_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(NA, "REVIEW_DIR", tmp_path)
    assert NA.review("X")[0] == NA.PENDING
    (tmp_path / "X.json").write_text(json.dumps({"rows": [{"correct": True}, {"correct": None}]}))
    assert NA.review("X")[0] == NA.PENDING                 # not every row judged
    rows = [{"correct": True}] * 98 + [{"correct": False}] * 2
    (tmp_path / "X.json").write_text(json.dumps({"rows": rows}))
    assert NA.review("X") == (NA.PASS, {"rows": 100, "false_positives": 2, "rate": 0.02})
    rows = [{"correct": True}] * 90 + [{"correct": False}] * 10
    (tmp_path / "X.json").write_text(json.dumps({"rows": rows}))
    assert NA.review("X")[0] == NA.FAIL


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(NA, "DRYRUN_DIR", tmp_path)
    monkeypatch.setattr(NA, "REVIEW_DIR", tmp_path / "review")
    d = tmp_path / "ET_STOCKS_RSS"
    d.mkdir()
    return d


def write(d, polls):
    (d / "events_2026-09-29.jsonl").write_text("\n".join(json.dumps(p) for p in polls) + "\n")


def test_passing_tests_alone_never_pass_a_source(evidence):
    write(evidence, session())
    v = NA.evaluate_source("ET_STOCKS_RSS", {"exit": 0, "summary": "ok"},
                           at=_dt.datetime.combine(D, _dt.time(15, 40), tzinfo=IST))
    c = {k: x["status"] for k, x in v["criteria"].items()}
    assert c["EVIDENCE"] == "PASS" and c["PIT"] == "PASS" and c["HEALTH"] == "PASS"
    # TERMS: APPROVED by the user 2026-09-29 (NEWS-COMPLIANCE); the source still cannot
    # pass without the human mapping review and measured latency
    assert c["TERMS"] == "PASS" and c["MAPPING"] == "PENDING" and c["LATENCY"] == "PENDING"
    assert v["status"] == "PENDING"


def test_blocked_or_impolite_polling_fails(evidence):
    write(evidence, [*session(), poll(15, 36, "BLOCKED")])
    assert NA.evaluate_source("ET_STOCKS_RSS", None)["criteria"]["HEALTH"]["status"] == "FAIL"
    write(evidence, session(step=1))                       # every minute: below the 120 s floor
    assert NA.evaluate_source("ET_STOCKS_RSS", None)["criteria"]["POLITENESS"]["status"] == "FAIL"


def test_feed_ttl_sets_the_expected_interval(evidence):
    """Regression (2026-09-29): BusinessLine declares <ttl>60</ttl>, so it is polled
    hourly; judged against its configured 180 s it never had a 'full session'."""
    bl = evidence.parent / "BL_MARKETS_RSS"
    bl.mkdir()
    hourly = [{**poll(9 + h, 5 + h), "ttl_s": 3600} for h in range(7)]
    write(bl, hourly)
    v = NA.evaluate_source("BL_MARKETS_RSS", None)["criteria"]
    assert v["EVIDENCE"]["status"] == "PASS"
    assert v["EVIDENCE"]["evidence"]["expected_interval_s"] == 3600
    assert v["POLITENESS"]["status"] == "PASS"
    # without the ttl the same hourly polls are not coverage for a 180 s source
    write(bl, [{k: x for k, x in p.items() if k != "ttl_s"} for p in hourly])
    assert NA.evaluate_source("BL_MARKETS_RSS", None)["criteria"]["EVIDENCE"]["status"] == "PENDING"


def test_polling_faster_than_the_feed_ttl_is_impolite(evidence):
    bl = evidence.parent / "BL_MARKETS_RSS"
    bl.mkdir()
    write(bl, [{**p, "ttl_s": 3600} for p in session(step=5)])
    assert NA.evaluate_source("BL_MARKETS_RSS", None)["criteria"]["POLITENESS"]["status"] == "FAIL"
