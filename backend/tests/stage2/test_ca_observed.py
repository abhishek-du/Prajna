"""Decision CA-OBSERVED (migration 0018, features-v3): a corporate action and its
factor are knowable when Prajna OBSERVED them - greatest(announcement end of day
(KN-CA), fetched_at) - and the price-adjustment horizon counts only actions
knowable before as_of. The KN-CA value and the announcement date are preserved.

Late-arriving actions (announced before as_of, stored after it) and a historical
recompute (a past snapshot recomputed after such an action arrives) must never
see the action. Test database only."""

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
from app.features import registry as RG
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import NOW, R, ist

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
AS_OF = ist(2026, 9, 24, 10, 0)            # after the bars, between announcement and fetch


@pytest.fixture
async def world(db_session):
    clock.freeze(NOW)
    await SEED.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)
    yield db_session
    clock.unfreeze()


async def _basis(s, basis):
    sha = (await s.execute(text("select distinct payload_sha256 from ohlcv_bar where "
                                "instrument_key=:k"), {"k": R})).scalar()
    await s.execute(text("""insert into ohlcv_payload_basis (payload_sha256, endpoint,
        price_basis, basis_as_of, basis_confidence, method_version) values
        (:h, 'historical', :b, '2026-09-24', 'HIGH', 'test')"""), {"h": sha, "b": basis})


async def _late_action(s, *, ex, announced, fetched, factor=None, kind="BONUS"):
    """An action whose KN-CA instant (end of the announcement date) precedes its fetch."""
    kn = ist(announced.year, announced.month, announced.day, 23, 59, 59)
    rid = await SEED._run(s, f"ca.{uuid.uuid4().hex[:6]}", source="UPSTOX_REST_V2")
    sha = await SEED._payload(s, rid, "UPSTOX_REST_V2")
    ca = (await s.execute(text("""
        insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
          ex_date, announcement_date, content_sha256, vendor_payload, source, run_id,
          payload_sha256, fetched_at, knowable_at, knowable_at_verified, knowable_at_basis)
        values ('INE002A01018', :k, 'RELIANCE', :t, :x, :a, :c, '{}', 'UPSTOX_REST_V2', :r,
                :h, :f, :kn, false, 'KN-CA') returning id"""),
        {"k": R, "t": kind, "x": ex, "a": announced, "c": uuid.uuid4().hex * 2, "r": rid,
         "h": sha, "f": fetched, "kn": kn})).scalar()
    if factor is not None:
        await s.execute(text("""
            insert into ca_factor (ca_id, instrument_key, action_type, ex_date, status, method,
              factor_price, factor_volume, knowable_at, vendor_applied, reason, method_version,
              derived_at, run_id) values (:c, :k, :t, :x, 'EXACT', 'BONUS_RATIO', :f, :f, :kn,
              'NOT_APPLIED', 'test', 'cafactor-v1', :d, :r)"""),
            {"c": ca, "k": R, "t": kind, "x": ex, "f": factor, "kn": kn, "d": fetched,
             "r": rid})
    return ca, kn


def _closes(res):
    return {r["market_date"].day: (r["close"], r["adjustment_status"]) for r in res["rows"]}


