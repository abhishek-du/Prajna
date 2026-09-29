"""Point-in-time news features (Phase 11) - a SEPARATE, PROPOSED feature set.

Ids carry the prefix "mnews_" (multi-source news): the approved registry already
has Upstox-based news_count_24h / news_count_7d / news_hours_since_last, and one
name must never mean two definitions.

Not part of the approved Stage 3 registry (features-v1): adding them there would
change the approved feature set and re-block Stage 3 production. They are
computed in DRY-RUN only. Decision FEATURE-NEWS-V2 is APPROVED (2026-09-29) with
activation after a production canary day; they then join the registry as a new
version.

Every input comes from app.canon.news_pit at the snapshot instant (knowable_at
< as_of; enrichments by their own knowable_at). MISSING_INPUT - never 0 - when
news coverage is not proven at as_of: no PRODUCTION news source had a
successful poll within its staleness window. With coverage, 0 is a real zero.

v2 candidate (built and tested; registered only at activation):
  * de-duplicated: an article marked DUPLICATE_ARTICLE is never counted (it is
    counted once, as mnews_duplicate_count_24h); backlog (a source's first poll:
    arrival time unknown) is never counted as an arrival
  * scope-v1 counts (market-wide, macro, geopolitical, commodity, currency,
    global market), corrections, edited articles, source diversity
  * quality state per snapshot (quality()): NORMAL (coverage proven); MISSING
    (no PRODUCTION poll ever before as_of) and STALE (polls exist, none
    succeeded within COVERAGE_WINDOW) -> every feature MISSING_INPUT; INVALID
    (a row not knowable before as_of, or the reader's row limit reached, so a
    count could be silently short) -> every feature MALFORMED_INPUT
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import news_pit as NP
from app.features.compute import MALFORMED_INPUT, MISSING_INPUT, Result, miss, ok

VERSION = "news-features-v2-candidate"
ROW_LIMIT = 50000
DECISION = {
    "FEATURE-NEWS-V2": {
        "status": "APPROVED",
        "decision": "These point-in-time news features join the Stage 3 registry as a new "
        "version, ACTIVATED only after a production canary day (PIT, de-duplication and "
        "coverage evidenced); until activation they are computed in dry-run only",
        "ref": "user 2026-09-29 ('After canary evidence'); see app/news/decisions.py",
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
    # v2
    "mnews_market_wide_news_count_24h",
    "mnews_macro_scope_news_count_24h",
    "mnews_geopolitical_news_count_24h",
    "mnews_commodity_news_count_24h",
    "mnews_currency_news_count_24h",
    "mnews_global_market_news_count_24h",
    "mnews_correction_count_24h",
    "mnews_edited_news_count_24h",
    "mnews_duplicate_count_24h",
    "mnews_unique_sources_24h",
)
_SCOPE = {"MARKET_WIDE": "market_wide", "MACRO": "macro_scope", "GEOPOLITICAL": "geopolitical",
          "COMMODITY": "commodity", "CURRENCY": "currency", "GLOBAL_MARKET": "global_market"}
_GROUP = {"REGULATORY": "regulatory", "CORPORATE": "corporate", "MACRO": "macro"}


async def coverage(s: AsyncSession, as_of: _dt.datetime) -> bool:
    """A PRODUCTION news poll succeeded shortly before as_of (so absence means none)."""
    return await coverage_state(s, as_of) == "NORMAL"


async def coverage_state(s: AsyncSession, as_of: _dt.datetime) -> str:
    """NORMAL / STALE (PRODUCTION polls exist before as_of, none succeeded within the
    window) / MISSING (no PRODUCTION poll before as_of at all)."""
    r = (await s.execute(text("""select
        bool_or(outcome in ('OK', 'NOT_MODIFIED') and finished_at >= :b), count(*)
        from news_poll where mode = 'PRODUCTION' and finished_at < :a"""),
        {"a": as_of, "b": as_of - COVERAGE_WINDOW})).one()
    return "NORMAL" if r[0] else ("STALE" if r[1] else "MISSING")


def quality(rows: list[dict[str, Any]], as_of: _dt.datetime, state: str) -> str:
    """The snapshot's quality: INVALID beats the coverage state."""
    if len(rows) >= ROW_LIMIT or any(r["knowable_at"] >= as_of for r in rows):
        return "INVALID"
    return state


