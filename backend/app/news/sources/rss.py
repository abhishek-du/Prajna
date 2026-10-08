"""Generic media feed parsers (PURE): RSS 2.0 and Google-News sitemaps.

Measured 2026-09-28 (tests/fixtures/news_media):
  ET, Business Standard, BusinessLine, Livemint   RSS 2.0; pubDate RFC-822 with +0530;
      guid = the article URL (BusinessLine: "article-<n>", isPermaLink=false)
      Business Standard adds bs:lastModification (-> source_updated_at), dc:publisher
      BusinessLine declares <ttl>60</ttl> (polled at most hourly)
  CNBC-TV18   Google-News sitemap: <url><loc> + news:publication_date (ISO-8601),
      news:title, news:keywords; <lastmod> (-> source_updated_at)

Stored (decision NEWS-CONTENT): title, URL, the feed's short description (HTML
stripped, cut at 500 characters), times, category. Never the article body here.
"""

from __future__ import annotations

import datetime as _dt
import email.utils
import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

from app.core.clock import UTC
from app.news.model import ItemObs, ParsedFeed, ParseIssue, stable_id

SUMMARY_MAX = 500
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
NS = {"dc": "http://purl.org/dc/elements/1.1/", "bs": "https://www.business-standard.com/rss/",
      "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
      "news": "http://www.google.com/schemas/sitemap-news/0.9"}


class FeedDecodeError(ValueError):
    """Not a feed of the expected kind (the raw bytes stay archived)."""


# a "&" that does not start a character or entity reference (publishers emit bare
# ampersands: Business Standard, 2026-10-06, "T&D sector" in <media:title> made the
# whole feed unparseable for most of the day)
_BARE_AMP = re.compile(rb"&(?!#[0-9]+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9._-]*;)")


def parse_xml(body: bytes) -> tuple[ET.Element, bool]:
    """Untrusted XML -> (root, repaired). Feeds need no DTD: any DOCTYPE / ENTITY
    declaration is refused before parsing. A strict parse comes first; only if it
    fails, ONE retry with bare ampersands escaped (no entity is ever expanded, no
    other repair is attempted). Anything else that is malformed stays MALFORMED."""
    if b"<!doctype" in body[:4096].lower() or b"<!entity" in body.lower():
        raise FeedDecodeError("DTD/entity declarations are refused")
    try:
        return ET.fromstring(body), False  # noqa: S314 - guarded above
    except ET.ParseError as e:
        first = e
    fixed = _BARE_AMP.sub(b"&amp;", body)
    if fixed != body:
        try:
            return ET.fromstring(fixed), True  # noqa: S314 - guarded above
        except ET.ParseError:
            pass
    raise FeedDecodeError(f"not XML: {first}") from None


def _root(body: bytes, want: str, issues: list | None = None) -> ET.Element:
    root, repaired = parse_xml(body)
    if repaired and issues is not None:
        issues.append(ParseIssue("REPAIRED_XML", "bare '&' escaped before parsing"))
    if root.tag.split("}")[-1] != want:
        raise FeedDecodeError(f"expected <{want}>, got <{root.tag}>")
    return root


def clean(text: str | None, limit: int = SUMMARY_MAX) -> str | None:
    if not text:
        return None
    t = _WS.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()
    return (t[:limit - 1] + "…" if len(t) > limit else t) or None


def rfc822(raw: str | None) -> _dt.datetime | None:
    if not raw:
        return None
    try:
        d = email.utils.parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        return None
    return d.astimezone(UTC) if d and d.tzinfo else None     # a zone-less time is not guessed


def iso(raw: str | None) -> _dt.datetime | None:
    if not raw:
        return None
    try:
        d = _dt.datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return d.astimezone(UTC) if d.tzinfo else None


def rss_parser(publisher: str) -> Callable[[bytes], ParsedFeed]:
    def parse(body: bytes) -> ParsedFeed:
        out = ParsedFeed()
        ch = _root(body, "rss", out.issues).find("channel")
        if ch is None:
            raise FeedDecodeError("RSS without <channel>")
        ttl = (ch.findtext("ttl") or "").strip()
        out.ttl_minutes = int(ttl) if ttl.isdigit() else None
        seen: set[str] = set()
        for it in ch.findall("item"):
            title = clean(it.findtext("title"), 1000)
            link = (it.findtext("link") or "").strip() or None
            if not title:
                out.issues.append(ParseIssue("MALFORMED_ITEM", f"item without title ({link})"))
                continue
            raw = (it.findtext("pubDate") or "").strip() or None
            pub = rfc822(raw)
            if raw and pub is None:
                out.issues.append(ParseIssue("BAD_TIMESTAMP", f"unparseable pubDate {raw!r}"))
            guid = (it.findtext("guid") or "").strip()
            sid = link or guid or stable_id(title, raw)
            if guid and not guid.startswith("http"):
                sid = f"{publisher}:{guid}"                    # BusinessLine "article-<n>"
            if sid in seen:
                out.issues.append(ParseIssue("DUPLICATE_IN_FEED", sid[:200]))
                continue
            seen.add(sid)
            cats = [c.text.strip() for c in it.findall("category") if c.text and c.text.strip()]
            out.items.append(ItemObs(
                source_article_id=sid, title=title, url=link,
                publisher=(it.findtext("dc:publisher", namespaces=NS) or publisher).strip(),
                published_at=pub, published_at_raw=raw, summary=clean(it.findtext("description")),
                category_raw=" / ".join(cats) or None,
                source_updated_at=rfc822(it.findtext("bs:lastModification", namespaces=NS)),
                author=clean(it.findtext("dc:creator", namespaces=NS), 200),
                language="en", region="IN"))
        return out
    return parse


