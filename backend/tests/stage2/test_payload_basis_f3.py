"""Finding F3 (decision F3-PAYLOAD-BASIS, features-v4): a factor counts as already
applied by the vendor (baked) only for a stored PAYLOAD none of whose bars the vendor
later re-served adjusted by that factor. BLSE 2026-10-06: its whole history was
fetched on the ex-date morning, before the vendor adjusted it; the payload's basis
date (the ex-date) and the factor's vendor_applied=APPLIED (proved by LATER
CA_ADJUSTMENT observations of only its last 4 bars) made it look baked, and the
adjusted series kept a false -50% jump. The evidence is per payload, not per bar:
a per-bar rule only moved the jump to the oldest un-re-served bar. Test database
only; the production BLSE values are verified by ops/measure/ca_fix_verify.py."""

from __future__ import annotations

import datetime as _dt
import json
import os
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
EX = _dt.date(2026, 9, 21)


@pytest.fixture
async def world(db_session):
    clock.freeze(NOW)
    await SEED.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)
    s = db_session
    # the stored payload: VENDOR_ADJUSTED with basis date = the ex-date (fetched that
    # morning, before the vendor adjusted)
    sha = (await s.execute(text("select distinct payload_sha256 from ohlcv_bar where "
                                "instrument_key=:k"), {"k": R})).scalar()
    await s.execute(text("""insert into ohlcv_payload_basis (payload_sha256, endpoint,
        price_basis, basis_as_of, basis_confidence, method_version) values
        (:h, 'historical', 'VENDOR_ADJUSTED', :d, 'HIGH', 'test')"""), {"h": sha, "d": EX})
    rid = await SEED._run(s, "ca.f3", source="UPSTOX_REST_V2")
    psha = await SEED._payload(s, rid, "UPSTOX_REST_V2")
    # the horizon (an old action) and the split itself, both stored long before as_of
    for kind, ex, c in (("DIVIDEND", _dt.date(2025, 9, 24), "0" * 64), ("SPLIT", EX, "1" * 64)):
        ca = (await s.execute(text("""
            insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
              ex_date, content_sha256, vendor_payload, source, run_id, payload_sha256,
              fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
            values ('INE002A01018', :k, 'RELIANCE', :t, :x, :c, '{}', 'UPSTOX_REST_V2', :r,
                    :h, :f, :f, false, 'KN-CA') returning id"""),
            {"k": R, "t": kind, "x": ex, "c": c, "r": rid, "h": psha,
             "f": ist(2025, 9, 1)})).scalar()
    await s.execute(text("""
        insert into ca_factor (ca_id, instrument_key, action_type, ex_date, status, method,
          factor_price, factor_volume, knowable_at, vendor_applied, reason, method_version,
          derived_at, run_id) values (:c, :k, 'SPLIT', :x, 'EXACT', 'FACE_VALUE', 2, 2, :kn,
          'APPLIED', 'test', 'cafactor-v1', now(), :r)"""),
        {"c": ca, "k": R, "x": EX, "kn": ist(2025, 9, 1), "r": rid})
    s.info["split_ca"] = ca
    s.info["obs_run"] = (rid, psha)
    yield s
    clock.unfreeze()


async def _re_served_adjusted(s, days):
    """The vendor later re-serves the given pre-ex bars divided by 2 (CA_ADJUSTMENT)."""
    rid, sha = s.info["obs_run"]
    for b in (await s.execute(text("""select instrument_id, session_date, bar_start_utc, open,
            high, low, close, volume from ohlcv_bar where instrument_key = :k
            and timeframe = '1d' and extract(day from session_date) = any(:d)"""),
            {"k": R, "d": days})).all():
        await s.execute(text("""insert into ohlcv_observation (instrument_id, timeframe,
            session_date, bar_start_utc, source, instrument_key, open, high, low, close, volume,
            run_id, payload_sha256, fetched_at, classification, reason, explained_by,
            method_version, created_at) values (:i, '1d', :d, :b, 'UPSTOX_REST_V3', :k,
            :o, :h, :l, :c, :v, :r, :sha, :f, 'CA_ADJUSTMENT', 'test', cast(:e as jsonb),
            'revision-v1', now())"""),
            {"i": b[0], "d": b[1], "b": b[2], "k": R, "o": b[3] / 2, "h": b[4] / 2,
             "l": b[5] / 2, "c": b[6] / 2, "v": b[7] * 2, "r": rid, "sha": sha,
             "f": ist(2026, 9, 24, 11, 0),
             "e": json.dumps({"ca_ids": [s.info["split_ca"]], "factor": "2"})})


