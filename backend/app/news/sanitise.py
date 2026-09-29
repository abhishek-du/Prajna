"""Untrusted feed text and links, made safe once for every source (pure).

Applied to every parsed item before anything is compared, stored or logged:
  title / summary / author / category   HTML entities decoded FIRST, then tags
      removed (so an encoded "&lt;script&gt;" cannot survive as a live tag),
      control characters removed (no log or terminal injection: no newline,
      no escape sequence), whitespace collapsed, length capped (ellipsis)
  url / attachment_url   kept only if an absolute http(s) URL with a host, no
      whitespace or control characters, at most 2,048 characters; otherwise
      dropped (None) with a BAD_URL issue - never a javascript:, data: or
      relative link. The source's own article id is not changed.
"""

from __future__ import annotations

import dataclasses
import html
import re
from urllib.parse import urlsplit

from app.news.model import ItemObs

TITLE_MAX = 1000
SUMMARY_MAX = 2000
SHORT_MAX = 500
URL_MAX = 2048
_TAG = re.compile(r"<[^>]*>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_WS = re.compile(r"\s+")


def text(s: str | None, limit: int) -> str | None:
    if not s:
        return None
    t = _TAG.sub(" ", html.unescape(s))
    t = _WS.sub(" ", _CONTROL.sub(" ", t)).strip()
    return (t[:limit - 1] + "…" if len(t) > limit else t) or None


def url(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip()
    if len(u) > URL_MAX or _CONTROL.search(u) or " " in u:
        return None
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    return u if p.scheme in ("http", "https") and p.hostname else None


def item(it: ItemObs) -> tuple[ItemObs | None, list[tuple[str, str]]]:
    """The safe item and its issues; None when nothing usable (no title) is left."""
    issues: list[tuple[str, str]] = []
    new = {"title": text(it.title, TITLE_MAX), "summary": text(it.summary, SUMMARY_MAX)}
    for f in ("author", "category_raw"):
        if getattr(it, f) is not None:
            new[f] = text(getattr(it, f), SHORT_MAX)
    new["publisher"] = text(it.publisher, SHORT_MAX) or "UNKNOWN"
    for f in ("url", "attachment_url"):
        v = getattr(it, f)
        if v is not None:
            new[f] = url(v)
            if new[f] is None:
                issues.append(("BAD_URL", f"{f} dropped: {text(v, 120)!r}"))
    if not new["title"]:
        return None, [*issues, ("MALFORMED_ITEM", "no usable title after sanitising")]
    return dataclasses.replace(it, **new), issues
