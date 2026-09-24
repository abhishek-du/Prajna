"""The one Upstox REST client: rate limited, retried, and stopped on a limit.

Every authenticated REST call Prajna makes to Upstox goes through
UpstoxRestClient.get(). Network only: it returns the vendor's bytes and never
archives or parses them; archiving stays in the ingest step, raw first.

RATE LIMITS. Documented as 50/s, 500/min and 2000 per 30 min, "enforced on a
per-API, per-user basis" (upstox.com/developer/api-documentation/rate-limiting).
Breaching them "might result in temporary suspension of access", and no HTTP
status is documented for a breach. So:
  * the limiter runs at LIMIT_FRACTION (90 %) of every window;
  * one limiter is shared by every caller in the process (shared_limiter()).
    Whether the historical and intraday candle endpoints count as one "API" is
    UNKNOWN; sharing one bucket is the conservative reading;
  * OPERATING RULE: one REST-heavy process at a time. Two processes (say, the
    pre-open runbook and a backfill) each hold their own limiter and could
    together exceed the vendor's limit. A cross-process limiter is not built.

RESPONSES.
  200                  returned
  other 4xx            returned with the vendor's error codes (e.g. UDAPI1148);
                       the caller records it as VENDOR_ERROR coverage
  401 / 403            VendorAuthError, never retried
  429 or rate-limit    RateLimited, never retried: stop, keep the checkpoint
  timeout, transport,  retried with exponential backoff, each attempt through
  500/502/503/504      the limiter again; VendorError once exhausted

The access token is sent only in the Authorization header. It is never put in
a URL, an exception or the attempt log.
"""

from __future__ import annotations

import asyncio
import bisect
import datetime as _dt
import json
import re
import time
import urllib.parse as up
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import httpx

from app.contracts.candles import Window, plan_windows
from app.contracts.timeframe import upstox_interval
from app.core.clock import now
from app.core.errors import RateLimited, VendorAuthError, VendorError

API = "https://api.upstox.com"
TIMEOUT = 30.0
WALL_TIMEOUT = 60.0        # whole-request wall clock (seconds)

DOCUMENTED_LIMITS = ((50, 1.0), (500, 60.0), (2000, 1800.0))   # (requests, seconds)
LIMIT_FRACTION = 0.9
LIMITS_BASIS = ("upstox rate-limiting docs (50/s, 500/min, 2000/30min per API per user), "
                "run at 90% because a breach means suspension")

RETRY_STATUSES = frozenset({500, 502, 503, 504})
BACKOFF = (1.0, 2.0, 4.0, 8.0)       # seconds before retry 1..4
QUOTE_MAX_KEYS = 500                 # documented for /v2/market-quote/quotes

# No rate-limit error code is documented; these phrases in an error message
# are treated as one. A false positive stops a job, which is safe.
_RATE_LIMIT_TEXT = re.compile(r"too many requests|rate.?limit|throttl", re.IGNORECASE)


def default_windows(fraction: float = LIMIT_FRACTION) -> tuple[tuple[int, float], ...]:
    if not 0 < fraction <= LIMIT_FRACTION:
        raise ValueError(f"rate fraction {fraction} outside (0, {LIMIT_FRACTION}]")
    return tuple((max(1, int(n * fraction)), s) for n, s in DOCUMENTED_LIMITS)


