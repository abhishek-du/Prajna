"""Versioned enrichment of news items: classification and entity links (pure).

Every result is a proposal stamped with its method and version; the stored row
gets knowable_at = the moment it was computed, so a later re-run under a new
version is a new row and never rewrites what a past as_of saw.

Classification (NSE_SUBJECT_V1): the exchange's own announcement subject mapped
to the request's taxonomy by explicit rules; an unmapped subject is OTHER with
confidence 0.5. It is a routing aid, not ground truth.

Entity links (nse-entity-v1). The file-name prefix is the UPLOADER's code, not
always the company's (a debenture trustee files for its issuer; a filing agent
under its own code), so a symbol alone is never proof:
  EXACT_SYMBOL 1.00  the file-name symbol is an included NSE_EQ symbol AND the
                     filer name agrees with that instrument's name
  COMPANY_NAME 0.90  the filer name agrees with exactly ONE included instrument
                     name (strict: a filer word may be left unmatched only if it
                     is a filler word, parenthesised, or trails a truncated vendor
                     name; vendor names are abbreviated: "PARAS DEF AND SPCE
                     TECH L" agrees with "Paras Defence and Space Technologies
                     Limited"; "Sundaram HOME Finance" does NOT agree with
                     "SUNDARAM FINANCE LTD"); fund/ETF
                     scheme filings are never mapped by name (measured false
                     positives: "Kotak ... Nifty MNC ETF" -> "KOTAK NIFTY ETF")
  ALIAS        0.95  the same filer name was mapped EXACT_SYMBOL earlier (a name
                     seen under two symbols is ambiguous and not used)
  UNRESOLVED   0     anything else, with the reason. Nothing is guessed.
Name agreement: every token of the instrument name, in order, is a
subsequence of a filer-name token starting with the same letter, and the first
tokens match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.news.model import ItemObs, normalise_title

CLASSIFY_VERSION = "nse-subject-v1"
ENTITY_VERSION = "nse-entity-v1"

# (pattern on the NSE subject, category) - first match wins
_SUBJECT_RULES: tuple[tuple[str, str], ...] = (
    (r"financial result|results?\b", "RESULTS"),
    (r"insolvency|bankrupt|liquidation", "BANKRUPTCY"),
    (r"default|delay in (payment|servicing)", "DEFAULT"),
    (r"credit rating", "RATING_CHANGE"),
    (r"buy ?back", "BUYBACK"),
    (r"bonus", "BONUS"),
    (r"split|sub-?division", "SPLIT"),
    (r"dividend", "DIVIDEND"),
    (r"record date|book closure|corporate action", "CORPORATE_ACTION"),
    (r"demerger|scheme of arrangement", "DEMERGER"),
    (r"acquisition|amalgamation|merger|takeover", "MERGER_ACQUISITION"),
    (r"preferential|qualified institutions|\bqip\b|rights issue|fund ?raising|"
     r"allotment|issue of securities", "FUNDRAISING"),
    (r"bagging|receiving of orders|contract", "ORDER_CONTRACT"),
    (r"change in (director|management|auditor|kmp)|appointment|resignation|cessation",
     "MANAGEMENT_CHANGE"),
    (r"litigation|dispute|arbitration|legal", "LITIGATION"),
    (r"fraud|default by promoter", "FRAUD_ALLEGATION"),
    (r"investigation|search|inspection|show cause|penalt", "INVESTIGATION"),
    (r"pledge|promoter", "PROMOTER_CHANGE"),
    (r"sast|substantial acquisition|stake", "STAKE_SALE"),
    (r"redemption|payment of interest|debenture|commercial paper|regulation 5[0-9]", "DEBT"),
    (r"regulator|sebi|rbi", "REGULATORY"),
)
_COMPILED = tuple((re.compile(p, re.I), c) for p, c in _SUBJECT_RULES)


@dataclass(frozen=True, slots=True)
class Classification:
    category: str
    confidence: float
    method: str
    version: str


@dataclass(frozen=True, slots=True)
class Link:
    instrument_key: str | None
    method: str
    confidence: float
    matched_text: str | None
    reason: str | None
    version: str


def classify(item: ItemObs) -> Classification:
    subj = item.category_raw or ""
    for rx, cat in _COMPILED:
        if rx.search(subj):
            return Classification(cat, 1.0, "EXCHANGE_SUBJECT", CLASSIFY_VERSION)
    return Classification("OTHER", 0.5, "EXCHANGE_SUBJECT", CLASSIFY_VERSION)


_NORM = re.compile(r"[^0-9a-z ]+")


def name_tokens(name: str) -> list[str]:
    t = normalise_title(name.replace("&", " and "))
    return [w for w in _NORM.sub(" ", t).split() if w not in ("the",)]


def _subseq(short: str, long: str) -> bool:
    it = iter(long)
    return all(c in it for c in short)


# words that never distinguish one company from another; a filer word may be
# left unmatched only if it is one of these, was in parentheses ("(Delhi)"), or
# trails a vendor name that is visibly truncated (the master cuts at ~25 chars)
_FILLER = frozenset({"limited", "ltd", "india", "and", "the", "co", "company",
                     "corporation", "corp", "private", "pvt", "of"})
_TRUNCATED_AT = 22
_PAREN = re.compile(r"\(([^)]*)\)")


def names_agree(filer: str, instrument_name: str, *, strict: bool = False) -> bool:
    """Every instrument-name token, in order, is a same-initial subsequence of a
    filer token, and the first tokens match. strict (name-only mapping): an
    unmatched filer word must be a filler, parenthesised, or trail a truncated
    vendor name - so "Sundaram HOME Finance" never agrees with "SUNDARAM FINANCE"."""
    f, v = name_tokens(filer), name_tokens(instrument_name)
    if len(v) < 2 or not f or f[0] != v[0]:
        return False
    j, used = 0, []
    for tok in v:
        while j < len(f) and not (f[j][0] == tok[0] and _subseq(tok, f[j])):
            j += 1
        if j == len(f):
            return False
        used.append(j)
        j += 1
    if not strict:
        return True
    paren = {t for m in _PAREN.findall(filer) for t in name_tokens(m)}
    last = used[-1]
    truncated = len(instrument_name.strip()) >= _TRUNCATED_AT
    for i, tok in enumerate(f):
        if i in used or tok in _FILLER or tok in paren:
            continue
        if i > last and truncated:
            continue
        return False
    return True


_FUND = re.compile(r"mutual fund|\betf\b|fund of fund|\bscheme\b", re.I)


class Universe:
    """Included NSE_EQ instruments: symbol -> (instrument_key, name)."""

    def __init__(self, rows: dict[str, tuple[str, str]]):
        self.by_symbol = rows
        self.by_first: dict[str, list[tuple[str, str, str]]] = {}
        for sym, (key, name) in rows.items():
            toks = name_tokens(name or "")
            if toks:
                self.by_first.setdefault(toks[0], []).append((sym, key, name))

    def by_name(self, filer: str) -> list[tuple[str, str, str]]:
        toks = name_tokens(filer)
        if not toks:
            return []
        return [c for c in self.by_first.get(toks[0], [])
                if names_agree(filer, c[2], strict=True)]


class Aliases:
    """filer name (normalised) -> set of symbols, learned from EXACT links only."""

    def __init__(self) -> None:
        self._m: dict[str, set[str]] = {}

    def learn(self, name: str, symbol: str) -> None:
        self._m.setdefault(normalise_title(name), set()).add(symbol)

    def lookup(self, name: str) -> tuple[str | None, str | None]:
        got = self._m.get(normalise_title(name))
        if not got:
            return None, None
        if len(got) > 1:
            return None, f"filer name linked to several symbols {sorted(got)}"
        return next(iter(got)), None

    def to_json(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in self._m.items()}

    @classmethod
    def from_json(cls, d: dict[str, list[str]]) -> Aliases:
        a = cls()
        a._m = {k: set(v) for k, v in d.items()}
        return a


def resolve(item: ItemObs, universe: Universe | None, aliases: Aliases) -> Link:
    def un(why: str, text: str | None = None) -> Link:
        return Link(None, "UNRESOLVED", 0.0, text or item.symbol_raw or item.title, why,
                    ENTITY_VERSION)

    if universe is None:
        return un("instrument universe unavailable (database not reachable)")
    note = None
    if item.symbol_raw:
        hit = universe.by_symbol.get(item.symbol_raw)
        if hit and names_agree(item.title, hit[1]):
            aliases.learn(item.title, item.symbol_raw)
            return Link(hit[0], "EXACT_SYMBOL", 1.0, item.symbol_raw, None, ENTITY_VERSION)
        note = (f"file-name symbol {item.symbol_raw} is {hit[1]!r}, not the filer" if hit
                else f"file-name symbol {item.symbol_raw} is not an included NSE_EQ symbol")
    if _FUND.search(item.title):
        return un(note or "fund scheme filing: not mapped by name", item.title)
    cands = universe.by_name(item.title)
    if len(cands) == 1:
        sym, key, name = cands[0]
        return Link(key, "COMPANY_NAME", 0.9, name, note, ENTITY_VERSION)
    if len(cands) > 1:
        return un(f"filer name agrees with several instruments {sorted(c[0] for c in cands)}",
                  item.title)
    sym, why = aliases.lookup(item.title)
    if sym and sym in universe.by_symbol:
        return Link(universe.by_symbol[sym][0], "ALIAS", 0.95, item.title,
                    "filer name previously filed under this symbol", ENTITY_VERSION)
    return un(why or note or "no symbol in the filing link and no name match", item.title)
