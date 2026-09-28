"""Non-company entity mentions and reviewed company aliases (pure).

Mentions (mentions-v1): indices, sectors, commodities, currencies, bond yields,
geopolitics, regulators, governments, central banks, macro indicators,
exchanges and courts. They are found by explicit word patterns in the title,
and each mention records the exact text that matched (evidence). A mention is
a routing aid, never a claim about impact.

Company aliases (alias-v1): a SHORT reviewed list of unambiguous market
abbreviations. They match only as the exact upper-case token in the ORIGINAL
headline (so "sbi" inside a word never matches) and resolve only when the
symbol is in the included NSE_EQ universe. They are fail-closed: an alias
followed by the word that makes it another company's name is ignored ("SBI
Life", "L&T Finance", "M&M Financial"). Ambiguous abbreviations ("HDFC",
"Tata", "Adani", "Bajaj", "Birla") are deliberately absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.news.enrich import Link, Universe, name_tokens
from app.news.model import ItemObs

MENTION_VERSION = "mentions-v1"
ALIAS_VERSION = "alias-v1"

# (entity_type, entity_id, pattern) - case-insensitive, word-bounded
_MENTIONS: tuple[tuple[str, str, str], ...] = (
    ("INDEX", "NIFTY_BANK", r"\b(bank nifty|nifty bank)\b"),
    ("INDEX", "NIFTY_50", r"\bnifty(\s?50)?\b(?!\s?(bank|it|pharma|auto|metal|fmcg|midcap|smallcap|"
                          r"realty|psu|energy|media|financial))"),
    ("INDEX", "SENSEX", r"\bsensex\b"),
    ("INDEX", "NIFTY_MIDCAP", r"\b(nifty )?midcap\b"),
    ("INDEX", "NIFTY_SMALLCAP", r"\b(nifty )?smallcap\b"),
    ("INDEX", "INDIA_VIX", r"\b(india )?vix\b"),
    ("SECTOR", "BANKING", r"(?<!nifty )\b(banks?|banking|psu banks?|lenders?)\b"),
    ("SECTOR", "IT", r"\b(it stocks|it sector|it services|tech stocks)\b"),
    ("SECTOR", "PHARMA", r"\b(pharma|pharmaceuticals?)\b"),
    ("SECTOR", "AUTO", r"\b(auto stocks|automobile|auto sector|two-wheeler|carmakers?)\b"),
    ("SECTOR", "METALS", r"\b(metal stocks|metals|steel sector)\b"),
    ("SECTOR", "REALTY", r"\b(realty|real estate)\b"),
    ("SECTOR", "INSURANCE", r"\binsur(ance|ers)\b"),
    ("SECTOR", "ENERGY", r"\b(oil and gas|oil & gas|power sector|renewables?)\b"),
    ("SECTOR", "FMCG", r"\bfmcg\b"),
    ("SECTOR", "DEFENCE", r"\bdefen[cs]e stocks?\b"),
    ("COMMODITY", "CRUDE_OIL", r"\b(crude|brent|wti|oil prices?)\b|\boil\b(?! india| and gas|"
                               r" & gas| marketing)"),
    ("COMMODITY", "GOLD", r"\bgold\b"),
    ("COMMODITY", "SILVER", r"\bsilver\b"),
    ("COMMODITY", "COPPER", r"\bcopper\b"),
    ("COMMODITY", "NATURAL_GAS", r"\bnatural gas\b"),
    ("CURRENCY", "INR", r"\b(rupee|inr)\b"),
    ("CURRENCY", "USD", r"\b(dollar|usd|dxy)\b"),
    ("BOND_YIELD", "US_10Y", r"\b(us|u\.s\.|treasury)\b.{0,30}\byields?\b|\b10-year\b"),
    ("BOND_YIELD", "IN_GSEC", r"\b(g-sec|gilt|india bond|government bond)"),
    ("GEOPOLITICAL", "US_IRAN", r"\biran\b"),
    ("GEOPOLITICAL", "ISRAEL", r"\bisrael\b"),
    ("GEOPOLITICAL", "RUSSIA_UKRAINE", r"\b(russia|ukraine)\b"),
    ("GEOPOLITICAL", "US_CHINA", r"\b(china|chinese|beijing)\b"),
    ("GEOPOLITICAL", "TARIFFS", r"\b(tariffs?|sanctions?|trade war)\b"),
    ("GEOPOLITICAL", "WAR_CONFLICT", r"\b(war|conflict|missile|strike on)\b"),
    ("REGULATOR", "SEBI", r"\bsebi\b"),
    ("REGULATOR", "IRDAI", r"\birdai\b"),
    ("REGULATOR", "TRAI", r"\btrai\b"),
    ("REGULATOR", "CCI", r"\bcci\b"),
    ("REGULATOR", "US_FDA", r"\b(us )?fda\b"),
    ("CENTRAL_BANK", "RBI", r"\b(rbi|reserve bank)\b"),
    ("CENTRAL_BANK", "US_FED", r"\b(fed|federal reserve|fomc)\b"),
    ("CENTRAL_BANK", "ECB", r"\becb\b"),
    ("CENTRAL_BANK", "BOJ", r"\b(boj|bank of japan)\b"),
    ("GOVERNMENT", "INDIA_GOVT", r"\b(government|govt|centre|ministry|finance minister|"
                                 r"budget|cabinet|gst council)\b"),
    ("MACRO_INDICATOR", "INFLATION", r"\b(inflation|cpi|wpi)\b"),
    ("MACRO_INDICATOR", "GDP", r"\bgdp\b"),
    ("MACRO_INDICATOR", "PMI", r"\bpmi\b"),
    ("MACRO_INDICATOR", "IIP", r"\biip\b"),
    ("MACRO_INDICATOR", "TRADE_DEFICIT", r"\btrade deficit\b"),
    ("MACRO_INDICATOR", "FII_DII_FLOWS", r"\b(fiis?|fpis?|diis?|foreign investors?)\b"),
    ("EXCHANGE", "NSE", r"\bnse\b"),
    ("EXCHANGE", "BSE", r"\bbse\b"),
    ("COURT", "SUPREME_COURT", r"\bsupreme court\b"),
    ("COURT", "HIGH_COURT", r"\bhigh court\b"),
    ("COURT", "NCLT_NCLAT", r"\bnclt\b|\bnclat\b"),
    ("COURT", "SAT", r"\bsecurities appellate\b"),
)
_COMPILED = tuple((t, e, re.compile(p, re.I)) for t, e, p in _MENTIONS)

# reviewed abbreviation -> NSE trading symbol (checked against the universe at use)
ALIASES: dict[str, str] = {
    "RIL": "RELIANCE", "SBI": "SBIN", "TCS": "TCS", "HUL": "HINDUNILVR", "L&T": "LT",
    "M&M": "M&M", "ITC": "ITC", "BEL": "BEL", "HAL": "HAL", "BHEL": "BHEL", "ONGC": "ONGC",
    "NTPC": "NTPC", "GAIL": "GAIL", "SAIL": "SAIL", "IOC": "IOC", "BPCL": "BPCL",
    "HPCL": "HINDPETRO", "IRCTC": "IRCTC", "LIC": "LICI", "NMDC": "NMDC", "IRFC": "IRFC",
    "PNB": "PNB", "BoB": "BANKBARODA", "IndiGo": "INDIGO", "Infy": "INFY",
}


# a word after an abbreviation that usually names a DIFFERENT group company
_GROUP_WORDS = frozenset("""life finance financial fin housing capital securities insurance
general amc mutual cards holdings ventures infotech technologies tech realty power energy
green renewables ports airports logistics foods consumer pharma chemicals""".split())


@dataclass(frozen=True, slots=True)
class Mention:
    entity_type: str
    entity_id: str
    confidence: float
    evidence: str
    version: str = MENTION_VERSION


def mentions(item: ItemObs) -> list[Mention]:
    """Non-company entities named in the headline (one per entity, first match)."""
    out, seen = [], set()
    for t, e, rx in _COMPILED:
        m = rx.search(item.title)
        if m and (t, e) not in seen:
            seen.add((t, e))
            out.append(Mention(t, e, 0.9, m.group(0)))
    return out


def _token_spans(title: str):
    """Upper-case-bearing tokens of the ORIGINAL title with the rest of the title."""
    for m in re.finditer(r"[A-Za-z][A-Za-z&]*", title):
        yield m.group(0), title[m.end():]


def alias_links(item: ItemObs, universe: Universe | None) -> list[Link]:
    """Reviewed abbreviations as exact tokens; an alias that starts another listed
    company's name together with the next word is ignored (fail-closed)."""
    if universe is None:
        return []
    firsts = {tuple(name_tokens(n or ""))[:4] for _k, n in universe.by_symbol.values()}
    out, keys = [], set()
    for tok, rest in _token_spans(item.title):
        sym = ALIASES.get(tok)
        if not sym or sym not in universe.by_symbol:
            continue
        key, name = universe.by_symbol[sym]
        nxt = name_tokens(rest)[:1]
        longer = tuple(name_tokens(tok) + nxt)
        own = tuple(name_tokens(name or ""))
        if nxt and (nxt[0] in _GROUP_WORDS or any(
                f[:len(longer)] == longer and f[:len(longer)] != own[:len(longer)]
                for f in firsts)):
            continue                       # "SBI Life", "L&T Finance", "M&M Financial"
        if key not in keys:
            keys.add(key)
            out.append(Link(key, "ALIAS", 0.85, tok, f"reviewed alias {tok} -> {sym} ({name})",
                            ALIAS_VERSION))
    return out
