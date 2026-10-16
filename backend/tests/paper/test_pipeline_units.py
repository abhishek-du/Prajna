"""Pure parts of the paper pipeline: the target-list contract, the Stage 6 limits, the
Stage 8 statistics and the strategy adapters (synthetic markets; no database)."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.core.clock import IST
from app.paper import monitor as MO
from app.paper import risk as RK
from app.paper import strategies as ST
from app.paper.targets import Target, TargetList, TargetListError
from tests.training.test_e4 import world

D = _dt.date(2026, 10, 15)
AT = _dt.datetime(2026, 10, 15, 9, 15, tzinfo=IST)


def tl(keys, at=AT, **kw):
    return TargetList("s1", D, at, tuple(Target(k, i + 1, float(i)) for i, k in
                                          enumerate(keys)), "test", **kw)


class TestContract:
    def test_valid_round_trip_and_stable_sha(self):
        a = tl(["A", "B"]).validate()
        b = TargetList.from_dict(a.to_dict())
        assert b == a and b.sha256() == a.sha256() and a.keys == ["A", "B"]

    @pytest.mark.parametrize("bad, why", [
        (dict(keys=["A", "A"]), "duplicate"),
        (dict(keys=["A"], at=AT + _dt.timedelta(seconds=1)), "look-ahead"),
        (dict(keys=["A"], at=AT.replace(tzinfo=None)), "timezone"),
        (dict(keys=["A"], exit_rule="TARGET_STOP"), "not simulated")])
    def test_invalid_lists_are_refused(self, bad, why):
        keys = bad.pop("keys")
        with pytest.raises(TargetListError, match=why):
            tl(keys, **bad).validate()

    def test_ranks_must_be_consecutive(self):
        with pytest.raises(TargetListError, match="ranks"):
            TargetList("s1", D, AT, (Target("A", 2),), "t").validate()

    def test_restriction_renumbers_and_keeps_scores(self):
        r = tl(["A", "B", "C"]).with_entries(["C", "A"])
        assert [(t.key, t.rank, t.score) for t in r.entries] == [("C", 1, 2.0), ("A", 2, 0.0)]


class TestRisk:
    CTX = {k: {"sector": "BANK" if k in "ABCD" else "S" + k, "prev_close": 100.0,
               "turnover": 1e9} for k in "ABCDEFGHIJKL"}

    def test_every_target_gets_a_decision_in_rule_order(self):
        ctx = {**self.CTX, "E": {**self.CTX["E"], "prev_close": 10.0},
               "F": {**self.CTX["F"], "turnover": None}}
        approved, dec = RK.apply(tl(list("ABCDEFGHIJKL")), ctx, RK.State(1e6))
        why = {d["key"]: d["reason"] for d in dec}
        assert why["D"] == "sector_cap"                       # 4th BANK name
        assert why["E"] == "min_price" and why["F"] == "min_turnover"
        assert approved.keys == list("ABCGHIJKL")              # 9 fit (limit 10)
        assert len(dec) == 12 and sum(d["decision"] == "APPROVED" for d in dec) == 9

    def test_max_positions(self):
        lim = RK.Limits(max_positions=2, max_names_per_sector=99)
        approved, dec = RK.apply(tl(list("ABCDE")), self.CTX, RK.State(1e6), lim)
        assert approved.keys == ["A", "B"]
        assert [d["reason"] for d in dec[2:]] == ["max_positions"] * 3

    @pytest.mark.parametrize("state, why", [
        (RK.State(1e6, drawdown_inr=100_000), "halted_drawdown"),
        (RK.State(1e6, last_day_pnl_inr=-30_000), "halted_daily_loss")])
    def test_halts_reject_everything(self, state, why):
        approved, dec = RK.apply(tl(["A", "B"]), self.CTX, state)
        assert approved.keys == [] and {d["reason"] for d in dec} == {why}

    def test_unknown_sector_is_its_own_bucket(self):
        ctx = {k: {**v, "sector": None} for k, v in self.CTX.items()}
        approved, _ = RK.apply(tl(list("ABCDE")), ctx, RK.State(1e6))
        assert approved.keys == ["A", "B", "C"]


class TestMonitor:
    def rows(self, rets, filled=10):
        return [{"session_date": D + _dt.timedelta(days=i), "recorded": r is not None,
                 "pnl_inr": None if r is None else r * 1e6, "ret": r,
                 "charges_inr": None if r is None else 100.0, "turnover_inr": 2e6,
                 "targets": 10, "filled": filled, "nifty_oc": 0.001, "c0": 0.0}
                for i, r in enumerate(rets)]

    def test_drawdown_and_summary(self):
        assert MO.max_drawdown([0.01, -0.02, -0.01, 0.05]) == pytest.approx(0.03)
        s = MO.summary(self.rows([0.01, -0.02, None, 0.005]))
        assert s["recorded"] == 3 and len(s["missing"]) == 1
        assert s["total_return"] == pytest.approx(-0.005) and s["hit_rate"] == pytest.approx(2 / 3)
        assert s["fill_rate"] == 1.0 and "not a profitability claim" in s["disclaimer"]

    def test_alerts(self):
        rows = self.rows([-0.04, -0.03, None], filled=0)
        al = MO.alerts(rows, MO.summary(rows))
        assert any(a.startswith("missing_session") for a in al)
        assert sum(a.startswith("no_fills") for a in al) == 2
        assert any(a.startswith("drawdown") for a in al)

    def test_psi(self):
        import numpy as np
        rng = np.random.default_rng(0)
        ref = rng.normal(0, 1, 5000).tolist()
        assert MO.psi(ref, rng.normal(0, 1, 5000).tolist()) < 0.02
        assert MO.psi(ref, rng.normal(1.0, 1, 5000).tolist()) > 0.25
        assert MO.psi([1.0] * 3, [1.0]) is None                 # too little reference

    def test_text_report(self):
        rows = self.rows([0.01, 0.0])
        t = MO.text_report("s1", D, D, MO.summary(rows), [])
        assert "PAPER" in t and "alerts: none" in t and "+1.00%" in t


class TestStrategies:
    def market(self, n=420):
        series = world(n_names=60, n=n, seed=5)
        days = [_dt.date(2025, 1, 1) + _dt.timedelta(days=i) for i in range(n)]
        return ST.Market(days, series, {k: "S" + k[-1] for k in series})

    def test_gap_fade_picks_the_largest_down_gaps(self):
        m = self.market()
        d = m.days[400]
        t = ST.gap_fade(m, d)
        sc = [e.score for e in t.entries]
        assert len(t.entries) == 10 and sc == sorted(sc, reverse=True) and sc[0] > 0
        assert t.decision_at == _dt.datetime.combine(d, _dt.time(9, 15), tzinfo=IST)

    def test_c0_is_random_but_deterministic(self):
        m = self.market()
        a, b = ST.c0(m, m.days[400]), ST.c0(m, m.days[400])
        assert a == b and len(a.entries) == 10 and a.keys != ST.c0(m, m.days[401]).keys

    def test_short_history_gives_an_empty_universe(self):
        m = self.market(n=200)                                 # < 260 valid closes
        assert ST.gap_fade(m, m.days[150]).entries == ()

    def test_context_reads_the_previous_session_only(self):
        m = self.market()
        d = m.days[400]
        c = ST.context(m, d)
        k = next(iter(m.series))
        assert c[k]["prev_close"] == m.series[k]["close"][399] and c[k]["sector"] == "S" + k[-1]
