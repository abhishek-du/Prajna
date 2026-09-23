"""Market Data Feed V3 authorization: access token -> one-time WebSocket URL.

    GET https://api.upstox.com/v3/feed/market-data-feed/authorize
        Authorization: Bearer <access token>
    -> {"status": "success", "data": {"authorized_redirect_uri": "wss://..."}}

The returned URL is single-use and carries its own credential, so it is never
logged or archived in full: only its scheme, host and path. Every (re)connect
asks for a fresh one.

An auth rejection (401/403) is VendorAuthError and is NOT retried: a dead token
does not heal by reconnecting, and hammering the endpoint with it is how an
account gets rate-limited. Token renewal is a separate, deliberate act
(`prajna upstox login`).

Not routed through vendor/upstox/rest.UpstoxRestClient (yet): one call per WebSocket
connection, and its 401 handling is specific to the feed. New authenticated REST calls
belong on the shared client.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from app.core.errors import VendorAuthError, VendorError

AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
TIMEOUT = 15.0


def redact_ws_url(url: str) -> str:
    """scheme://host/path only — the query string is the credential."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


async def authorize_feed_v3(
    access_token: str, *, client: httpx.AsyncClient | None = None
) -> str:
    if not access_token:
        raise VendorAuthError("no Upstox access token (blocker B0)")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        r = await client.get(AUTHORIZE_URL, headers=headers)
    except httpx.HTTPError as e:
        raise VendorError(f"feed authorize request failed: {type(e).__name__}: {e}") from None
    finally:
        if own:
            await client.aclose()

    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code in (401, 403):
        codes = [e.get("errorCode") for e in body.get("errors", []) if isinstance(e, dict)]
        raise VendorAuthError(f"feed authorize rejected: HTTP {r.status_code} {codes}")
    if r.status_code != 200 or body.get("status") != "success":
        raise VendorError(f"feed authorize failed: HTTP {r.status_code} {str(body)[:300]}")

    url = (body.get("data") or {}).get("authorized_redirect_uri") or ""
    if urlsplit(url).scheme not in ("wss", "ws"):
        raise VendorError(f"feed authorize returned no WebSocket URL (got {redact_ws_url(url)!r})")
    return url
