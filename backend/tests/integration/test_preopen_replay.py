"""Archive -> replay -> rows: deterministic, idempotent, fail-closed."""

from __future__ import annotations

import datetime as _dt
import gzip
import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.clock import now
from app.core.errors import AuthorizationError
from app.ingest.preopen import replay_archive
from app.parsers.upstox_feed_v3 import parse_frame
from app.storage.frame_archive import FrameArchiveReader, FrameArchiveWriter, RecordKind
from app.vendor.upstox.proto import PROTO_SHA256
from tests.support.upstox_frames import (
    NIFTYBEES,
    RELIANCE,
    SESSION,
    frame,
    ist,
    market_ff,
    status_frame,
)

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
LAG = _dt.timedelta(milliseconds=35)


def _write_archive(path, frames, *, header=None, close=True):
    w = FrameArchiveWriter(path, header or {
        "session_date": SESSION.isoformat(), "proto_sha256": PROTO_SHA256,
        "endpoint": "wss://test/v3/feed", "source": "UPSTOX_WS_V3",
    })
    w.append_event("connected", ist(8, 55))
    for at, data in frames:
        w.append_frame(data, at + LAG)
    if close:
        w.close()
    return path


def _session_frames():
    return [
        (ist(9, 0, 1), status_frame(ist(9, 0, 1), {"NSE_EQ": ("PRE_OPEN_START", ist(9, 0))})),
        (ist(9, 0, 2), frame({RELIANCE: market_ff(), NIFTYBEES: market_ff(iep=285.4)},
                             ist(9, 0, 2), kind=1)),
        (ist(9, 3, 0), frame({RELIANCE: market_ff(iep=2459.0, ieq=15000)}, ist(9, 3))),
        (ist(9, 7, 59), status_frame(ist(9, 7, 59),
                                     {"NSE_EQ": ("PRE_OPEN_M_END", ist(9, 7, 58))})),
    ]


async def _seed_session(s, day=SESSION):
    """trading_session is M2's; the test asserts one the way M2 will."""
    rid, sha = uuid.uuid4(), uuid.uuid4().hex * 2
    await s.execute(text("""
        insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
            code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
            started_at, rows_written)
        values (:r,'UPSTOX_REST_V2','calendar','test','{}','t',:c,ARRAY['pytest'],'pytest',
                'COMMIT','RUNNING',:a,:n,0)"""),
        {"r": rid, "c": "c" * 64, "a": "a" * 64, "n": now()})
    await s.execute(text("""
        insert into raw_payload (payload_sha256, source, vendor_endpoint, request_params,
            byte_size, content_type, storage_uri, first_seen_run, fetched_at)
        values (:s,'UPSTOX_REST_V2','test','{}',1,'application/json','/dev/null',:r,:n)"""),
        {"s": sha, "r": rid, "n": now()})
    await s.execute(text("""
        insert into trading_session (session_date, is_trading_day, session_type,
            preopen_start_ist, preopen_end_ist, open_ist, close_ist,
            source, run_id, payload_sha256, fetched_at, knowable_at, knowable_at_basis)
        values (:d, true, 'NORMAL', '09:00', '09:15', '09:15', '15:30',
                'UPSTOX_REST_V2', :r, :s, :n, :n, 'test')"""),
        {"d": day, "r": rid, "s": sha, "n": now()})


async def _count(s, table):
    return (await s.execute(text(f"select count(*) from {table}"))).scalar()


