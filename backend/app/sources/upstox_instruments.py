"""Download the Upstox instrument master. The only network code for it.

Public, unauthenticated (no Upstox token, no account). The bytes are returned
EXACTLY as served — still gzipped — so the archive and its sha256 describe the
vendor's file, not our decompression of it.

The master carries no generated-at or valid-from, so the honest knowable_at is
our fetch time (contracts.knowable.for_snapshot_download).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

import httpx

from app.core.clock import now
from app.core.errors import VendorError

MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
TIMEOUT = 180.0


@dataclass(frozen=True, slots=True)
class DownloadedMaster:
    data: bytes
    fetched_at: _dt.datetime
    http_status: int
    url: str
    last_modified: str | None


async def download_master(
    *, client: httpx.AsyncClient | None = None, url: str = MASTER_URL
) -> DownloadedMaster:
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
    try:
        r = await client.get(url, headers={"Accept-Encoding": "identity"})
    except httpx.HTTPError as e:
        raise VendorError(f"instrument master download failed: {type(e).__name__}: {e}") from None
    finally:
        if own:
            await client.aclose()
    fetched_at = now()
    if r.status_code != 200 or not r.content:
        raise VendorError(f"instrument master: HTTP {r.status_code}, {len(r.content)} bytes")
    return DownloadedMaster(r.content, fetched_at, r.status_code, str(r.url),
                            r.headers.get("last-modified"))
