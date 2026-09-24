"""Upstox connector over the existing UpstoxRestClient (auth, rate limiter,
retries with exponential backoff, 429 stop, 60 s wall-clock timeout). Adds
only the classification; it does not archive (callers archive raw bytes
first, as Stage 1 does) and makes no decision about the data."""

from __future__ import annotations

import httpx

from app.connectors.base import FetchOutcome, FetchResult, Validator, classify_body
from app.core.errors import RateLimited, VendorAuthError, VendorError
from app.vendor.upstox.rest import UpstoxRestClient


class UpstoxConnector:
    def __init__(self, rest: UpstoxRestClient, *, source: str = "UPSTOX_REST"):
        self.rest, self.source = rest, source

    async def fetch(self, endpoint: str, *, validator: Validator | None = None
                    ) -> FetchResult:
        def fail(outcome: FetchOutcome, detail: str) -> FetchResult:
            return FetchResult(outcome, self.source, endpoint, None, None, None, None,
                               detail=detail[:300])
        try:
            r = await self.rest.get(endpoint)
        except RateLimited as e:
            return fail(FetchOutcome.RATE_LIMITED, str(e))
        except VendorAuthError as e:
            return fail(FetchOutcome.AUTH_ERROR, str(e))
        except VendorError as e:           # retries exhausted: "... last <status|error>"
            msg = str(e)
            last = msg.rsplit("last ", 1)[-1].strip()
            if last.isdigit():
                return fail(FetchOutcome.HTTP_ERROR, msg)
            return fail(FetchOutcome.TIMEOUT if "Timeout" in last
                        else FetchOutcome.TRANSPORT_ERROR, msg)
        except (httpx.TimeoutException, TimeoutError) as e:
            return fail(FetchOutcome.TIMEOUT, repr(e))
        except httpx.TransportError as e:
            return fail(FetchOutcome.TRANSPORT_ERROR, repr(e))
        base = dict(source=self.source, endpoint=endpoint, url=r.url, http_status=r.status,
                    fetched_at=r.fetched_at, data=r.data, request_id=r.request_id,
                    retry_count=max(len(r.attempts) - 1, 0), error_codes=r.error_codes,
                    attempts=r.attempts)
        if r.status == 200:
            outcome, detail = classify_body(r.data, validator)
            return FetchResult(outcome, detail=detail, **base)
        if r.error_codes:
            return FetchResult(FetchOutcome.VENDOR_ERROR, detail=",".join(r.error_codes), **base)
        return FetchResult(FetchOutcome.HTTP_ERROR, detail=f"HTTP {r.status}", **base)

    async def aclose(self) -> None:
        await self.rest.aclose()
