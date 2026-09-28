"""Article content retrieval (Phase 8). Never fatal, never a bypass.

Order of checks (the first that fails decides the status; later steps are not
attempted, so a blocked source never receives a request):
  TERMS_BLOCKED   the source's terms review is not APPROVED, or its adapter does
                  not allow bodies (Source.body_allowed, default False)
  ROBOTS_BLOCKED  robots.txt disallows the URL for our user agent (robots.txt that
                  cannot be read counts as disallowed: fail-closed)
  HTTP_BLOCKED    401 / 403 / 451 - no retry, no cookies, no challenge solving
  PAYWALL         402, or a subscription wall in the page
  NOT_AVAILABLE   no usable article text (< 300 characters)
  ERROR           network error or another HTTP status
  AVAILABLE       the extracted article text (tags stripped)
Nothing here raises: an unavailable body leaves the item as it was.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import re
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.clock import now
from app.news.http import TIMEOUT_S, USER_AGENT
from app.news.sources import Source

MIN_TEXT = 300
_PAYWALL = re.compile(r"subscribe to (continue|read)|premium (article|story)|"
                      r"this (article|story) is for (subscribers|members)|paywall", re.I)
_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_ARTICLE = re.compile(r"<article[^>]*>(.*?)</article>", re.S | re.I)
_PARA = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ContentResult:
    status: str
    http_status: int | None
    robots_allowed: bool | None
    terms_status: str
    body: str | None
    content_sha256: str | None
    error: str | None
    fetched_at: _dt.datetime


def extract(page: str) -> str:
    page = _SCRIPT.sub(" ", page)
    m = _ARTICLE.search(page)
    scope = m.group(1) if m else page
    paras = [_WS.sub(" ", html.unescape(_TAG.sub(" ", p))).strip() for p in _PARA.findall(scope)]
    return "\n\n".join(p for p in paras if len(p) > 40)


class RobotsCache:
    def __init__(self) -> None:
        self._rp: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    async def allowed(self, url: str, transport=None) -> bool:
        host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if host not in self._rp:
            try:
                async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S) as c:
                    r = await c.get(f"{host}/robots.txt", headers={"User-Agent": USER_AGENT})
                if r.status_code == 200:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(r.text.splitlines())
                    self._rp[host] = rp
                elif r.status_code in (404, 410):
                    self._rp[host] = urllib.robotparser.RobotFileParser()   # no rules
                    self._rp[host].parse([])
                else:
                    self._rp[host] = None                 # unreadable: fail-closed
            except httpx.HTTPError:
                self._rp[host] = None
        rp = self._rp[host]
        return rp is not None and rp.can_fetch(USER_AGENT, url)


async def fetch_content(url: str | None, src: Source, robots: RobotsCache, *,
                        transport=None) -> ContentResult:
    t = now()

    def res(status, *, http=None, robots_ok=None, body=None, error=None):
        sha = hashlib.sha256(body.encode()).hexdigest() if body else None
        return ContentResult(status, http, robots_ok, src.compliance, body, sha, error, t)

    if src.compliance != "APPROVED" or not src.body_allowed:
        return res("TERMS_BLOCKED", error=f"terms {src.compliance}; body_allowed="
                                          f"{src.body_allowed}")
    if not url or not url.startswith("https://"):
        return res("NOT_AVAILABLE", error="no https article URL")
    if not await robots.allowed(url, transport):
        return res("ROBOTS_BLOCKED", robots_ok=False)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S,
                                     follow_redirects=False) as c:
            r = await c.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as e:
        return res("ERROR", robots_ok=True, error=f"{type(e).__name__}"[:200])
    if r.status_code in (401, 403, 451):
        return res("HTTP_BLOCKED", http=r.status_code, robots_ok=True)
    if r.status_code == 402 or (r.status_code == 200 and _PAYWALL.search(r.text[:200000])):
        return res("PAYWALL", http=r.status_code, robots_ok=True)
    if r.status_code != 200:
        return res("ERROR", http=r.status_code, robots_ok=True, error=f"HTTP {r.status_code}")
    text = extract(r.text)
    if len(text) < MIN_TEXT:
        return res("NOT_AVAILABLE", http=200, robots_ok=True, error="no usable article text")
    return res("AVAILABLE", http=200, robots_ok=True, body=text)
