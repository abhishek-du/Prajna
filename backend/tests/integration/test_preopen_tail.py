"""PREOPEN-TAIL: replay a capture while it records, the ready marker, its verification,
and acceptance of a tail-run chain (user 2026-10-22: PRE_OPEN before the open)."""

from __future__ import annotations

import datetime as _dt
import json
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.acceptance.preopen_day import _replayed
from app.ingest.preopen import (
    READY_MARGIN,
    NotReady,
    TailPass,
    replay_archive,
    tail_session,
    verify_ready,
)
from app.storage.frame_archive import FrameArchiveWriter
from app.vendor.upstox.proto import PROTO_SHA256
from tests.integration.test_preopen_replay import _seed_session, _session_frames
from tests.support.upstox_frames import NIFTYBEES, RELIANCE, SESSION, frame, ist, market_ff

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
LAG = _dt.timedelta(milliseconds=35)
AS_OF = ist(9, 8)                     # PRE_OPEN as_of on a 09:00 pre-open


def _writer(path, session_id="sess1", shard=0):
    return FrameArchiveWriter(path, {
        "session_date": SESSION.isoformat(), "proto_sha256": PROTO_SHA256,
        "endpoint": "wss://test/v3/feed", "source": "UPSTOX_WS_V3",
        "session_id": session_id, "shard_index": shard})


def _append(w, frames):
    for at, data in frames:
        w.append_frame(data, at + LAG)


async def _ticks(s):
    return (await s.execute(text("select count(*) from preopen_tick"))).scalar()


def _manifest(tmp_path, archives, session_id="sess1"):
    m = tmp_path / "x.session.json"
    m.write_text(json.dumps({"session_id": session_id, "session_date": SESSION.isoformat(),
                             "shards": [{"index": i, "archive": str(a)}
                                        for i, a in enumerate(archives)]}))
    return m


class TestTailPass:
    async def test_passes_commit_only_new_records_and_final_verifies(self, db_session,
                                                                     tmp_path):
        await _seed_session(db_session)
        arc = tmp_path / "c0.frames.gz"
        w = _writer(arc)
        w.append_event("connected", ist(8, 55))
        fr = _session_frames()
        _append(w, fr[:2])                               # still recording

        p1 = await replay_archive(db_session, arc, commit=True, token=TOKEN,
                                  tail=TailPass(0, ist(9, 1)))
        assert p1.status == "COMPLETE" and p1.next_seq == 3 and p1.ticks_inserted == 2
        assert not p1.truncated and not any(a["kind"] == "GAP" for a in p1.anomalies)

        empty = await replay_archive(db_session, arc, commit=True, token=TOKEN,
                                     tail=TailPass(3, ist(9, 2)))
        assert empty.status == "EMPTY" and empty.run_id is None and empty.next_seq == 3

        _append(w, fr[2:])
        p2 = await replay_archive(db_session, arc, commit=True, token=TOKEN,
                                  tail=TailPass(3, ist(9, 8, 6)))
        assert (p2.status, p2.next_seq, p2.ticks_inserted, p2.records) == ("COMPLETE", 5, 1, 2)
        w.close()
        fin = await replay_archive(db_session, arc, commit=True, token=TOKEN,
                                   tail=TailPass(5, ist(9, 21), final=True))
        assert fin.status == "COMPLETE" and fin.records == 0 and fin.error is None
        assert not any(a["severity"] == "FAIL" for a in fin.anomalies)

        tp = (await db_session.execute(text("""select request_params->'tail' from ingest_run
            where run_id = any(cast(:r as uuid[])) order by started_at"""),
            {"r": [str(p1.run_id), str(p2.run_id), str(fin.run_id)]})).scalars().all()
        assert [(t["seq_from"], t["seq_to"], t["final"]) for t in tp] == [
            (0, 3, False), (3, 5, False), (5, 5, True)]

        # the tail wrote what a full replay writes: a full replay now finds all present
        full = await replay_archive(db_session, arc, commit=True, token=TOKEN)
        assert full.rows_written == 0 and full.ticks_already_present == 3

    async def test_final_pass_detects_a_stream_that_disagrees_with_its_manifest(
            self, db_session, tmp_path):
        await _seed_session(db_session)
        arc = tmp_path / "c0.frames.gz"
        w = _writer(arc)
        _append(w, _session_frames())
        w.close()
        mp = arc.with_name(arc.name + ".manifest.json")
        doc = json.loads(mp.read_text())
        doc["stream_sha256"] = "0" * 64
        mp.write_text(json.dumps(doc))
        fin = await replay_archive(db_session, arc, commit=True, token=TOKEN,
                                   tail=TailPass(0, ist(9, 21), final=True))
        assert fin.status == "FAILED" and "stream" in json.dumps(fin.anomalies)


