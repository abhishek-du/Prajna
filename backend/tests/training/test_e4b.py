"""E4b pure computation (pre-registration approved 2026-10-19; step 1: code + synthetic
tests; nothing here reads the database or runs the experiment)."""

from __future__ import annotations

import copy
import datetime as _dt
from collections import Counter

import numpy as np
import pytest

from app.training import e3 as E3
from app.training import e4b as X

N_SESS = 420
DAYS = range(280, N_SESS)


def world(n_names=80, n=N_SESS, fade=0.0, mom=0.0, orb=0.0, early=0.0, seed=0,
          short=()):
    """Daily + 15m + 1h bars from one 15m path per session. Planted effects, applied to
    the 15m returns after the signal bar(s): fade = -fade x gap over 09:30 ... 15:00;
    mom = mom x the first-hour return over 10:15 ... 15:00; orb = +orb over 09:30 ...
    15:00 for a green 09:15 bar with a 09:15 volume spike; early = -early x gap over
    09:30 ... 10:15, half of it given back over 10:30 ... 15:00 (a reversion a target
    captures and a time exit partly loses). `short`: sessions where the
    index (and every name) has only the first 6 bars (a special session)."""
    rng = np.random.default_rng(seed)
    series = {}
    for j in range(n_names):
        s = {"open": [], "high": [], "low": [], "close": [], "volume": [], "m15": [], "h1": []}
        c = 100.0 * (1 + j / n_names)
        for d in range(n):
            g = rng.normal(0, 0.02)
            o = c * (1 + g)
            r = rng.normal(0, 0.003, X.M15_SLOTS)
            v = rng.uniform(1e4, 2e4, X.M15_SLOTS)
            spike = rng.random() < 0.15
            if spike:
                v[0] *= 4
            r[1:24] += -fade * g / 23
            r[1:5] += -early * g / 4
            r[5:24] += early * g / 2 / 19
            fh = float(np.prod(1 + r[:4]) - 1)
            r[4:24] += mom * fh / 20
            if spike and r[0] > 0:
                r[1:24] += orb / 23
            bars, p = [], o
            for i in range(X.M15_SLOTS):
                q = p * (1 + r[i])
                u = abs(rng.normal(0, 0.001))
                bars.append((p, max(p, q) * (1 + u), min(p, q) * (1 - u), q, float(v[i])))
                p = q
            if d in short:
                bars = bars[:6] + [None] * (X.M15_SLOTS - 6)
            live = [b for b in bars if b]
            h1 = []
            for k in range(X.H1_SLOTS):
                grp = [b for b in bars[4 * k:min(4 * k + 4, X.M15_SLOTS)] if b]
                h1.append((grp[0][0], max(b[1] for b in grp), min(b[2] for b in grp),
                           grp[-1][3], sum(b[4] for b in grp)) if grp else None)
            s["open"].append(o)
            s["close"].append(live[-1][3])
            s["high"].append(max(b[1] for b in live))
            s["low"].append(min(b[2] for b in live))
            s["volume"].append(sum(b[4] for b in live))
            s["m15"].append(bars)
            s["h1"].append(h1)
            c = live[-1][3]
        series[f"K{j:03d}"] = s
    index = {"m15": [[(1, 1, 1, 1, 1)] * X.M15_SLOTS if d not in short
                     else [(1, 1, 1, 1, 1)] * 6 + [None] * 19 for d in range(n)]}
    return series, X.regular_sessions(index)


@pytest.fixture(scope="module")
def flat():
    return world(seed=1)


def years(n, start=2022):
    d, out = _dt.date(start, 1, 3), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.year)
        d += _dt.timedelta(days=1)
    return out


