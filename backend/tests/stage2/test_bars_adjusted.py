"""PIT-safe corporate-action adjustment (phase 7): raw observed bars +
corporate actions known at as_of = the adjusted view a trader had then.
Never vendor-adjusted history passed off as point-in-time."""

from __future__ import annotations

import datetime as _dt
import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.canon import pit
from app.canon import process as P
from app.core import clock
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import NOW, R, ist

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
VISIBLE = ist(2026, 9, 24, 8, 0, 0, 1)            # the seed's bars are knowable at 08:00


@pytest.fixture
async def world(db_session):
    clock.freeze(NOW)
    await SEED.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)
    yield db_session
    clock.unfreeze()


async def _basis(s, basis, as_of_date=_dt.date(2026, 9, 24)):
    sha = (await s.execute(text("select distinct payload_sha256 from ohlcv_bar where "
                                "instrument_key=:k"), {"k": R})).scalar()
    await s.execute(text("""insert into ohlcv_payload_basis (payload_sha256, endpoint,
        price_basis, basis_as_of, basis_confidence, method_version) values
        (:h, 'historical', :b, :d, 'HIGH', 'test')"""), {"h": sha, "b": basis, "d": as_of_date})


async def _event(s, *, ex, knowable, factor, applied="NOT_APPLIED", kind="BONUS"):
    rid = await SEED._run(s, f"ca.{uuid.uuid4().hex[:6]}", source="UPSTOX_REST_V2")
    sha = await SEED._payload(s, rid, "UPSTOX_REST_V2")
    ca = (await s.execute(text("""
        insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
          ex_date, content_sha256, vendor_payload, source, run_id, payload_sha256,
          fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values ('INE002A01018', :k, 'RELIANCE', :t, :x, :c, '{}', 'UPSTOX_REST_V2', :r, :h,
                :f, :kn, false, 'KN-CA') returning id"""),
        {"k": R, "t": kind, "x": ex, "c": uuid.uuid4().hex * 2, "r": rid, "h": sha,
         "f": max(knowable, ist(2026, 9, 1)), "kn": knowable})).scalar()
    await s.execute(text("""
        insert into ca_factor (ca_id, instrument_key, action_type, ex_date, status, method,
          factor_price, factor_volume, knowable_at, vendor_applied, reason, method_version,
          derived_at, run_id) values (:c, :k, :t, :x, 'EXACT', 'BONUS_RATIO', :f, :f, :kn,
          :a, 'test', 'cafactor-v1', now(), :r)"""),
        {"c": ca, "k": R, "t": kind, "x": ex, "f": factor, "kn": knowable, "a": applied,
         "r": rid})
    return ca


async def _horizon(s):
    """The real feed reaches back to ex-date 2025-09-24: an old dividend sets the
    corporate-action horizon (vendor-adjusted bars before it are LOW confidence)."""
    rid = await SEED._run(s, "ca.old", source="UPSTOX_REST_V2")
    sha = await SEED._payload(s, rid, "UPSTOX_REST_V2")
    await s.execute(text("""
        insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
          ex_date, content_sha256, vendor_payload, source, run_id, payload_sha256,
          fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values ('INE002A01018', :k, 'RELIANCE', 'DIVIDEND', '2025-09-24', :c, '{}',
                'UPSTOX_REST_V2', :r, :h, :f, :f, false, 'KN-CA')"""),
        {"k": R, "c": "0" * 64, "r": rid, "h": sha, "f": ist(2025, 9, 1)})


def _closes(res):
    return {r["market_date"].day: (r["close"], r["adjustment_status"]) for r in res["rows"]}