# ── rate limiter ────────────────────────────────────────────────────────────
class RateLimiter:
    """Sliding-log limiter over several windows at once.

    A call is admitted only when, for EVERY (limit, span), fewer than `limit`
    calls happened in the last `span` seconds. Callers are served in order
    (one lock), so no caller can starve another or overshoot a window.

    Time is kept in integer MICROSECONDS, and a call counts as inside a window
    until it is older than span + BOUNDARY_GUARD. Float seconds made the
    boundary comparison flip on ~1e-13 differences and admitted a 1,801st call
    into an 1,800 window (found by the long-run test). The guard keeps the
    limiter strictly on the safe side of the vendor's own boundary.
    """

    BOUNDARY_GUARD_US = 1_000      # 1 ms

    def __init__(self, windows: Sequence[tuple[int, float]] | None = None, *,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.windows = tuple(sorted(windows or default_windows(), key=lambda w: w[1]))
        if any(n < 1 or s <= 0 for n, s in self.windows):
            raise ValueError(f"bad rate-limit windows {self.windows}")
        self._spans_us = tuple((n, round(s * 1_000_000) + self.BOUNDARY_GUARD_US)
                               for n, s in self.windows)
        self._clock, self._sleep = clock, sleep
        self._log: list[int] = []
        self._lock = asyncio.Lock()
        self._horizon_us = max(s for _, s in self._spans_us)
        self.admitted = 0

    def _now_us(self) -> int:
        return round(self._clock() * 1_000_000)

    def _wait_needed_us(self, t: int) -> int:
        cut = bisect.bisect_right(self._log, t - self._horizon_us)
        if cut:
            del self._log[:cut]
        wait = 0
        for limit, span in self._spans_us:
            first = bisect.bisect_right(self._log, t - span)      # oldest call in this window
            in_window = len(self._log) - first
            if in_window >= limit:
                # the call that must age out before one more is allowed
                expires = self._log[first + in_window - limit] + span
                wait = max(wait, expires - t)
        return wait

    async def acquire(self) -> float:
        """Wait for room, record the call, return the seconds waited."""
        async with self._lock:
            waited = 0.0
            while True:
                t = self._now_us()
                w = self._wait_needed_us(t)
                if w <= 0:
                    self._log.append(t)
                    self.admitted += 1
                    return waited
                secs = w / 1_000_000
                await self._sleep(secs)
                waited += secs

    def count_in(self, span: float) -> int:
        t = self._now_us()
        return len(self._log) - bisect.bisect_right(self._log, t - round(span * 1_000_000))


_SHARED: RateLimiter | None = None


def shared_limiter() -> RateLimiter:
    """The process-wide limiter every UpstoxRestClient uses by default."""
    global _SHARED
    if _SHARED is None:
        from app.core.config import get_settings
        _SHARED = RateLimiter(default_windows(get_settings().PRAJNA_UPSTOX_RATE_FRACTION))
    return _SHARED


# ── client ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Attempt:
    n: int
    at: _dt.datetime
    status: int | None
    error: str | None
    limiter_wait_s: float
    backoff_wait_s: float


@dataclass(frozen=True, slots=True)
class RestResponse:
    url: str
    status: int
    data: bytes                      # exactly as served
    fetched_at: _dt.datetime
    error_codes: tuple[str, ...]
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)
    # the vendor's correlation id, when a response header carries one
    request_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200


_REQUEST_ID_HEADERS = ("x-request-id", "x-requestid", "request-id", "x-amzn-requestid",
                       "cf-ray")


def _request_id(headers) -> str | None:
    for h in _REQUEST_ID_HEADERS:
        v = headers.get(h)
        if v:
            return f"{h}={v}"[:120]
    return None


def error_codes(data: bytes) -> tuple[str, ...]:
    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return ()
    errs = body.get("errors") if isinstance(body, dict) else None
    out = []
    for e in errs if isinstance(errs, list) else []:
        if isinstance(e, dict):
            c = e.get("errorCode") or e.get("error_code")
            if c:
                out.append(str(c))
    return tuple(out)


def _error_text(data: bytes) -> str:
    try:
        return data.decode("utf-8", "replace")[:500]
    except Exception:
        return ""


