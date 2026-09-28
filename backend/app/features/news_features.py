"""Point-in-time news features (Phase 11) - a SEPARATE, PROPOSED feature set.

Ids carry the prefix "mnews_" (multi-source news): the approved registry already
has Upstox-based news_count_24h / news_count_7d / news_hours_since_last, and one
name must never mean two definitions.

Not part of the approved Stage 3 registry (features-v1): adding them there would
change the approved feature set and re-block Stage 3 production. They are
computed in DRY-RUN only (`prajna stage3 news-features`) until decision
FEATURE-NEWS-V2 is approved and they join the registry as a new version.

Every input comes from app.canon.news_pit at the snapshot instant (knowable_at
< as_of; enrichments by their own knowable_at). MISSING_INPUT - never 0 - when
news coverage is not proven at as_of: no PRODUCTION news source had a
successful poll within its staleness window. With coverage, 0 is a real zero.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import news_pit as NP
from app.features.compute import MISSING_INPUT, Result, miss, ok

VERSION = "news-features-v0-proposed"
DECISION = {
    "FEATURE-NEWS-V2": {
        "status": "PENDING",
        "decision": "Add these point-in-time news features to the Stage 3 registry as a new "
        "version (windows 1h/4h/24h/3d as listed); until approved they are dry-run only",
        "ref": "news programme phase 11 (2026-09-28)",
    }
}
COVERAGE_WINDOW = _dt.timedelta(hours=2)
H = _dt.timedelta(hours=1)

FEATURES = (
    "mnews_news_count_1h",
    "mnews_news_count_4h",
    "mnews_news_count_24h",
    "mnews_news_count_3d",
    "mnews_unique_publishers_1h",
    "mnews_unique_publishers_24h",
    "mnews_breaking_news_count_24h",
    "mnews_high_relevance_news_count_24h",
    "mnews_negative_news_count_24h",
    "mnews_positive_news_count_24h",
    "mnews_mixed_news_count_24h",
    "mnews_regulatory_news_count_24h",
    "mnews_corporate_news_count_24h",
    "mnews_macro_news_count_24h",
    "mnews_news_velocity_1h",
    "mnews_news_velocity_24h",
    "mnews_publisher_diversity_24h",
    "mnews_story_group_count_24h",
    "mnews_new_story_count_24h",
    "mnews_updated_story_count_24h",
    "mnews_time_since_last_news_s",
    "mnews_time_since_last_high_relevance_news_s",
)
_GROUP = {"REGULATORY": "regulatory", "CORPORATE": "corporate", "MACRO": "macro"}


async def coverage(s: AsyncSession, as_of: _dt.datetime) -> bool:
    """A PRODUCTION news poll succeeded shortly before as_of (so absence means none)."""
    return bool(
        (
            await s.execute(
                text("""select 1 from news_poll where mode = 'PRODUCTION'
        and outcome in ('OK', 'NOT_MODIFIED') and finished_at < :a and finished_at >= :b
        limit 1"""),
                {"a": as_of, "b": as_of - COVERAGE_WINDOW},
            )
        ).first()
    )


def compute(rows: list[dict[str, Any]], as_of: _dt.datetime, covered: bool) -> dict[str, Result]:
    """Pure: the feature values from the items visible at as_of."""
    if not covered:
        return {f: miss(MISSING_INPUT) for f in FEATURES}

    def win(h: float) -> list[dict]:
        return [r for r in rows if as_of - r["knowable_at"] <= H * h]

    d1, d4, d24, d72 = win(1), win(4), win(24), win(72)
    out: dict[str, Result] = {
        "mnews_news_count_1h": ok(len(d1)),
        "mnews_news_count_4h": ok(len(d4)),
        "mnews_news_count_24h": ok(len(d24)),
        "mnews_news_count_3d": ok(len(d72)),
        "mnews_unique_publishers_1h": ok(len({r["publisher"] for r in d1})),
        "mnews_unique_publishers_24h": ok(len({r["publisher"] for r in d24})),
        "mnews_breaking_news_count_24h": ok(sum(1 for r in d24 if r.get("is_breaking"))),
        "mnews_high_relevance_news_count_24h": ok(
            sum(1 for r in d24 if r.get("potential_impact") == "HIGH")
        ),
    }
    for k in ("negative", "positive", "mixed"):
        out[f"mnews_{k}_news_count_24h"] = ok(
            sum(1 for r in d24 if r.get("impact_direction") == k.upper())
        )
    for grp, name in _GROUP.items():
        out[f"mnews_{name}_news_count_24h"] = ok(
            sum(1 for r in d24 if (r.get("assessment_evidence") or {}).get("event_group") == grp)
        )
    prior23 = len(d24) - len(d1)
    out["mnews_news_velocity_1h"] = (
        ok(len(d1) / (prior23 / 23)) if prior23 else miss("DIVISION_UNDEFINED")
    )
    prior48 = len(d72) - len(d24)
    out["mnews_news_velocity_24h"] = (
        ok(len(d24) / (prior48 / 2)) if prior48 else miss("DIVISION_UNDEFINED")
    )
    out["mnews_publisher_diversity_24h"] = (
        ok(len({r["publisher"] for r in d24}) / len(d24)) if d24 else miss("DIVISION_UNDEFINED")
    )
    stories24 = {r["story_id"] for r in d24 if r.get("story_id") is not None}
    out["mnews_story_group_count_24h"] = ok(len(stories24))
    out["mnews_new_story_count_24h"] = ok(sum(1 for r in d24 if r.get("story_method") == "FOUNDER"))
    out["mnews_updated_story_count_24h"] = ok(
        len(
            {
                r["story_id"]
                for r in d24
                if r.get("story_id") and r.get("story_method") not in (None, "FOUNDER")
            }
        )
    )
    last = max((r["knowable_at"] for r in rows), default=None)
    out["mnews_time_since_last_news_s"] = (
        ok((as_of - last).total_seconds()) if last else miss(MISSING_INPUT)
    )
    hi = max((r["knowable_at"] for r in rows if r.get("potential_impact") == "HIGH"), default=None)
    out["mnews_time_since_last_high_relevance_news_s"] = (
        ok((as_of - hi).total_seconds()) if hi else miss(MISSING_INPUT)
    )
    return out


async def snapshot(
    s: AsyncSession, as_of: _dt.datetime, instrument_key: str | None
) -> dict[str, Result]:
    """Features for one instrument (or market-wide when instrument_key is None)."""
    rows = await NP.items(
        s, as_of, instrument_key=instrument_key, since=as_of - _dt.timedelta(days=3), limit=5000
    )
    return compute(rows, as_of, await coverage(s, as_of))
