"""Potential relevance of a news item (assess-v1, pure, rule-based).

This estimates POTENTIAL RELEVANCE from explicit evidence. It is not a truth
label and not a price prediction: "company receives a Rs 5,000 crore order"
is STOCK / HIGH potential impact, never "the stock will rise". Every output
lists the rule and the text that produced it.

  market_scope      STOCK (listed-company link) > SECTOR > INDEX / MARKET >
                    MACRO (central bank, macro indicator, currency, yield,
                    commodity) > GLOBAL (geopolitics); else UNKNOWN
  potential_impact  from the event category, raised to HIGH by an explicit size
                    (>= Rs 1,000 crore on an order, fund raise or deal; a move of
                    >= 5% on a single stock); OTHER is LOW with a company, else UNKNOWN
  impact_direction  explicit direction words in the headline only: POSITIVE,
                    NEGATIVE, MIXED (both), NEUTRAL ("unchanged", "flat"), else UNKNOWN
  is_breaking       observable only: (a) the source says "breaking"/"just in";
                    (b) a LIVE discovery (not backlog) of a HIGH item within 15 min
                    of its publication; (c) a second publisher confirmed the story
                    within 30 min of its first observation
Event groups: CORPORATE / MACRO / MARKET / REGULATORY / GEOPOLITICAL / OTHER.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

VERSION = "assess-v1"

GROUP = {
    **dict.fromkeys(("RESULTS", "EARNINGS", "GUIDANCE", "DIVIDEND", "BONUS", "SPLIT", "BUYBACK",
                     "FUNDRAISING", "MERGER_ACQUISITION", "DEMERGER", "STAKE_SALE", "BLOCK_DEAL",
                     "PROMOTER_CHANGE", "MANAGEMENT_CHANGE", "ORDER_CONTRACT", "RATING_CHANGE",
                     "DEFAULT", "BANKRUPTCY", "DEBT", "CORPORATE_ACTION", "BROKERAGE_ACTION",
                     "FRAUD_ALLEGATION"), "CORPORATE"),
    **dict.fromkeys(("INTEREST_RATE", "INFLATION", "GDP", "FII_DII", "COMMODITIES", "MACRO"),
                    "MACRO"),
    **dict.fromkeys(("MARKET_WIDE", "SECTOR_EVENT"), "MARKET"),
    **dict.fromkeys(("REGULATORY", "GOVERNMENT_POLICY", "INVESTIGATION", "LITIGATION"),
                    "REGULATORY"),
    "GEOPOLITICAL": "GEOPOLITICAL",
}
_HIGH = frozenset({"RESULTS", "MERGER_ACQUISITION", "DEMERGER", "BANKRUPTCY", "DEFAULT",
                   "FRAUD_ALLEGATION", "INVESTIGATION", "RATING_CHANGE", "INTEREST_RATE"})
_MEDIUM = frozenset({"ORDER_CONTRACT", "FUNDRAISING", "DIVIDEND", "BONUS", "SPLIT", "BUYBACK",
                     "MANAGEMENT_CHANGE", "BROKERAGE_ACTION", "STAKE_SALE", "BLOCK_DEAL",
                     "PROMOTER_CHANGE", "COMMODITIES", "FII_DII", "INFLATION", "GDP",
                     "REGULATORY", "GOVERNMENT_POLICY", "LITIGATION", "MARKET_WIDE",
                     "GEOPOLITICAL", "GUIDANCE", "CORPORATE_ACTION", "DEBT"})
_SIZED = frozenset({"ORDER_CONTRACT", "FUNDRAISING", "MERGER_ACQUISITION", "STAKE_SALE"})
_AMOUNT = re.compile(r"(?:rs\.?|₹|inr)\s?([\d,]+(?:\.\d+)?)\s?(crore|cr\b|lakh crore)", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_POS = re.compile(r"\b(rise|rises|rose|jump|jumps|jumped|surge|surges|surged|soar|soars|rally|"
                  r"rallies|gain|gains|gained|climb|climbs|upgrade|upgrades|beats?|record high|"
                  r"52-week high|wins?|bags?|approves?|approval|profit rises)\b", re.I)
_NEG = re.compile(r"\b(fall|falls|fell|drop|drops|dropped|slump|slumps|plunge|plunges|tumble|"
                  r"tumbles|crash|crashes|slide|slides|sink|sinks|decline|declines|"
                  r"downgrade|downgrades|miss|misses|loss|losses|52-week low|lower circuit|"
                  r"default|probe|penalty|fraud|sell-off|selloff)\b", re.I)
_NEUTRAL = re.compile(r"\b(unchanged|flat|steady|holds)\b", re.I)
_BREAKING = re.compile(r"\b(breaking|just in)\b", re.I)
_MACRO_TYPES = frozenset({"CENTRAL_BANK", "MACRO_INDICATOR", "CURRENCY", "BOND_YIELD",
                          "COMMODITY"})


@dataclass(frozen=True, slots=True)
class Assessment:
    market_scope: str
    potential_impact: str
    impact_direction: str
    is_breaking: bool
    breaking_reason: str | None
    event_group: str
    evidence: dict = field(default_factory=dict)
    basis: str = "RULES"
    version: str = VERSION


def _crore(title: str) -> float | None:
    best = None
    for num, unit in _AMOUNT.findall(title):
        v = float(num.replace(",", "")) * (100000 if unit.lower() == "lakh crore" else 1)
        best = v if best is None else max(best, v)
    return best


def assess(title: str, category: str, *, companies: list[str], mentions: list[tuple[str, str]],
           backlog: bool, published_at: _dt.datetime | None, discovered_at: _dt.datetime,
           confirmed_by: list[str] | None = None) -> Assessment:
    ev: dict = {"category": category}
    types = {t for t, _ in mentions}
    if companies:
        scope = "STOCK"
    elif "SECTOR" in types:
        scope = "SECTOR"
    elif "INDEX" in types or category == "MARKET_WIDE":
        scope = "MARKET" if category == "MARKET_WIDE" else "INDEX"
    elif types & _MACRO_TYPES:
        scope = "MACRO"
    elif "GEOPOLITICAL" in types:
        scope = "GLOBAL"
    else:
        scope = "UNKNOWN"
    ev["scope_from"] = companies[:3] or sorted(f"{t}:{e}" for t, e in mentions)[:4]

    if category in _HIGH:
        impact = "HIGH"
    elif category in _MEDIUM:
        impact = "MEDIUM"
    else:
        impact = "LOW" if companies else "UNKNOWN"
    cr = _crore(title)
    if cr is not None:
        ev["amount_crore"] = cr
        if category in _SIZED and cr >= 1000:
            impact = "HIGH"
            ev["impact_rule"] = "sized event >= Rs 1,000 crore"
    pcts = [float(p) for p in _PCT.findall(title)]
    if scope == "STOCK" and pcts and max(pcts) >= 5:
        impact = "HIGH"
        ev["impact_rule"] = f"single-stock move {max(pcts)}% >= 5%"

    pos, neg = _POS.findall(title), _NEG.findall(title)
    if pos and neg:
        direction = "MIXED"
    elif pos:
        direction = "POSITIVE"
    elif neg:
        direction = "NEGATIVE"
    elif _NEUTRAL.search(title):
        direction = "NEUTRAL"
    else:
        direction = "UNKNOWN"
    ev["direction_words"] = sorted({w.lower() for w in pos + neg})[:6]

    reason = None
    if _BREAKING.search(title):
        reason = "source labels it breaking"
    elif (not backlog and impact == "HIGH" and published_at is not None
          and _dt.timedelta(0) <= discovered_at - published_at <= _dt.timedelta(minutes=15)):
        reason = "live discovery of a HIGH item within 15 min of publication"
    elif confirmed_by:
        reason = f"confirmed by another publisher within 30 min: {sorted(confirmed_by)[:3]}"
    return Assessment(scope, impact, direction, reason is not None, reason,
                      GROUP.get(category, "OTHER"), ev)
