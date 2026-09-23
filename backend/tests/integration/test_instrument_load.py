"""M3.0 current-instrument load, on the REAL 2026-09-23 Upstox master."""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import json
import os
import pathlib

import pytest
from sqlalchemy import text

from app.acceptance.instruments import evaluate
from app.contracts.universe import select_preopen
from app.core.clock import UTC
from app.ingest import instruments as I
from app.ingest.instruments import (
    REQUIRED_INDEX_KEYS,
    load_current_instruments,
    plan_instruments,
    selection_sha256,
)
from app.parsers.upstox_instrument_master import parse_master
from app.storage.payload_store import PayloadStore

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FIXTURE = (pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_master"
           / "NSE_2026-09-23.json.gz")
REAL = FIXTURE.read_bytes()
REAL_SHA = "bf4a5db89c9e4129e5a281d9397e1f2d979ef8681e322e8479693fe20ba12331"
HELD_AT = _dt.datetime(2026, 9, 23, 7, 51, 19, 960000, tzinfo=UTC)
RELIANCE, NIFTYBEES = "NSE_EQ|INE002A01018", "NSE_EQ|INF204KB14I2"


def _archive(root: pathlib.Path, data: bytes) -> str:
    """Archive like the real run did, and pin the file time (the fetched_at bound)."""
    sp = PayloadStore(root).put(data, source="UPSTOX_ASSETS", fetched_at=HELD_AT,
                                content_type="application/gzip", ext="json.gz")
    os.utime(sp.path, (HELD_AT.timestamp(), HELD_AT.timestamp()))
    return sp.sha256


def _variant(mutate) -> bytes:
    rows = json.loads(gzip.decompress(REAL))
    mutate(rows)
    return gzip.compress(json.dumps(rows).encode(), mtime=0)


async def _load(s, root, sha, commit=True):
    return await load_current_instruments(s, master_sha256=sha, archive_root=root,
                                          commit=commit, token=TOKEN if commit else None)


async def _n(s):
    return (await s.execute(text("select count(*) from instrument"))).scalar()


def test_fixture_is_the_real_archived_master():
    assert hashlib.sha256(REAL).hexdigest() == REAL_SHA


def test_plan_matches_the_m1_selection_exactly():
    plan = plan_instruments(REAL, REAL_SHA)
    m1 = select_preopen(parse_master(REAL).instruments)
    assert len(plan.equity_keys) == 3525 and plan.equity_keys == m1.members
    assert plan.index_keys == REQUIRED_INDEX_KEYS
    assert len(plan.rows) == 3528 and plan.issues.anomalies == []


def test_plan_is_deterministic_and_order_independent():
    a = plan_instruments(REAL, REAL_SHA)
    b = plan_instruments(REAL, REAL_SHA)
    c = plan_instruments(_variant(lambda rows: rows.reverse()), "x")
    assert a.rows_sha256 == b.rows_sha256 == c.rows_sha256


