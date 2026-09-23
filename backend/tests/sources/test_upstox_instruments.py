"""The master download, against a mocked transport. No network."""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import VendorError
from app.sources.upstox_instruments import MASTER_URL, download_master
from tests.support import upstox_master as M


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_bytes_are_returned_exactly_as_served():
    body, seen = M.master_bytes(M.ALL), {}

    def handler(req):
        seen["url"], seen["headers"] = str(req.url), dict(req.headers)
        return httpx.Response(200, content=body, headers={"last-modified": "Tue, 22 Sep 2026"})

    async with _client(handler) as c:
        d = await download_master(client=c)
    assert d.data == body and d.http_status == 200 and d.last_modified.startswith("Tue")
    assert seen["url"] == MASTER_URL
    assert "authorization" not in seen["headers"]      # public asset: no token sent


async def test_http_error_is_loud():
    async with _client(lambda req: httpx.Response(404, content=b"nope")) as c:
        with pytest.raises(VendorError, match="404"):
            await download_master(client=c)


async def test_empty_body_is_loud():
    async with _client(lambda req: httpx.Response(200, content=b"")) as c:
        with pytest.raises(VendorError):
            await download_master(client=c)
