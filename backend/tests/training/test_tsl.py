"""label-tsl-long-v1 (approved contract 2026-10-12: k = 1.5, gross only): the pure
outcome rules (tick rounding, R_BELOW_TICK, touch, 1-minute resolution), and the build on
the Stage 3 seed world (dataset-specific ATR, PIT timing, exclusions, determinism,
immutability of label-v2, integrity). Test database only."""

from __future__ import annotations

import datetime as _dt
import os
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.canon import process as CP
from app.core import clock
from app.features import snapshots as SN
from app.training import integrity as IG
from app.training import labels as L
from app.training import policy as P
from app.training import replay as RP
from app.training import samples as SM
from app.training import tsl as TS
from tests.support import stage3_seed as W

TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
STRICT = P.DATASETS["strict"]
T5 = D("0.05")


def m(minute, h, lo):
    return (_dt.datetime(2026, 10, 7, 3, 45 + minute, tzinfo=_dt.UTC), D(h), D(lo))


class TestOutcomeRules:
    def test_contract_examples_tick_rounding(self):
        """The decision-sheet examples, k given explicitly where the sheet did."""
        r = TS.outcome(D("100.00"), D("101"), D("99"), D("100.5"), T5, 0.025, None, D(1))
        assert (r["target"], r["stop"]) == (D("105.00"), D("97.50"))
        r = TS.outcome(D("213.55"), D("214"), D("213"), D("213.6"), T5, 0.0183, None, D("1.5"))
        assert (r["target"], r["stop"]) == (D("225.30"), D("207.70"))
        r = TS.outcome(D("48.37"), D("49"), D("48"), D("48.5"), D("0.01"), 0.031, None, D(1))
        assert (r["target"], r["stop"]) == (D("51.37"), D("46.88"))
        r = TS.outcome(D("12.35"), D("12.4"), D("12.3"), D("12.35"), T5, 0.004, None, D("0.5"))
        assert r["reason"] == "R_BELOW_TICK" and r["outcome"] is None

    def test_target_stop_horizon(self):
        e = D("100.00")                                     # k = 1.5, atr 0.02 -> R = 3
        t = TS.outcome(e, D("106.10"), D("98"), D("104"), T5, 0.02, None)
        assert (t["target"], t["stop"]) == (D("106.00"), D("97.00"))
        assert (t["outcome"], t["gross"], t["r"]) == (1.0, 0.06, 2.0)
        assert t["flags"] == ["RESOLUTION_DAILY"]
        s = TS.outcome(e, D("103"), D("96.5"), D("99"), T5, 0.02, None)
        assert (s["outcome"], s["gross"], s["r"]) == (-1.0, -0.03, -1.0)
        h = TS.outcome(e, D("105"), D("97.5"), D("101.25"), T5, 0.02, None)
        assert (h["outcome"], h["gross"]) == (0.0, 0.0125) and h["r"] == pytest.approx(1.25 / 3)

    def test_both_touched(self):
        e, args = D("100.00"), (D("106.5"), D("96.5"), D("100"), T5, 0.02)
        a = TS.outcome(e, *args, None)
        assert a["reason"] == "AMBIGUOUS_ORDER" and a["flags"] == ["RESOLUTION_NO_1M"]
        bars = [m(0, "101", "99"), m(1, "106.5", "100"), m(2, "100", "96.5")]
        t = TS.outcome(e, *args, bars)
        assert t["outcome"] == 1.0 and t["flags"] == ["RESOLUTION_1M"]
        bars = [m(0, "101", "96.5"), m(1, "106.5", "100")]
        assert TS.outcome(e, *args, bars)["outcome"] == -1.0
        bars = [m(0, "106.5", "96.5")]
        same = TS.outcome(e, *args, bars)
        assert same["reason"] == "AMBIGUOUS_ORDER" and same["flags"] == [
            "RESOLUTION_1M_SAME_MINUTE"]
        bars = [m(0, "106.2", "99"), m(1, "100", "96.5")]          # 1m high <> daily high
        bad = TS.outcome(e, *args, bars)
        assert bad["reason"] == "AMBIGUOUS_ORDER" and bad["flags"] == [
            "RESOLUTION_1M_INCONSISTENT"]

    def test_missing_atr_is_excluded_never_zero(self):
        r = TS.outcome(D("100"), D("101"), D("99"), D("100"), T5, None, None)
        assert r == {**r, "reason": "ATR_NOT_VALID", "outcome": None, "gross": None, "r": None}


