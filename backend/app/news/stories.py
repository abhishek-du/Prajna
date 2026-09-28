"""Story grouping across publishers (story-v1, pure).

An article joins an existing story only on explicit evidence, recorded with it:

  SAME_URL    same canonical URL                                   score 1.0
  SAME_TITLE  same normalised title                                0.95
  SIMILAR     title-word Jaccard J (content words) AND time proximity AND a
              corroborating signal:
                J >= 0.25, |dt| <= 2 h, a shared listed company, same event category
                J >= 0.50, |dt| <= 6 h, a shared company, or (neither has a company
                           AND a shared non-company entity AND the same category)
                J >= 0.70, |dt| <= 3 h (near-identical wording alone)
                                                                   score J
  otherwise the article FOUNDS a new story.
Regulator and exchange documents (SEBI orders, NSE filings) share title templates
while concerning different parties ("Remittance Order ... RC No. 9209" vs
"... 9207"), so for them only SAME_URL / SAME_TITLE apply (measured 2026-09-28).

Point in time: only members that were knowable when the new article was
discovered are candidates, so a snapshot never learns a grouping early, and a
later article joining a story is a new membership row with its own knowable_at.
Source-level observations are never merged or destroyed.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from app.news.enrich import name_tokens

VERSION = "story-v1"
WINDOW = _dt.timedelta(hours=6)
_STOP = frozenset("""a an the of in on at to for and or as by with from is are was were be be
its it this that after before over under amid into up down new says said may will could
shares share stock stocks today live updates update news report reports rs crore cr lakh
per cent percent here what why how check key""".split())


def words(title: str) -> frozenset[str]:
    return frozenset(t for t in name_tokens(title) if t not in _STOP and not t.isdigit()
                     and len(t) > 1)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass(slots=True)
class Member:
    item_key: str                 # "<source>|<source_article_id>"
    story_id: str
    source: str
    words: frozenset[str]
    canonical_url: str | None
    title_hash: str
    companies: frozenset[str]
    entities: frozenset[str]      # non-company mentions "TYPE:ID"
    category: str
    t: _dt.datetime               # published_at, else discovered_at (proximity only)
    knowable_at: _dt.datetime     # when Prajna knew this member
    strict: bool = False          # regulator/exchange documents: exact matches only


@dataclass(frozen=True, slots=True)
class Assignment:
    story_id: str | None          # None = founds a new story
    method: str                   # FOUNDER / SAME_URL / SAME_TITLE / SIMILAR
    score: float
    evidence: dict


@dataclass(slots=True)
class StoryIndex:
    members: list[Member] = field(default_factory=list)
    next_id: int = 1

    def new_id(self) -> str:
        sid = f"S{self.next_id}"
        self.next_id += 1
        return sid

    def assign(self, m: Member, at: _dt.datetime) -> Assignment:
        """Decide `m`'s story using only members knowable at `at`."""
        best: tuple[float, str, Member, dict] | None = None
        for c in self.members:
            if c.knowable_at > at or c.item_key == m.item_key or abs(c.t - m.t) > WINDOW:
                continue
            dt_min = round(abs((c.t - m.t).total_seconds()) / 60, 1)
            ev = {"with": c.item_key, "with_source": c.source, "dt_minutes": dt_min}
            if m.canonical_url and m.canonical_url == c.canonical_url:
                cand = (1.0, "SAME_URL", c, ev)
            elif m.title_hash == c.title_hash:
                cand = (0.95, "SAME_TITLE", c, ev)
            elif m.strict or c.strict:
                continue          # each filing/order is its own legal document
            else:
                j = jaccard(m.words, c.words)
                shared_co = sorted(m.companies & c.companies)
                shared_en = sorted(m.entities & c.entities)
                same_cat = m.category == c.category and m.category != "OTHER"
                hrs = dt_min / 60
                ok = ((j >= 0.25 and hrs <= 2 and shared_co and same_cat)
                      or (j >= 0.5 and hrs <= 6 and (shared_co or (
                          not m.companies and not c.companies and shared_en and same_cat)))
                      or (j >= 0.7 and hrs <= 3))
                if not ok:
                    continue
                ev |= {"jaccard": round(j, 3), "shared_companies": shared_co,
                       "shared_entities": shared_en, "same_category": same_cat}
                cand = (round(j, 4), "SIMILAR", c, ev)
            if best is None or cand[0] > best[0]:
                best = cand
        if best is None:
            return Assignment(None, "FOUNDER", 1.0, {"reason": "no matching earlier article"})
        return Assignment(best[2].story_id, best[1], best[0], best[3])

    def add(self, m: Member) -> None:
        self.members.append(m)

    def prune(self, now: _dt.datetime) -> None:
        self.members = [c for c in self.members if now - c.t <= WINDOW * 2]
