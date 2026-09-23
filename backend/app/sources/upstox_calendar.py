"""Upstox market-information endpoints for the session calendar. Network only.

Authenticated (the cached access token). Bytes are returned exactly as served
so the archive and its sha256 describe the vendor's response.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

import httpx

from app.core.clock import now
from app.core.errors import VendorAuthError, VendorError

API = "https://api.upstox.com"
HOLIDAYS_PATH = "/v2/market/holidays"
TIMINGS_PATH = "/v2/market/timings/{date}"
TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    data: bytes
    fetched_at: _dt.datetime
    http_status: int


class UpstoxCalendarClient:
    def __init__(self, access_token: str, *, client: httpx.AsyncClient | None = None):
        if not access_token:
            raise VendorAuthError("no Upstox access token (blocker B0)")
        self._token = access_token
        self._own = client is None
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT)

    async def _get(self, path: str) -> Fetched:
        url = API + path
        try:
            r = await self._client.get(url, headers={"Authorization": f"Bearer {self._token}",
                                                     "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise VendorError(f"{path}: {type(e).__name__}: {e}") from None
        fetched = now()
        if r.status_code in (401, 403):
            raise VendorAuthError(f"{path}: HTTP {r.status_code} (token rejected)")
        if r.status_code != 200:
            raise VendorError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
        return Fetched(url, r.content, fetched, r.status_code)

    async def holidays(self) -> Fetched:
        return await self._get(HOLIDAYS_PATH)

    async def timings(self, day: _dt.date) -> Fetched:
        return await self._get(TIMINGS_PATH.format(date=day.isoformat()))

    async def aclose(self) -> None:
        if self._own:
            await self._client.aclose()
