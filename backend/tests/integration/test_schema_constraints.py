"""The invariants are enforced by the DATABASE, not merely by application code.

Each test here corresponds to a measured V1 failure. If the constraint is
dropped in a future migration, the test fails.
"""

from __future__ import annotations

import datetime as _dt
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.clock import UTC, now

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def _mk_run(s, *, mode="COMMIT", authz="a" * 64, status="RUNNING"):
    rid = uuid.uuid4()
    await s.execute(text("""
        insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
            code_git_sha, config_sha256, argv, operator, mode, status,
            authz_token_sha256, started_at, rows_written)
        values (:r,'UPSTOX_WS_V3','t','wss://x','{}','deadbeef',:c,
                ARRAY['pytest'],'test',:m,:st,:a, :now, 0)
    """), {"r": rid, "c": "c" * 64, "m": mode, "st": status, "a": authz, "now": now()})
    return rid


async def _mk_payload(s, rid, sha=None):
    sha = sha or uuid.uuid4().hex + uuid.uuid4().hex[:32]
    await s.execute(text("""
        insert into raw_payload (payload_sha256, source, vendor_endpoint, request_params,
            byte_size, content_type, storage_uri, first_seen_run, fetched_at)
        values (:s,'UPSTOX_WS_V3','wss://x','{}',1,'application/x-protobuf','/tmp/x',:r,:now)
    """), {"s": sha, "r": rid, "now": now()})
    return sha


class TestRunLedgerIntegrity:
    async def test_commit_run_requires_authorization(self, db_session):
        """V1's gate gave 269,642 unauthorized rows; here it is a CHECK."""
        with pytest.raises(IntegrityError, match="ck_run_commit_requires_authz"):
            await _mk_run(db_session, mode="COMMIT", authz=None)

    async def test_complete_run_must_have_finished_at(self, db_session):
        """V1's run c4332067 sat RUNNING for six days. Unrepresentable here."""
        rid = await _mk_run(db_session)
        with pytest.raises(IntegrityError, match="ck_run_complete_has_finish"):
            await db_session.execute(
                text("update ingest_run set status='COMPLETE' where run_id=:r"), {"r": rid}
            )

    async def test_dry_run_cannot_claim_rows(self, db_session):
        rid = await _mk_run(db_session, mode="DRY_RUN", authz=None)
        with pytest.raises(IntegrityError, match="ck_run_dryrun_writes_nothing"):
            await db_session.execute(
                text("update ingest_run set rows_written=5 where run_id=:r"), {"r": rid}
            )

    async def test_invalid_status_rejected(self, db_session):
        with pytest.raises(IntegrityError, match="ck_run_status"):
            await _mk_run(db_session, status="WEIRD")


class TestProvenanceEnforcement:
    async def test_knowable_at_cannot_postdate_fetched_at(self, db_session):
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        t = now()
        with pytest.raises(IntegrityError, match="ck_trading_session_knowable"):
            await db_session.execute(text("""
                insert into trading_session (session_date, is_trading_day, session_type,
                    open_ist, close_ist, source, run_id, payload_sha256,
                    fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
                values ('2026-09-22', true, 'NORMAL', '09:15', '15:30',
                        'UPSTOX_REST_V2', :r, :s, :f, :k, false, 'test')
            """), {"r": rid, "s": sha, "f": t, "k": t + _dt.timedelta(hours=1)})

    async def test_row_without_run_id_rejected(self, db_session):
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        with pytest.raises(IntegrityError):
            await db_session.execute(text("""
                insert into trading_session (session_date, is_trading_day, session_type,
                    open_ist, close_ist, source, run_id, payload_sha256,
                    fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
                values ('2026-09-23', true, 'NORMAL','09:15','15:30','UPSTOX_REST_V2',
                        NULL, :s, :n, :n, false, 'test')
            """), {"s": sha, "n": now()})


