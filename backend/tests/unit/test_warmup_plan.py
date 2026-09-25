"""Targeted warm-up planning: the depth a feature contract needs, never the
deferred full backfill; read-only arithmetic over measured vendor limits."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.ops.warmup import PER_30_MIN, cost, window_for

D = _dt.date


def test_window_is_the_n_most_recent_completed_sessions():
    days = [D(2026, 9, 24), D(2026, 9, 23), D(2026, 9, 22), D(2026, 9, 21), D(2026, 9, 18)]
    assert window_for(days, 1) == (D(2026, 9, 24), D(2026, 9, 24))
    assert window_for(days, 5) == (D(2026, 9, 18), D(2026, 9, 24))   # weekend skipped by data


def test_asking_for_more_sessions_than_known_fails_closed():
    with pytest.raises(ValueError):
        window_for([D(2026, 9, 24)], 2)
    with pytest.raises(ValueError):
        window_for([D(2026, 9, 24)], 0)


def test_minutes_cost_one_request_per_calendar_month_touched():
    c = cost("1m", D(2026, 8, 27), D(2026, 9, 24), 3531, 0.5)
    assert c["windows_per_instrument"] == 2 and c["requests"] == 7062
    assert c["hours_at_fraction"] == round(7062 / (PER_30_MIN * 2 * 0.5), 2)


def test_hours_cost_one_request_per_three_consecutive_months():
    assert cost("1h", D(2026, 8, 27), D(2026, 9, 24), 10, 0.5)["windows_per_instrument"] == 1
    assert cost("1h", D(2026, 9, 1), D(2026, 11, 30), 10, 0.5)["windows_per_instrument"] == 1
    assert cost("1h", D(2026, 9, 1), D(2026, 12, 5), 10, 0.5)["windows_per_instrument"] == 2


def test_documented_quota_is_used():
    assert PER_30_MIN == 2000
