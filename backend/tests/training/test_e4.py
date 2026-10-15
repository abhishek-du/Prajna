"""E4a pure computation (design approved 2026-10-15; step 1: code + synthetic tests;
nothing here reads the database or runs the experiment)."""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pytest

from app.training import e2 as X2
from app.training import e4 as X


def world(n_names=120, n=420, fade=0.0, seed=0):
    """Daily bars. With fade > 0, a name's open -> close return is -fade x its gap (a
    planted gap-fade effect); 0 = no edge. Gaps are independent N(0, 2%)."""
    rng = np.random.default_rng(seed)
    series = {}
    for j in range(n_names):
        c, rows = 100.0 * (1 + j / n_names), {"open": [], "high": [], "low": [], "close": [],
                                             "volume": []}
        for _ in range(n):
            g = rng.normal(0, 0.02)
            o = c * (1 + g)
            r = -fade * g + rng.normal(0, 0.012)
            c = o * (1 + r)
            rows["open"].append(o)
            rows["close"].append(c)
            rows["high"].append(max(o, c) * 1.004)
            rows["low"].append(min(o, c) * 0.996)
            rows["volume"].append(float(rng.uniform(5e4, 2e5)))
        series[f"K{j:03d}"] = rows
    return series


def years(n, start=2021):
    d, out = _dt.date(start, 1, 1), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.year)
        d += _dt.timedelta(days=1)
    return out


def run(series, predictor="gap_fade", k=10, capital=1_000_000, days=range(270, 420)):
    rows = []
    for d in days:
        sess = X.apply_mask(X.form_session(series, d, {}, predictor, k=k, seed=3), series)
        rows.append(X.primary(sess, series, X.SessionCost(capital, half_spread_bps=3.63)))
    s = [r["s"] for r in rows if r["s"] is not None]
    pl = [r["placebo"] for r in rows if r["placebo"] is not None]
    y = years(len(s), 2021)
    prim = X.summarise(s, y, b=1000)
    plac = X.summarise(pl, years(len(pl), 2021), b=1000)
    stressed = [r["p_gross"] - 1.5 * r["cost"] - r["c2_gross"] for r in rows if r["s"] is not None]
    return rows, prim, X.acceptance(prim, at_stress=float(np.mean(stressed)), placebo=plac,
                                    need_years=1)


class TestSignals:
    def test_gap_is_open_over_previous_close(self):
        s = {"open": [100.0, 103.0], "close": [100.0, 101.0], "volume": [1, 1]}
        assert X.gap(s, 1) == pytest.approx(0.03)
        assert X.gap_fade(s, 1) == pytest.approx(-0.03)

    def test_volume_spike_uses_only_sessions_before_d(self):
        vol = [100.0] * 25
        s = {"open": [100.0] * 26, "close": [100.0] * 26, "volume": [*vol, 1e9]}
        assert X.volume_spike(s, 25) is False          # d's own (huge) volume ignored
        s["volume"][24] = 200.0                          # d - 1 spikes: 2x the mean
        assert X.volume_spike(s, 25) is True
        assert X.gap_and_go({**s, "open": [100.0] * 25 + [102.0]}, 25) == pytest.approx(0.02)

    def test_picks_never_read_anything_of_d_but_the_open(self):
        series = world()
        d = 300
        before = X.form_session(series, d, {}, "gap_fade", seed=1)["arms"]
        for s in series.values():
            for col in ("high", "low", "close", "volume"):
                s[col][d:] = [1.0] * (len(s[col]) - d)
            s["open"][d + 1:] = [1.0] * (len(s["open"]) - d - 1)
        after = X.form_session(series, d, {}, "gap_fade", seed=1)["arms"]
        assert before == after