class TestInstrumentSCD2:
    async def _insert(self, s, rid, sha, key, vf, vt):
        _d = lambda x: _dt.date.fromisoformat(x)
        await s.execute(text("""
            insert into instrument (instrument_key, segment, exchange, trading_symbol,
                valid_from, valid_to, source, run_id, payload_sha256,
                fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values (:k,'NSE_EQ','NSE','RELIANCE',:vf,:vt,'UPSTOX_ASSETS',:r,:s,
                    :n,:n,false,'test')
        """), {"k": key, "vf": _d(vf), "vt": _d(vt), "r": rid, "s": sha, "n": now()})

    async def test_overlapping_validity_is_impossible(self, db_session):
        """V1 overwrote its instrument master daily, so a rename silently
        rewrote the meaning of every historical reference."""
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        k = "NSE_EQ|INE002A01018"
        await self._insert(db_session, rid, sha, k, "2026-01-01", "2026-06-01")
        with pytest.raises(IntegrityError, match="ex_instrument_no_overlap"):
            await self._insert(db_session, rid, sha, k, "2026-05-01", "2026-12-01")

    async def test_adjacent_ranges_are_allowed(self, db_session):
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        k = "NSE_EQ|INE002A01018"
        await self._insert(db_session, rid, sha, k, "2026-01-01", "2026-06-01")
        await self._insert(db_session, rid, sha, k, "2026-06-01", "2026-12-01")

    async def test_two_instruments_may_share_an_isin(self, db_session):
        """CRESTO/SILLYMONKS and KDGREEN/MANBRO are real collisions in V1."""
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        for key in ("NSE_EQ|INE203Y01012", "NSE_EQ|INE203Y01012_B"):
            await self._insert(db_session, rid, sha, key, "2026-01-01", "2026-12-01")


class TestOhlcvSourceCollision:
    async def test_two_sources_observe_the_same_bar_without_overwriting(self, db_session):
        """THE fix for V1's 14 daily anchors: source is in the primary key, so
        two observations coexist instead of one silently winning."""
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        await db_session.execute(text("""
            insert into instrument (instrument_id, instrument_key, segment, exchange,
                trading_symbol, valid_from, valid_to, source, run_id, payload_sha256,
                fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values (9001,'NSE_EQ|INE002A01018','NSE_EQ','NSE','RELIANCE',
                    '2026-01-01','infinity','UPSTOX_ASSETS',:r,:s,:n,:n,false,'t')
        """), {"r": rid, "s": sha, "n": now()})

        async def bar(src, close):
            await db_session.execute(text("""
                insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc,
                    source, instrument_key, open, high, low, close, volume, vendor_ts_raw,
                    run_id, payload_sha256, fetched_at, knowable_at,
                    knowable_at_verified, knowable_at_basis)
                values (9001,'1d','2026-09-01','2026-09-01T03:45:00+00',:src,
                        'NSE_EQ|INE002A01018',100,110,90,:c,1000,'raw',:r,:s,:n,:n,false,'t')
            """), {"src": src, "c": close, "r": rid, "s": sha, "n": now()})

        await bar("UPSTOX_REST_V3", 105)
        await bar("UPSTOX_WS_V3", 107)          # disagrees — and that is RECORDED
        n = (await db_session.execute(text(
            "select count(*) from ohlcv_bar where instrument_id=9001"))).scalar()
        assert n == 2

    async def test_impossible_ohlc_rejected(self, db_session):
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        await db_session.execute(text("""
            insert into instrument (instrument_id, instrument_key, segment, exchange,
                trading_symbol, valid_from, valid_to, source, run_id, payload_sha256,
                fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values (9002,'NSE_EQ|INE999A01018','NSE_EQ','NSE','X',
                    '2026-01-01','infinity','UPSTOX_ASSETS',:r,:s,:n,:n,false,'t')
        """), {"r": rid, "s": sha, "n": now()})
        with pytest.raises(IntegrityError, match="ck_ohlcv_sane"):
            await db_session.execute(text("""
                insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc,
                    source, instrument_key, open, high, low, close, volume, vendor_ts_raw,
                    run_id, payload_sha256, fetched_at, knowable_at,
                    knowable_at_verified, knowable_at_basis)
                values (9002,'1d','2026-09-01','2026-09-01T03:45:00+00','UPSTOX_REST_V3',
                        'NSE_EQ|INE999A01018',100,80,90,105,1000,'raw',:r,:s,:n,:n,false,'t')
            """), {"r": rid, "s": sha, "n": now()})