def run(series, regular, hyp, capital=1_000_000):
    rows = []
    for d in DAYS:
        if not regular[d]:
            continue
        sess = X.form_session(series, d, {}, hyp, regular, seed=3)
        rows.append(X.primary(X.E4.apply_mask(sess, series), series,
                              X.E4.SessionCost(capital, half_spread_bps=5.0)))
    ok = [r for r in rows if r["s"] is not None]
    s = [r["s"] for r in ok]
    pl = [r["placebo"] for r in rows if r["placebo"] is not None]
    # spread the sessions over 5 synthetic years so A3 is meaningful
    y = [2022 + (i * 5) // len(s) for i in range(len(s))]
    prim = X.summarise(s, y, b=999)
    plac = X.summarise(pl, years(len(pl)), b=999)
    stressed = float(np.mean([r["p_gross"] - 1.5 * r["cost"] - r["c2_gross"] for r in ok]))
    delta = (X.summarise([r["delta"] for r in ok], y, b=999) if hyp == "B3" else None)
    return rows, prim, X.acceptance(prim, at_stress=stressed, placebo=plac, delta=delta)


class TestSessionsAndBars:
    def test_a_short_special_session_is_not_regular(self):
        _, regular = world(n_names=2, n=10, short={4})
        assert regular == [True] * 4 + [False] + [True] * 5

    def test_exit_is_the_1515_open_with_a_fallback_to_the_last_earlier_close(self):
        series, _ = world(n_names=1, n=3)
        s = series["K000"]
        assert X.time_exit(s, "B1", 2) == s["m15"][2][24][0]
        assert X.time_exit(s, "B2", 2) == s["h1"][2][6][0]
        s["m15"][2][24] = s["m15"][2][23] = None
        assert X.time_exit(s, "B1", 2) == s["m15"][2][22][3]
        assert X.time_exit(s, "B1", 2, official_close=True) == s["close"][2]

    def test_the_open_consistency_mask_drops_a_mismatched_name(self, flat):
        series = copy.deepcopy(flat[0])
        d = 300
        base = [r[0] for r in X.eligible(series, d, {}, "B2")]
        assert "K005" in base
        b = series["K005"]["m15"][d][0]
        series["K005"]["m15"][d][0] = (b[0] * 1.02, *b[1:])
        keys = [r[0] for r in X.eligible(series, d, {}, "B2")]
        assert keys == [k for k in base if k != "K005"]


class TestSignals:
    def test_relative_volume_uses_the_previous_14_regular_sessions_only(self):
        series, regular = world(n_names=1, n=40, short={30})
        s, d = series["K000"], 35
        prev = [i for i in range(d - 1, -1, -1) if regular[i]][:14]
        assert 30 not in prev and len(prev) == 14
        want = s["m15"][d][0][4] / np.mean([s["m15"][i][0][4] for i in prev])
        assert X.relative_volume(s, d, regular) == pytest.approx(want)
        s["m15"][d][0] = (*s["m15"][d][0][:4], 1e12)          # d's own volume only moves rv
        assert X.relative_volume(s, d, regular) > want

    def test_relative_volume_needs_ten_present_and_no_ca_in_the_window(self):
        series, regular = world(n_names=1, n=40)
        s, d = series["K000"], 35
        assert X.relative_volume(s, d, regular, {d - 3}) is None
        assert X.relative_volume(s, d, regular, {d}) is None
        assert X.relative_volume(s, d, regular, {d - 20}) is not None
        for i in range(d - 5, d):
            s["m15"][i][0] = None
        assert X.relative_volume(s, d, regular) is None             # 9 of 14 present

    def test_b1_requires_a_green_first_bar_and_b2_excludes_the_gap(self):
        series, regular = world(n_names=1, n=40)
        s, d = series["K000"], 35
        o = s["m15"][d][0][0]
        s["m15"][d][0] = (o, o * 1.01, o * 0.99, o * 0.995, 1e5)
        assert X.score(s, "B1", d, regular) is None
        h = s["h1"][d][0]
        s["open"][d] = s["close"][d - 1] * 1.10                     # a +10% gap
        assert X.score(s, "B2", d, regular) == pytest.approx(h[3] / h[0] - 1)

    @pytest.mark.parametrize(("hyp", "m15_from", "h1_from"), [("B1", 1, 0), ("B2", 4, 1),
                                                             ("B3", 1, 0)])
    def test_picks_never_read_a_bar_at_or_after_the_signal_instant(self, flat, hyp,
                                                                  m15_from, h1_from):
        """Every bar starting at or after the signal instant (and every later session)
        is replaced; B1 and B3 also lose the 09:15 1h bar (it ends at 10:15) and B3 every
        field of the 09:15 15m bar but its open."""
        series, regular = copy.deepcopy(flat[0]), flat[1]
        d = 300
        before = X.form_session(series, d, {}, hyp, regular, seed=1)["arms"]
        assert before["P"]
        junk = (1.0, 9.0, 0.5, 2.0, 1.0)
        for s in series.values():
            for col in ("high", "low", "close", "volume"):
                s[col][d:] = [1.0] * (len(s[col]) - d)
            s["open"][d + 1:] = [1.0] * (len(s["open"]) - d - 1)
            for tf, start in (("m15", m15_from), ("h1", h1_from)):
                s[tf][d][start:] = [junk] * (len(s[tf][d]) - start)
                for i in range(d + 1, len(s[tf])):
                    s[tf][i] = [None] * len(s[tf][i])
            if hyp == "B3":
                b = s["m15"][d][0]
                s["m15"][d][0] = (b[0], 9e9, 1e-9, 1.0, 1.0)
        after = X.form_session(series, d, {}, hyp, regular, seed=1)["arms"]
        assert before == after


def path(*bars):
    """A 15m day: given bars first, then flat bars at the last close."""
    out = list(bars)
    last = out[-1][3]
    out += [(last, last, last, last, 1.0)] * (X.M15_SLOTS - len(out))
    return {"open": [100.0], "close": [last], "m15": [out]}


class TestTargetStop:
    def test_target_first_then_stop_first(self):
        s = path((100, 100.5, 99.5, 100, 1), (100, 102.5, 99.8, 102, 1), (102, 102, 97, 97, 1))
        assert X.target_stop_exit(s, 0, 100.0, 0.02) == (102.0, "target")
        s = path((100, 100.5, 97.9, 98.5, 1), (98.5, 103, 98, 103, 1))
        assert X.target_stop_exit(s, 0, 100.0, 0.02) == (98.0, "stop")

    def test_both_in_one_bar_counts_the_stop(self):
        s = path((100, 103, 97, 101, 1))
        assert X.target_stop_exit(s, 0, 100.0, 0.02) == (98.0, "both")

    def test_a_bar_opening_beyond_the_level_fills_at_its_open(self):
        s = path((100, 100.5, 99.5, 100, 1), (96.5, 97, 96, 96.8, 1))
        assert X.target_stop_exit(s, 0, 100.0, 0.02) == (96.5, "stop")
        s = path((100, 100.5, 99.5, 100, 1), (104, 105, 103.5, 104.5, 1))
        assert X.target_stop_exit(s, 0, 100.0, 0.02) == (104.0, "target")

    def test_no_touch_exits_at_1515_and_the_1515_bar_is_not_a_touch_bar(self):
        s = path((100, 100.5, 99.5, 100.2, 1))
        s["m15"][0][24] = (100.3, 110, 90, 100, 1)
        assert X.target_stop_exit(s, 0, 100.0, 0.02) == (100.3, "time")

    def test_bars_after_the_touch_bar_do_not_change_the_exit(self):
        s = path((100, 100.5, 99.5, 100, 1), (100, 102.5, 99.8, 102, 1))
        first = X.target_stop_exit(s, 0, 100.0, 0.02)
        for i in range(2, X.M15_SLOTS):
            s["m15"][0][i] = (50, 200, 10, 60, 1)
        assert X.target_stop_exit(s, 0, 100.0, 0.02) == first


class TestBook:
    def test_an_unfilled_pick_holds_cash_and_costs_nothing(self, flat):
        series, regular = copy.deepcopy(flat[0]), flat[1]
        d = 300
        sess = X.form_session(series, d, {}, "B2", regular, k=10, seed=2)
        cost = X.E4.SessionCost(1_000_000, 5.0)
        full = X.primary(sess, series, cost)
        victim = sess["arms"]["P"][0]
        r_v = X.trade_return(series[victim], "B2", d)[0]
        series[victim]["h1"][d][1] = None                          # no 10:15 bar
        part = X.primary(sess, series, cost)
        assert part["unfilled"] == 1 and part["picks"] == 10
        assert part["p_gross"] == pytest.approx(full["p_gross"] - r_v / 10)
        assert part["cost"] == pytest.approx(full["cost"] * 0.9, rel=0.02)
        assert part["s"] == pytest.approx(part["p_gross"] - part["cost"] - part["c2_gross"])

    def test_controls_match_the_hypothesis_axis_and_never_overlap(self, flat):
        series, regular = flat
        d = 310
        for hyp in X.HYPOTHESES:
            sess = X.form_session(series, d, {}, hyp, regular, k=10, seed=4)
            u = X.eligible(series, d, {}, hyp)
            q = dict(zip([r[0] for r in u], X.E4.bins(np.array([r[3] for r in u]), 5).tolist(),
                         strict=True))
            p, c2 = sess["arms"]["P"], sess["arms"]["C2"]
            assert p and not set(p) & set(c2)
            assert not Counter(q[x] for x in c2) - Counter(q[x] for x in p)

    def test_b3_picks_are_the_e4a_gap_fade_picks(self, flat):
        series, regular = flat
        d = 305
        b3 = X.form_session(series, d, {}, "B3", regular, k=10, seed=1)["arms"]["P"]
        e4 = X.E4.form_session(series, d, {}, "gap_fade", k=10, seed=1)["arms"]["P"]
        assert b3 == e4

    def test_b3_delta_is_zero_when_no_level_can_be_touched(self, flat):
        series, regular = flat
        sess = X.form_session(series, 300, {}, "B3", regular, k=10, seed=1)
        r = X.primary(sess, series, X.E4.SessionCost(1_000_000, 5.0), mult=1e6)
        assert r["delta"] == pytest.approx(0.0, abs=1e-15) and r["exits"] == {"time": 10}


class TestInference:
    def test_level_is_bonferroni_over_three_and_the_mde_matches_the_design(self):
        assert X.LEVEL == pytest.approx(1 - 0.05 / 3)
        assert 7e-4 < X.minimum_detectable(0.008, 1120) < 8e-4
        assert 1.1e-3 < X.minimum_detectable(0.012, 1120) < 1.2e-3

    @pytest.mark.parametrize("hyp", X.HYPOTHESES)
    def test_a_no_edge_world_does_not_pass(self, flat, hyp):
        _, prim, acc = run(*flat, hyp)
        assert acc["A1"] != "PASS" and acc["candidate"]["status"] != "ACCEPTED-EXPLORATORY"
        assert prim.mean < 0                                       # pure cost
        if hyp == "B3":
            assert acc["adopt_target_stop"] is False

    @pytest.mark.parametrize(("hyp", "kw"), [("B1", {"orb": 0.02}),
                                             ("B2", {"mom": 3.0, "n_names": 250}),
                                             ("B3", {"early": 1.0})])
    def test_a_planted_effect_above_costs_passes(self, hyp, kw):
        """B2 matches on its own signal: with 80 names (45 cells) about 6 of 10 picks
        find no control in the depleted top cells and the placebo arm is biased; at 250
        names (as the real 500) about 0.6 are unmatched and the placebo is clean."""
        _, prim, acc = run(*world(seed=5, **kw), hyp)
        assert prim.mean > 0.002 and acc["A1"] == "PASS" and acc["A2"] == "PASS"
        assert acc["candidate"]["status"] == "ACCEPTED-EXPLORATORY"
        if hyp == "B3":                     # the target locks the early reversion in
            assert acc["delta"]["ci"][0] > 0 and acc["adopt_target_stop"] is True

    def test_an_all_day_fade_keeps_the_time_exit(self):
        """A fade that runs to the close: the target exits early, the time exit wins."""
        _, _, acc = run(*world(seed=5, fade=0.5), "B3")
        assert acc["delta"]["ci"][1] < 0 and acc["adopt_target_stop"] is False

    def test_other_hypotheses_do_not_profit_from_a_fade_world(self):
        w = world(seed=6, fade=0.5)
        for hyp in ("B1", "B2"):
            assert run(*w, hyp)[2]["A1"] != "PASS"

    def test_b3_adoption_needs_acceptance_and_a_positive_delta(self):
        acc_res = E3.Result(0.003, (0.002, 0.004), 900, 6.0,
                            {y: 0.003 for y in range(2022, 2027)}, -0.01)
        pl = E3.Result(0.0, (-0.001, 0.001), 900, 0.0, {}, 0.0)
        good = E3.Result(0.001, (0.0002, 0.002), 900, 3.0, {}, 0.0)
        flat_d = E3.Result(0.0005, (-0.0005, 0.0015), 900, 1.0, {}, 0.0)
        assert X.acceptance(acc_res, at_stress=0.001, placebo=pl, delta=good)[
            "adopt_target_stop"] is True
        assert X.acceptance(acc_res, at_stress=0.001, placebo=pl, delta=flat_d)[
            "adopt_target_stop"] is False
        assert "adopt_target_stop" not in X.acceptance(acc_res, at_stress=0.001, placebo=pl)
