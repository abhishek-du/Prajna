"""Source-independent news observations and normalisation helpers (pure)."""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|ref$|from$|source$)", re.I)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ItemObs:
    """One item as a feed presented it in one response (before Prajna's timing)."""
    source_article_id: str
    title: str
    url: str | None
    publisher: str
    published_at: _dt.datetime | None          # the publisher's claim (UTC); informational
    published_at_raw: str | None
    summary: str | None = None
    category_raw: str | None = None
    symbol_raw: str | None = None
    attachment_url: str | None = None
    source_updated_at: _dt.datetime | None = None
    author: str | None = None
    language: str | None = None
    region: str | None = None


@dataclass(frozen=True, slots=True)
class ParseIssue:
    kind: str                                   # MALFORMED_ITEM / BAD_TIMESTAMP / DUPLICATE_IN_FEED
    detail: str


@dataclass(slots=True)
class ParsedFeed:
    items: list[ItemObs] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    ttl_minutes: int | None = None              # the feed's own refresh hint (RSS <ttl>)


def canonical_url(url: str | None) -> str | None:
    """Lower-case scheme/host, https, no fragment, no tracking parameters, no
    trailing slash, no '/amp' suffix."""
    if not url:
        return None
    p = urlsplit(url.strip())
    q = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                   if not _TRACKING.match(k)])
    path = re.sub(r"/amp/?$", "", p.path).rstrip("/") or "/"
    return urlunsplit(("https", p.netloc.lower(), path, q, ""))


def normalise_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title).casefold()
    t = _PUNCT.sub(" ", t)
    return _SPACE.sub(" ", t).strip()


def title_hash(title: str) -> str:
    return hashlib.sha256(normalise_title(title).encode()).hexdigest()


def stable_id(*parts: str | None) -> str:
    """An id for items whose feed gives none: sha256 of the identifying fields."""
    return "sha256:" + hashlib.sha256("\x1f".join(p or "" for p in parts).encode()).hexdigest()
