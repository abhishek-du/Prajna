"""The pre-open WebSocket recorder. Its only job is to put bytes on disk.

    authorize -> connect -> subscribe -> [recv -> ARCHIVE] ... -> close

It does not write the database. Rows come from replaying the archive this
produces (app/ingest/preopen.py), so a live session and a later replay run the
same code on the same bytes.

Everything a later reader needs in order to trust (or distrust) the capture is
recorded IN the archive, as EVENT records next to the frames: every connect,
subscribe, disconnect, stale period, reconnect, the subscription cap and the
keys it excluded, and which keys never produced a single frame.

Readiness is EVENT-DRIVEN, never a sleep:
  * `connected`  — the WebSocket handshake completed (the subscribe goes out
                   immediately after, on the same connection);
  * `market_info` — the vendor's first market_info frame arrived;
  * `subscription_confirmed` — the first frame carrying a subscribed key.

Liveness:
  * transport heartbeat: WebSocket ping/pong (ping_interval / ping_timeout);
  * data watchdog: no frame carrying a SUBSCRIBED key for `stale_after`
    seconds is `stale`, and the connection is recycled — a socket can be alive
    while the feed behind it is dead, and Upstox ignores an unserviceable
    subscription silently (seen live: market_info, then nothing);
  * reconnects are bounded, with exponential backoff, a FRESH authorize each
    time (the URL is single-use) and a full resubscribe. Only a connection that
    delivered subscribed data resets the failure count.

UNVERIFIED VENDOR LIMITS (carried as config, not facts): the per-connection
key cap for `full` (B5), the wire mode string (B6), and how many keys one
subscribe message may carry.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from app.contracts.provenance import Source
from app.contracts.universe import SubscriptionPlan, plan_subscription
from app.core.clock import IST, now, to_utc
from app.core.errors import PrajnaError, VendorAuthError, VendorError
from app.core.logging import get_logger
from app.storage.frame_archive import FrameArchiveWriter
from app.vendor.upstox.feed_auth import redact_ws_url
from app.vendor.upstox.proto import PROTO_SHA256
from app.vendor.upstox.proto import MarketDataFeed_pb2 as pb

log = get_logger("upstox.preopen_ws")

# Re-exported: the plan is a contract (app/contracts/universe.py), not a
# recorder detail. One implementation of "sort, then cap" for the project.
__all__ = [
    "PreopenRecorder", "RecorderConfig", "RecorderGaveUp", "RecorderSummary",
    "SubscriptionPlan", "open_capture_archive", "plan_subscription",
]

Authorizer = Callable[[], Awaitable[str]]
EventHook = Callable[[str, dict[str, Any]], None]


class RecorderGaveUp(PrajnaError):
    """Reconnect budget exhausted. The archive up to this point is intact."""


class _Stale(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RecorderConfig:
    mode: str = "full"                 # wire string; B6 — "full" vs full_d30
    cap: int | None = 2000             # UNVERIFIED (B5)
    subscribe_chunk: int = 500         # UNVERIFIED keys per subscribe message
    stale_after: float = 30.0          # seconds without a frame
    ping_interval: float = 10.0
    ping_timeout: float = 10.0
    open_timeout: float = 15.0
    max_reconnects: int = 10
    backoff_initial: float = 1.0
    backoff_max: float = 30.0
    max_frame_bytes: int = 64 * 1024 * 1024
    heartbeat_every: float = 60.0      # seconds between `heartbeat` evidence events
    proxy: str | bool | None = True    # websockets default: honour env proxies

    def public(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def archive_path_for(
    root: pathlib.Path, session_date: _dt.date, started: _dt.datetime
) -> pathlib.Path:
    s = to_utc(started)
    return (pathlib.Path(root) / Source.UPSTOX_WS_V3.value / f"{s:%Y}" / f"{s:%m}" / f"{s:%d}"
            / f"preopen_{session_date.isoformat()}_{s:%H%M%S}Z.frames.gz")


def open_capture_archive(
    root: pathlib.Path, *, session_date: _dt.date, plan: SubscriptionPlan,
    config: RecorderConfig, started: _dt.datetime | None = None, extra: dict | None = None,
    path: pathlib.Path | None = None,
) -> FrameArchiveWriter:
    """The header records the whole plan, so the archive is self-describing."""
    started = started or now()
    header = {
        "session_date": session_date.isoformat(),
        "source": Source.UPSTOX_WS_V3.value,
        "stream": "preopen",
        "endpoint": "upstox market-data-feed v3 (wss)",
        "proto_sha256": PROTO_SHA256,
        "started_at": to_utc(started).isoformat(),
        "config": config.public(),
        "requested_count": len(plan.requested),
        "subscribed_keys": list(plan.subscribed),
        "subscribed_keys_sha256": plan.keys_sha256,
        "excluded_keys": list(plan.excluded),
        "duplicate_keys_removed": plan.duplicates,
        **(extra or {}),
    }
    return FrameArchiveWriter(path or archive_path_for(root, session_date, started), header)


@dataclass(slots=True)
class RecorderSummary:
    stop_reason: str = ""
    frames: int = 0
    text_frames: int = 0
    connections: int = 0
    reconnects: int = 0
    stale_periods: int = 0
    undecodable_for_control: int = 0
    keys_seen: int = 0
    never_seen: list[str] = field(default_factory=list)
    archive: str = ""


class PreopenRecorder:
    def __init__(
        self,
        writer: FrameArchiveWriter,
        authorize: Authorizer,
        plan: SubscriptionPlan,
        config: RecorderConfig | None = None,
        *,
        stop_at: _dt.datetime | None = None,
        max_frames: int | None = None,
        stop: asyncio.Event | None = None,
        on_event: EventHook | None = None,
    ):
        self.w = writer
        self.authorize = authorize
        self.plan = plan
        self.cfg = config or RecorderConfig()
        self.stop_at = to_utc(stop_at) if stop_at else None
        self.max_frames = max_frames
        self.stop = stop or asyncio.Event()
        self.on_event = on_event
        self.summary = RecorderSummary(archive=str(writer.path))
        self._subscribed = set(plan.subscribed)
        self._seen: set[str] = set()
        self._got_data = False   # this connection delivered data for a subscribed key

    # ── evidence ────────────────────────────────────────────────────────────
    def _event(self, name: str, **detail: Any) -> None:
        self.w.append_event(name, now(), **detail)
        log.info(f"preopen_ws.{name}", **{k: v for k, v in detail.items()
                                          if not isinstance(v, list | tuple)})
        if self.on_event:
            self.on_event(name, detail)

    # ── stop conditions ─────────────────────────────────────────────────────
    def _seconds_left(self) -> float | None:
        if self.stop_at is None:
            return None
        return (self.stop_at - now()).total_seconds()

    def _should_stop(self) -> str | None:
        if self.stop.is_set():
            return "stop_requested"
        if self.max_frames is not None and self.summary.frames >= self.max_frames:
            return "max_frames"
        left = self._seconds_left()
        if left is not None and left <= 0:
            return "window_end"
        return None

    async def _pause(self, seconds: float) -> None:
        """Back off, but wake immediately on stop."""
        left = self._seconds_left()
        if left is not None:
            seconds = min(seconds, max(left, 0))
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)
        except TimeoutError:
            pass

    # ── main loop ───────────────────────────────────────────────────────────
    async def run(self) -> RecorderSummary:
        try:
            if self.plan.excluded:
                self._event("coverage_cap", requested=len(self.plan.requested),
                            cap=self.cfg.cap, subscribed=len(self.plan.subscribed),
                            dropped_keys=list(self.plan.excluded),
                            basis="cap is UNVERIFIED (B5)")
            if self.plan.duplicates:
                self._event("duplicate_keys_removed", count=self.plan.duplicates)
            await self._loop()
        finally:
            self._finish()
        return self.summary

    async def _loop(self) -> None:
        failures = 0
        while (reason := self._should_stop()) is None:
            try:
                url = await self.authorize()
                self._event("authorized", endpoint=redact_ws_url(url))
                await self._session(url)
                failures = 0            # a session that ended by a stop condition
                continue
            except VendorAuthError as e:
                self._event("auth_failed", error=str(e)[:300])
                self.summary.stop_reason = "auth_failed"
                raise
            except _Stale:
                self.summary.stale_periods += 1
                why = {"reason": "stale"}
            except ConnectionClosed as e:
                why = {"reason": "closed", "code": e.rcvd.code if e.rcvd else None,
                       "detail": (e.rcvd.reason if e.rcvd else "")[:200]}
            except (OSError, TimeoutError, InvalidHandshake, InvalidURI, VendorError) as e:
                why = {"reason": type(e).__name__, "detail": str(e)[:300]}

            if self._should_stop():
                break
            # A connection that delivered data was a success that later ended;
            # only back-to-back connections that yield nothing count as failing.
            failures = 1 if self._got_data else failures + 1
            self._event("disconnected", **why, consecutive_failures=failures)
            if failures > self.cfg.max_reconnects:
                self._event("gave_up", consecutive_failures=failures,
                            max_reconnects=self.cfg.max_reconnects)
                self.summary.stop_reason = "gave_up"
                raise RecorderGaveUp(
                    f"{failures} consecutive failed connections; archive kept at {self.w.path}")
            delay = min(self.cfg.backoff_max, self.cfg.backoff_initial * 2 ** (failures - 1))
            self._event("reconnect_scheduled", attempt=failures, delay_s=delay)
            self.summary.reconnects += 1
            await self._pause(delay)
        self.summary.stop_reason = self.summary.stop_reason or reason or self._should_stop() or ""

    async def _session(self, url: str) -> None:
        self._got_data = False
        async with connect(
            url, open_timeout=self.cfg.open_timeout, ping_interval=self.cfg.ping_interval,
            ping_timeout=self.cfg.ping_timeout, max_size=self.cfg.max_frame_bytes,
            proxy=self.cfg.proxy, compression=None,
        ) as ws:
            self.summary.connections += 1
            self._event("connected", connection=self.summary.connections)
            await self._subscribe(ws)
            await self._pump(ws)
            self._event("closing", reason=self._should_stop())
            await ws.close()

    async def _subscribe(self, ws: ClientConnection) -> None:
        keys = list(self.plan.subscribed)
        n = self.cfg.subscribe_chunk
        for i in range(0, len(keys), n):
            chunk = keys[i : i + n]
            guid = uuid.uuid4().hex
            msg = json.dumps({"guid": guid, "method": "sub",
                              "data": {"mode": self.cfg.mode, "instrumentKeys": chunk}},
                             separators=(",", ":")).encode()
            # Upstox V3 takes requests as BINARY frames.
            await ws.send(msg)
            self._event("subscribe_sent", guid=guid, mode=self.cfg.mode, count=len(chunk),
                        chunk_index=i // n, message_sha256=hashlib.sha256(msg).hexdigest())

    async def _pump(self, ws: ClientConnection) -> None:
        """Receive until a stop condition. The watchdog measures time since the
        last frame carrying a SUBSCRIBED key, not since any frame: live on
        2026-09-23 an ignored subscription (full_d30 without Plus) produced a
        market_info frame and then silence, and a feed of keyless frames is no
        healthier than no feed at all."""
        loop = asyncio.get_running_loop()
        confirmed = market_info = False
        last_useful = last_beat = loop.time()
        while self._should_stop() is None:
            left = self._seconds_left()
            quiet = loop.time() - last_useful
            timeout = self.cfg.stale_after - quiet
            if left is not None:
                timeout = min(timeout, left)
            try:
                if timeout <= 0:
                    raise TimeoutError
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
            except TimeoutError:
                if self._should_stop():
                    return
                self._event("stale", silent_for_s=self.cfg.stale_after,
                            subscribed_data_seen=confirmed)
                raise _Stale from None

            recv_at = now()
            self.w.append_frame(msg, recv_at)          # ARCHIVE FIRST, always
            self.summary.frames += 1
            if loop.time() - last_beat >= self.cfg.heartbeat_every:
                # Transport liveness as evidence: the last ping round-trip.
                last_beat = loop.time()
                self._event("heartbeat", ping_rtt_ms=round(ws.latency * 1000, 3),
                            frames=self.summary.frames, keys_seen=len(self._seen))
            if isinstance(msg, str):
                self.summary.text_frames += 1
                continue

            # Control-plane peek only. Failure here never loses data: the bytes
            # are already archived and replay decodes them properly.
            try:
                fr = pb.FeedResponse.FromString(msg)
            except Exception:
                self.summary.undecodable_for_control += 1
                continue
            if not market_info and fr.HasField("marketInfo"):
                market_info = True
                self._event("market_info", vendor_ts=fr.currentTs)
            hit = self._subscribed.intersection(fr.feeds.keys()) if fr.feeds else set()
            if hit:
                self._seen |= hit
                last_useful = loop.time()
                self._got_data = True
                if not confirmed:
                    confirmed = True
                    self._event("subscription_confirmed", first_keys=len(hit),
                                feed_type=pb.Type.Name(fr.type) if fr.type in pb.Type.values()
                                else fr.type)

    def _finish(self) -> None:
        never = sorted(self._subscribed - self._seen)
        self.summary.keys_seen = len(self._seen)
        self.summary.never_seen = never
        self.summary.stop_reason = self.summary.stop_reason or "error"
        self._event("capture_end", stop_reason=self.summary.stop_reason,
                    frames=self.summary.frames, connections=self.summary.connections,
                    reconnects=self.summary.reconnects, keys_seen=len(self._seen),
                    never_seen_count=len(never), never_seen_keys=never,
                    ended_at_ist=now().astimezone(IST).isoformat())
        self.w.close()