class TestUniverseControlsMask:
    def test_unexplained_huge_gap_is_a_data_error_not_a_signal(self):
        series = world(n_names=30)
        d = 300
        s = series["K000"]
        s["open"][d] = s["close"][d - 1] * 0.5          # -50%: an unrecorded split
        keys = [r[0] for r in X.eligible(series, d, {})]
        assert "K000" not in keys and len(keys) == 29

    def test_controls_match_the_gap_quintile_and_never_overlap(self):
        series = world()
        d = 300
        sess = X.form_session(series, d, {}, "gap_fade", k=10, seed=2)
        u = X.eligible(series, d, {})
        q = dict(zip([r[0] for r in u], X.bins(np.array([r[3] for r in u]), 5).tolist(),
                     strict=True))
        p, c2 = sess["arms"]["P"], sess["arms"]["C2"]
        assert len(p) == 10 and not set(p) & set(c2)
        from collections import Counter
        assert not Counter(q[x] for x in c2) - Counter(q[x] for x in p)   # same gap cells
        assert not set(p) & set(sess["arms"]["PL"]) and not set(p) & set(sess["arms"]["PLC"])

    def test_locked_day_is_dropped_from_every_arm(self):
        series = world(n_names=30)
        d = 300
        sess = X.form_session(series, d, {}, "gap_fade", k=5, seed=1)
        victim = sess["arms"]["P"][0]
        series[victim]["high"][d] = series[victim]["low"][d] = series[victim]["open"][d]
        out = X.apply_mask(sess, series)
        assert all(victim not in v for v in out["arms"].values())
        assert out["masked_picks"] == 1


class TestCosts:
    def test_mis_round_trip_matches_the_design_table(self):
        c = X.SessionCost(1_000_000, half_spread_bps=3.63)
        frac = c.fraction([f"N{i}" for i in range(10)], [0.0] * 10)   # Rs 1 L orders
        assert frac * 1e4 == pytest.approx(8.3 + 2 * 3.63, abs=0.15)
        frac5 = X.SessionCost(1_000_000, 3.63).fraction([f"N{i}" for i in range(5)], [0.0] * 5)
        assert frac5 * 1e4 == pytest.approx(5.9 + 2 * 3.63, abs=0.15)  # Rs 2 L orders

    def test_no_dp_charge_and_stt_on_the_sell_only(self):
        assert X.MIS.dp_per_scrip_sell_inr == 0 and X.MIS.stt_buy == 0
        assert X.MIS.stt_sell == pytest.approx(0.00025)
        assert X2.order_cost_inr(10_000, "BUY", X.MIS) < X2.order_cost_inr(10_000, "SELL", X.MIS)

    def test_cost_enters_once_and_the_control_is_untraded(self):
        series = world(n_names=60)
        sess = X.form_session(series, 300, {}, "gap_fade", k=10, seed=1)
        cost = X.SessionCost(1_000_000, 3.63)
        r = X.primary(sess, series, cost)
        assert r["s"] == pytest.approx(r["p_gross"] - r["cost"] - r["c2_gross"])
        assert r["cost"] > 0


class TestInference:
    def test_no_edge_world_does_not_pass(self):
        _, prim, acc = run(world(fade=0.0, seed=4))
        assert acc["A1"] != "PASS" and acc["candidate"]["status"] != "ACCEPTED-EXPLORATORY"
        assert prim.mean < 0                          # pure cost

    def test_a_planted_gap_fade_effect_above_costs_passes(self):
        _, prim, acc = run(world(fade=0.5, seed=5))
        assert prim.mean > 0.002 and acc["A1"] == "PASS" and acc["A2"] == "PASS"
        assert acc["candidate"]["status"] == "ACCEPTED-EXPLORATORY"

    def test_gap_and_go_does_not_profit_from_a_fade_world(self):
        _, _, acc = run(world(fade=0.5, seed=5), predictor="gap_and_go")
        assert acc["A1"] != "PASS"

    def test_minimum_detectable_effect_matches_the_design(self):
        assert 7e-4 < X.minimum_detectable(0.01, 1400) < 8e-4      # about 7.5 bps
