"""Daily instrument-master refresh on a real (test) database (phase 2).

Synthetic masters prove each lifecycle rule; the real 2026-09-23 and
2026-09-25 masters (fixtures, byte-identical to the archived payloads) replay
the incident: RCDL-RE removed, 4 new listings, CHAVDA's lot size versioned."""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import os
import pathlib
import uuid

import pytest
from sqlalchemy import text

from app.core.clock import IST
from app.ingest.instrument_refresh import refresh_instruments
from app.storage.payload_store import PayloadStore

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_master"
T0 = _dt.datetime(2026, 9, 23, 13, 0, tzinfo=IST)
INDICES = [{"segment": "NSE_INDEX", "name": n, "exchange": "NSE", "instrument_type": "INDEX",
            "instrument_key": f"NSE_INDEX|{n}", "exchange_token": str(i),
            "trading_symbol": n.upper().replace(" ", "")}
           for i, n in enumerate(("Nifty 50", "Nifty Bank", "India VIX"))]


def _isin(i: int) -> str:
    """A syntactically valid Indian ISIN (Luhn check digit) for equity i."""
    body = f"INE{i:04d}A010"
    digits = "".join(str(int(c, 36)) for c in body)
    total = 0
    for n, ch in enumerate(reversed(digits)):
        d = int(ch)
        if n % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return body + str((10 - total % 10) % 10)


def _eq(i: int, **kw) -> dict:
    row = {"segment": "NSE_EQ", "name": f"CO {i}", "exchange": "NSE", "isin": _isin(i),
           "instrument_type": "EQ", "instrument_key": f"NSE_EQ|{_isin(i)}", "lot_size": 1,
           "freeze_quantity": 100000.0, "exchange_token": str(1000 + i), "tick_size": 5.0,
           "trading_symbol": f"S{i}", "qty_multiplier": 1.0, "security_type": "NORMAL"}
    row.update(kw)
    return row


def _master(rows) -> bytes:
    return gzip.compress(json.dumps([*INDICES, *rows]).encode())


async def _refresh(s, data, at, tmp_path, commit=True):
    return await refresh_instruments(s, data, fetched_at=at, commit=commit, token=TOKEN,
                                     store=PayloadStore(tmp_path))


async def _state(s):
    return {r.instrument_key: r for r in (await s.execute(text(
        "select * from instrument where segment <> 'GLOBAL_INDEX'"))).all()}


async def _periods(s, key):
    return [(r.status, r.valid_to.year > 9000) for r in (await s.execute(text("""
        select p.status, p.valid_to from instrument_lifecycle_period p join instrument i
        using (instrument_id) where i.instrument_key = :k order by p.valid_from"""),
        {"k": key})).all()]


