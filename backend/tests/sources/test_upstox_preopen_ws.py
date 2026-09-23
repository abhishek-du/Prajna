"""The recorder against a scripted local feed: bytes verbatim, event-driven
readiness, watchdog, bounded reconnect, nothing excluded silently."""

from __future__ import annotations

import asyncio
import datetime as _dt
import pathlib

import httpx
import pytest

from app.core.clock import now
from app.core.errors import VendorAuthError, VendorError
from app.sources.upstox_preopen_ws import (
    PreopenRecorder,
    RecorderConfig,
    RecorderGaveUp,
    open_capture_archive,
    plan_subscription,
)
from app.storage.frame_archive import FrameArchiveReader, RecordKind, manifest_path
from app.vendor.upstox.feed_auth import authorize_feed_v3
from tests.support.fake_upstox_ws import FakeUpstoxFeed
from tests.support.upstox_frames import NIFTYBEES, RELIANCE

KEYS = [RELIANCE, NIFTYBEES]
FAST = RecorderConfig(stale_after=2.0, backoff_initial=0.01, backoff_max=0.05,
                      max_reconnects=3, open_timeout=2.0, proxy=None)


class Auth:
    def __init__(self, feed: FakeUpstoxFeed):
        self.feed, self.calls = feed, 0

    async def __call__(self) -> str:
        self.calls += 1
        return self.feed.url(self.calls)


def _recorder(tmp_path, feed, *, keys=KEYS, cfg=FAST, **kw):
    plan = plan_subscription(keys, cfg.cap)
    w = open_capture_archive(tmp_path, session_date=now().date(), plan=plan, config=cfg)
    auth = Auth(feed)
    return PreopenRecorder(w, auth, plan, cfg, **kw), auth


def _read(path):
    recs = list(FrameArchiveReader(path))
    frames = [r.payload for r in recs if r.kind is RecordKind.BINARY]
    events = [r.event() for r in recs if r.kind is RecordKind.EVENT]
    return recs, frames, events


def _names(events):
    return [e["event"] for e in events]


async def _run(rec):
    async with asyncio.timeout(10):
        return await rec.run()


class TestHappyPath:
    async def test_every_frame_is_archived_verbatim(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 100)]) as feed:
            rec, _ = _recorder(tmp_path, feed, max_frames=7)
            summary = await _run(rec)
        _, frames, _ = _read(summary.archive)
        assert summary.stop_reason == "max_frames" and summary.frames == 7
        assert frames == feed.sent[0][:7]

    async def test_readiness_is_driven_by_vendor_events(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 100)]) as feed:
            rec, _ = _recorder(tmp_path, feed, max_frames=4)
            summary = await _run(rec)
        _, _, events = _read(summary.archive)
        names = _names(events)
        assert names[:5] == ["authorized", "connected", "subscribe_sent", "market_info",
                             "subscription_confirmed"]
        assert names[-1] == "capture_end"
        assert manifest_path(pathlib.Path(summary.archive)).exists()

    async def test_subscribe_message_shape(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 100)]) as feed:
            rec, _ = _recorder(tmp_path, feed, max_frames=3)
            await _run(rec)
        (sub,) = feed.subscriptions[0]
        assert sub["method"] == "sub" and sub["data"]["mode"] == "full"
        assert sub["data"]["instrumentKeys"] == sorted(KEYS) and len(sub["guid"]) == 32

    async def test_one_time_url_credential_is_never_archived(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 100)]) as feed:
            rec, _ = _recorder(tmp_path, feed, max_frames=3)
            summary = await _run(rec)
        recs, _, events = _read(summary.archive)
        assert all(b"SECRET" not in r.payload for r in recs if r.kind is RecordKind.EVENT)
        assert events[0]["endpoint"] == f"ws://127.0.0.1:{feed.port}/v3/feed"

    async def test_window_end_stops_the_capture(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 10**6)], interval=0.02) as feed:
            rec, _ = _recorder(tmp_path, feed, stop_at=now() + _dt.timedelta(seconds=0.5))
            summary = await _run(rec)
        assert summary.stop_reason == "window_end" and summary.frames > 3

    async def test_heartbeat_evidence_is_archived(self, tmp_path):
        cfg = RecorderConfig(**{**FAST.public(), "heartbeat_every": 0.05,
                                "ping_interval": 0.05})
        async with FakeUpstoxFeed([("stream", 10**6)], interval=0.02) as feed:
            rec, _ = _recorder(tmp_path, feed, cfg=cfg, max_frames=25)
            summary = await _run(rec)
        beats = [e for e in _read(summary.archive)[2] if e["event"] == "heartbeat"]
        assert beats and all(isinstance(b["ping_rtt_ms"], float) for b in beats)
        assert any(b["ping_rtt_ms"] > 0 for b in beats)

    async def test_subscribe_is_chunked(self, tmp_path):
        keys = [f"NSE_EQ|INE00000{i:04d}" for i in range(5)]
        cfg = RecorderConfig(**{**FAST.public(), "subscribe_chunk": 2})
        async with FakeUpstoxFeed([("stream", 100)]) as feed:
            rec, _ = _recorder(tmp_path, feed, keys=keys, cfg=cfg, max_frames=3)
            await _run(rec)
        assert [len(s["data"]["instrumentKeys"]) for s in feed.subscriptions[0]] == [2, 2, 1]