class TestPitAdjustment:
    async def test_raw_bars_adjust_only_once_the_action_is_knowable(self, world):
        s = world
        await _basis(s, "RAW_OBSERVED")
        await _event(s, ex=_dt.date(2026, 9, 21), knowable=ist(2026, 9, 24, 9, 0),
                     factor=Decimal(2))
        before = await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 9, 0))    # AT: unknown
        assert _closes(before)[14] == (Decimal("105.000000"), "AS_STORED")
        after = await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 9, 0, 0, 1))
        c = _closes(after)
        assert c[14] == (Decimal("52.500000"), "ADJUSTED")      # before the ex-date: / 2
        assert c[22] == (Decimal("105.000000"), "AS_STORED")    # on/after the ex-date
        vol = {r["market_date"].day: r["volume"] for r in after["rows"]}
        assert vol[14] == 2000 and vol[22] == 1000

    async def test_a_future_action_never_changes_an_earlier_view(self, world):
        s = world
        await _basis(s, "RAW_OBSERVED")
        first = await pit.bars_adjusted(s, R, "1d", NOW)
        # announced tomorrow, effective next week: invisible at NOW
        await _event(s, ex=_dt.date(2026, 9, 30), knowable=ist(2026, 9, 25, 23, 59, 59),
                     factor=Decimal(5))
        # announced before NOW but ex-date after NOW: known, not yet effective
        await _event(s, ex=_dt.date(2026, 9, 29), knowable=ist(2026, 9, 20, 23, 59, 59),
                     factor=Decimal(3))
        again = await pit.bars_adjusted(s, R, "1d", NOW)
        assert _closes(again) == _closes(first)
        assert all(r["adjustment_status"] == "AS_STORED" for r in again["rows"])
        later = await pit.bars_adjusted(s, R, "1d", ist(2026, 10, 1))
        assert _closes(later)[14][0] == Decimal("7.000000")    # 105 / (3 * 5)

    async def test_vendor_baked_adjustment_nets_out_or_is_refused(self, world):
        s = world
        await _horizon(s)
        await _basis(s, "VENDOR_ADJUSTED", as_of_date=_dt.date(2026, 9, 24))
        await _event(s, ex=_dt.date(2026, 9, 21), knowable=ist(2026, 9, 24, 9, 0),
                     factor=Decimal(2), applied="APPLIED")
        # known at as_of: the vendor's baked factor IS the one we need -> as stored
        known = await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 10, 0))
        assert _closes(known)[14] == (Decimal("105.000000"), "AS_STORED")
        # not yet knowable at as_of, but already baked into the stored value:
        # undoing it would reconstruct from a rounded vendor value -> refused
        early = await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 8, 30))
        assert 14 not in _closes(early) and early["refused"]["reconstructed"] >= 1
        rec = await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 8, 30),
                                      allow_reconstructed=True)
        assert _closes(rec)[14] == (Decimal("210.000000"), "RECONSTRUCTED")

    async def test_unknown_vendor_treatment_is_low_confidence(self, world):
        s = world
        await _basis(s, "VENDOR_ADJUSTED")
        await _event(s, ex=_dt.date(2026, 9, 21), knowable=ist(2026, 9, 10),
                     factor=Decimal("1.1"), applied="UNKNOWN")
        res = await pit.bars_adjusted(s, R, "1d", NOW)
        assert 14 not in _closes(res) and res["refused"]["low_confidence"] >= 1
        ok = await pit.bars_adjusted(s, R, "1d", NOW, allow_low_confidence=True)
        assert all(r["basis_confidence"] == "LOW" for r in ok["rows"]
                   if r["market_date"].day < 21)

    async def test_no_recorded_basis_is_never_trusted(self, world):
        res = await pit.bars_adjusted(world, R, "1d", NOW)
        assert res["rows"] == [] and res["refused"]["low_confidence"] == 6

    async def test_strict_bar_knowability_is_unchanged(self, world):
        s = world
        await _basis(s, "RAW_OBSERVED")
        assert (await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 8, 0)))["rows"] == []
        assert len((await pit.bars_adjusted(s, R, "1d", VISIBLE))["rows"]) == 6


async def test_vendor_adjusted_bars_older_than_the_horizon_are_low_confidence(world):
    s = world
    await _basis(s, "VENDOR_ADJUSTED")
    await _event(s, ex=_dt.date(2026, 9, 21), knowable=ist(2026, 9, 10), factor=Decimal(2),
                 applied="APPLIED")
    res = await pit.bars_adjusted(s, R, "1d", NOW)          # horizon = 2026-09-21 here
    assert {r["market_date"].day for r in res["rows"]} == {22}
    assert res["refused"]["low_confidence"] == 5 and res["horizon"] == _dt.date(2026, 9, 21)
