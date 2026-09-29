"""Market scope of a news item, scope-v1 (pure, rule-based, explainable).

One PRIMARY scope and every other scope that also applies (secondary), from
the item's own evidence only: its event category (enrich), its resolved
company links, its entity mentions (entities, mentions-v1), a short list of
global-market words, and the kind of source. A scope routes an item; it is not
an impact claim. Nothing is dropped: an item with no market signal is stored
and labelled IRRELEVANT (low confidence), never deleted.

Primary, first rule that applies:
  REGULATORY     regulatory / investigation category, a regulator's own feed, or
                 a regulator / court named without a listed company
  CORPORATE      a corporate-event category (results, M&A, fund raise, dividend,
                 rating, management, order, default ...), listed company or not
                 (an unlisted company's IPO is a corporate event)
  COMPANY        a listed company otherwise (price moves, broker calls, filings)
  GEOPOLITICAL   geopolitical category or mention (Iran, tariffs, war ...)
  CURRENCY       rupee / dollar named
  COMMODITY      commodity category or mention (crude, gold ...)
  MACRO          macro category (rates, inflation, GDP, flows, policy) or a central
                 bank / macro indicator / bond yield / government named
  GLOBAL_MARKET  foreign markets named (Wall St, Dow, Nasdaq, S&P, Nikkei ...)
  SECTOR         a sector named, or a sector-event category
  MARKET_WIDE    market-wide category, an Indian index or exchange named
  -- only when none of the above applies (confidence 0.5):
  CORPORATE      an exchange filing (every filing is some entity's corporate disclosure,
                 even when the filer is not resolved to a listed company)
  CORPORATE      corporate-event words (IPO, listing, order win, appointment, stake ...)
  MARKET_WIDE    market words (stocks, shares, trade setup, investors, bonds, yields ...)
  IRRELEVANT     none of the above (confidence 0.3)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VERSION = "scope-v1"
METHOD = "SCOPE_RULES"
SCOPES = ("REGULATORY", "CORPORATE", "COMPANY", "GEOPOLITICAL", "CURRENCY", "COMMODITY",
          "MACRO", "GLOBAL_MARKET", "SECTOR", "MARKET_WIDE", "IRRELEVANT")

CORPORATE_EVENTS = frozenset((
    "RESULTS", "EARNINGS", "GUIDANCE", "DIVIDEND", "BONUS", "SPLIT", "BUYBACK", "FUNDRAISING",
    "MERGER_ACQUISITION", "DEMERGER", "STAKE_SALE", "BLOCK_DEAL", "PROMOTER_CHANGE",
    "MANAGEMENT_CHANGE", "ORDER_CONTRACT", "RATING_CHANGE", "DEFAULT", "BANKRUPTCY", "DEBT",
    "CORPORATE_ACTION", "FRAUD_ALLEGATION", "LITIGATION"))
REGULATORY_EVENTS = frozenset(("REGULATORY", "INVESTIGATION"))
MACRO_EVENTS = frozenset(("INTEREST_RATE", "INFLATION", "GDP", "FII_DII", "MACRO",
                          "GOVERNMENT_POLICY"))
MACRO_MENTIONS = frozenset(("CENTRAL_BANK", "MACRO_INDICATOR", "BOND_YIELD", "GOVERNMENT"))
GLOBAL = re.compile(r"\b(wall st(reet)?|dow( jones)?|nasdaq|s&p( 500)?|nikkei|hang seng|kospi|"
                    r"ftse|dax|shanghai composite|asian (markets?|stocks|shares|peers)|"
                    r"global (markets?|stocks|cues|equities)|european (markets?|stocks)|"
                    r"us (markets?|stocks|equities))\b", re.IGNORECASE)
CORPORATE_WORDS = re.compile(
    r"\b(ipos?|listing|lists|debut|gmp|bags|wins|order|orders|contract|appoints?|appointed|"
    r"resigns?|ceo|cfo|acquires?|acquisition|merger|stake|buyback|dividend|fund ?raise|raises|qip|"
    r"results|q[1-4]|net profit|revenue)\b", re.IGNORECASE)
MARKET_WORDS = re.compile(
    r"\b(stocks?|shares?|equit(y|ies)|markets?|trade setup|pre-market|opening bell|investors?|"
    r"mutual funds?|sips?|etfs?|bonds?|yields?|brokerages?|target price|rally|sell-?off|"
    r"dalal street|d-street|indices|gainers|losers|breadth|straight session)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Scope:
    primary: str
    secondary: tuple[str, ...]
    confidence: float
    evidence: dict = field(default_factory=dict)
    method: str = METHOD
    version: str = VERSION


def scope(*, title: str, category: str, companies: list[str],
          mentions: list[tuple[str, str]], source_kind: str) -> Scope:
    """`companies`: resolved instrument keys; `mentions`: (entity_type, entity_id);
    `source_kind`: the source's enrich kind (EXCHANGE / REGULATOR / HEADLINE)."""
    types = {t for t, _ in mentions}
    g = GLOBAL.search(title)
    rules = (
        ("REGULATORY", category in REGULATORY_EVENTS or source_kind == "REGULATOR"
         or (not companies and bool(types & {"REGULATOR", "COURT"}))),
        ("CORPORATE", category in CORPORATE_EVENTS),
        ("COMPANY", bool(companies) and category not in CORPORATE_EVENTS),
        ("GEOPOLITICAL", category == "GEOPOLITICAL" or "GEOPOLITICAL" in types),
        ("CURRENCY", "CURRENCY" in types),
        ("COMMODITY", category == "COMMODITIES" or "COMMODITY" in types),
        ("MACRO", category in MACRO_EVENTS or bool(types & MACRO_MENTIONS)),
        ("GLOBAL_MARKET", g is not None),
        ("SECTOR", category == "SECTOR_EVENT" or "SECTOR" in types),
        ("MARKET_WIDE", category == "MARKET_WIDE" or bool(types & {"INDEX", "EXCHANGE"})),
    )
    hits = [name for name, ok in rules if ok]
    ev = {"category": category, "companies": len(companies),
          "mentions": sorted(f"{t}:{e}" for t, e in mentions), "source_kind": source_kind}
    if g:
        ev["global_text"] = g.group(0)
    if not hits:
        if source_kind == "EXCHANGE":
            return Scope("CORPORATE", (), 0.5, {**ev, "rule": "exchange filing"})
        for name, rx in (("CORPORATE", CORPORATE_WORDS), ("MARKET_WIDE", MARKET_WORDS)):
            if m := rx.search(title):
                return Scope(name, (), 0.5, {**ev, "rule": "vocabulary", "text": m.group(0)})
        return Scope("IRRELEVANT", (), 0.3, {**ev, "rule": "no market signal"})
    # a category or a company link is stronger evidence than a word in the title
    strong = category != "OTHER" or bool(companies) or source_kind == "REGULATOR"
    return Scope(hits[0], tuple(hits[1:]), 0.8 if strong else 0.6, ev)
