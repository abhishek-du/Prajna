"""A polite feed client: one per source.

  * conditional GET (If-None-Match / If-Modified-Since): an unchanged feed is a
    304 with no body
  * never faster than the configured interval nor the feed's own <ttl>
  * +-20% jitter on every interval (sources are not polled in lock-step)
  * 429 / 503 -> RATE_LIMITED, honouring Retry-After; 5xx / network errors ->
    exponential backoff (x2, capped at 30 min)
  * that backoff is the circuit breaker: after consecutive failures the source
    is probed once per (growing) backoff period, never in a tight loop
  * 401 -> AUTH_FAILED and 403 -> BLOCKED: the source STOPS. There is no retry,
    no cookie or JavaScript challenge handling, and no user-agent rotation.
Transport is injectable (httpx.MockTransport in tests; the network is blocked there).
"""

from __future__ import annotations

import datetime as _dt
import random
from dataclasses import dataclass, field

import httpx

from app.core.clock import now

USER_AGENT = "PrajnaResearch/0.1 (market-data research; polite RSS polling)"
BACKOFF_CAP_S = 1800
TIMEOUT_S = 20.0


@dataclass(slots=True)
class FetchResult:
    # OK / NOT_MODIFIED / RATE_LIMITED / BLOCKED / AUTH_FAILED / ERROR
    outcome: str
    started_at: _dt.datetime
    finished_at: _dt.datetime
    http_status: int | None = None
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    retry_after_s: int | None = None
    error: str | None = None


@dataclass(slots=True)
class SourceState:
    """What the client remembers about one source between polls."""
    etag: str | None = None
    last_modified: str | None = None
    failures: int = 0
    stopped: str | None = None        # BLOCKED / AUTH_FAILED: never polled again automatically
    rate_limited_until: _dt.datetime | None = None
    ttl_s: int | None = None
    history: list[str] = field(default_factory=list)   # last outcomes (health)

    def note(self, outcome: str) -> None:
        self.history = [*self.history, outcome][-60:]


def next_delay(base_s: float, state: SourceState, rng: random.Random) -> float:
    """Seconds until the next poll: max(interval, ttl), backoff on failure, jitter."""
    d = max(base_s, float(state.ttl_s or 0))
    if state.failures:
        d = min(BACKOFF_CAP_S, max(d, 30.0) * (2 ** (state.failures - 1)))
    if state.rate_limited_until is not None:
        d = max(d, (state.rate_limited_until - now()).total_seconds())
    return d * rng.uniform(0.8, 1.2)


def _retry_after(v: str | None) -> int | None:
    if not v:
        return None
    try:
        return max(0, int(v.strip()))
    except ValueError:
        return None


async def fetch(url: str, state: SourceState, *,
                transport: httpx.AsyncBaseTransport | None = None) -> FetchResult:
    """One conditional GET. Updates `state` (validators, failures, stop)."""
    if state.stopped:
        t = now()
        return FetchResult(state.stopped, t, t, error=f"source stopped: {state.stopped}")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, */*"}
    if state.etag:
        headers["If-None-Match"] = state.etag
    if state.last_modified:
        headers["If-Modified-Since"] = state.last_modified
    t0 = now()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S,
                                     follow_redirects=False) as c:
            r = await c.get(url, headers=headers)
    except httpx.HTTPError as e:
        state.failures += 1
        state.note("ERROR")
        return FetchResult("ERROR", t0, now(), error=f"{type(e).__name__}: {e}"[:300])
    t1 = now()
    res = FetchResult("ERROR", t0, t1, http_status=r.status_code,
                      etag=r.headers.get("etag"), last_modified=r.headers.get("last-modified"))
    if r.status_code == 200:
        res.outcome, res.body = "OK", r.content
        state.etag, state.last_modified = res.etag, res.last_modified
        state.failures, state.rate_limited_until = 0, None
    elif r.status_code == 304:
        res.outcome = "NOT_MODIFIED"
        state.failures, state.rate_limited_until = 0, None
    elif r.status_code in (429, 503):
        res.outcome = "RATE_LIMITED"
        res.retry_after_s = _retry_after(r.headers.get("retry-after"))
        state.failures += 1
        if res.retry_after_s is not None:
            state.rate_limited_until = t1 + _dt.timedelta(seconds=res.retry_after_s)
    elif r.status_code == 403:
        res.outcome = state.stopped = "BLOCKED"
        res.error = "HTTP 403: the source refuses this client; stopped (no bypass)"
    elif r.status_code == 401:
        res.outcome = state.stopped = "AUTH_FAILED"
        res.error = "HTTP 401; stopped"
    else:
        state.failures += 1
        res.error = f"HTTP {r.status_code}"
    state.note(res.outcome)
    return res


def health(state: SourceState, *, last_ok: _dt.datetime | None, stale_after_s: float,
           at: _dt.datetime | None = None) -> str:
    """HEALTHY / DEGRADED / STALE / RATE_LIMITED / BLOCKED / AUTH_FAILED."""
    at = at or now()
    if state.stopped:
        return state.stopped
    if state.rate_limited_until is not None and state.rate_limited_until > at:
        return "RATE_LIMITED"
    if last_ok is None or (at - last_ok).total_seconds() > stale_after_s:
        return "STALE"
    recent = state.history[-10:]
    if recent and sum(1 for o in recent if o not in ("OK", "NOT_MODIFIED")) / len(recent) > 0.2:
        return "DEGRADED"
    return "HEALTHY"
