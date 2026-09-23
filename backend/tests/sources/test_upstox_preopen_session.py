"""Multi-connection capture: deterministic, disjoint shards, each connection
independent, one manifest that accounts for every key."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.contracts.universe import plan_shards
from app.core.clock import now
from app.sources.upstox_preopen_session import PreopenCaptureSession
from app.sources.upstox_preopen_ws import RecorderConfig
from app.storage.frame_archive import FrameArchiveReader, RecordKind
from tests.support.fake_upstox_ws import FakeUpstoxFeed

KEYS = [f"NSE_EQ|INE{i:09d}" for i in range(7)]
CFG = RecorderConfig(stale_after=2.0, backoff_initial=0.01, backoff_max=0.05,
                     max_reconnects=2, open_timeout=2.0, proxy=None, cap=3)


def _auth(feed):
    calls = {"n": 0}

    async def authorize():
        calls["n"] += 1
        return feed.url(calls["n"])
    return authorize, calls


def _session(tmp_path, feed, *, keys=KEYS, per=3, conns=3, cfg=CFG, **kw):
    plan = plan_shards(keys, per_connection=per, max_connections=conns)
    auth, calls = _auth(feed)
    return PreopenCaptureSession(tmp_path, session_date=now().date(), plan=plan,
                                 authorize=auth, config=cfg, **kw), calls


def _events(path):
    return [r.event() for r in FrameArchiveReader(path) if r.kind is RecordKind.EVENT]


async def _run(s):
    async with asyncio.timeout(15):
        return await s.run()


class TestPlan:
    def test_shards_are_contiguous_disjoint_and_complete(self):
        p = plan_shards(reversed(KEYS), per_connection=3, max_connections=3)
        assert p.shards == (tuple(KEYS[0:3]), tuple(KEYS[3:6]), tuple(KEYS[6:7]))
        flat = [k for s in p.shards for k in s]
        assert len(flat) == len(set(flat)) == len(KEYS) and p.excluded == ()

    def test_same_universe_same_assignment(self):
        a = plan_shards(KEYS, per_connection=3, max_connections=3)
        b = plan_shards(KEYS[::-1] + KEYS[:2], per_connection=3, max_connections=3)
        assert a.shards == b.shards and b.duplicates == 2

    def test_beyond_total_capacity_is_excluded_by_name(self):
        p = plan_shards(KEYS, per_connection=2, max_connections=2)
        assert [len(s) for s in p.shards] == [2, 2] and p.excluded == tuple(KEYS[4:])

    def test_measured_live_numbers_cover_the_current_universe(self):
        keys = [f"NSE_EQ|K{i:05d}" for i in range(3525)]
        p = plan_shards(keys, per_connection=2000, max_connections=2)
        assert [len(s) for s in p.shards] == [2000, 1525] and p.excluded == ()

    @pytest.mark.parametrize("per, conns", [(0, 1), (1, 0)])
    def test_nonsense_capacity_is_refused(self, per, conns):
        with pytest.raises(ValueError):
            plan_shards(KEYS, per_connection=per, max_connections=conns)


class TestSession:
    async def test_every_connection_gets_its_own_archive_and_subscription(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 10**6)]) as feed:
            s, calls = _session(tmp_path, feed, max_frames_per_connection=4)
            doc = await _run(s)
        assert doc["status"] == "complete" and len(doc["shards"]) == 3
        assert calls["n"] == 3                      # one fresh authorize per connection
        subs = sorted(tuple(c[0]["data"]["instrumentKeys"]) for c in feed.subscriptions)
        assert subs == [tuple(KEYS[0:3]), tuple(KEYS[3:6]), tuple(KEYS[6:7])]
        archives = {sh["archive"] for sh in doc["shards"]}
        assert len(archives) == 3
        for sh in doc["shards"]:
            h = FrameArchiveReader(sh["archive"])
            list(h)
            assert h.header["session_id"] == doc["session_id"]
            assert h.header["shard_index"] == sh["index"] and h.header["shard_count"] == 3
        assert doc["coverage"] == {"subscribed": 7, "seen": 7, "never_seen": 0,
                                   "never_seen_keys": []}

    async def test_one_connection_failing_does_not_stop_the_others(self, tmp_path):
        """Shard 1's subscription is ignored (as full_d30 was, live): it goes
        stale, exhausts its reconnects and gives up; shards 0 and 2 finish."""
        cfg = RecorderConfig(**{**CFG.public(), "stale_after": 0.2, "max_reconnects": 1})
        async with FakeUpstoxFeed([("stream", 10**6)],
                                  per_key_script={KEYS[3]: [("ignore",)]}) as feed:
            s, _ = _session(tmp_path, feed, cfg=cfg, max_frames_per_connection=4)
            doc = await _run(s)
        assert doc["status"] == "partial"
        errs = {sh["index"]: sh["error"] for sh in doc["shards"]}
        assert errs[0] is None and errs[2] is None and "RecorderGaveUp" in errs[1]
        assert doc["coverage"]["never_seen_keys"] == KEYS[3:6]
        assert doc["coverage"]["seen"] == 4

    async def test_drop_and_stale_are_per_connection(self, tmp_path):
        cfg = RecorderConfig(**{**CFG.public(), "stale_after": 0.3, "max_reconnects": 3})
        script = {KEYS[0]: [("drop", 1), ("stream", 10**6)],
                  KEYS[3]: [("silent",), ("stream", 10**6)]}
        async with FakeUpstoxFeed([("stream", 10**6)], per_key_script=script) as feed:
            s, _ = _session(tmp_path, feed, cfg=cfg, max_frames_per_connection=6)
            doc = await _run(s)
        assert doc["status"] == "complete"
        names = [[e["event"] for e in _events(sh["archive"])] for sh in doc["shards"]]
        assert "disconnected" in names[0] and "stale" not in names[0]
        assert "stale" in names[1]
        assert "disconnected" not in names[2] and "stale" not in names[2]

    async def test_manifest_exists_while_running(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 10**6)]) as feed:
            s, _ = _session(tmp_path, feed, max_frames_per_connection=2)
            running = json.loads(s.manifest_path.read_text())
            assert running["status"] == "running" and running["coverage"] is None
            assert [sh["keys"] for sh in running["shards"]] == [3, 3, 1]
            await _run(s)

    async def test_capacity_exclusions_are_recorded_once(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 10**6)]) as feed:
            s, _ = _session(tmp_path, feed, per=3, conns=2, max_frames_per_connection=3)
            doc = await _run(s)
        assert doc["universe"]["excluded_by_capacity"] == KEYS[6:]
        caps = [[e for e in _events(sh["archive"]) if e["event"] == "coverage_cap"]
                for sh in doc["shards"]]
        assert len(caps[0]) == 1 and caps[0][0]["dropped_keys"] == KEYS[6:] and caps[1] == []

    async def test_no_credential_in_any_archive_or_manifest(self, tmp_path):
        async with FakeUpstoxFeed([("stream", 10**6)]) as feed:
            s, _ = _session(tmp_path, feed, max_frames_per_connection=3)
            await _run(s)
        assert b"SECRET" not in s.manifest_path.read_bytes()
        for w in s.writers:
            for r in FrameArchiveReader(w.path):
                if r.kind is RecordKind.EVENT:
                    assert b"SECRET" not in r.payload
