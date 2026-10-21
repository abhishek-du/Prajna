"""Analyst actions and headline sentiment per company (features-v5; docs/STAGE3_FEATURES_V5.md).
Pure. RULE-BASED (analyst-v1): explicit words in the headline only, not a model and not a
truth label; a headline about several companies is never attributed (the caller passes
only headlines linked to exactly one instrument).

  action(title)  UP: an upgrade ("upgrades", "upgraded to 'Buy'", "EPS upgrades") or a
                 raised target ("raises target", "target price raised"); DOWN: the
                 opposite; None: neither, or both (a mixed headline counts for nothing).
                 Not analyst actions: "to upgrade" (a project), an index reclassification
                 ("largecap upgrade"), an upgrade "market"
  sentiment      mean over articles of the headline direction (app.news.assess, rules):
                 POSITIVE +1, NEGATIVE -1, MIXED 0, NEUTRAL 0; UNKNOWN is not counted
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Iterable, Sequence
from typing import Any

from app.features.compute import MISSING_INPUT, NOT_APPLICABLE, Result, miss, ok

VERSION = "analyst-v1"
_NOT = re.compile(r"\bto\s+upgrade\b|\b(large|mid|small)\s*cap\s+upgrade|\bupgrade\s+"
                  r"(market|systems?|projects?|works?|plan)\b", re.I)
# a raised / cut target: at most 3 words between the verb and "(price) target", none of them
# an amount ("raises Rs 450 crore ... targets Rs 1,500 crore" is a fund raise)
_GAP = r"\s+(?:(?![\d₹]|rs\b|inr\b|crore\b)[\w'\u2019.&-]+\s+){0,3}(?:price\s+)?targets?\b"
_UP = re.compile(r"\bupgrade[sd]?\b|\b(?:raises?|raised|raising|hikes?|hiked|lifts?|lifted|ups|"
                 r"increases?|increased)" + _GAP + r"|\btargets?\s+(?:price\s+)?"
                 r"(?:raised|hiked|upgraded?|upgrades)\b", re.I)
_DOWN = re.compile(r"\bdowngrade[sd]?\b|\b(?:cuts?|cutting|lowers?|lowered|slash(?:es|ed)?|"
                   r"trims?|trimmed|reduces?|reduced)" + _GAP + r"|\btargets?\s+(?:price\s+)?"
                   r"(?:cut|lowered|slashed|trimmed|downgraded?)\b", re.I)
PREFILTER = r"(upgrade|downgrade|target)"
WINDOW = _dt.timedelta(days=30)
DIRECTION_SCORE = {"POSITIVE": 1.0, "NEGATIVE": -1.0, "MIXED": 0.0, "NEUTRAL": 0.0}


def action(title: str | None) -> str | None:
    t = _NOT.sub(" ", title or "")
    up, down = bool(_UP.search(t)), bool(_DOWN.search(t))
    return "UP" if up and not down else "DOWN" if down and not up else None


def counts(headlines: Iterable[tuple[_dt.datetime, str | None]], as_of: _dt.datetime,
           covered: bool) -> tuple[Result, Result]:
    """(upgrades, downgrades) of the WINDOW before as_of; (MISSING_INPUT,)*2 uncovered."""
    if not covered:
        return miss(MISSING_INPUT), miss(MISSING_INPUT)
    acts = [action(t) for at, t in headlines if as_of - at <= WINDOW]
    return ok(float(acts.count("UP"))), ok(float(acts.count("DOWN")))


def sentiment(rows: Sequence[dict[str, Any]], as_of: _dt.datetime, hours: int) -> Result:
    """Rows: the company's de-duplicated multi-source articles (coverage checked by the
    caller); none with a known direction in the window -> NOT_APPLICABLE."""
    cut = as_of - _dt.timedelta(hours=hours)
    s = [DIRECTION_SCORE[r["impact_direction"]] for r in rows
         if r["knowable_at"] > cut and r.get("impact_direction") in DIRECTION_SCORE]
    return ok(sum(s) / len(s)) if s else miss(NOT_APPLICABLE)