def _closes(res):
    return {r["market_date"].day: (r["close"], r["adjustment_status"]) for r in res["rows"]}


async def test_without_evidence_the_vendor_baked_factor_nets_out(world):
    """No later re-service of the bar: the vendor's APPLIED treatment holds (unchanged
    behaviour) - the stored pre-ex value is taken as already adjusted."""
    res = await pit.bars_adjusted(world, R, "1d", NOW)
    assert _closes(res)[14] == (Decimal("105.000000"), "AS_STORED")


async def test_a_payload_re_served_adjusted_was_raw_and_is_adjusted(world):
    """BLSE pattern: only the LAST pre-ex bar was later re-served /2 -> the whole
    payload is raw for the split -> every pre-ex bar adjusted /2, no jump anywhere."""
    await _re_served_adjusted(world, [18])
    res = await pit.bars_adjusted(world, R, "1d", NOW)
    c = _closes(res)
    assert c[14] == (Decimal("52.500000"), "ADJUSTED")
    assert all(c[d][1] == "ADJUSTED" for d in (14, 15, 16, 17, 18))
    assert c[22][1] == "AS_STORED"                          # on/after the ex-date
    vol = {r["market_date"].day: r["volume"] for r in res["rows"]}
    assert vol[14] == 2000


async def test_evidence_must_name_this_action(world):
    """An observation explained by another action never un-bakes this one."""
    rid, sha = world.info["obs_run"]
    b = (await world.execute(text("""select instrument_id, session_date, bar_start_utc
        from ohlcv_bar where instrument_key = :k and extract(day from session_date) = 18"""),
        {"k": R})).one()
    await world.execute(text("""insert into ohlcv_observation (instrument_id, timeframe,
        session_date, bar_start_utc, source, instrument_key, open, high, low, close, volume,
        run_id, payload_sha256, fetched_at, classification, reason, explained_by,
        method_version, created_at) values (:i, '1d', :d, :b, 'UPSTOX_REST_V3', :k, 1, 1, 1, 1,
        1, :r, :sha, :f, 'CA_ADJUSTMENT', 'test', cast(:e as jsonb), 'revision-v1', now())"""),
        {"i": b[0], "d": b[1], "b": b[2], "k": R, "r": rid, "sha": sha,
         "f": ist(2026, 9, 24, 11, 0), "e": json.dumps({"ca_ids": [999999999]})})
    c = _closes(await pit.bars_adjusted(world, R, "1d", NOW))
    assert all(c[d][1] == "AS_STORED" for d in (14, 15, 16, 17, 18))


def test_registry_v4_versions_only_adjusted_bar_features():
    from app.features import registry as RG
    assert RG.VERSION == "features-v4" and RG.F3_PAYLOAD_BASIS_ACTIVE
    base = {f.id: f.version for f in RG.FEATURES_V1 + RG.NEWS_V2_FEATURES}
    for f in RG.FEATURES:
        bars = f.scope == "INSTRUMENT" and bool({"daily_bars", "nifty_bars"} & set(f.inputs))
        ca = f.scope == "INSTRUMENT" and "corporate_actions" in f.inputs
        assert f.version == base[f.id] + (1 if (bars or ca) else 0) + (1 if bars else 0), f.id
    assert RG.BY_ID["ca_days_to_any"].version == 2 and RG.BY_ID["ret_1d"].version == 3
    assert RG.BY_ID["index_ret_1d"].version == 1
