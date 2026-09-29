"""Proposed point-in-time news features: pure calculations, MISSING_INPUT without
proven coverage (never a silent zero), and no look-ahead through news_pit."""

from __future__ import annotations

import datetime as _dt

from app.core.clock import IST
from app.features import news_features as NF

AS_OF = _dt.datetime(2026, 9, 28, 12, 0, tzinfo=IST)


def row(
    minutes_ago,
    *,
    publisher="ET",
    impact="MEDIUM",
    direction="UNKNOWN",
    breaking=False,
    group="CORPORATE",
    story=1,
    method="FOUNDER",
):
    return {
        "knowable_at": AS_OF - _dt.timedelta(minutes=minutes_ago),
        "publisher": publisher,
        "potential_impact": impact,
        "impact_direction": direction,
        "is_breaking": breaking,
        "assessment_evidence": {"event_group": group},
        "story_id": story,
        "story_method": method,
    }


def test_without_coverage_everything_is_missing_input_not_zero():
    got = NF.compute([], AS_OF, covered=False)
    assert set(got) == set(NF.FEATURES)
    assert all(v == (None, "MISSING_INPUT") for v in got.values())


def test_with_coverage_zero_is_a_real_zero():
    got = NF.compute([], AS_OF, covered=True)
    assert got["mnews_news_count_24h"] == (0.0, None)
    assert got["mnews_time_since_last_news_s"] == (None, "MISSING_INPUT")  # no news ever seen
    assert got["mnews_publisher_diversity_24h"] == (None, "DIVISION_UNDEFINED")


def test_counts_windows_and_recency():
    rows = [
        row(10, impact="HIGH", direction="NEGATIVE", breaking=True),
        row(30, publisher="Mint", story=1, method="SAME_TITLE"),
        row(5 * 60, group="MACRO", story=2),
        row(30 * 60, story=3),
        row(60 * 60, direction="POSITIVE", story=4),
    ]
    g = NF.compute(rows, AS_OF, covered=True)
    assert g["mnews_news_count_1h"] == (2.0, None) and g["mnews_news_count_4h"] == (2.0, None)
    assert g["mnews_news_count_24h"] == (3.0, None) and g["mnews_news_count_3d"] == (5.0, None)
    assert g["mnews_unique_publishers_1h"] == (2.0, None)
    assert g["mnews_breaking_news_count_24h"] == (1.0, None)
    assert g["mnews_high_relevance_news_count_24h"] == (1.0, None)
    assert g["mnews_negative_news_count_24h"] == (1.0, None)
    assert g["mnews_positive_news_count_24h"] == (0.0, None)
    assert g["mnews_macro_news_count_24h"] == (1.0, None)
    assert g["mnews_story_group_count_24h"] == (2.0, None)
    assert g["mnews_updated_story_count_24h"] == (1.0, None)
    assert g["mnews_new_story_count_24h"] == (2.0, None)
    assert g["mnews_time_since_last_news_s"] == (600.0, None)
    assert g["mnews_time_since_last_high_relevance_news_s"] == (600.0, None)
    assert g["mnews_news_velocity_1h"] == (2 / (1 / 23), None)


def test_not_in_the_approved_stage3_registry():
    from app.features.registry import BY_ID

    assert not set(NF.FEATURES) & set(BY_ID)
    # APPROVED 2026-09-29 with activation only after a production canary day: until
    # then no mnews_* feature is in the registry
    assert NF.DECISION["FEATURE-NEWS-V2"]["status"] == "APPROVED"