def compute(rows: list[dict[str, Any]], as_of: _dt.datetime, covered: bool | str
            ) -> dict[str, Result]:
    """Pure: the feature values from the items visible at as_of. `covered`: a bool
    (v0 callers) or the coverage state (NORMAL / STALE / MISSING)."""
    state = ("NORMAL" if covered else "MISSING") if isinstance(covered, bool) else covered
    q = quality(rows, as_of, state)
    if q == "INVALID":
        return {f: miss(MALFORMED_INPUT) for f in FEATURES}
    if q != "NORMAL":
        return {f: miss(MISSING_INPUT) for f in FEATURES}
    # backlog (in a source's first successful poll: it existed before Prajna watched,
    # its arrival time is unknown) is not a news arrival: counting it at go-live made
    # a one-time spike (2,002 articles knowable at once, 2026-09-29 17:33 IST)
    rows = [r for r in rows if not r.get("backlog")]
    dups = [r for r in rows if r.get("dedup_decision") == "DUPLICATE_ARTICLE"]
    rows = [r for r in rows if r.get("dedup_decision") != "DUPLICATE_ARTICLE"]

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
    for sc, name in _SCOPE.items():
        out[f"mnews_{name}_news_count_24h"] = ok(sum(1 for r in d24 if r.get("scope") == sc))
    out["mnews_correction_count_24h"] = ok(
        sum(1 for r in d24 if r.get("dedup_decision") == "STORY_CORRECTION"))
    out["mnews_edited_news_count_24h"] = ok(sum(1 for r in d24 if r.get("edited")))
    out["mnews_duplicate_count_24h"] = ok(
        sum(1 for r in dups if as_of - r["knowable_at"] <= H * 24))
    out["mnews_unique_sources_24h"] = ok(len({r.get("source") for r in d24}))
    return out


async def snapshot(
    s: AsyncSession, as_of: _dt.datetime, instrument_key: str | None
) -> dict[str, Result]:
    """Features for one instrument (or market-wide when instrument_key is None)."""
    rows = await NP.items(
        s, as_of, instrument_key=instrument_key, since=as_of - _dt.timedelta(days=3),
        limit=ROW_LIMIT)
    return compute(rows, as_of, await coverage_state(s, as_of))


# ── Stage 3 wiring (v2 candidate): one read per snapshot, market-wide + per company ──
COMPANY_FEATURES = (
    "mnews_company_count_1h",
    "mnews_company_count_4h",
    "mnews_company_count_24h",
    "mnews_company_count_3d",
    "mnews_company_story_count_24h",
    "mnews_company_correction_count_24h",
    "mnews_company_time_since_last_s",
)


def compute_company(rows: list[dict[str, Any]], as_of: _dt.datetime, state: str
                    ) -> dict[str, Result]:
    """Pure: one company's news features from ITS linked rows (de-duplicated). The
    quality state is the snapshot's (coverage is proven market-wide, not per company):
    with coverage, no linked news is a real 0; without it, MISSING_INPUT."""
    q = quality(rows, as_of, state)
    if q == "INVALID":
        return {f: miss(MALFORMED_INPUT) for f in COMPANY_FEATURES}
    if q != "NORMAL":
        return {f: miss(MISSING_INPUT) for f in COMPANY_FEATURES}
    rows = [r for r in rows if r.get("dedup_decision") != "DUPLICATE_ARTICLE"
            and not r.get("backlog")]

    def win(h: float) -> list[dict]:
        return [r for r in rows if as_of - r["knowable_at"] <= H * h]

    d24 = win(24)
    last = max((r["knowable_at"] for r in rows), default=None)
    return {
        "mnews_company_count_1h": ok(len(win(1))),
        "mnews_company_count_4h": ok(len(win(4))),
        "mnews_company_count_24h": ok(len(d24)),
        "mnews_company_count_3d": ok(len(win(72))),
        "mnews_company_story_count_24h": ok(len({r["story_id"] for r in d24
                                                 if r.get("story_id") is not None})),
        "mnews_company_correction_count_24h": ok(sum(
            1 for r in d24 if r.get("dedup_decision") == "STORY_CORRECTION")),
        "mnews_company_time_since_last_s": (ok((as_of - last).total_seconds()) if last
                                            else miss(MISSING_INPUT)),
    }


async def snapshot_inputs(s: AsyncSession, as_of: _dt.datetime
                          ) -> tuple[list[dict[str, Any]], str]:
    """Every PRODUCTION multi-source row of the 3 days before as_of (one read) and the
    coverage state at as_of."""
    rows = await NP.items(s, as_of, since=as_of - _dt.timedelta(days=3), limit=ROW_LIMIT)
    return rows, await coverage_state(s, as_of)
