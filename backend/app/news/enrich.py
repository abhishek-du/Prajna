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


# ── media headlines (headline-entity-v1, media-keywords-v1) ─────────────────
HEADLINE_VERSION = "headline-entity-v2"
KEYWORD_VERSION = "media-keywords-v1"
# words that cannot identify a company on their own (a name made only of these,
# e.g. "Indian Bank", is never matched from a headline: too easy to misread)
COMMON = frozenset("""india indian bank banks gold silver power energy oil gas capital finance
financial market markets global national international general united first new steel cement
auto motors motor tech technologies technology infra infrastructure housing industries industry
services holdings investment investments share shares stock stocks fund funds life insurance
city union central federal state royal star prime future sun hindustan bharat asian america
american world home health care pharma pharmaceuticals chemicals textiles sugar paper metals
realty developers engineering systems solutions software digital media green water gujarat
maharashtra tamil nadu kerala karnataka punjab bengal delhi mumbai rajasthan and of the""".split())
_SUFFIX = frozenset({"ltd", "limited", "l", "co", "corp", "corporation", "company", "inc", "plc"})


def name_core(name: str) -> tuple[str, ...]:
    toks = name_tokens(name)
    while toks and toks[-1] in _SUFFIX:
        toks.pop()
    return tuple(toks)


class HeadlineIndex:
    """Company-name cores found as whole phrases in headlines."""

    def __init__(self, universe: Universe):
        by_core: dict[tuple[str, ...], list[tuple[str, str, str]]] = {}
        for sym, (key, name) in universe.by_symbol.items():
            core = name_core(name or "")
            if not core or all(t in COMMON for t in core):
                continue
            if len(core) == 1 and len(core[0]) < 5:
                continue
            by_core.setdefault(core, []).append((sym, key, name))
        self.cores = {c: v[0] for c, v in by_core.items() if len(v) == 1}   # unique only
        # a one-word name that starts another company's name ("Kalpataru" / "Kalpataru
        # Project Int") is used only when the headline's next word does not continue
        # that other name ("Kalpataru Projects ..." is not Kalpataru Ltd; v2: checked
        # per headline instead of dropping the name everywhere)
        self.seconds: dict[str, set[str]] = {}
        for c in by_core:
            if len(c) > 1:
                self.seconds.setdefault(c[0], set()).add(c[1])
        self.max_len = max((len(c) for c in self.cores), default=1)

    def find(self, text: str) -> list[tuple[tuple[str, ...], tuple[str, str, str]]]:
        toks = name_tokens(text)
        out, i = [], 0
        while i < len(toks):
            for n in range(min(self.max_len, len(toks) - i), 0, -1):   # longest first
                c = tuple(toks[i:i + n])
                nxt = toks[i + n] if i + n < len(toks) else ""
                if n == 1 and nxt and any(
                        nxt == w or nxt.rstrip("s") == w.rstrip("s") or w.startswith(nxt)
                        or nxt.startswith(w) for w in self.seconds.get(c[0], ())):
                    continue                   # continues another company's name
                if c in self.cores:
                    out.append((c, self.cores[c]))
                    i += n
                    break
            else:
                i += 1
        return out


# headline-entity-v2 context guards (from the 2026-09-29 mapping review: a link is
# kept only when the headline is ABOUT that company)
# a word after the name that makes it ANOTHER entity ("Kalpataru Projects",
# "Suraj Estate", "Alankit Assignments", "Premier League", "M&M Financial",
# "Tata Motors PV")
CONTINUATION = frozenset("""projects project estate estates assignments league passenger
vehicles pv cv international industries ventures holdings capital securities finance
financial fin services life general insurance housing power energy green renewables ports
airports logistics foods consumer chemicals realty developers infra infrastructure trust
amc prudential""".split())
# a name that has meant two listed companies since a demerger
AMBIGUOUS = frozenset({("tata", "motors")})
# an intermediary named as the speaker, rater or broker is not the subject
# ("CARE Ratings reaffirms ratings of ...", "Angel One sees 25% upside in ...")
INTERMEDIARY = re.compile(r"rating|securities|broking|\bamc\b|asset manag|angel one|motilal|"
                          r"crisil|icra|capital market", re.I)
ROLE_VERBS = frozenset("""sees expects reaffirms reaffirmed upgrades downgrades maintains
initiates retains assigns explains prefers rates recommends""".split())


