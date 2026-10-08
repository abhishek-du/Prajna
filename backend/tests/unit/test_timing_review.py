"""Decision TIMING-REVIEW (2026-10-08): the 1m/15m/1h completion margin is 300 s
from 18:30 IST that day; a fetch is judged by the margin in force at ITS time, so
an earlier fetch that waited the 120 s then in force is not made a violation."""

from __future__ import annotations

import datetime as _dt

from app.acceptance.stage1 import DECISIONS
from app.contracts import timing as T

UTC = _dt.UTC


def test_the_margin_is_300_s_from_the_review():
    for tf in ("1m", "15m", "1h"):
        assert T.margin(tf) == _dt.timedelta(seconds=300)
        assert T.margin_s_at(tf, T.MARGIN_EFFECTIVE_FROM) == 300.0
        assert T.margin_s_at(tf, T.MARGIN_EFFECTIVE_FROM - _dt.timedelta(seconds=1)) == 120.0
    assert T.MARGIN_EFFECTIVE_FROM == _dt.datetime(2026, 10, 8, 13, 0, tzinfo=UTC)


def test_the_observed_maximum_has_headroom():
    observed_max = 200.4                      # 1m NSE_INDEX|Nifty 50, 9 sessions
    m = T.margin("1m").total_seconds()
    assert m - observed_max >= 99 and round(m / observed_max, 1) == 1.5    # ~1.5x


def test_out_of_scope_5m_is_unchanged():
    assert T.margin_s_at("5m", T.MARGIN_EFFECTIVE_FROM) == 120.0


def test_the_review_is_recorded_and_the_grace_decision_too():
    r = DECISIONS["TIMING-REVIEW"]
    assert r["status"] == "APPROVED" and "300 s" in r["decision"] and "2026-10-08" in r["ref"]
    g = DECISIONS["D-NEW-LISTING-GRACE"]
    assert g["status"] == "APPROVED" and "7 days" in g["decision"]


def test_a_bar_is_final_only_after_bar_end_plus_the_margin():
    start = _dt.datetime(2026, 10, 9, 4, 0, tzinfo=UTC)
    end = start + _dt.timedelta(minutes=1)
    assert not T.is_final(start, "1m", end + _dt.timedelta(seconds=299))
    assert T.is_final(start, "1m", end + _dt.timedelta(seconds=300))