class TestSyntheticLifecycle:
    async def test_full_lifecycle(self, db_session, tmp_path):
        s = db_session
        base = [_eq(i) for i in range(1, 41)]
        r1 = await _refresh(s, _master(base), T0, tmp_path)
        assert r1.status == "COMPLETE" and len(r1.new_keys) == 43
        st = await _state(s)
        assert all(r.lifecycle_status == "ACTIVE" for r in st.values())
        ids = {k: r.instrument_id for k, r in st.items()}
        k1, k2, k3 = (f"NSE_EQ|{_isin(i)}" for i in (1, 2, 3))

        # a stored bar of instrument 1, to prove nothing about it is deleted
        await s.execute(text("""
            insert into ohlcv_bar (instrument_id, timeframe, session_date, bar_start_utc,
              source, instrument_key, open, high, low, close, volume, vendor_ts_raw, run_id,
              payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            select :i, '1d', '2026-09-22', '2026-09-21 18:30+00', 'UPSTOX_REST_V3', :k,
                   10, 11, 9, 10, 100, 'x', run_id, payload_sha256, fetched_at, fetched_at,
                   false, 't' from instrument where instrument_id = :i"""),
            {"i": ids[k1], "k": k1})

        # day 2: 1 removed, 2 moved to an ineligible series, 3 lot size, 41 new
        day2 = [r for r in base if r["instrument_key"] != k1]
        day2 = [_eq(2, instrument_type="N1") if r["instrument_key"] == k2
                else _eq(3, lot_size=2000) if r["instrument_key"] == k3 else r for r in day2]
        day2.append(_eq(41))
        r2 = await _refresh(s, _master(day2), T0 + _dt.timedelta(days=2), tmp_path)
        assert r2.status == "COMPLETE", r2.error
        assert r2.new_keys == [f"NSE_EQ|{_isin(41)}"]
        assert r2.transitions == {"REMOVED_FROM_MASTER": [k1], "INELIGIBLE": [k2]}
        assert set(r2.changed_keys) == {k2, k3}
        st = await _state(s)
        assert len(st) == 44                                   # nothing deleted
        assert st[k1].lifecycle_status == "REMOVED_FROM_MASTER"
        assert st[k1].valid_to.year == 9999                    # identity never closed (infinity)
        assert st[k3].instrument_id == ids[k3] and st[k3].lot_size == 2000
        versions = (await s.execute(text("""select lot_size, valid_to::text from
            instrument_attribute_version where instrument_id = :i order by valid_from"""),
            {"i": ids[k3]})).all()
        assert [v[0] for v in versions] == [1, 2000] and versions[1][1] == "infinity"
        assert (await s.execute(text("select count(*) from ohlcv_bar where instrument_id=:i"),
                                {"i": ids[k1]})).scalar() == 1
        assert await _periods(s, k1) == [("ACTIVE", False), ("REMOVED_FROM_MASTER", True)]

        # the same master again: idempotent
        r3 = await _refresh(s, _master(day2), T0 + _dt.timedelta(days=2, hours=1), tmp_path)
        assert r3.new_keys == [] and r3.changed_keys == [] and r3.transitions == {}

        # day 4: instrument 1 reappears -> same id, ACTIVE again
        r4 = await _refresh(s, _master([*day2, _eq(1)]), T0 + _dt.timedelta(days=4), tmp_path)
        assert r4.transitions == {"ACTIVE": [k1]} and r4.new_keys == []
        st = await _state(s)
        assert st[k1].instrument_id == ids[k1] and st[k1].lifecycle_status == "ACTIVE"
        assert await _periods(s, k1) == [("ACTIVE", False), ("REMOVED_FROM_MASTER", False),
                                         ("ACTIVE", True)]

    async def test_vendor_rejection_on_two_sessions_then_recovery(self, db_session, tmp_path):
        s = db_session
        base = [_eq(i) for i in range(1, 41)]
        await _refresh(s, _master(base), T0, tmp_path)
        k5 = f"NSE_EQ|{_isin(5)}"
        payload = (await s.execute(text("select payload_sha256 from raw_payload limit 1"))).scalar()

        async def run(status, day):
            rid = uuid.uuid4()
            at = _dt.datetime(2026, 9, day, 21, 0, tzinfo=IST)
            await s.execute(text("""
                insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
                  code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
                  started_at, finished_at, rows_written)
                values (:r, 'UPSTOX_REST_V3', :st, 't', '{}', 't', :c, ARRAY['x'], 'pytest',
                        'COMMIT', :status, :h, :t, :t, 0)"""),
                {"r": rid, "st": f"ohlcv.1m.{k5}", "c": "c" * 64, "status": status,
                 "h": "a" * 64, "t": at})
            if status == "FAILED":
                await s.execute(text("""insert into ingest_anomaly (run_id, severity, kind,
                    subject, detail, created_at) values (:r, 'FAIL', 'VENDOR_ERROR', :k,
                    cast(:d as jsonb), :t)"""),
                    {"r": rid, "k": k5, "t": at, "d": json.dumps(
                        {"codes": "UDAPI100011", "http_status": 400,
                         "payload_sha256": payload})})

        await run("FAILED", 23)
        r = await _refresh(s, _master(base), T0 + _dt.timedelta(days=1), tmp_path)
        assert r.transitions == {}                             # one session is not enough
        await run("FAILED", 24)
        r = await _refresh(s, _master(base), T0 + _dt.timedelta(days=2), tmp_path)
        assert r.transitions == {"VENDOR_REJECTED": [k5]}
        await run("COMPLETE", 25)
        r = await _refresh(s, _master(base), T0 + _dt.timedelta(days=3), tmp_path)
        assert r.transitions == {"ACTIVE": [k5]}

    async def test_truncated_master_changes_nothing(self, db_session, tmp_path):
        s = db_session
        await _refresh(s, _master([_eq(i) for i in range(1, 41)]), T0, tmp_path)
        r = await _refresh(s, _master([_eq(i) for i in range(1, 11)]),
                           T0 + _dt.timedelta(days=1), tmp_path)
        assert r.status == "FAILED" and "COVERAGE_DROP:instrument_master" in r.error
        st = await _state(s)
        assert all(v.lifecycle_status == "ACTIVE" for v in st.values()) and len(st) == 43

    async def test_dry_run_writes_nothing(self, db_session, tmp_path):
        s = db_session
        r = await _refresh(s, _master([_eq(i) for i in range(1, 41)]), T0, tmp_path,
                           commit=False)
        assert r.status == "COMPLETE" and len(r.new_keys) == 43
        assert await _state(s) == {}


class TestRealMasterReplay:
    """2026-09-23 -> 2026-09-25, the real incident."""

    async def test_rcdl_re_removed_new_listings_and_versions(self, db_session, tmp_path):
        s = db_session
        m23 = (FIX / "NSE_2026-09-23.json.gz").read_bytes()
        m25 = (FIX / "NSE_2026-09-25.json.gz").read_bytes()
        r1 = await _refresh(s, m23, _dt.datetime(2026, 9, 23, 13, 21, tzinfo=IST), tmp_path)
        assert r1.status == "COMPLETE" and len(r1.new_keys) == 3528
        chavda = "NSE_EQ|INE0PT101017"
        before = (await _state(s))[chavda].instrument_id
        r2 = await _refresh(s, m25, _dt.datetime(2026, 9, 25, 8, 25, tzinfo=IST), tmp_path)
        assert r2.status == "COMPLETE", r2.error
        st = await _state(s)
        assert {st[k].trading_symbol for k in r2.new_keys} == {
            "SPECTRAA", "SONA", "AXIOMGAS", "KHERIAAUTO"}
        assert r2.transitions.get("REMOVED_FROM_MASTER") == ["NSE_EQ|INE0BZQ20011"]
        assert st["NSE_EQ|INE0BZQ20011"].lifecycle_status == "REMOVED_FROM_MASTER"
        assert st[chavda].instrument_id == before and st[chavda].lot_size == 2000
        assert chavda in r2.changed_keys
        active = sum(v.lifecycle_status == "ACTIVE" for v in st.values())
        assert active == 3528 - 1 + 4 - len(r2.transitions.get("INELIGIBLE", []))