class UpstoxRestClient:
    def __init__(
        self,
        access_token: str,
        *,
        client: httpx.AsyncClient | None = None,
        limiter: RateLimiter | None = None,
        backoff: Sequence[float] = BACKOFF,
        jitter: Callable[[], float] = lambda: 0.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        base_url: str = API,
    ):
        if not access_token:
            raise VendorAuthError("no Upstox access token (blocker B0)")
        self._token = access_token
        self._own = client is None
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT)
        self.limiter = limiter or shared_limiter()
        self._backoff, self._jitter, self._sleep = tuple(backoff), jitter, sleep
        self._base = base_url

    async def get(self, path: str) -> RestResponse:
        if not path.startswith("/"):
            raise ValueError(f"path must start with '/': {path!r}")
        url = self._base + path
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        attempts: list[Attempt] = []
        backoff_wait = 0.0
        for n in range(1, len(self._backoff) + 2):
            limiter_wait = await self.limiter.acquire()
            at = now()
            try:
                # httpx's per-phase timeouts did not fire on a half-closed socket
                # (observed 2026-09-24: 25 min hang); bound the whole request.
                r = await asyncio.wait_for(self._client.get(url, headers=headers),
                                           timeout=WALL_TIMEOUT)
            except (httpx.TimeoutException, httpx.TransportError, TimeoutError) as e:
                attempts.append(Attempt(n, at, None, type(e).__name__, limiter_wait,
                                        backoff_wait))
                retry = True
            else:
                fetched = now()
                attempts.append(Attempt(n, at, r.status_code, None, limiter_wait, backoff_wait))
                codes = error_codes(r.content)
                if r.status_code == 429 or (r.status_code >= 400 and
                                            _RATE_LIMIT_TEXT.search(_error_text(r.content))):
                    raise RateLimited(f"{path}: HTTP {r.status_code} {list(codes)} after "
                                      f"{n} attempt(s): rate limited; stop and resume later")
                if r.status_code in (401, 403):
                    raise VendorAuthError(f"{path}: HTTP {r.status_code} {list(codes)} "
                                          "(token rejected)")
                if r.status_code in RETRY_STATUSES:
                    retry = True
                else:
                    return RestResponse(url, r.status_code, r.content, fetched, codes,
                                        tuple(attempts), _request_id(r.headers))
            if not retry or n > len(self._backoff):
                break
            backoff_wait = self._backoff[n - 1] + self._jitter()
            await self._sleep(backoff_wait)
        last = attempts[-1]
        raise VendorError(f"{path}: gave up after {len(attempts)} attempt(s); last "
                          f"{last.status or last.error}")

    async def aclose(self) -> None:
        if self._own:
            await self._client.aclose()


# ── paths ───────────────────────────────────────────────────────────────────
def _key(instrument_key: str) -> str:
    return up.quote(instrument_key, safe="")


def historical_candle_path(instrument_key: str, timeframe: str, window: Window) -> str:
    """/v3/historical-candle/{key}/{unit}/{step}/{to}/{from}. The window must
    be one the vendor accepts (a single plan_windows window)."""
    plan = plan_windows(timeframe, window.from_date, window.to_date)
    if plan.unavailable is not None or plan.windows != (window,):
        raise ValueError(f"{window} is not a single requestable {timeframe} window")
    unit, step = upstox_interval(timeframe)
    return (f"/v3/historical-candle/{_key(instrument_key)}/{unit}/{step}/"
            f"{window.to_date.isoformat()}/{window.from_date.isoformat()}")


def intraday_candle_path(instrument_key: str, timeframe: str) -> str:
    unit, step = upstox_interval(timeframe)
    return f"/v3/historical-candle/intraday/{_key(instrument_key)}/{unit}/{step}"


def quotes_path(instrument_keys: Sequence[str]) -> str:
    keys = list(instrument_keys)
    if not keys or len(keys) > QUOTE_MAX_KEYS:
        raise ValueError(f"{len(keys)} keys; the quotes API takes 1..{QUOTE_MAX_KEYS}")
    return "/v2/market-quote/quotes?instrument_key=" + ",".join(_key(k) for k in keys)
