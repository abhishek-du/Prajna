"""Master -> archived payload -> universe rows, reproducible from its hash."""

from __future__ import annotations

import datetime as _dt
import hashlib
import os

import pytest
from sqlalchemy import text

from app.contracts.universe import keys_sha256, rules_sha256
from app.core.clock import UTC
from app.ingest.universe import load_archived_master, select_universe
from app.storage.payload_store import PayloadStore
from tests.support import upstox_master as M

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
DAY = _dt.date(2026, 9, 24)
FETCHED = _dt.datetime(2026, 9, 24, 2, 0, tzinfo=UTC)   # 07:30 IST
ELIGIBLE_KEYS = sorted(r["instrument_key"] for r in M.ELIGIBLE)


async def _select(s, tmp_path, data=None, *, day=DAY, cap=5, commit=True, fetched=FETCHED):
    return await select_universe(
        s, data if data is not None else M.master_bytes(M.ALL), fetched_at=fetched,
        session_date=day, cap=cap, commit=commit, token=TOKEN if commit else None,
        store=PayloadStore(tmp_path),
    )


async def _members(s, universe="preopen", day=DAY):
    return list((await s.execute(text(
        "select instrument_key from instrument_universe_membership "
        "where universe=:u and session_date=:d order by rank"), {"u": universe, "d": day}
    )).scalars())


class TestSelectAndPersist:
    async def test_members_and_cap_exclusions_are_recorded_by_name(self, db_session, tmp_path):
        rep = await _select(db_session, tmp_path)
        assert rep.status == "COMPLETE", rep.anomalies
        assert await _members(db_session) == ELIGIBLE_KEYS
        assert await _members(db_session, "preopen.cap_excluded") == ELIGIBLE_KEYS[5:]
        assert rep.subscribed_keys == ELIGIBLE_KEYS[:5] and rep.cap_excluded == ELIGIBLE_KEYS[5:]
        assert rep.members == 8 and rep.rows_written == 8 + 3

        cap = (await db_session.execute(text(
            "select detail from ingest_anomaly where run_id=:r and kind='COVERAGE_CAP'"),
            {"r": rep.run_id})).scalar()
        assert cap["dropped_keys"] == ELIGIBLE_KEYS[5:] and "UNVERIFIED" in cap["basis"]

    async def test_every_exclusion_is_counted_under_a_rule(self, db_session, tmp_path):
        rep = await _select(db_session, tmp_path)
        assert sum(rep.counts.values()) == len(M.ALL)
        assert rep.counts["excluded:segment=NSE_FO"] == 1
        assert rep.counts["excluded:series=SG"] == 1

    async def test_provenance_ties_every_row_to_the_master_bytes(self, db_session, tmp_path):
        data = M.master_bytes(M.ALL)
        rep = await _select(db_session, tmp_path, data)
        assert rep.master_sha256 == hashlib.sha256(data).hexdigest()
        rows = (await db_session.execute(text("""
            select distinct m.payload_sha256, m.knowable_at, m.fetched_at, m.knowable_at_verified,
                   p.byte_size, p.source, r.request_params->>'rules_sha256' as rules
            from instrument_universe_membership m
            join raw_payload p using (payload_sha256) join ingest_run r on r.run_id = m.run_id
        """))).all()
        (row,) = rows
        assert row.payload_sha256 == rep.master_sha256 and row.byte_size == len(data)
        assert row.source == "UPSTOX_ASSETS" and row.rules == rules_sha256()
        assert row.knowable_at == row.fetched_at == FETCHED and row.knowable_at_verified is False

    async def test_reselecting_from_the_archived_payload_is_identical(self, db_session, tmp_path):
        first = await _select(db_session, tmp_path)
        data, fetched, _ = await load_archived_master(db_session, first.master_sha256)
        assert hashlib.sha256(data).hexdigest() == first.master_sha256 and fetched == FETCHED
        again = await _select(db_session, tmp_path, data, day=DAY + _dt.timedelta(days=1),
                              fetched=fetched)
        assert again.status == "COMPLETE"
        assert (again.members_sha256, again.subscribed_sha256, again.cap_excluded) == (
            first.members_sha256, first.subscribed_sha256, first.cap_excluded)
        assert again.members_sha256 == keys_sha256(ELIGIBLE_KEYS)


