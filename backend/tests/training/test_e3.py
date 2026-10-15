"""E3 pure computation (design approved 2026-10-15; step 1: code + synthetic tests;
nothing here reads the database or runs the experiment)."""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pytest

from app.training import e2 as X2
from app.training import e3 as X

CNC = X2.Rates(brokerage_flat_inr=20.0, brokerage_pct=None, stt_buy=0.001, stt_sell=0.001,
               stamp_buy=0.00015, exchange_txn=0.0000307, sebi=0.000001, gst=0.18,
               dp_per_scrip_sell_inr=20.0, source="test", as_of="test")


def sessions(n, start=_dt.date(2020, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += _dt.timedelta(days=1)
    return out


def flat_series(n, px=100.0, vol=1000.0):
    return {"open": [px] * n, "high": [px] * n, "low": [px] * n, "close": [px] * n,
            "volume": [vol] * n}


def world(n_names=60, n=700, drift_sd=0.0, seed=0):
    """Random-walk names; drift_sd > 0 gives each name a persistent drift, so past 12-1
    momentum predicts the next month (a planted momentum effect); 0 = no edge."""
    rng = np.random.default_rng(seed)
    ss = sessions(n)
    series = {}
    drift = rng.normal(0, drift_sd, n_names) if drift_sd else np.zeros(n_names)
    for j in range(n_names):
        r = rng.normal(drift[j], 0.012, n)
        c = 100 * np.exp(np.cumsum(r))
        series[f"K{j:02d}"] = {"open": list(c), "high": list(c * 1.005), "low": list(c * 0.995),
                               "close": list(c), "volume": list(rng.uniform(5e4, 2e5, n))}
    return ss, series


def run(series, ss, predictor="mom_12_1", k=10, capital=1_000_000):
    plan = X.month_plan(ss)[13:]
    books = {a: [] for a in ("P", "C2", "PL", "PLC")}
    for f, e, x in plan:
        m = X.form_month(series, f, {}, predictor, k=k, seed=2)
        for a in books:
            books[a].append((f, e, x, m["arms"][a]))
    B = {a: X.month_book(v, series) for a, v in books.items()}
    cm = X2.CostModel(CNC, capital, half_spread_bps=5.0)
    years = X.years_of(ss, plan)
    prim = X.summarise(X.primary_series(B["P"], B["C2"], cm), years, b=1000)
    plac = X.summarise([a.gross - b.gross for a, b in zip(B["PL"].months, B["PLC"].months,
                                                          strict=True)], years, b=1000)
    stressed = X2.CostModel(CNC, capital, half_spread_bps=5.0, multiplier=1.5)
    st = float(np.mean(X.primary_series(B["P"], B["C2"], stressed)))
    return prim, X.acceptance(prim, at_stress=st, placebo=plac, need_years=2)


class TestCalendar:
    def test_month_plan_is_last_session_then_next_two_month_starts(self):
        ss = sessions(70)
        plan = X.month_plan(ss)
        for f, e, x in plan:
            assert (ss[f].year, ss[f].month) != (ss[e].year, ss[e].month)
            assert ss[e].day <= 3 and e == f + 1
            assert (ss[x].year, ss[x].month) != (ss[e].year, ss[e].month)
            assert (ss[x - 1].year, ss[x - 1].month) == (ss[e].year, ss[e].month)
        assert len(plan) == 2                     # Jan->Feb, Feb->Mar; March incomplete


class TestSignals:
    def test_momentum_skips_the_last_month(self):
        c = [100.0] * 300
        c[300 - 1 - 252] = 50.0
        c[300 - 1 - 21] = 75.0
        assert X.mom_12_1(c, 299) == pytest.approx(0.5)
        c[299] = 1e6                               # the last month never matters
        assert X.mom_12_1(c, 299) == pytest.approx(0.5)
        assert X.mom_12_1(c, 200) is None          # not enough history

    def test_52w_high_proximity(self):
        c, h = [100.0] * 300, [100.0] * 300
        h[100] = 200.0
        assert X.high_52w_proximity(c, h, 299) == pytest.approx(0.5)
        h[10] = 1000.0                             # older than 252 sessions: ignored
        assert X.high_52w_proximity(c, h, 299) == pytest.approx(0.5)

    def test_signals_never_read_after_formation(self):
        ss, series = world()
        f = X.month_plan(ss)[20][0]
        before = {k: (X.mom_12_1(s["close"], f), X.high_52w_proximity(s["close"], s["high"], f))
                  for k, s in series.items()}
        for s in series.values():
            for col in ("open", "high", "low", "close"):
                s[col][f + 1:] = [1.0] * (len(s[col]) - f - 1)
        after = {k: (X.mom_12_1(s["close"], f), X.high_52w_proximity(s["close"], s["high"], f))
                 for k, s in series.items()}
        assert before == after


class TestUniverseAndMask:
    def test_suspect_jump_unless_explained(self):
        s = flat_series(10)
        s["close"][5] = s["open"][5] = 50.0       # -50%: an unrecorded split
        assert X.suspect_sessions(s) == {5, 6}    # the drop and the jump back
        assert X.suspect_sessions(s, exact_factor_days={5, 6}) == set()

    def test_eligibility_uses_the_past_only(self):
        ss, series = world(n_names=20)
        f = 400
        sus = {"K00": {f - 10}, "K01": {f + 5}}    # K01's suspect lies in the future
        keys = [r[0] for r in X.eligible(series, f, sus)]
        assert "K00" not in keys and "K01" in keys
        cheap = {**series["K02"], "close": [10.0] * len(ss)}
        assert "K02" not in [r[0] for r in X.eligible({"K02": cheap}, f, {})]

    def test_mask_drops_the_name_from_every_arm(self):
        m = {"arms": {a: ["A", "B"] for a in X.ARMS}, "perm": [["A", "C"]]}
        out = X.apply_mask(m, {"A": {12}}, 10, 30)
        assert all(v == ["B"] for v in out["arms"].values())
        assert out["perm"] == [["C"]] and out["masked_picks"] == 1

    def test_arms_are_disjoint_and_sized(self):
        ss, series = world()
        f = X.month_plan(ss)[20][0]
        m = X.form_month(series, f, {}, "mom_12_1", k=10, seed=1, perm_draws=3)
        p = set(m["arms"]["P"])
        assert len(p) == 10 and not p & set(m["arms"]["C2"]) and not p & set(m["arms"]["PL"])
        assert not p & set(m["arms"]["PLC"]) and all(len(x) == 10 for x in m["perm"])


class TestBookAndCosts:
    def test_netting_trades_only_the_difference(self):
        s = {k: flat_series(100) for k in "ABC"}
        b = X.month_book([(0, 1, 20, ["A", "B"]), (20, 21, 40, ["A", "C"])], s)
        m0, m1 = b.months
        assert m0.buys == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)} and not m0.sells
        assert m1.buys == {"C": pytest.approx(0.5)} and m1.sells == {"B": pytest.approx(0.5)}

    def test_returns_are_entry_open_to_exit_open(self):
        s = {"A": flat_series(50)}
        s["A"]["open"][20] = 110.0
        b = X.month_book([(0, 1, 20, ["A"])], s)
        assert b.months[0].gross == pytest.approx(0.10)

    def test_missing_exit_is_valued_at_the_last_open_and_counted(self):
        s = {"A": flat_series(50)}
        s["A"]["open"][18] = 105.0
        s["A"]["open"][19] = None
        s["A"]["open"][20] = None
        b = X.month_book([(0, 1, 20, ["A"])], s)
        assert b.months[0].missing_exit == 1 and b.months[0].gross == pytest.approx(0.05)

    def test_costs_once_and_control_untraded(self):
        s = {k: flat_series(100) for k in "ABCD"}
        p = X.month_book([(0, 1, 20, ["A", "B"]), (20, 21, 40, ["C", "D"])], s)
        c = X.month_book([(0, 1, 20, ["C", "D"]), (20, 21, 40, ["A", "B"])], s)
        cm = X2.CostModel(CNC, 1_000_000, half_spread_bps=5.0)
        prim = X.primary_series(p, c, cm)
        for m, v in zip(p.months, prim, strict=True):
            assert v == pytest.approx(-sum(X.month_costs(m, cm).values()))   # flat prices
        assert all(v < 0 for v in prim)

    def test_monthly_cost_hurdle_is_small_at_k10(self):
        s = {f"N{i}": flat_series(100) for i in range(20)}
        p = X.month_book([(0, 1, 20, [f"N{i}" for i in range(10)]),
                          (20, 21, 40, [f"N{i}" for i in range(10, 20)])], s)
        cm = X2.CostModel(CNC, 1_000_000, half_spread_bps=5.0)
        full_turn = sum(X.month_costs(p.months[1], cm).values())   # sell 10 + buy 10
        assert 0.002 < full_turn < 0.005                            # 0.2-0.5% per month