class TestPreopenMultipleCaptures:
    async def test_two_frames_at_different_vendor_ts_both_persist(self, db_session):
        """The whole point of frame-level capture: the EVOLUTION of IEP and
        imbalance through 09:00-09:15 is the signal, not the end state."""
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        await db_session.execute(text("""
            insert into trading_session (session_date, is_trading_day, session_type,
                preopen_start_ist, preopen_end_ist, open_ist, close_ist,
                source, run_id, payload_sha256, fetched_at, knowable_at,
                knowable_at_verified, knowable_at_basis)
            values ('2026-09-22', true,'NORMAL','09:00','09:15','09:15','15:30',
                    'UPSTOX_REST_V2',:r,:s,:n,:n,false,'t')
        """), {"r": rid, "s": sha, "n": now()})

        async def tick(vts, iep, seq):
            await db_session.execute(text("""
                insert into preopen_tick (session_date, instrument_key, frame_seq, vendor_ts,
                    feed_type, request_mode, iep, ieq, iiq_total, tbq, tsq,
                    source, run_id, payload_sha256, fetched_at, knowable_at,
                    knowable_at_verified, knowable_at_basis)
                values ('2026-09-22','NSE_EQ|INE002A01018',:q,:v,'live_feed','full_d5',
                        :iep, 49205, 51020, 162508, 213528,'UPSTOX_WS_V3',:r,:s,
                        :f,:v,true,'upstox_ws_v3.currentTs')
            """), {"q": seq, "v": vts, "iep": iep, "r": rid, "s": sha,
                   "f": vts + _dt.timedelta(seconds=1)})

        t1 = _dt.datetime(2026, 9, 22, 3, 35, tzinfo=UTC)
        t2 = _dt.datetime(2026, 9, 22, 3, 39, 40, tzinfo=UTC)
        await tick(t1, 1240.0, 1)
        await tick(t2, 1247.6, 2)
        rows = (await db_session.execute(text(
            "select iep from preopen_tick where instrument_key='NSE_EQ|INE002A01018' "
            "order by vendor_ts"))).scalars().all()
        assert [float(x) for x in rows] == [1240.0, 1247.6]

    async def test_same_frame_twice_is_rejected(self, db_session):
        """Archive replay must be idempotent."""
        rid = await _mk_run(db_session)
        sha = await _mk_payload(db_session, rid)
        await db_session.execute(text("""
            insert into trading_session (session_date, is_trading_day, session_type,
                open_ist, close_ist, source, run_id, payload_sha256, fetched_at,
                knowable_at, knowable_at_verified, knowable_at_basis)
            values ('2026-09-22', true,'NORMAL','09:15','15:30','UPSTOX_REST_V2',
                    :r,:s,:n,:n,false,'t')
        """), {"r": rid, "s": sha, "n": now()})
        vts = _dt.datetime(2026, 9, 22, 3, 39, 40, tzinfo=UTC)
        stmt = text("""
            insert into preopen_tick (session_date, instrument_key, frame_seq, vendor_ts,
                feed_type, request_mode, iep, source, run_id, payload_sha256,
                fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values ('2026-09-22','NSE_EQ|INE002A01018',1,:v,'live_feed','full_d5',
                    1247.6,'UPSTOX_WS_V3',:r,:s,:f,:v,true,'t')
        """)
        p = {"v": vts, "r": rid, "s": sha, "f": vts + _dt.timedelta(seconds=1)}
        await db_session.execute(stmt, p)
        with pytest.raises(IntegrityError, match="uq_preopen_tick_observation"):
            await db_session.execute(stmt, p)