class TestTailSession:
    async def test_marker_after_the_ready_pass_and_verified(self, db_session, tmp_path):
        await _seed_session(db_session)
        arcs = []
        for i, keys in enumerate(([RELIANCE], [NIFTYBEES])):
            a = tmp_path / f"c{i}.frames.gz"
            w = _writer(a, shard=i)
            _append(w, [(ist(9, 3), frame({k: market_ff()}, ist(9, 3))) for k in keys])
            w.close()
            arcs.append(a)
        marker = tmp_path / "ready.json"
        out = await tail_session(db_session, _manifest(tmp_path, arcs), token=TOKEN,
                                 ready_at=AS_OF + READY_MARGIN - _dt.timedelta(days=3650),
                                 interval_s=0, marker=marker)
        assert out["status"] == "COMPLETE" and out["passes"] == 1, out
        assert out["late_ticks"] == 0 and out["ready"]["analyze"]["ok"] in (True, False)
        assert [sh["runs"] for sh in out["shards"]] == [1, 1] and await _ticks(db_session) == 2

        # pass_started_at is "now" (2026+), which is after SESSION's as_of + margin
        ev = await verify_ready(db_session, SESSION, AS_OF, marker)
        assert ev["records"] == [1, 1]

        m = json.loads(marker.read_text())
        early = dict(m, pass_started_at=(AS_OF + READY_MARGIN
                                         - _dt.timedelta(seconds=1)).isoformat())
        marker.write_text(json.dumps(early))
        with pytest.raises(NotReady, match="before as_of"):
            await verify_ready(db_session, SESSION, AS_OF, marker)

        gap = dict(m, shards=[dict(m["shards"][0], next_seq=2), m["shards"][1]])
        marker.write_text(json.dumps(gap))
        with pytest.raises(NotReady, match="runs end at"):
            await verify_ready(db_session, SESSION, AS_OF, marker)

        missing = dict(m, shards=[dict(m["shards"][0], run_ids=[]), m["shards"][1]])
        marker.write_text(json.dumps(missing))
        with pytest.raises(NotReady):
            await verify_ready(db_session, SESSION, AS_OF, marker)

    async def test_no_marker_is_not_ready(self, db_session, tmp_path):
        with pytest.raises(NotReady, match="no marker"):
            await verify_ready(db_session, SESSION, AS_OF, tmp_path / "absent.json")

    async def test_a_failed_pass_stops_the_tail(self, db_session, tmp_path):
        # no trading_session row: every pass FAILS (fail closed), nothing is marked ready
        a = tmp_path / "c0.frames.gz"
        w = _writer(a)
        _append(w, _session_frames()[:2])
        w.close()
        marker = tmp_path / "ready.json"
        out = await tail_session(db_session, _manifest(tmp_path, [a]), token=TOKEN,
                                 ready_at=AS_OF, interval_s=0, marker=marker)
        assert out["status"] == "FAILED" and not marker.exists()


class TestAcceptanceChain:
    def _r(self, a, b, final=False, status="COMPLETE"):
        return SimpleNamespace(seq_from=a, seq_to=b, final=final, status=status)

    def test_tail_chain_full_and_gaps(self):
        assert _replayed("x", [self._r(0, 5), self._r(5, 9), self._r(9, 9, True)]) == "tail"
        assert _replayed("x", [self._r(0, 5), self._r(6, 9, True)]) is None       # gap
        assert _replayed("x", [self._r(0, 5), self._r(5, 9)]) is None             # no final
        assert _replayed("x", [self._r(0, 5), self._r(5, 9, True, "FAILED")]) is None
        assert _replayed("x", [self._r(0, 5), self._r(None, None)]) == "full"     # fallback
        assert _replayed("x", []) is None


class TestLockReuse:
    def test_reusable_only_when_passing_same_mode_and_fresh(self):
        from app.features.locks import REUSE_MAX, LockReport
        r = LockReport("RUN")
        r.add("x", True, "")
        t = r.evaluated_at
        assert r.reusable("RUN", t + REUSE_MAX) and not r.reusable("BACKFILL", t)
        assert not r.reusable("RUN", t + REUSE_MAX + _dt.timedelta(seconds=1))
        r.add("y", False, "")
        assert not r.reusable("RUN", t)
