"""A scripted stand-in for the Upstox V3 feed server, on loopback.

Each connection follows one step of a script:

    ("stream", n)     market_info, then initial_feed, then n live frames, then
                      keep streaming slowly until the client leaves
    ("drop", n)       like stream, then close with 1011 after n live frames
    ("silent",)       market_info + initial_feed, then nothing (a dead feed)
    ("reject", code)  refuse the WebSocket handshake with this HTTP status

`per_key_script` overrides the script for connections whose FIRST subscribed
key is the given key, indexed by how often that key's connection has
connected, so concurrent connections (one per shard) can behave differently.

The server records exactly what it sent, so tests can assert the archive holds
those bytes verbatim, and what it received, so tests can check subscriptions.
"""

from __future__ import annotations

import asyncio
import json
from http import HTTPStatus

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from app.core.clock import now
from app.vendor.upstox.proto import MarketDataFeed_pb2 as pb
from tests.support.upstox_frames import frame, market_ff, status_frame


class FakeUpstoxFeed:
    def __init__(self, script, *, only_keys: set[str] | None = None, interval: float = 0.01,
                 per_key_script: dict[str, list] | None = None):
        self.script = list(script)
        self.per_key_script = per_key_script or {}
        self._per_key_n: dict[str, int] = {}
        self.only_keys = only_keys
        self.interval = interval
        self.connections = 0
        self.sent: list[list[bytes]] = []
        self.subscriptions: list[list[dict]] = []
        self._server = None
        self.port = 0

    def _step(self, n: int):
        return self.script[min(n, len(self.script) - 1)]

    def _process_request(self, connection, request):
        step = self._step(self.connections)
        if step[0] == "reject":
            self.connections += 1
            self.sent.append([])
            self.subscriptions.append([])
            status = HTTPStatus(step[1])
            return Response(status.value, status.phrase, Headers(), b"rejected")
        return None

    def _feed(self, keys, kind, iep):
        keys = [k for k in keys if self.only_keys is None or k in self.only_keys]
        return frame({k: market_ff(iep=iep) for k in keys}, now(), kind=kind)

    async def _handler(self, ws):
        conn = self.connections
        self.connections += 1
        step = self._step(conn)
        sent: list[bytes] = []
        subs: list[dict] = []
        self.sent.append(sent)
        self.subscriptions.append(subs)

        async def send(data: bytes):
            sent.append(data)
            await ws.send(data)

        await send(status_frame(now(), {"NSE_EQ": ("PRE_OPEN_START", now())}))
        msg = await ws.recv()
        subs.append(json.loads(msg))
        keys = [k for s in subs for k in s["data"]["instrumentKeys"]]
        # Drain any further subscribe chunks the client sends straight away.
        while True:
            try:
                more = await asyncio.wait_for(ws.recv(), timeout=0.05)
            except TimeoutError:
                break
            subs.append(json.loads(more))
            keys += subs[-1]["data"]["instrumentKeys"]

        if keys and keys[0] in self.per_key_script:
            n = self._per_key_n.get(keys[0], 0)
            self._per_key_n[keys[0]] = n + 1
            ks = self.per_key_script[keys[0]]
            step = ks[min(n, len(ks) - 1)]
        if step[0] == "ignore":
            # Seen live with full_d30: market_info, then silence for our keys.
            await ws.wait_closed()
            return
        await send(self._feed(keys, pb.initial_feed, 2458.0))
        if step[0] == "silent":
            await ws.wait_closed()
            return
        i = 0
        while True:
            if step[0] == "drop" and i >= step[1]:
                await ws.close(1011, "scripted drop")
                return
            await asyncio.sleep(self.interval)
            try:
                await send(self._feed(keys, pb.live_feed, 2458.0 + 0.05 * (i + 1)))
            except Exception:
                return
            i += 1

    async def __aenter__(self):
        self._server = await serve(self._handler, "127.0.0.1", 0,
                                   process_request=self._process_request, compression=None)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    def url(self, n: int) -> str:
        # The query string stands in for Upstox's one-time credential.
        return f"ws://127.0.0.1:{self.port}/v3/feed?code=SECRET-{n}"