class TestLateArrivingAction:
    async def test_invisible_until_fetched_and_kn_ca_preserved(self, world):
        s = world
        ca, kn = await _late_action(s, ex=_dt.date(2026, 9, 30), announced=_dt.date(2026, 9, 1),
                                    fetched=ist(2026, 9, 24, 11, 0))
        assert [a["id"] for a in await pit.corporate_actions(s, AS_OF, R)] == []
        later = await pit.corporate_actions(s, ist(2026, 9, 24, 11, 0, 0, 1), R)
        assert [a["id"] for a in later] == [ca]
        assert later[0]["knowable_at"] == ist(2026, 9, 24, 11, 0)
        assert later[0]["knowable_at_basis"].startswith("OBSERVED (CA-OBSERVED)")
        # the announcement evidence is kept, unchanged
        raw = (await s.execute(text("""select announcement_date, knowable_at, knowable_at_basis
            from canon_corporate_action_kn_ca where id = :c"""), {"c": ca})).one()
        assert tuple(raw) == (_dt.date(2026, 9, 1), kn, "KN-CA")
        assert (await s.execute(text("select knowable_at from corporate_action where id = :c"),
                                {"c": ca})).scalar() == kn

    async def test_factor_applies_only_after_the_fetch(self, world):
        s = world
        await _basis(s, "RAW_OBSERVED")
        await _late_action(s, ex=_dt.date(2026, 9, 21), announced=_dt.date(2026, 9, 10),
                           fetched=ist(2026, 9, 24, 11, 0), factor=Decimal(2))
        before = await pit.bars_adjusted(s, R, "1d", AS_OF)        # KN-CA would adjust here
        assert _closes(before)[14] == (Decimal("105.000000"), "AS_STORED")
        assert before["events_known"] == []
        after = await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 11, 0, 0, 1))
        assert _closes(after)[14] == (Decimal("52.500000"), "ADJUSTED")

    async def test_horizon_counts_only_actions_knowable_at_as_of(self, world):
        s = world
        await _basis(s, "VENDOR_ADJUSTED")
        # the only action (it sets the horizon) is stored after as_of
        await _late_action(s, ex=_dt.date(2025, 9, 24), announced=_dt.date(2025, 9, 1),
                           fetched=ist(2026, 9, 24, 11, 0), kind="DIVIDEND")
        early = await pit.bars_adjusted(s, R, "1d", AS_OF)
        assert early["horizon"] is None and early["rows"] == []      # depth unknown: LOW
        assert early["refused"]["low_confidence"] == 6
        late = await pit.bars_adjusted(s, R, "1d", ist(2026, 9, 24, 11, 0, 0, 1))
        assert late["horizon"] == _dt.date(2025, 9, 24) and len(late["rows"]) == 6


class TestHistoricalRecompute:
    async def test_a_past_snapshot_recomputed_after_a_late_action_is_unchanged(self, world):
        """The features of a past as_of, recomputed today after an action announced
        before that as_of has been stored, are identical (values and provenance)."""
        from app.features import engine as E
        from app.features.snapshots import Snapshot
        s = world
        await _basis(s, "RAW_OBSERVED")
        snap = Snapshot(_dt.date(2026, 9, 24), "PRE_SESSION", AS_OF, _dt.date(2026, 9, 23))
        before = await E.compute_snapshot(s, snap, [R], with_context=False, with_sector=False)
        await _late_action(s, ex=_dt.date(2026, 9, 21), announced=_dt.date(2026, 9, 10),
                           fetched=ist(2026, 9, 24, 11, 0), factor=Decimal(2), kind="BONUS")
        await _late_action(s, ex=_dt.date(2026, 9, 29), announced=_dt.date(2026, 9, 15),
                           fetched=ist(2026, 9, 24, 11, 30), kind="DIVIDEND")
        again = await E.compute_snapshot(s, snap, [R], with_context=False, with_sector=False)
        sig = lambda res: sorted((r.feature_id, r.value, r.reason, r.inputs_sha256)  # noqa: E731
                                 for r in res.rows)
        assert sig(again) == sig(before)
        assert {r.feature_id: r.reason for r in again.rows}["ca_days_to_dividend"] \
            == "MISSING_INPUT"


class TestRegistryV3:
    def test_versions_bumped_only_for_ca_dependent_features(self):
        # features-v3 introduced the bump; features-v4 (F3-PAYLOAD-BASIS) adds its own
        assert RG.CA_OBSERVED_ACTIVE and RG.VERSION in ("features-v3", "features-v4")
        f3 = getattr(RG, "F3_PAYLOAD_BASIS_ACTIVE", False)
        v1 = {f.id: f.version for f in RG.FEATURES_V1 + RG.NEWS_V2_FEATURES}
        for f in RG.FEATURES:
            dependent = f.scope == "INSTRUMENT" and bool(
                {"daily_bars", "nifty_bars", "corporate_actions"} & set(f.inputs))
            later = 1 if f3 and RG._f3_payload_basis(f) else 0
            assert f.version - later == v1[f.id] + (1 if dependent else 0), f.id
        bumped = {f.id for f in RG.FEATURES if f.version != v1[f.id]}
        assert {"ret_1d", "sma_200", "beta_60", "ca_days_to_any", "sector_rs_20",
                "preopen_gap_pct"} <= bumped
        assert not bumped & {"index_ret_1d", "india_vix_level", "global_ret_1d",
                             "fii_net_cash_1d", "preopen_imbalance", "mnews_news_count_24h",
                             "pe", "news_count_24h"}
        assert len(bumped) == 37
