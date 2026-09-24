"""The connector contract. Every fetch ends in exactly ONE FetchOutcome; no
error is ever turned into "empty data"."""

from __future__ import annotations

import datetime as _dt
import enum
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class FetchOutcome(str, enum.Enum):
    OK_DATA = "OK_DATA"
    OK_EMPTY_WINDOW = "OK_EMPTY_WINDOW"        # valid response: the vendor has nothing
    EMPTY_BODY = "EMPTY_BODY"                  # 200 with no bytes
    MALFORMED = "MALFORMED"                    # not JSON, or not the vendor's envelope
    STRUCTURALLY_INVALID = "STRUCTURALLY_INVALID"   # JSON envelope, broken contract
    HTTP_ERROR = "HTTP_ERROR"                  # non-2xx without a vendor error code
    VENDOR_ERROR = "VENDOR_ERROR"              # 4xx with the vendor's error code
    AUTH_ERROR = "AUTH_ERROR"                  # 401 / 403
    RATE_LIMITED = "RATE_LIMITED"              # 429 or a rate-limit message
    TIMEOUT = "TIMEOUT"                        # per-phase or wall-clock timeout
    TRANSPORT_ERROR = "TRANSPORT_ERROR"        # connection / TLS / DNS

    @property
    def ok(self) -> bool:
        return self in (FetchOutcome.OK_DATA, FetchOutcome.OK_EMPTY_WINDOW)


@dataclass(frozen=True, slots=True)
class FetchResult:
    outcome: FetchOutcome
    source: str
    endpoint: str
    url: str | None
    http_status: int | None
    fetched_at: _dt.datetime | None
    data: bytes | None                         # raw bytes exactly as served
    request_id: str | None = None
    retry_count: int = 0
    error_codes: tuple[str, ...] = ()
    detail: str = ""
    attempts: tuple[Any, ...] = field(default_factory=tuple)


# A validator inspects a decoded 2xx body: returns "data", "empty", or an error
# string (the contract it breaks).
Validator = Callable[[Any], str]


def classify_body(data: bytes, validator: Validator | None) -> tuple[FetchOutcome, str]:
    if not data:
        return FetchOutcome.EMPTY_BODY, "200 with an empty body"
    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError) as e:
        return FetchOutcome.MALFORMED, f"not JSON: {e}"[:200]
    if not isinstance(body, dict) or body.get("status") != "success" or "data" not in body:
        return FetchOutcome.MALFORMED, "not the vendor success envelope"
    verdict = validator(body["data"]) if validator else ("empty" if body["data"] in
                                                         (None, [], {}) else "data")
    if verdict == "data":
        return FetchOutcome.OK_DATA, ""
    if verdict == "empty":
        return FetchOutcome.OK_EMPTY_WINDOW, ""
    return FetchOutcome.STRUCTURALLY_INVALID, verdict[:200]


class Connector(Protocol):
    source: str

    async def fetch(self, endpoint: str, *, validator: Validator | None = None
                    ) -> FetchResult: ...

    async def aclose(self) -> None: ...