class TestReplay:
    async def test_commit_writes_rows_with_full_provenance(self, db_session, tmp_path):
        await _seed_session(db_session)
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())
        rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)

        assert rep.status == "COMPLETE", rep.anomalies
        assert (rep.frames, rep.events, rep.ticks_inserted) == (4, 1, 3)
        assert rep.book_rungs_inserted == 15 and rep.statuses_inserted == 2
        assert rep.request_modes == {"full_d5": 3}

        rows = (await db_session.execute(text("""
            select t.instrument_key, t.iep, t.frame_seq, t.knowable_at, t.fetched_at,
                   t.knowable_at_verified, p.storage_uri, r.status, r.rows_written
            from preopen_tick t join raw_payload p using (payload_sha256)
            join ingest_run r on r.run_id = t.run_id order by t.vendor_ts, t.instrument_key
        """))).all()
        assert [r.instrument_key for r in rows] == [RELIANCE, NIFTYBEES, RELIANCE]
        assert rows[2].iep == Decimal("2459.0000")
        assert all(r.knowable_at <= r.fetched_at and r.knowable_at_verified for r in rows)
        assert rows[0].storage_uri.endswith(f"#seq={rows[0].frame_seq}")
        assert rows[0].status == "COMPLETE" and rows[0].rows_written == rep.rows_written

        statuses = (await db_session.execute(text(
            "select status from preopen_session_status order by vendor_updated_at"))).scalars()
        assert list(statuses) == ["PRE_OPEN_START", "PRE_OPEN_M_END"]

    async def test_replay_twice_is_idempotent(self, db_session, tmp_path):
        await _seed_session(db_session)
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())
        first = await replay_archive(db_session, arc, commit=True, token=TOKEN)
        counts = [await _count(db_session, t) for t in
                  ("preopen_tick", "preopen_book", "preopen_session_status", "raw_payload")]

        second = await replay_archive(db_session, arc, commit=True, token=TOKEN)
        assert second.status == "COMPLETE" and second.rows_written == 0
        assert second.ticks_already_present == first.ticks_inserted
        assert [await _count(db_session, t) for t in
                ("preopen_tick", "preopen_book", "preopen_session_status", "raw_payload")] == counts

    async def test_database_rows_equal_parser_output(self, db_session, tmp_path):
        """live archive -> replay -> the same typed rows the parser produces."""
        await _seed_session(db_session)
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())
        await replay_archive(db_session, arc, commit=True, token=TOKEN)

        expected = [
            t for rec in FrameArchiveReader(arc) if rec.kind is RecordKind.BINARY
            for t in parse_frame(rec.payload, frame_seq=rec.seq, fetched_at=rec.recv_at,
                                 session_date=SESSION).ticks
        ]
        got = (await db_session.execute(text(
            "select instrument_key, vendor_ts, iep, ieq, tbq, request_mode, knowable_at "
            "from preopen_tick order by frame_seq, instrument_key"))).all()
        assert [(g.instrument_key, g.vendor_ts, g.iep, g.ieq, g.tbq, g.request_mode,
                 g.knowable_at) for g in got] == [
            (e.instrument_key, e.vendor_ts, e.iep, e.ieq, e.tbq, e.request_mode,
             e.provenance.knowable_at) for e in expected]

    async def test_dry_run_writes_only_the_ledger(self, db_session, tmp_path):
        await _seed_session(db_session)
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())
        before = await _count(db_session, "raw_payload")
        rep = await replay_archive(db_session, arc, commit=False, token=None)
        assert rep.status == "COMPLETE" and rep.ticks_parsed == 3 and rep.rows_written == 0
        assert await _count(db_session, "preopen_tick") == 0
        assert await _count(db_session, "raw_payload") == before
        mode = (await db_session.execute(text(
            "select mode from ingest_run where run_id=:r"), {"r": rep.run_id})).scalar()
        assert mode == "DRY_RUN"


class TestFailClosed:
    async def test_commit_requires_the_write_token(self, db_session, tmp_path):
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())
        with pytest.raises(AuthorizationError):
            await replay_archive(db_session, arc, commit=True, token=None)

    async def test_missing_trading_session_is_not_fabricated(self, db_session, tmp_path):
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())
        rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
        assert rep.status == "FAILED"
        assert any(a["subject"] == "trading_session" for a in rep.anomalies)
        assert await _count(db_session, "preopen_tick") == 0
        assert await _count(db_session, "trading_session") == 0

    async def test_conflicting_observation_fails_instead_of_keeping_the_first(
        self, db_session, tmp_path
    ):
        """Same (instrument, currentTs), different content: not a duplicate."""
        await _seed_session(db_session)
        at = ist(9, 5)
        a = _write_archive(tmp_path / "a.frames.gz", [(at, frame({RELIANCE: market_ff()}, at))])
        b = _write_archive(tmp_path / "b.frames.gz",
                           [(at, frame({RELIANCE: market_ff(iep=2470.0)}, at))])
        assert (await replay_archive(db_session, a, commit=True, token=TOKEN)).status == "COMPLETE"
        rep = await replay_archive(db_session, b, commit=True, token=TOKEN)
        assert rep.status == "FAILED"
        dup = [x for x in rep.anomalies if x["kind"] == "DUPLICATE_KEY"]
        assert dup and "iep" in dup[0]["detail"]["differing"]
        assert await _count(db_session, "preopen_tick") == 1

    async def test_undecodable_frame_fails_the_run_but_stays_archived(self, db_session, tmp_path):
        await _seed_session(db_session)
        arc = _write_archive(tmp_path / "s.frames.gz",
                             [*_session_frames(), (ist(9, 8), b"\xff\xff\xff")])
        rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
        assert rep.status == "FAILED" and rep.undecodable == 1
        assert await _count(db_session, "preopen_tick") == 0
        # The bad bytes are still there, verbatim, for a later decoder.
        assert [r.payload for r in FrameArchiveReader(arc)][-1] == b"\xff\xff\xff"
        run = (await db_session.execute(text(
            "select status, rows_written from ingest_run where run_id=:r"),
            {"r": rep.run_id})).one()
        assert run.status == "FAILED" and run.rows_written == 0

    async def test_crashed_capture_replays_what_it_has_and_says_so(self, db_session, tmp_path):
        await _seed_session(db_session)
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames(), close=False)
        rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
        assert rep.status == "COMPLETE" and rep.ticks_inserted == 3
        assert any(a["kind"] == "GAP" and "manifest" in a["detail"]["reason"]
                   for a in rep.anomalies)

    async def test_tampered_archive_is_rejected(self, db_session, tmp_path):
        await _seed_session(db_session)
        arc = _write_archive(tmp_path / "s.frames.gz", _session_frames())
        raw = bytearray(gzip.decompress(arc.read_bytes()))
        raw[-5] ^= 0x01
        arc.write_bytes(gzip.compress(bytes(raw)))
        rep = await replay_archive(db_session, arc, commit=True, token=TOKEN)
        assert rep.status == "FAILED" and await _count(db_session, "preopen_tick") == 0