class TestLiveness:
    async def test_drop_reauthorizes_and_resubscribes(self, tmp_path):
        async with FakeUpstoxFeed([("drop", 2), ("stream", 100)]) as feed:
            rec, auth = _recorder(tmp_path, feed, max_frames=4 + 5)
            summary = await _run(rec)
        recs, frames, events = _read(summary.archive)
        assert auth.calls == 2 and summary.connections == 2 and summary.reconnects == 1
        assert [s[0]["data"]["instrumentKeys"] for s in feed.subscriptions] == [sorted(KEYS)] * 2
        assert frames == feed.sent[0] + feed.sent[1][:5]
        assert [r.seq for r in recs] == list(range(len(recs)))
        disc = next(e for e in events if e["event"] == "disconnected")
        assert disc["reason"] == "closed" and disc["code"] == 1011

    async def test_stale_feed_is_detected_and_recycled(self, tmp_path):
        cfg = RecorderConfig(**{**FAST.public(), "stale_after": 0.3})
        async with FakeUpstoxFeed([("silent",), ("stream", 100)]) as feed:
            rec, _ = _recorder(tmp_path, feed, cfg=cfg, max_frames=2 + 4)
            summary = await _run(rec)
        _, _, events = _read(summary.archive)
        assert "stale" in _names(events) and summary.stale_periods == 1
        assert summary.connections == 2

    async def test_reconnects_are_bounded(self, tmp_path):
        async with FakeUpstoxFeed([("reject", 503)]) as feed:
            rec, auth = _recorder(tmp_path, feed)
            with pytest.raises(RecorderGaveUp):
                await _run(rec)
        _, _, events = _read(rec.w.path)
        assert auth.calls == FAST.max_reconnects + 1
        assert "gave_up" in _names(events) and _names(events)[-1] == "capture_end"
        assert manifest_path(rec.w.path).exists()   # archive closed cleanly anyway

    async def test_silently_ignored_subscription_still_gives_up(self, tmp_path):
        """Seen live 2026-09-23 with full_d30: Upstox sends market_info and then
        nothing for any subscribed key, with no error. market_info is not data
        for our keys, so those connections must count as failures."""
        cfg = RecorderConfig(**{**FAST.public(), "stale_after": 0.2, "max_reconnects": 2})
        async with FakeUpstoxFeed([("stream", 10**6)], only_keys=set()) as feed:
            rec, auth = _recorder(tmp_path, feed, cfg=cfg)
            with pytest.raises(RecorderGaveUp):
                await _run(rec)
        assert auth.calls == 3 and rec.summary.never_seen == sorted(KEYS)

    async def test_auth_failure_is_not_retried(self, tmp_path):
        async def dead_token():
            raise VendorAuthError("feed authorize rejected: HTTP 401 ['UDAPI100050']")
        async with FakeUpstoxFeed([("stream", 1)]) as feed:
            rec, _ = _recorder(tmp_path, feed)
            rec.authorize = dead_token
            with pytest.raises(VendorAuthError):
                await _run(rec)
        _, _, events = _read(rec.w.path)
        assert _names(events).count("auth_failed") == 1 and feed.connections == 0


