"""Upstox news response -> articles + the vendor's article/instrument links. PURE.

Endpoint: GET /v2/news?category=instrument_keys&instrument_keys=<k1,...k30>
          &page_number=<n>&page_size=<=100

Shape MEASURED 2026-09-24 (tests/fixtures/upstox_news):
  {"status": "success",
   "data": {"<instrument_key>": [article, ...], ...},     # only keys WITH news
   "metadata": {"page": {"page_number", "page_size", "total_records", "total_pages"}}}
  article = {heading, summary, thumbnail, article_link, published_time (epoch ms)}

- There is no article id and no publisher field. The link ends in
  `article-<n>/`; that number is kept as vendor_article_id (it is the
  vendor's own identifier, read from the vendor's own URL). publisher stays
  NULL, never an invented name.
- One article can be listed under several keys: total_records counts
  DISTINCT articles (11 for 12 listings in the fixture). Articles are
  identified by (sha256(heading), published_time), the news_article key.
- Only the last 7 days are served (docs). Nothing older can be fetched later.

knowable_at of an article = its published_time (vendor publication instant,
verified; see for_announced_fact). A published_time AFTER the fetch is a
clock problem: CLOCK_SKEW (WARN), and the fetch time is used instead.

Nothing here touches the network, the database or the filesystem.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.contracts.knowable import Knowable, for_announced_fact
from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.clock import UTC

MAX_KEYS = 30                    # docs: at most 30 instrument keys per request
MAX_PAGE_SIZE = 100              # docs: page_size 1..100
MAX_PAGES = 100                  # docs: page_number 1..100
_ARTICLE_KEYS = frozenset({"heading", "summary", "thumbnail", "article_link", "published_time"})
_ENVELOPE = frozenset({"status", "data", "metadata"})
_ARTICLE_ID = re.compile(r"article-(\d+)/?$")
KNOWABLE_WHAT = "upstox news published_time"


class NewsDecodeError(Exception):
    """Not a news response at all. The archived bytes stay re-parseable."""


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Article:
    headline: str
    headline_sha256: str
    published_at: _dt.datetime
    body: str | None
    url: str | None
    vendor_article_id: str | None
    vendor_payload: dict[str, Any]
    knowable: Knowable

    @property
    def key(self) -> tuple[str, _dt.datetime]:
        return self.headline_sha256, self.published_at


@dataclass(slots=True)
class ParsedNews:
    articles: dict[tuple[str, _dt.datetime], Article] = field(default_factory=dict)
    links: set[tuple[tuple[str, _dt.datetime], str]] = field(default_factory=set)
    per_key: dict[str, int] = field(default_factory=dict)
    page_number: int | None = None
    total_pages: int | None = None
    total_records: int | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(i.severity is AnomalySeverity.FAIL for i in self.issues)


def request_path(keys: list[str] | tuple[str, ...], page: int,
                 page_size: int = MAX_PAGE_SIZE) -> str:
    if not keys or len(keys) > MAX_KEYS:
        raise ValueError(f"1..{MAX_KEYS} instrument keys per request, got {len(keys)}")
    if not 1 <= page <= MAX_PAGES or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page {page} / page_size {page_size} outside the documented range")
    from urllib.parse import quote
    ks = ",".join(quote(k, safe="") for k in keys)
    return (f"/v2/news?category=instrument_keys&instrument_keys={ks}"
            f"&page_number={page}&page_size={page_size}")


def parse_news(data: bytes, *, http_status: int, requested_keys: list[str] | tuple[str, ...],
               fetched_at: _dt.datetime) -> ParsedNews:
    if http_status != 200:
        raise NewsDecodeError(f"HTTP {http_status}")
    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError) as e:
        raise NewsDecodeError(f"not JSON: {e}") from None
    if not isinstance(body, dict) or body.get("status") != "success":
        raise NewsDecodeError(f"not a success envelope: {str(body)[:200]}")

    out = ParsedNews()

    def issue(sev, kind, subject, **detail):
        out.issues.append(Issue(sev, kind, subject, detail))

    if not set(body) <= _ENVELOPE:
        issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "news", envelope_keys=sorted(body))
    page = ((body.get("metadata") or {}).get("page") or {})
    out.page_number, out.total_pages = page.get("page_number"), page.get("total_pages")
    out.total_records = page.get("total_records")
    data_ = body.get("data")
    if data_ in (None, []):
        data_ = {}                      # no news for any requested key: a valid empty result
    if not isinstance(data_, dict):
        issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "news",
              reason="data is not an object")
        return out
    extra = set(data_) - set(requested_keys)
    if extra:
        issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "news",
              reason="articles for keys that were not requested", keys=sorted(extra)[:10])

    for ikey, items in data_.items():
        if not isinstance(items, list):
            issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, ikey, reason="not a list")
            continue
        out.per_key[ikey] = len(items)
        for a in items:
            if not isinstance(a, dict) or not set(a) <= _ARTICLE_KEYS or "heading" not in a \
                    or "published_time" not in a:
                issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, ikey,
                      reason="article keys differ", keys=sorted(a) if isinstance(a, dict) else None)
                continue
            head, ts = a["heading"], a["published_time"]
            if not isinstance(head, str) or not head.strip():
                issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, ikey, reason="empty heading")
                continue
            if isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0:
                issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, ikey,
                      reason="published_time not a positive int (epoch ms)", raw=str(ts)[:40])
                continue
            published = _dt.datetime.fromtimestamp(ts / 1000, UTC)
            if published > fetched_at:
                issue(AnomalySeverity.WARN, AnomalyKind.CLOCK_SKEW, ikey,
                      reason="published_time after fetched_at; knowable_at = fetched_at",
                      published=published.isoformat(), fetched=fetched_at.isoformat())
                knowable = for_announced_fact(None, fetched_at, what=KNOWABLE_WHAT)
            else:
                knowable = for_announced_fact(published, fetched_at, what=KNOWABLE_WHAT)
            link = a.get("article_link")
            m = _ARTICLE_ID.search(link) if isinstance(link, str) else None
            art = Article(
                headline=head, headline_sha256=hashlib.sha256(head.encode()).hexdigest(),
                published_at=published, body=a.get("summary") or None,
                url=link if isinstance(link, str) and link else None,
                vendor_article_id=m.group(1) if m else None,
                vendor_payload=a, knowable=knowable)
            prev = out.articles.get(art.key)
            if prev is not None and prev.vendor_payload != a:
                # Same article identity, different content within ONE response:
                # keep the first, record the difference; never merge silently.
                issue(AnomalySeverity.WARN, AnomalyKind.DUPLICATE_KEY, ikey,
                      reason="same heading+published_time with different fields in one response",
                      heading=head[:120])
            else:
                out.articles.setdefault(art.key, art)
            out.links.add((art.key, ikey))
    return out
