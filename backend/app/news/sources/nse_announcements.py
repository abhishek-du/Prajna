"""NSE corporate announcements RSS (pilot adapter, decision NEWS-PILOT). PURE parse.

Feed: https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml
Measured 2026-09-28 (tests/fixtures/nse_announcements): ~1,200 items covering the
current day, <ttl>5</ttl>, ETag + Last-Modified supported.

  <item>
    <title>Company Name Limited</title>                 the filer
    <link>https://nsearchives.nseindia.com/corporate/SYMBOL_ddmmyyyyHHMMSS_x.pdf</link>
    <description>... has informed the Exchange ... |SUBJECT: Trading Window</description>
    <pubDate>28-Sep-2026 15:31:17</pubDate>             IST wall time, NO zone
  </item>

- The NSE symbol is read ONLY from /corporate/<SYMBOL>_<14 digits>_ file names
  (the exchange's own naming). XBRL (/corporate/xbrl/...), debt (/content/debt/...)
  and mutual-fund NAV items (empty link) carry no symbol: symbol_raw is None and
  entity resolution decides (never guessed here).
- source_article_id = the link (one filing = one document); items without a link
  use a hash of (title, description, pubDate).
- publisher = "NSE" (the exchange disseminates the filing); the filer is the title.
- The body is the PDF attachment: not fetched (content_available False).
"""

from __future__ import annotations

import datetime as _dt
import re
import xml.etree.ElementTree as ET

from app.core.clock import IST, UTC
from app.news.model import ItemObs, ParsedFeed, ParseIssue, stable_id

KEY = "NSE_ANNOUNCEMENTS"
URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
PUBLISHER = "NSE"
_SYMBOL = re.compile(r"^https?://nsearchives\.nseindia\.com/corporate/([A-Za-z0-9&\-]+?)_\d{14}_")
_SUBJECT = re.compile(r"\|\s*SUBJECT:\s*(.+?)\s*$", re.S)


class FeedDecodeError(ValueError):
    """Not an RSS document at all (the raw bytes stay archived)."""


def parse_pubdate(raw: str | None) -> _dt.datetime | None:
    """'28-Sep-2026 15:31:17' (IST wall time) -> UTC."""
    if not raw:
        return None
    try:
        return _dt.datetime.strptime(raw.strip(), "%d-%b-%Y %H:%M:%S").replace(
            tzinfo=IST).astimezone(UTC)
    except ValueError:
        return None


def symbol_from_link(link: str | None) -> str | None:
    m = _SYMBOL.match(link or "")
    return m.group(1).upper() if m else None


def parse(body: bytes) -> ParsedFeed:
    # untrusted XML: RSS needs no DTD, so any DOCTYPE/ENTITY declaration is refused
    # before parsing (entity expansion); expat >= 2.4 also limits amplification and
    # ElementTree never resolves external entities
    head = body[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in body.lower():
        raise FeedDecodeError("DTD/entity declarations are refused")
    try:
        root = ET.fromstring(body)  # noqa: S314 - guarded above
    except ET.ParseError as e:
        raise FeedDecodeError(f"not XML: {e}") from None
    ch = root.find("channel")
    if root.tag != "rss" or ch is None:
        raise FeedDecodeError(f"not an RSS channel (root <{root.tag}>)")
    out = ParsedFeed()
    ttl = (ch.findtext("ttl") or "").strip()
    out.ttl_minutes = int(ttl) if ttl.isdigit() else None
    seen: set[str] = set()
    for it in ch.findall("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip() or None
        desc = (it.findtext("description") or "").strip() or None
        raw = (it.findtext("pubDate") or "").strip() or None
        if not title:
            out.issues.append(ParseIssue("MALFORMED_ITEM", f"item without title (link {link})"))
            continue
        pub = parse_pubdate(raw)
        if raw and pub is None:
            out.issues.append(ParseIssue("BAD_TIMESTAMP", f"unparseable pubDate {raw!r}"))
        sid = link or stable_id(title, desc, raw)
        if sid in seen:
            out.issues.append(ParseIssue("DUPLICATE_IN_FEED", sid[:200]))
            continue
        seen.add(sid)
        m = _SUBJECT.search(desc or "")
        out.items.append(ItemObs(
            source_article_id=sid, title=title, url=link, publisher=PUBLISHER,
            published_at=pub, published_at_raw=raw, summary=desc,
            category_raw=m.group(1).strip() if m else None, symbol_raw=symbol_from_link(link),
            attachment_url=link, language="en", region="IN"))
    return out
