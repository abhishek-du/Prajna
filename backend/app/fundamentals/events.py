"""Results events from NSE announcements (docs/STAGE1_FUNDAMENTALS_RND.md F2, F1, F5b;
approved 2026-10-19). PURE: text in, events out; no I/O.

  INTIMATION   "Board Meeting to be held on 26-Oct-2026 to consider ... Financial results
               ... for the period ended September 2026": the results calendar (F2)
  OUTCOME      the results themselves were disseminated (Outcome of Board Meeting with
               financial results, Financial Results Updates, Integrated Filing- Financial):
               the trigger of the event-driven fundamentals refresh (F1)
  ESTIMATE_NEWS  a results headline that says the numbers beat / missed / matched the
               street's estimates (F5b): BEAT, MISS, INLINE, MIXED

Every event keeps the text's sha256 and the parser version; nothing here guesses a
date that the text does not state (an unparsed date is None, and counted).
"""

from __future__ import annotations

import calendar
import datetime as _dt
import hashlib
import re
from dataclasses import dataclass

PARSER_VERSION = "results-events-v1"
KINDS = ("INTIMATION", "OUTCOME", "HISTORICAL_FILING", "ESTIMATE_NEWS")
VERDICTS = ("BEAT", "MISS", "INLINE", "MIXED")
OUTCOME_CATEGORIES = ("Financial Results Updates", "Integrated Filing- Financial")
OUTCOME_IF_RESULTS = ("Outcome of Board Meeting", "Outcome of Board Meeting-XBRL")
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
_MONTHS["sept"] = 9

_RESULTS = re.compile(r"financial\s+results?", re.I)
_MEETING = re.compile(r"board\s+meeting\s+to\s+be\s+held\s+on\s+(\d{1,2})[-/ ]([A-Za-z]{3,9})"
                      r"[-/ ,]+(\d{4})", re.I)
_ENDED = re.compile(r"\bended\s+(?:on\s+)?(.{3,24}?\d{4})", re.I)
_KIND = (("H", re.compile(r"half[\s-]*year", re.I)),
         ("9M", re.compile(r"nine\s+months", re.I)),
         ("Q", re.compile(r"quarter", re.I)),
         ("FY", re.compile(r"\b(annual|year\s+ended|financial\s+year)\b", re.I)))

# "Street" alone counts ("misses Street"), but not inside "D-Street" (the market)
_EST = r"(estimates?|expectations?|(?<![-\w])street|forecasts?|consensus|poll)"
_BEAT = re.compile(r"\b(beats?|beating|tops?|topped|above|exceeds?|exceeded|surpass\w*|"
                   r"ahead\s+of)\b[^.|;]{0,40}?\b" + _EST + r"\b", re.I)
_MISS = re.compile(r"\b(miss(es|ed)?|below|lags?|lagged|falls?\s+short\s+of|fell\s+short\s+of|"
                   r"trails?)\b[^.|;]{0,40}?\b" + _EST + r"\b", re.I)
_INLINE = re.compile(r"\bin[\s-]+line\s+with\b[^.|;]{0,20}?\b" + _EST + r"\b", re.I)
_RESULTS_CONTEXT = re.compile(r"\b(Q[1-4]|results?|earnings|profit|revenue|PAT|EBITDA|"
                              r"margin|NII)\b", re.I)
_FQ = re.compile(r"\bQ([1-4])\b", re.I)


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    meeting_date: _dt.date | None = None
    period_end: _dt.date | None = None
    period_kind: str | None = None
    verdict: str | None = None
    flags: tuple[str, ...] = ()


def text_sha256(*parts: str | None) -> str:
    return hashlib.sha256("\x1f".join(p or "" for p in parts).encode()).hexdigest()


def _month_end(year: int, month: int) -> _dt.date:
    return _dt.date(year, month, calendar.monthrange(year, month)[1])


def parse_period_end(fragment: str) -> _dt.date | None:
    """'September 2026', 'September 30, 2026', '30th September, 2026', '30.09.2026',
    'Sept. 30 2026' -> the month end (Indian results periods end on a month end)."""
    f = fragment.strip()
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", f)
    if m:
        mo, yr = int(m.group(2)), int(m.group(3))
        return _month_end(yr, mo) if 1 <= mo <= 12 else None
    yr = re.search(r"(\d{4})", f)
    for w in re.findall(r"[A-Za-z]+", f):
        mo = _MONTHS.get(w.lower().rstrip("."))
        if mo and yr:
            return _month_end(int(yr.group(1)), mo)
    return None


def period_kind(text: str) -> str | None:
    for k, rx in _KIND:
        if rx.search(text):
            return k
    return None


def _ended(text: str) -> _dt.date | None:
    m = _ENDED.search(text)
    return parse_period_end(m.group(1)) if m else None


def _period(txt: str, latest: _dt.date | None) -> tuple[_dt.date | None, tuple[str, ...]]:
    """The stated period end; a period ending after `latest` (results cannot precede
    their period: a filer's typo such as 'June 2027' in October 2026) is dropped,
    never guessed, and flagged."""
    pe = _ended(txt)
    if pe is not None and latest is not None and pe > latest:
        return None, ("PERIOD_AFTER_MEETING",)
    return pe, ()


def classify_announcement(category: str | None, summary: str | None,
                          published: _dt.date | None = None) -> Event | None:
    """An NSE announcement -> INTIMATION / OUTCOME, or None (not about results)."""
    cat, txt = (category or "").strip(), summary or ""
    if cat == "Board Meeting Intimation":
        if not _RESULTS.search(txt):
            return None
        m = _MEETING.search(txt)
        md = None
        if m:
            mo = _MONTHS.get(m.group(2).lower())
            try:
                md = _dt.date(int(m.group(3)), mo, int(m.group(1))) if mo else None
            except ValueError:
                md = None
        pe, fl = _period(txt, md or published)
        return Event("INTIMATION", meeting_date=md, period_end=pe,
                     period_kind=period_kind(txt), flags=fl)
    if cat in OUTCOME_CATEGORIES or (cat in OUTCOME_IF_RESULTS and _RESULTS.search(txt)):
        pe, fl = _period(txt, published)
        return Event("OUTCOME", period_end=pe, period_kind=period_kind(txt), flags=fl)
    return None


def fiscal_quarter_end(q: int, published: _dt.date) -> _dt.date:
    """Indian fiscal quarter Qn (Q1 = Apr-Jun ... Q4 = Jan-Mar): the latest end of that
    quarter on or before the publication date."""
    month = {1: 6, 2: 9, 3: 12, 4: 3}[q]
    y = published.year
    end = _month_end(y, month)
    return end if end <= published else _month_end(y - 1, month)


def estimate_verdict(title: str | None) -> str | None:
    """A results headline -> BEAT / MISS / INLINE / MIXED, or None."""
    t = title or ""
    if not _RESULTS_CONTEXT.search(t):
        return None
    beat, miss, inline = bool(_BEAT.search(t)), bool(_MISS.search(t)), bool(_INLINE.search(t))
    if beat and miss:
        return "MIXED"
    if beat:
        return "BEAT"
    if miss:
        return "MISS"
    return "INLINE" if inline else None


def classify_news(title: str | None, published: _dt.date) -> Event | None:
    v = estimate_verdict(title)
    if v is None:
        return None
    m = _FQ.search(title or "")
    pe = fiscal_quarter_end(int(m.group(1)), published) if m else None
    return Event("ESTIMATE_NEWS", period_end=pe, period_kind="Q" if pe else None, verdict=v)
