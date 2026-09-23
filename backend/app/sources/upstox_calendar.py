"""Upstox market-information endpoints for the session calendar. Network only.

Authenticated (the cached access token), through the shared UpstoxRestClient.
Bytes are returned exactly as served so the archive and its sha256 describe
the vendor's response.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

import httpx

from app.core.errors import VendorAuthError, VendorError
from app.vendor.upstox.rest import API, UpstoxRestClient

# API is re-exported: ingest/calendar.py builds URLs from it.
__all__ = ["API", "HOLIDAYS_PATH", "TIMINGS_PATH", "Fetched", "UpstoxCalendarClient"]

HOLIDAYS_PATH = "/v2/market/holidays"
TIMINGS_PATH = "/v2/market/timings/{date}"


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    data: bytes
    fetched_at: _dt.datetime
    http_status: int


class UpstoxCalendarClient:
    """Calendar endpoints over the shared UpstoxRestClient (rate limited,
    retried on transient errors, stopped on a rate limit)."""

    def __init__(self, access_token: str, *, client: httpx.AsyncClient | None = None,
                 rest: UpstoxRestClient | None = None):
        if not access_token:
            raise VendorAuthError("no Upstox access token (blocker B0)")
        self._rest = rest or UpstoxRestClient(access_token, client=client)

    async def _get(self, path: str) -> Fetched:
        r = await self._rest.get(path)          # 401/403, 429 and exhaustion raise
        if not r.ok:
            raise VendorError(f"{path}: HTTP {r.status} {list(r.error_codes)} "
                              f"{r.data[:200]!r}")
        return Fetched(r.url, r.data, r.fetched_at, r.status)

    async def holidays(self) -> Fetched:
        return await self._get(HOLIDAYS_PATH)

    async def timings(self, day: _dt.date) -> Fetched:
        return await self._get(TIMINGS_PATH.format(date=day.isoformat()))

    async def aclose(self) -> None:
        await self._rest.aclose()