@pytest.mark.db
@pytest.mark.integration
@pytest.mark.isolation("REPEATABLE READ")
class TestBuild:
    @pytest.fixture
    async def world(self, db_session):
        clock.freeze(W.NOW)
        ids = await W.seed(db_session)
        await CP.process(db_session, commit=True, token=TOKEN)
        await db_session.execute(text("update instrument set tick_size = 5"))   # 0.05
        await db_session.commit()
        db_session.info["ids"] = ids
        hist = W.history()
        days = hist[-20:]
        rid = await RP.open_run(db_session, STRICT, days[0], days[-1], None, "test",
                                code={"git_sha": "t", "dirty": False})
        for d in days:
            await RP.replay_snapshot(db_session, STRICT,
                                     await SN.resolve(db_session, d, "PRE_SESSION"), rid)
        db_session.info["days"] = days
        yield db_session
        clock.unfreeze()

    async def test_build_pit_exclusions_determinism_and_integrity(self, world):
        days = world.info["days"]
        await L.build_v2(world, days[0], days[-1], cutoff=W.NOW, keys=[W.A, W.B])
        v2_before = (await world.execute(text("""select count(*), md5(string_agg(md5(concat_ws(
            '|', session_date, instrument_key, label_id, value, status, reason)), '' order by id))
            from training_label where label_version = 'label-v2'"""))).one()
        rep = await TS.build(world, "strict", days[0], days[-1], cutoff=W.NOW)
        assert rep["label_version"] == "label-tsl-long-v1-strict" and rep["drift_vs_stored"] == 0
        lab = {(r[0], r[1], r[2]): (r[3], r[4], r[5], r[6]) for r in (await world.execute(text("""
            select instrument_key, session_date, label_id, value, status, reason, flags
            from training_label where label_version = 'label-tsl-long-v1-strict'"""))).all()}
        # A rises by 1 a day: open = close - 0.5, high = close + 1 -> a target is reached
        # when R is small; whatever it is, every VALID outcome is consistent
        outs = {v[0] for k, v in lab.items() if k[2] == TS.OUTCOME and v[1] == "VALID"}
        assert outs <= {1.0, -1.0, 0.0} and outs
        # E (vendor-adjusted bars before the horizon) -> BAR_REFUSED; early ATR -> missing
        reasons = {v[2] for v in lab.values() if v[1] == "MISSING_INPUT"}
        assert reasons <= {"BAR_REFUSED", "ATR_NOT_VALID", "R_BELOW_TICK", "AMBIGUOUS_ORDER",
                           "MALFORMED_BAR", "SPECIAL_SESSION"}
        e_rows = {v[2] for k, v in lab.items() if k[0] == W.E}
        assert e_rows <= {"BAR_REFUSED", "ATR_NOT_VALID", "SPECIAL_SESSION"}
        # PIT: every label starts after the PRE_SESSION as_of of its session
        late = (await world.execute(text("""select count(*) from training_label l
            join training_session_done d on d.dataset_version = :v and d.snapshot = 'PRE_SESSION'
             and d.session_date = l.session_date
            where l.label_version = 'label-tsl-long-v1-strict' and l.label_start_at <= d.as_of"""),
            {"v": STRICT.version})).scalar()
        assert late == 0
        assert (await IG.checks_for(world, "label-tsl-long-v1-strict"))["pass"]
        again = await TS.build(world, "strict", days[0], days[-1], cutoff=W.NOW)
        assert again["inserted"] == 0 and again["rows_sha256"] == rep["rows_sha256"]
        v2_after = (await world.execute(text("""select count(*), md5(string_agg(md5(concat_ws(
            '|', session_date, instrument_key, label_id, value, status, reason)), '' order by id))
            from training_label where label_version = 'label-v2'"""))).one()
        assert v2_after == v2_before                         # label-v2 untouched
        sm = await SM.build(world, STRICT.version, "label-tsl-long-v1-strict")
        assert sm["samples"] == sm["inserted"] > 0
        assert (await IG.sample_checks(world, STRICT.version, "label-tsl-long-v1-strict"))["pass"]

    async def test_a_dataset_label_cannot_join_another_dataset(self, world):
        with pytest.raises(RP.BuildContractError, match="belongs to"):
            await SM.build(world, STRICT.version, "label-tsl-long-v1-asif")