class TestIdempotence:
    async def test_repeated_run_is_a_no_op(self, db_session, tmp_path):
        first = await _select(db_session, tmp_path)
        second = await _select(db_session, tmp_path)
        assert second.status == "COMPLETE" and second.already_recorded
        assert second.rows_written == 0 and second.members_sha256 == first.members_sha256
        n = (await db_session.execute(text(
            "select count(*) from instrument_universe_membership"))).scalar()
        assert n == first.rows_written

    async def test_input_row_order_does_not_change_the_selection(self, db_session, tmp_path):
        a = await _select(db_session, tmp_path, M.master_bytes(M.ALL))
        b = await _select(db_session, tmp_path, M.master_bytes(M.ALL[::-1]),
                          day=DAY + _dt.timedelta(days=1))
        assert a.master_sha256 != b.master_sha256          # different files...
        assert a.members_sha256 == b.members_sha256        # ...same universe

    async def test_a_different_universe_for_the_same_session_fails(self, db_session, tmp_path):
        await _select(db_session, tmp_path)
        smaller = [r for r in M.ALL if r is not M.NIFTYBEES]
        rep = await _select(db_session, tmp_path, M.master_bytes(smaller))
        assert rep.status == "FAILED"
        dup = next(a for a in rep.anomalies if a["kind"] == "DUPLICATE_KEY")
        assert dup["detail"]["lost"] == [M.NIFTYBEES["instrument_key"]]
        assert await _members(db_session) == ELIGIBLE_KEYS


class TestFailClosed:
    async def test_dry_run_archives_but_writes_no_rows(self, db_session, tmp_path):
        rep = await _select(db_session, tmp_path, commit=False)
        assert rep.status == "COMPLETE" and rep.rows_written == 0
        assert await _members(db_session) == []
        n = (await db_session.execute(text("select count(*) from raw_payload"))).scalar()
        assert n == 0
        # archive-first holds on a dry run too
        assert PayloadStore.read(rep.archive_path, rep.master_sha256)

    async def test_undecodable_master_fails_but_stays_archived(self, db_session, tmp_path):
        rep = await _select(db_session, tmp_path, b"<html>maintenance</html>")
        assert rep.status == "FAILED" and await _members(db_session) == []
        assert PayloadStore.read(rep.archive_path, rep.master_sha256) == \
            b"<html>maintenance</html>"

    async def test_universe_collapse_against_the_last_session_fails(self, db_session, tmp_path):
        await _select(db_session, tmp_path, cap=None)
        tiny = [M.RELIANCE, *M.INELIGIBLE]
        rep = await _select(db_session, tmp_path, M.master_bytes(tiny),
                            day=DAY + _dt.timedelta(days=1), cap=None)
        assert rep.status == "FAILED"
        assert any(a["kind"] == "COVERAGE_DROP" for a in rep.anomalies)

    async def test_malformed_master_rows_surface_as_anomalies(self, db_session, tmp_path):
        rep = await _select(db_session, tmp_path, M.master_bytes([*M.ALL, {"segment": "NSE_EQ"}]))
        assert rep.status == "COMPLETE" and rep.rejected_rows == {"excluded:malformed_row": 1}
        kinds = (await db_session.execute(text(
            "select subject from ingest_anomaly where run_id=:r and kind='PARSE_REJECT'"),
            {"r": rep.run_id})).scalars().all()
        assert kinds == ["excluded:malformed_row"]

    async def test_commit_requires_the_token(self, db_session, tmp_path):
        from app.core.errors import AuthorizationError
        with pytest.raises(AuthorizationError):
            await select_universe(db_session, M.master_bytes(M.ALL), fetched_at=FETCHED,
                                  session_date=DAY, cap=5, commit=True, token=None,
                                  store=PayloadStore(tmp_path))