def news_sitemap_parser(publisher: str) -> Callable[[bytes], ParsedFeed]:
    def parse(body: bytes) -> ParsedFeed:
        out = ParsedFeed()
        root = _root(body, "urlset", out.issues)
        seen: set[str] = set()
        for u in root.findall("sm:url", NS):
            loc = (u.findtext("sm:loc", namespaces=NS) or "").strip() or None
            title = clean(u.findtext("news:news/news:title", namespaces=NS), 1000)
            if not loc or not title:
                out.issues.append(ParseIssue("MALFORMED_ITEM", f"url without loc/title ({loc})"))
                continue
            if loc in seen:
                out.issues.append(ParseIssue("DUPLICATE_IN_FEED", loc[:200]))
                continue
            seen.add(loc)
            raw = (u.findtext("news:news/news:publication_date", namespaces=NS) or "").strip() \
                or None
            pub = iso(raw)
            if raw and pub is None:
                out.issues.append(ParseIssue("BAD_TIMESTAMP", f"unparseable date {raw!r}"))
            out.items.append(ItemObs(
                source_article_id=loc, title=title, url=loc, publisher=publisher,
                published_at=pub, published_at_raw=raw, summary=None,
                category_raw=clean(u.findtext("news:news/news:keywords", namespaces=NS), 500),
                source_updated_at=iso(u.findtext("sm:lastmod", namespaces=NS)),
                language=(u.findtext("news:news/news:publication/news:language", namespaces=NS)
                          or "en"), region="IN"))
        return out
    return parse


_SEBI_DATE = re.compile(r"^\s*(\d{1,2}) ([A-Za-z]{3}), (\d{4})")


def sebi_date(raw: str | None) -> _dt.date | None:
    """'24 Sep, 2026 +0530' -> 2026-09-24. SEBI gives a DATE only."""
    m = _SEBI_DATE.match(raw or "")
    if not m:
        return None
    try:
        return _dt.datetime.strptime(" ".join(m.groups()), "%d %b %Y").date()
    except ValueError:
        return None


def sebi_parser() -> Callable[[bytes], ParsedFeed]:
    """SEBI's RSS (https://www.sebi.gov.in/sebirss.xml; <ttl>60</ttl>, ~30 items):
    press releases, circulars, orders. pubDate is a DATE without a time
    ("24 Sep, 2026 +0530"): published_at stays None (a time is never invented;
    no latency can be claimed) and the raw date is kept. category_raw is the
    site section from the URL (e.g. "enforcement/orders")."""
    def parse(body: bytes) -> ParsedFeed:
        out = ParsedFeed()
        ch = _root(body, "rss", out.issues).find("channel")
        if ch is None:
            raise FeedDecodeError("RSS without <channel>")
        ttl = (ch.findtext("ttl") or "").strip()
        out.ttl_minutes = int(ttl) if ttl.isdigit() else None
        seen: set[str] = set()
        for it in ch.findall("item"):
            title = clean(it.findtext("title"), 1000)
            link = (it.findtext("link") or "").strip() or None
            if not title or not link:
                out.issues.append(ParseIssue("MALFORMED_ITEM", f"item without title/link ({link})"))
                continue
            if link in seen:
                out.issues.append(ParseIssue("DUPLICATE_IN_FEED", link[:200]))
                continue
            seen.add(link)
            raw = (it.findtext("pubDate") or "").strip() or None
            if raw and sebi_date(raw) is None:
                out.issues.append(ParseIssue("BAD_TIMESTAMP", f"unparseable pubDate {raw!r}"))
            path = [p for p in link.split("sebi.gov.in/", 1)[-1].split("/") if p][:2]
            desc = clean(it.findtext("description"))
            out.items.append(ItemObs(
                source_article_id=link, title=title, url=link, publisher="SEBI",
                published_at=None, published_at_raw=raw,
                summary=desc if desc != title else None,
                category_raw="/".join(path) or None, language="en", region="IN"))
        return out
    return parse
