"""Dedup decisions, rule version dedup-v2 (docs/NEWS_DEDUP_SPEC.md). Pure.

Every stored article and every stored edit gets exactly one decision. A decision
only MARKS: the article is stored in any case, edits stay observations, and
nothing is merged or deleted.

A NEW article (a (source, source_article_id) never stored before), in order:
  DUPLICATE_ARTICLE  the SAME source already stored, within 24 h before it,
                     the same canonical URL        (SAME_SOURCE_URL), or
                     the same title and summary    (SAME_SOURCE_CONTENT), or
                     the same normalised title     (SAME_SOURCE_TITLE) - the last
                     two not for exchange / regulator sources (dedup-v2): an NSE
                     title is the filer's name, and separate filings (a different
                     document link) can carry identical boilerplate text; those
                     join one story (STORY_RELATED) instead of being marked
                     duplicates. For them only the same link is a duplicate.
  STORY_CORRECTION   it joins an existing story and its title carries a
                     correction marker             (CORRECTION_MARKER)
  STORY_RELATED      it joins an existing story (another article, usually another
                     source)                       (STORY_SAME_URL / _SAME_TITLE / _SIMILAR)
  NEW_ARTICLE        otherwise                     (FIRST_SEEN)

An EDIT (a later observation of a stored article):
  STORY_CORRECTION   the new title gains a correction marker (CORRECTION_MARKER)
  STORY_UPDATE       the title, summary or published time changed (MATERIAL_EDIT)
  (none)             only source_updated_at changed: stored as an observation, no
                     decision (not a material change)
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any

VERSION = "dedup-v2"
WINDOW = _dt.timedelta(hours=24)
MATERIAL = ("title", "summary", "published_at")
CORRECTION = re.compile(
    r"\b(correction|corrected|corrigendum|erratum|clarification|clarifies|clarified|"
    r"retracts?|retracted|withdrawn|revised|rectification)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Prior:
    """An article the same source stored earlier (the comparison set)."""
    item_id: int
    canonical_url: str | None
    title_norm_hash: str
    content_sha256: str
    discovered_at: _dt.datetime


@dataclass(frozen=True, slots=True)
class Decision:
    decision: str
    rule: str
    related_item_id: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    version: str = VERSION


def decide_new(*, canonical_url: str | None, title_norm_hash: str, content_sha256: str,
               title: str, discovered_at: _dt.datetime, priors: list[Prior],
               exchange: bool, story_method: str | None,
               story_evidence: dict | None = None) -> Decision:
    """The decision for a newly stored article. `priors`: the same source's
    earlier articles; `story_method`: its story-v1 membership (FOUNDER when it
    started a story, None when it has none)."""
    window = [p for p in priors if discovered_at - WINDOW <= p.discovered_at <= discovered_at]
    for rule, hit in (
            ("SAME_SOURCE_URL", lambda p: canonical_url and p.canonical_url == canonical_url),
            ("SAME_SOURCE_CONTENT", lambda p: not exchange
             and p.content_sha256 == content_sha256),
            ("SAME_SOURCE_TITLE", lambda p: not exchange
             and p.title_norm_hash == title_norm_hash)):
        match = next((p for p in sorted(window, key=lambda p: p.discovered_at) if hit(p)), None)
        if match is not None:
            return Decision("DUPLICATE_ARTICLE", rule, match.item_id,
                            {"duplicate_of": match.item_id,
                             "first_seen": match.discovered_at.isoformat(),
                             "window_h": WINDOW.total_seconds() / 3600})
    joined = story_method not in (None, "FOUNDER")
    if joined and (m := CORRECTION.search(title)):
        return Decision("STORY_CORRECTION", "CORRECTION_MARKER", None,
                        {"marker": m.group(0), "story_method": story_method,
                         **(story_evidence or {})})
    if joined:
        return Decision("STORY_RELATED", f"STORY_{story_method}", None, dict(story_evidence or {}))
    return Decision("NEW_ARTICLE", "FIRST_SEEN", None, {"story_method": story_method})


def decide_edit(changed: list[str], *, old_title: str | None, new_title: str) -> Decision | None:
    """The decision for an edit of a stored article, or None when not material."""
    material = [c for c in changed if c in MATERIAL]
    if not material:
        return None
    m = CORRECTION.search(new_title)
    if "title" in material and m and not CORRECTION.search(old_title or ""):
        return Decision("STORY_CORRECTION", "CORRECTION_MARKER", None,
                        {"marker": m.group(0), "changed": material})
    return Decision("STORY_UPDATE", "MATERIAL_EDIT", None, {"changed": material})