class TestLoad:
    async def test_initial_load(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        assert await _n(db_session) == 0
        rep = await _load(db_session, tmp_path, sha)
        assert rep.status == "COMPLETE", rep.anomalies
        assert (rep.equity, rep.indices, rep.inserted) == (3525, 3, 3528)
        assert rep.anomalies == [] and await _n(db_session) == 3528

        r = (await db_session.execute(text(
            "select * from instrument where instrument_key=:k"), {"k": NIFTYBEES})).one()
        assert (r.isin, r.instrument_type, r.segment, r.trading_symbol) == (
            "INF204KB14I2", "EQ", "NSE_EQ", "NIFTYBEES")
        assert str(r.valid_from) == "2026-09-23" and str(r.valid_to) == "9999-12-31"
        v = (await db_session.execute(text(
            "select isin, segment, instrument_type, lot_size from instrument "
            "where instrument_key='NSE_INDEX|Nifty 50'"))).one()
        assert v == (None, "NSE_INDEX", "INDEX", None)

    async def test_provenance_and_master_sha_are_preserved(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        rep = await _load(db_session, tmp_path, sha)
        p = (await db_session.execute(text("""
            select count(*) n, count(distinct payload_sha256) payloads, min(payload_sha256) sha,
                   count(*) filter (where knowable_at > fetched_at) bad,
                   count(*) filter (where knowable_at_verified) verified,
                   min(fetched_at) f0, max(fetched_at) f1, count(distinct run_id) runs
            from instrument"""))).one()
        assert (p.n, p.payloads, p.sha, p.bad, p.verified, p.runs) == (3528, 1, REAL_SHA,
                                                                      0, 0, 1)
        assert p.f0 == p.f1 == HELD_AT
        rp = (await db_session.execute(text(
            "select byte_size, storage_uri, source from raw_payload where payload_sha256=:s"),
            {"s": REAL_SHA})).one()
        assert rp.byte_size == len(REAL) and rp.source == "UPSTOX_ASSETS"
        assert PayloadStore.read(rp.storage_uri, REAL_SHA) == REAL
        run = (await db_session.execute(text(
            "select request_params from ingest_run where run_id=:r"), {"r": rep.run_id})).one()
        assert run.request_params["selection_sha256"] == selection_sha256()
        assert "CURRENT" in run.request_params["scope"]

    async def test_second_run_is_a_no_op(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        first = await _load(db_session, tmp_path, sha)
        second = await _load(db_session, tmp_path, sha)
        assert second.status == "COMPLETE" and second.inserted == 0
        assert second.already_current == 3528 and await _n(db_session) == 3528
        assert second.planned_rows_sha256 == first.planned_rows_sha256
        assert second.fetched_at_basis == "raw_payload.fetched_at"
        assert second.fetched_at == first.fetched_at

    async def test_dry_run_writes_no_instruments(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        rep = await _load(db_session, tmp_path, sha, commit=False)
        assert rep.status == "COMPLETE" and rep.would_insert == 3528 and rep.inserted == 0
        assert await _n(db_session) == 0


class TestFailClosed:
    async def test_identical_duplicate_row_is_a_warned_no_op(self, db_session, tmp_path):
        def dup(rows):
            rows.append(next(r for r in rows if r["instrument_key"] == RELIANCE))
        sha = _archive(tmp_path, _variant(dup))
        rep = await _load(db_session, tmp_path, sha)
        assert rep.status == "COMPLETE" and rep.inserted == 3528
        assert [a["kind"] for a in rep.anomalies] == ["DUPLICATE_KEY"]
        assert rep.anomalies[0]["severity"] == "WARN"

    async def test_conflicting_duplicate_row_fails(self, db_session, tmp_path):
        def dup(rows):
            r = dict(next(r for r in rows if r["instrument_key"] == RELIANCE))
            r["lot_size"] = 5
            rows.append(r)
        rep = await _load(db_session, tmp_path, _archive(tmp_path, _variant(dup)))
        assert rep.status == "FAILED" and await _n(db_session) == 0
        assert any(a["kind"] == "DUPLICATE_KEY" and a["severity"] == "FAIL"
                   for a in rep.anomalies)

    async def test_changed_attribute_on_existing_instrument_fails(self, db_session, tmp_path):
        await _load(db_session, tmp_path, _archive(tmp_path, REAL))

        def retick(rows):
            next(r for r in rows if r["instrument_key"] == RELIANCE)["tick_size"] = 0.1
        rep = await _load(db_session, tmp_path, _archive(tmp_path, _variant(retick)))
        assert rep.status == "FAILED"
        dup = next(a for a in rep.anomalies if a["kind"] == "DUPLICATE_KEY")
        assert dup["subject"] == RELIANCE and "tick_size" in dup["detail"]["differing"]
        t = (await db_session.execute(text(
            "select tick_size from instrument where instrument_key=:k"), {"k": RELIANCE})).one()
        assert str(t.tick_size) != "0.1000"          # never overwritten
        assert await _n(db_session) == 3528

    async def test_malformed_master_fails_and_writes_nothing(self, db_session, tmp_path):
        rep = await _load(db_session, tmp_path, _archive(tmp_path, b"<html>maintenance</html>"))
        assert rep.status == "FAILED" and await _n(db_session) == 0

    async def test_wrong_typed_field_is_schema_drift(self, db_session, tmp_path):
        def drift(rows):
            next(r for r in rows if r["instrument_key"] == NIFTYBEES)["lot_size"] = "1"
        rep = await _load(db_session, tmp_path, _archive(tmp_path, _variant(drift)))
        assert rep.status == "FAILED" and await _n(db_session) == 0
        assert any(a["kind"] == "SCHEMA_DRIFT" and a["subject"] == "field:lot_size"
                   for a in rep.anomalies)

    async def test_key_segment_mismatch_is_excluded_by_name(self, db_session, tmp_path):
        def mismatch(rows):
            next(r for r in rows if r["instrument_key"] == NIFTYBEES)["segment"] = "NSE_FO"
        rep = await _load(db_session, tmp_path, _archive(tmp_path, _variant(mismatch)))
        assert rep.status == "COMPLETE" and rep.equity == 3524
        assert any(a["subject"] == "excluded:key_segment_mismatch" for a in rep.anomalies)

    async def test_missing_required_index_fails(self, db_session, tmp_path):
        def drop(rows):
            rows[:] = [r for r in rows if r.get("instrument_key") != "NSE_INDEX|India VIX"]
        rep = await _load(db_session, tmp_path, _archive(tmp_path, _variant(drop)))
        assert rep.status == "FAILED" and await _n(db_session) == 0

    async def test_tampered_archive_is_refused_before_parsing(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        path = I.locate_archived(tmp_path, sha)
        path.write_bytes(gzip.compress(_variant(lambda rows: rows.pop())))
        rep = await _load(db_session, tmp_path, sha)
        assert rep.status == "FAILED" and "corrupt" in rep.error
        assert rep.rows_in_master == 0 and await _n(db_session) == 0

    async def test_failure_mid_insert_rolls_everything_back(self, db_session, tmp_path,
                                                           monkeypatch):
        sha = _archive(tmp_path, REAL)
        real, calls = I.pg_insert, {"n": 0}

        def flaky(model):
            calls["n"] += 1
            if calls["n"] == 3:
                raise ConnectionResetError("database went away mid-load")
            return real(model)
        monkeypatch.setattr(I, "pg_insert", flaky)
        with pytest.raises(ConnectionResetError):
            await _load(db_session, tmp_path, sha)
        assert await _n(db_session) == 0
        run = (await db_session.execute(text(
            "select status, rows_written from ingest_run where stream='instrument.current'"))).one()
        assert run.status == "FAILED" and run.rows_written == 0

    async def test_current_row_not_in_selection_is_kept_and_warned(self, db_session, tmp_path):
        await _load(db_session, tmp_path, _archive(tmp_path, REAL))

        def drop(rows):
            rows[:] = [r for r in rows if r.get("instrument_key") != RELIANCE]
        rep = await _load(db_session, tmp_path, _archive(tmp_path, _variant(drop)))
        assert rep.status == "COMPLETE" and rep.current_not_selected == 1
        assert await _n(db_session) == 3528


class TestAcceptance:
    async def test_full_chain_passes_after_load(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        await _load(db_session, tmp_path, sha)
        doc = await evaluate(db_session, master_sha256=sha, archive_root=tmp_path)
        assert doc["verdict"] == "PASS", doc
        assert [c["id"] for c in doc["checks"]] == ["I1", "I2", "I3", "I4", "I5", "I6", "I7"]

    async def test_fails_if_the_source_hash_changes(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        await _load(db_session, tmp_path, sha)
        I.locate_archived(tmp_path, sha).write_bytes(gzip.compress(b"[]"))
        doc = await evaluate(db_session, master_sha256=sha, archive_root=tmp_path)
        assert doc["verdict"] == "FAIL" and doc["checks"][0]["status"] == "FAIL"

    async def test_fails_if_an_instrument_changed_silently(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        await _load(db_session, tmp_path, sha)
        await db_session.execute(text(
            "update instrument set lot_size = 7 where instrument_key = :k"), {"k": RELIANCE})
        doc = await evaluate(db_session, master_sha256=sha, archive_root=tmp_path)
        by = {c["id"]: c["status"] for c in doc["checks"]}
        assert doc["verdict"] == "FAIL" and by["I5"] == "FAIL" and by["I7"] == "FAIL"

    async def test_fails_if_the_selection_rules_change(self, db_session, tmp_path, monkeypatch):
        sha = _archive(tmp_path, REAL)
        await _load(db_session, tmp_path, sha)
        from app.contracts import universe as U
        monkeypatch.setattr(U, "TRADEABLE_EQUITY_SERIES", frozenset({"EQ"}))
        doc = await evaluate(db_session, master_sha256=sha, archive_root=tmp_path,
                             replay=False)
        assert {c["id"]: c["status"] for c in doc["checks"]}["I3"] == "FAIL"

    async def test_fails_if_provenance_is_missing(self, db_session, tmp_path):
        sha = _archive(tmp_path, REAL)
        await _load(db_session, tmp_path, sha)
        await db_session.execute(text(
            "update instrument set knowable_at_basis = '' where instrument_key = :k"),
            {"k": RELIANCE})
        doc = await evaluate(db_session, master_sha256=sha, archive_root=tmp_path,
                             replay=False)
        assert {c["id"]: c["status"] for c in doc["checks"]}["I4"] == "FAIL"
