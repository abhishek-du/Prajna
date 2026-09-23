"""Failure and recovery cases not covered elsewhere.

The full index of Stage-1 failure tests, and where each lives, is in
docs/STAGE_1_COMPLETION_MATRIX.md §Failure/recovery.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.ingest import preopen as P
from app.ingest.preopen import replay_archive
from app.vendor.upstox.proto import MarketDataFeed_pb2 as pb
from tests.integration.test_preopen_replay import (
    _count,
    _seed_session,
    _session_frames,
    _write_archive,
)
from tests.support.upstox_frames import RELIANCE, frame, ist, market_ff, varint

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]


async def test_identical_frame_twice_in_one_archive_is_one_observation(db_session, tmp_path):
    """E.g. a vendor resend. Same bytes, same key and currentTs: not a conflict."""
    await _seed_session(db_session)
    at = ist(9, 4)
    f = frame({RELIANCE: market_ff()}, at)
    arc = _write_archive(tmp_path / "s.frames.gz", [(at, f), (at, f)])
    rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
    assert rep.status == "COMPLETE", rep.anomalies
    assert (rep.ticks_parsed, rep.ticks_inserted, rep.ticks_already_present) == (2, 1, 1)
    assert await _count(db_session, "preopen_tick") == 1


async def test_schema_drift_in_a_live_frame_fails_the_replay(db_session, tmp_path):
    await _seed_session(db_session)
    f = market_ff()
    raw = f.fullFeed.marketFF.SerializeToString() + varint(17 << 3) + varint(5)
    f.fullFeed.marketFF.Clear()
    f.fullFeed.marketFF.MergeFromString(raw)
    at = ist(9, 5)
    arc = _write_archive(tmp_path / "s.frames.gz", [(at, frame({RELIANCE: f}, at))])
    rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
    assert rep.status == "FAILED"
    assert any(a["kind"] == "SCHEMA_DRIFT" for a in rep.anomalies)
    assert await _count(db_session, "preopen_tick") == 0


async def test_never_seen_key_becomes_a_database_anomaly(db_session, tmp_path):
    from app.storage.frame_archive import FrameArchiveWriter
    from app.vendor.upstox.proto import PROTO_SHA256

    await _seed_session(db_session)
    at = ist(9, 3)
    w = FrameArchiveWriter(tmp_path / "s.frames.gz", {
        "session_date": "2026-09-24", "proto_sha256": PROTO_SHA256})
    w.append_frame(frame({RELIANCE: market_ff()}, at), at)
    w.append_event("capture_end", at, never_seen_count=1,
                   never_seen_keys=["NSE_EQ|INF204KB14I2"])
    w.close()
    rep = await replay_archive(db_session, w.path, commit=True, token=TOKEN)
    assert rep.status == "COMPLETE"
    drop = (await db_session.execute(text(
        "select detail from ingest_anomaly where run_id=:r and kind='COVERAGE_DROP'"),
        {"r": rep.run_id})).scalar()
    assert drop["keys"] == ["NSE_EQ|INF204KB14I2"]


async def test_replay_after_an_interrupted_replay(db_session, tmp_path, monkeypatch):
    """A crash mid-write rolls back EVERY staged row; the run is FAILED with
    rows_written 0; the next replay of the same archive completes in full."""
    await _seed_session(db_session)
    arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())

    real_ticks, calls = P._Writer.ticks, {"n": 0}

    async def dies_on_second_frame(self, rows):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConnectionResetError("database went away mid-replay")
        return await real_ticks(self, rows)

    monkeypatch.setattr(P._Writer, "ticks", dies_on_second_frame)
    with pytest.raises(ConnectionResetError):
        await replay_archive(db_session, arc, commit=True, token=TOKEN)
    failed = (await db_session.execute(text(
        "select status, rows_written, error from ingest_run where stream='preopen'"))).one()
    assert failed.status == "FAILED" and failed.rows_written == 0
    assert "went away" in failed.error
    for t in ("preopen_tick", "preopen_book", "preopen_session_status"):
        assert await _count(db_session, t) == 0, t

    monkeypatch.setattr(P._Writer, "ticks", real_ticks)
    rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
    assert rep.status == "COMPLETE" and rep.ticks_inserted == 3
    assert await _count(db_session, "preopen_tick") == 3


async def test_status_only_frames_before_the_session_are_kept(db_session, tmp_path):
    """market_info frames with no feeds (08:55, before pre-open) are valid
    evidence and must not trip the session-date check."""
    await _seed_session(db_session)
    mi = pb.MarketInfo()
    mi.segmentStatus["NSE_EQ"] = pb.NORMAL_CLOSE
    at = ist(8, 55)
    early = pb.FeedResponse(type=pb.market_info, currentTs=int(at.timestamp() * 1000),
                            marketInfo=mi).SerializeToString()
    arc = _write_archive(tmp_path / "s.frames.gz", [(at, early), *_session_frames()])
    rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
    assert rep.status == "COMPLETE" and rep.feed_types["market_info"] == 3


def test_capture_refuses_an_expired_token_before_opening_anything(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from app.cli import main as cli
    from app.vendor.upstox import auth

    class Rec:
        access_token, user_id = "expired", "X"

    monkeypatch.setattr(auth, "load_cached", lambda: Rec())
    monkeypatch.setattr(auth, "probe", lambda tok: (False, {"errors": [
        {"errorCode": "UDAPI100050"}]}))
    monkeypatch.setenv("PRAJNA_ARCHIVE_DIR", str(tmp_path))
    from app.core import config
    config.get_settings.cache_clear()
    keys = tmp_path / "k.txt"
    keys.write_text("NSE_EQ|INE002A01018\n")
    until = "23:59"
    try:
        res = CliRunner().invoke(cli.app, ["--plain", "ingest", "preopen-capture",
                                           "--keys-file", str(keys), "--until", until,
                                           "--session-date", _today_ist()])
    finally:
        config.get_settings.cache_clear()
    assert res.exit_code == 3, res.output
    assert not list(tmp_path.rglob("*.frames.gz"))


def _today_ist() -> str:
    from app.core.clock import now_ist
    return now_ist().date().isoformat()
