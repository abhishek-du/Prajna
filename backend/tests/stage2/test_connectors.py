"""Stage 2.1: every fetch ends in exactly one classified outcome."""

from __future__ import annotations

import asyncio

import httpx
import pytest

import app.vendor.upstox.rest as R
from app.connectors import FetchOutcome, UpstoxConnector


def _conn(handler, backoff=(0.0,)):
    rest = R.UpstoxRestClient("tok", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)), limiter=R.RateLimiter(windows=((1000, 1.0),)),
        sleep=lambda s: asyncio.sleep(0), backoff=backoff)
    return UpstoxConnector(rest)


def _resp(status, content=b"", headers=None):
    return lambda req: httpx.Response(status, content=content, headers=headers or {})


@pytest.mark.parametrize("handler,outcome", [
    (_resp(200, b'{"status":"success","data":{"candles":[[1]]}}'), FetchOutcome.OK_DATA),
    (_resp(200, b'{"status":"success","data":[]}'), FetchOutcome.OK_EMPTY_WINDOW),
    (_resp(200, b""), FetchOutcome.EMPTY_BODY),
    (_resp(200, b"<html>"), FetchOutcome.MALFORMED),
    (_resp(200, b'{"status":"error"}'), FetchOutcome.MALFORMED),
    (_resp(400, b'{"status":"error","errors":[{"errorCode":"UDAPI1148"}]}'),
     FetchOutcome.VENDOR_ERROR),
    (_resp(404, b"not found"), FetchOutcome.HTTP_ERROR),
    (_resp(401, b"{}"), FetchOutcome.AUTH_ERROR),
    (_resp(429, b"Too Many Requests"), FetchOutcome.RATE_LIMITED),
])
async def test_outcome_classification(handler, outcome):
    r = await _conn(handler).fetch("/v3/x")
    assert r.outcome is outcome
    assert r.outcome.ok == (outcome in (FetchOutcome.OK_DATA, FetchOutcome.OK_EMPTY_WINDOW))


async def test_structurally_invalid_is_not_empty():
    def validator(data):
        return "data" if isinstance(data, dict) and "candles" in data else "no candles key"
    r = await _conn(_resp(200, b'{"status":"success","data":{"x":1}}')).fetch(
        "/v3/x", validator=validator)
    assert r.outcome is FetchOutcome.STRUCTURALLY_INVALID and "candles" in r.detail


async def test_metadata_request_id_and_raw_bytes():
    body = b'{"status":"success","data":{"a":1}}'
    r = await _conn(_resp(200, body, {"x-request-id": "abc123"})).fetch("/v2/y")
    assert r.data == body and r.http_status == 200 and r.fetched_at is not None
    assert r.request_id == "x-request-id=abc123" and r.retry_count == 0
    assert r.source == "UPSTOX_REST" and r.endpoint == "/v2/y"


async def test_retries_are_counted_then_success():
    calls = iter([503, 503, 200])

    def h(req):
        st = next(calls)
        return httpx.Response(st, content=b'{"status":"success","data":{"a":1}}'
                              if st == 200 else b"")
    r = await _conn(h, backoff=(0.0, 0.0, 0.0)).fetch("/v2/z")
    assert r.outcome is FetchOutcome.OK_DATA and r.retry_count == 2


async def test_exhausted_5xx_is_http_error_not_empty():
    r = await _conn(_resp(503), backoff=(0.0, 0.0)).fetch("/v2/z")
    assert r.outcome is FetchOutcome.HTTP_ERROR and r.data is None


async def test_wall_clock_timeout_never_hangs(monkeypatch):
    monkeypatch.setattr(R, "WALL_TIMEOUT", 0.05)

    async def hang(req):
        await asyncio.sleep(5)
    r = await asyncio.wait_for(_conn(hang).fetch("/v2/slow"), timeout=3)
    assert r.outcome is FetchOutcome.TIMEOUT


async def test_connection_failure_is_transport_error():
    def boom(req):
        raise httpx.ConnectError("refused")
    r = await _conn(boom).fetch("/v2/down")
    assert r.outcome is FetchOutcome.TRANSPORT_ERROR