def _words(s: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9&'\u2019.]*", s)


def context_reject(title: str, start: int, end: int, name: str) -> str | None:
    """Why a name found at title[start:end] must NOT be linked, else None."""
    before, after = _words(title[:start]), _words(title[end:])
    nxt = re.sub(r"['\u2019]s?$", "", after[0].lower().rstrip(".")) if after else ""
    prev = before[-1].lower() if before else ""
    if nxt in CONTINUATION:
        return f"followed by {after[0]!r}: another entity"
    if not after and title[:start].rstrip().endswith(":"):
        return "named after a colon at the end: an attribution"
    ordered = re.search(r"\b(orders?|contracts?|deals?)\b", title[:start], re.I)
    if (prev == "from" and ordered) or (before and nxt in ("order", "orders", "contract",
                                                             "contracts")):
        return "named as the customer of an order"
    if INTERMEDIARY.search(name) and (nxt in ROLE_VERBS or prev in ("of", "by")):
        return "an intermediary speaking / rating / recommending"
    return None


def _span(title: str, core: tuple[str, ...]) -> tuple[int, int] | None:
    pat = r"[^A-Za-z0-9]+".join(r"(?:and|&)" if t == "and" else re.escape(t) for t in core)
    m = re.search(rf"(?<![A-Za-z0-9]){pat}(?![A-Za-z0-9])", title, re.I)
    return (m.start(), m.end()) if m else None


def resolve_headline(item: ItemObs, universe: Universe | None, index: HeadlineIndex | None
                     ) -> list[Link]:
    """Every uniquely named company whose name core appears in the headline.
    Multi-word names 0.8, single distinctive words 0.6; none -> one UNRESOLVED."""
    if universe is None or index is None:
        return [Link(None, "UNRESOLVED", 0.0, item.title,
                     "instrument universe unavailable (database not reachable)",
                     HEADLINE_VERSION)]
    links, keys, rejected = [], set(), []
    for core, (_sym, key, name) in index.find(item.title):
        if key in keys:
            continue
        span = _span(item.title, core)
        why = ("a name shared by two listed companies" if core in AMBIGUOUS else
               "matched only as a lower-case word" if span and len(core) == 1
               and item.title[span[0]].islower() else
               context_reject(item.title, *span, name) if span else None)
        if why:
            rejected.append(f"{' '.join(core)}: {why}")
            continue
        keys.add(key)
        links.append(Link(key, "COMPANY_NAME", 0.8 if len(core) > 1 else 0.6, " ".join(core),
                          f"headline names {name!r}", HEADLINE_VERSION))
    return links or [Link(None, "UNRESOLVED", 0.0, item.title,
                          "; ".join(rejected) or "no uniquely named company in the headline",
                          HEADLINE_VERSION)]


_KEYWORDS: tuple[tuple[str, str], ...] = (
    (r"\bq[1-4]\b.*\b(result|profit|loss|revenue)|\bresults?\b|net profit|quarterly", "RESULTS"),
    (r"\bguidance\b|\boutlook\b.*\bfy", "GUIDANCE"),
    (r"\bipos?\b|\bqips?\b|fund ?rais|rights issue|\bofs\b", "FUNDRAISING"),
    (r"\bbuyback\b", "BUYBACK"), (r"\bbonus\b", "BONUS"), (r"stock split|\bsplit\b", "SPLIT"),
    (r"\bdividend\b", "DIVIDEND"), (r"demerger", "DEMERGER"),
    (r"acqui|merger|takeover|\bstake\b.*\bbuy", "MERGER_ACQUISITION"),
    (r"block deal|bulk deal", "BLOCK_DEAL"), (r"stake sale|sells? stake|offload", "STAKE_SALE"),
    (r"promoter", "PROMOTER_CHANGE"),
    (r"\b(bags?|bagged|wins?|won|receives?|received|secures?|secured)\b.*\b(order|contract|deal)"
     r"|\border (worth|from|win|inflow|book)", "ORDER_CONTRACT"),
    (r"target price|upgrade|downgrade|\bbuy\b|\bsell\b rating|brokerage|initiates coverage",
     "BROKERAGE_ACTION"),
    (r"credit rating|moody|fitch|\bs&p\b|crisil|icra", "RATING_CHANGE"),
    (r"insolvency|bankrupt|\bnclt\b", "BANKRUPTCY"), (r"default", "DEFAULT"),
    (r"fraud|scam|money laundering", "FRAUD_ALLEGATION"),
    (r"\bed\b raid|\bcbi\b|probe|investigat|raid", "INVESTIGATION"),
    (r"court|litigation|lawsuit|\bnclat\b|arbitration", "LITIGATION"),
    (r"\bceo\b|\bmd\b|chairman|resign|appoint", "MANAGEMENT_CHANGE"),
    (r"repo rate|rate cut|rate hike|\bmpc\b|monetary policy|\bfed\b|fomc", "INTEREST_RATE"),
    (r"inflation|\bcpi\b|\bwpi\b", "INFLATION"), (r"\bgdp\b", "GDP"),
    (r"\bfiis?\b|\bfpis?\b|\bdiis?\b|foreign invest", "FII_DII"),
    (r"crude|brent|\boil\b|\bgold\b|\bsilver\b|copper|commodit", "COMMODITIES"),
    (r"\bwar\b|iran|israel|russia|ukraine|china|tariff|sanction|geopolit", "GEOPOLITICAL"),
    (r"\bsebi\b|\brbi\b|regulat|irdai|circular", "REGULATORY"),
    (r"budget|government|ministry|\bgst\b|policy", "GOVERNMENT_POLICY"),
    (r"sensex|nifty|market (crash|rally|fall|close)|dalal street|stock market", "MARKET_WIDE"),
)
_KW = tuple((re.compile(p, re.I), c) for p, c in _KEYWORDS)


REGULATOR_VERSION = "regulator-source-v1"


def classify_regulator(item: ItemObs) -> Classification:
    """A regulator's own publication is REGULATORY by source (the section - orders,
    circulars, press releases - is kept in category_raw); keywords are not used,
    so "Settlement Order" is never read as a business order."""
    return Classification("REGULATORY", 0.9, "SOURCE_SECTION", REGULATOR_VERSION)


def classify_keywords(item: ItemObs) -> Classification:
    """First matching keyword rule on the headline; a heuristic (confidence 0.6)."""
    for rx, cat in _KW:
        if rx.search(item.title):
            return Classification(cat, 0.6, "KEYWORD_RULES", KEYWORD_VERSION)
    return Classification("OTHER", 0.3, "KEYWORD_RULES", KEYWORD_VERSION)