class TestCoverage:
    def test_cap_is_deterministic_and_names_every_excluded_key(self):
        keys = [f"NSE_EQ|INE00000{i:04d}" for i in (4, 1, 3, 0, 2, 1)]
        plan = plan_subscription(keys, cap=3)
        assert plan.subscribed == tuple(sorted(set(keys))[:3])
        assert plan.excluded == ("NSE_EQ|INE000000003", "NSE_EQ|INE000000004")
        assert plan.duplicates == 1
        assert plan_subscription(reversed(keys), cap=3) == plan

    def test_malformed_key_is_refused(self):
        with pytest.raises(ValueError):
            plan_subscription(["RELIANCE"], cap=None)

    async def test_cap_is_recorded_and_only_kept_keys_are_subscribed(self, tmp_path):
        keys = [f"NSE_EQ|INE00000{i:04d}" for i in range(5)]
        cfg = RecorderConfig(**{**FAST.public(), "cap": 3})
        async with FakeUpstoxFeed([("stream", 100)]) as feed:
            rec, _ = _recorder(tmp_path, feed, keys=keys, cfg=cfg, max_frames=3)
            summary = await _run(rec)
        _, _, events = _read(summary.archive)
        cap = next(e for e in events if e["event"] == "coverage_cap")
        assert cap["dropped_keys"] == keys[3:]
        assert feed.subscriptions[0][0]["data"]["instrumentKeys"] == keys[:3]

    async def test_keys_that_never_produce_a_frame_are_named(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 100)], only_keys={RELIANCE}) as feed:
            rec, _ = _recorder(tmp_path, feed, max_frames=4)
            summary = await _run(rec)
        assert summary.never_seen == [NIFTYBEES]
        _, _, events = _read(summary.archive)
        assert events[-1]["never_seen_keys"] == [NIFTYBEES]


class TestFeedAuthorize:
    def _client(self, status, body):
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(status, json=body)))

    async def test_success_returns_the_ws_url(self):
        body = {"status": "success", "data": {"authorized_redirect_uri": "wss://x/feed?code=1"}}
        async with self._client(200, body) as c:
            assert await authorize_feed_v3("tok", client=c) == "wss://x/feed?code=1"

    async def test_expired_token_is_auth_error(self):
        body = {"status": "error", "errors": [{"errorCode": "UDAPI100050"}]}
        async with self._client(401, body) as c:
            with pytest.raises(VendorAuthError, match="UDAPI100050"):
                await authorize_feed_v3("tok", client=c)

    async def test_missing_url_is_vendor_error(self):
        async with self._client(200, {"status": "success", "data": {}}) as c:
            with pytest.raises(VendorError):
                await authorize_feed_v3("tok", client=c)

    async def test_no_token_is_refused_before_any_request(self):
        with pytest.raises(VendorAuthError, match="B0"):
            await authorize_feed_v3("")

    def test_request_carries_bearer_token(self):
        seen = {}

        def handler(req):
            seen.update(req.headers)
            return httpx.Response(200, json={"status": "success", "data": {
                "authorized_redirect_uri": "wss://x/y"}})

        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                await authorize_feed_v3("tok123", client=c)
        asyncio.run(go())
        assert seen["authorization"] == "Bearer tok123"