class TestInference:
    def test_year_gate_and_candidate(self):
        x = [0.01] * 60
        years = [2021 + i // 12 for i in range(60)]
        r = X.summarise(x, years, b=500)
        pl = X.summarise(list(np.random.default_rng(0).normal(0, 0.01, 60)), years, b=500)
        acc = X.acceptance(r, at_stress=0.005, placebo=pl)
        assert acc["A3"] == "PASS" and acc["A3_positive_years"] == "5/5"
        bad = X.summarise([-0.01] * 60, years, b=500)
        assert X.acceptance(bad, at_stress=-0.02, placebo=pl)["candidate"]["status"] == "FAIL"

    def test_no_edge_world_does_not_pass(self):
        ss, series = world(drift_sd=0.0, seed=3)
        _, acc = run(series, ss)
        assert acc["A1"] != "PASS" and acc["candidate"]["status"] != "ACCEPTED-EXPLORATORY"

    def test_a_planted_momentum_effect_passes(self):
        ss, series = world(n_names=80, drift_sd=0.004, seed=5)
        prim, acc = run(series, ss)
        assert prim.mean > 0.01 and acc["A1"] == "PASS" and acc["A2"] == "PASS"
        assert acc["candidate"]["status"] == "ACCEPTED-EXPLORATORY"

    def test_minimum_detectable_effect(self):
        assert X.minimum_detectable(0.035, 68) == pytest.approx(2.8 * 0.035 / np.sqrt(68))
