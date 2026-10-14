"""E2 pure computation (DRAFT protocol; nothing here runs the experiment): labels and
corporate actions, purged/embargoed folds, staggered-tranche accounting, dated cost
rates (checked against the Upstox charges API responses of 2026-10-13), matched
controls and placebo, the block bootstrap and the acceptance gates. Synthetic data."""

from __future__ import annotations

import numpy as np
import pytest

from app.training import e2 as X

# delivery (CNC) charges as returned by GET /v2/charges/brokerage on 2026-10-13
# (var/stage4/costs/charges_20261013T093619Z.json): the rates below reproduce them
CNC = X.Rates(brokerage_flat_inr=20.0, brokerage_pct=None, stt_buy=0.001, stt_sell=0.001,
              stamp_buy=0.00015, exchange_txn=0.0000307, sebi=0.000001, gst=0.18,
              dp_per_scrip_sell_inr=0.0, source="Upstox GET /v2/charges/brokerage",
              as_of="2026-10-13T09:36:18Z")


class TestLabels:
    def test_open_to_open_and_missing_sessions(self):
        opens = [100.0, 101, 102, 103, 104, 110, 111]
        assert X.hold_label(opens, 0) == (pytest.approx(0.10), None)
        assert X.hold_label(opens, 2) == (None, "NO_EXIT_SESSION")
        assert X.hold_label([100.0, 1, 1, 1, 1, None], 0) == (None, "SESSION_MISSING")
        assert X.hold_label([0.0, 1, 1, 1, 1, 2], 0) == (None, "MALFORMED_PRICE")

    def test_split_inside_the_window_is_adjusted_not_a_loss(self):
        raw = [100.0, 102, 51, 52, 53, 54]           # 2:1 split, ex at index 2
        r, why = X.hold_label(raw, 0)
        assert why is None and r == pytest.approx(-0.46)      # unadjusted: a fake crash
        adj = X.back_adjust(raw, {2: 0.5})
        assert adj[:2] == [50.0, 51.0] and adj[2:] == raw[2:]
        assert X.hold_label(adj, 0)[0] == pytest.approx(54 / 50 - 1)

    def test_dividends_count_only_for_the_holder_of_record(self):
        opens = [100.0, 100, 98, 98, 98, 98]         # ex-dividend of 2 at index 2
        assert X.hold_label(opens, 0)[0] == pytest.approx(-0.02)                 # price only
        assert X.hold_label(opens, 0, dividends={2: 2.0})[0] == pytest.approx(0.0)
        assert X.hold_label(opens, 0, dividends={0: 2.0})[0] == pytest.approx(-0.02)  # before t


class TestFolds:
    def test_embargo_purges_every_train_label_window(self):
        folds = X.make_folds(260)
        assert folds
        for f in folds:
            tr, va, te = f["train"], f["valid"], f["test"]
            assert tr.stop - 1 + X.H < va.start                # TRAIN label ends first
            assert va.stop - 1 + X.H < te.start                # VALID label ends first
            assert te.stop - 1 + X.H < 260                     # every TEST label exits
        tests = [t for f in folds for t in f["test"]]
        assert tests == sorted(set(tests))                     # disjoint, chronological

    def test_too_short_an_embargo_is_refused(self):
        with pytest.raises(ValueError, match="leak"):
            X.make_folds(260, embargo=1)


def flat(n, px=100.0):
    return [px] * n


class TestBook:
    def test_ramp_staggering_and_netting(self):
        opens = {k: flat(20) for k in "ABCDEFG"}
        picks = {d: ["A", "B"] for d in range(0, 20)}
        picks[3] = ["A", "C"]
        book = X.tranche_book(picks, opens, range(4, 12))
        assert [b.day for b in book] == list(range(4, 12))
        assert all(b.ret == pytest.approx(0.0) for b in book)        # flat prices
        d4 = book[0]                       # 5th formation: ramp complete, nothing expires
        assert d4.buys == {"A": pytest.approx(0.1), "B": pytest.approx(0.1)} and not d4.sells
        d8 = book[4]                       # tranche of day 3 (A, C) expires, day 8 (A, B) enters
        assert d8.sells == {"C": pytest.approx(0.1)}               # A nets out
        assert d8.buys == {"B": pytest.approx(0.1)}
        d9 = book[5]
        assert not d9.buys and not d9.sells                         # A,B -> A,B: no trade
        assert X.turnover(book) == pytest.approx(np.mean([0.2, 0, 0, 0, 0.1, 0, 0, 0]))

    def test_returns_drift_and_compound_like_the_holdings(self):
        up = [100 * 1.01 ** i for i in range(30)]                   # +1% every session
        opens = {"A": up, "B": flat(30)}
        book = X.tranche_book({d: ["A"] for d in range(30)}, opens, range(10, 20))
        assert all(b.ret == pytest.approx(0.01) for b in book)      # fully invested in A
        mixed = X.tranche_book({d: ["A", "B"] for d in range(30)}, opens, range(10, 12))
        assert 0.005 < mixed[0].ret < 0.01        # A's weight drifted above one half

    def test_suspended_name_is_marked_flat_and_counted(self):
        opens = {"A": flat(20), "B": flat(20)}
        opens["B"][9] = None
        book = X.tranche_book({d: ["A", "B"] for d in range(20)}, opens, range(8, 10))
        assert book[0].missing_marks > 0 and book[0].ret == pytest.approx(0.0)

    def test_a_move_across_a_suspension_is_booked_when_the_name_reopens(self):
        """Audit 2026-10-14: the drift used open(d) -> open(d + 1), so a held name's
        move between its last open and its reopening was never booked."""
        opens = {"A": [100.0, 100, None, None, 150, 150, 150, 150, 150, 150]}
        book = X.tranche_book({0: ["A"]}, opens, range(0, 6))
        assert [b.missing_marks for b in book][1:3] == [1, 1]           # flat, counted
        assert book[3].ret == pytest.approx(0.1)          # 1/5 of the book: +50% on reopen
        assert np.prod([1 + b.ret for b in book]) == pytest.approx(1.1)


class TestCosts:
    @pytest.mark.parametrize("value,side,total", [
        (10430.1, "BUY", 35.98), (99665.4, "BUY", 141.95), (499485.9, "BUY", 616.69),
        (10430.1, "SELL", 34.42), (99665.4, "SELL", 127.00), (499485.9, "SELL", 541.77)])
    def test_rates_reproduce_the_broker_charges_api(self, value, side, total):
        assert X.order_cost_inr(value, side, CNC) == pytest.approx(total, abs=0.03)

    def test_intraday_brokerage_is_the_lower_of_flat_and_percent(self):
        mis = X.Rates(20.0, 0.0006, 0.0, 0.00025, 0.00003, 0.0000307, 0.000001, 0.18, 0.0,
                      "Upstox GET /v2/charges/brokerage", "2026-10-13T09:36:18Z")
        assert X.order_cost_inr(10430.1, "BUY", mis) == pytest.approx(8.09, abs=0.03)
        assert X.order_cost_inr(499485.9, "SELL", mis) == pytest.approx(167.15, abs=0.03)

    def test_day_cost_spread_and_slippage_are_separate(self):
        day = X.BookDay(0, 0.0, {"A": 0.1}, {"B": 0.1}, 2, 0)
        base = X.CostModel(CNC, capital_inr=1_000_000, half_spread_bps=0.0)
        spread = X.CostModel(CNC, capital_inr=1_000_000, half_spread_bps=5.0)
        slip = X.CostModel(CNC, capital_inr=1_000_000, half_spread_bps=5.0, slippage_bps=5.0)
        c0, c1, c2 = base.day_cost(day), spread.day_cost(day), slip.day_cost(day)
        assert c1 - c0 == pytest.approx(0.2 * 5 / 10_000)          # both sides, once each
        assert c2 - c1 == pytest.approx(0.2 * 5 / 10_000)
        assert X.CostModel(CNC, 1_000_000, 5.0, multiplier=1.5).day_cost(day) == \
            pytest.approx(1.5 * c1)

    def test_flat_fees_dominate_small_positions(self):
        small = X.CostModel(CNC, capital_inr=1_000_000, half_spread_bps=0)
        big = X.CostModel(CNC, capital_inr=100_000_000, half_spread_bps=0)
        day = X.BookDay(0, 0.0, {f"K{i}": 0.002 for i in range(100)}, {}, 100, 0)
        assert small.day_cost(day) > 2.5 * big.day_cost(day)      # INR 2k vs 200k orders

    def test_cost_parts_sum_to_the_total_and_are_counted_once(self):
        day = X.BookDay(0, 0.001, {"A": 0.1, "B": 0.05}, {"C": 0.1}, 3, 0)
        r = X.Rates(**{**CNC.__dict__, "dp_per_scrip_sell_inr": 20.0})
        cm = X.CostModel(r, capital_inr=1_000_000, half_spread_bps=5.0, slippage_bps=10.0)
        parts = cm.day_cost_parts(day)
        assert set(parts) == set(X.COST_PARTS)
        assert sum(parts.values()) == pytest.approx(cm.day_cost(day))
        assert parts["dp"] == pytest.approx(23.60 / 1_000_000)           # one scrip sold
        assert parts["spread"] == pytest.approx(0.25 * 5 / 10_000)
        assert parts["slippage"] == pytest.approx(0.25 * 10 / 10_000)
        assert sum(parts.values()) - parts["dp"] == pytest.approx(
            sum(X.order_cost_inr(v * 1e6, s, CNC) for s, v in
                (("BUY", 0.1), ("BUY", 0.05), ("SELL", 0.1))) / 1e6 + 0.25 * 15 / 10_000)
        summ = X.cost_summary([day], cm)
        assert summ["net"] == pytest.approx(0.001 - cm.day_cost(day))

    def test_measured_half_spread_per_name_with_the_proxy_as_fallback(self):
        day = X.BookDay(0, 0.0, {"A": 0.1}, {"B": 0.1}, 2, 0)
        cm = X.CostModel(CNC, 1_000_000, half_spread_bps=5.0,
                         half_spread_measured={(0, "A"): 12.0, (1, "B"): 30.0})
        assert cm.day_cost_parts(day)["spread"] == pytest.approx(0.1 * (12 + 5) / 10_000)
        assert cm.spread_coverage([day]) == {"measured": 1, "proxy": 1}


class TestControls:
    def keys(self, n=200):
        rng = np.random.default_rng(0)
        return [f"K{i:03d}" for i in range(n)], rng.lognormal(15, 2, n), rng.uniform(.01, .06, n)

    def test_matched_controls_share_the_cell_and_never_overlap(self):
        keys, tv, atr = self.keys()
        chosen = keys[:40]
        ctl, unmatched = X.matched_controls(keys, tv, atr, chosen, np.random.default_rng(1))
        cell = dict(zip(keys, zip(X.E.deciles(tv), X.E.deciles(atr), strict=True), strict=True))
        assert len(ctl) + unmatched == 40 and len(set(ctl)) == len(ctl)
        assert not set(ctl) & set(chosen)
        from collections import Counter
        want, free = Counter(cell[k] for k in chosen), Counter(cell[k] for k in keys[40:])
        assert Counter(cell[k] for k in ctl) == {c: min(n, free[c]) for c, n in want.items()
                                                  if min(n, free[c])}
        assert unmatched == sum(max(0, n - free[c]) for c, n in want.items())
        again, _ = X.matched_controls(keys, tv, atr, chosen, np.random.default_rng(1))
        assert again == ctl                                         # seeded, reproducible

    def test_placebo_excludes_the_picks(self):
        keys, _, _ = self.keys(50)
        p = X.placebo_picks(keys, keys[:10], np.random.default_rng(2))
        assert len(p) == 10 and not set(p) & set(keys[:10])


class TestInference:
    def test_block_must_cover_the_overlap(self):
        with pytest.raises(ValueError, match="2H"):
            X.summarise([0.0] * 50, [0] * 50, block=5)

    def test_acceptance_gates(self):
        rng = np.random.default_rng(3)
        good = list(rng.normal(0.004, 0.002, 100))
        folds = [i // 20 for i in range(100)]
        r = X.summarise(good, folds, b=2000)
        zero = X.summarise(list(rng.normal(0, 0.002, 100)), folds, b=2000)
        acc = X.acceptance(r, net_at_1p5=0.001, placebo=zero, gross=r, folds_total=5)
        assert acc["A1"] == "PASS" and acc["A3"] == "PASS" and acc["A4"] == "PASS"
        bad = X.summarise([-x for x in good], folds, b=2000)
        assert X.acceptance(bad, net_at_1p5=-0.1, placebo=r, gross=bad, folds_total=5) == {
            **X.acceptance(bad, net_at_1p5=-0.1, placebo=r, gross=bad, folds_total=5),
            "A1": "FAIL", "A2": "FAIL", "A3": "FAIL", "A4": "FAIL"}
        assert X.verdict((-0.1, 0.2)) == "UNPROVEN"
        assert X.acceptance(r, net_at_1p5=0, placebo=zero, gross=r, folds_total=5,
                            other_net_mean=r.mean + 1)["A5"] == "FAIL"


class TestProtocolIssues:
    def test_identical_costs_on_c2_credit_lower_turnover_not_an_edge(self):
        """Evidence for proposed change PC-1 (docs/STAGE4_E2_PROTOCOL_CHANGE_PROPOSAL.md):
        with zero gross edge, a persistent P book minus a re-drawn C2 book, both
        costed, shows a positive "net excess" while P loses money net of costs."""
        names = [f"N{i}" for i in range(400)]
        opens = {k: flat(40) for k in names}
        rng = np.random.default_rng(0)
        p = X.tranche_book({d: names[:100] for d in range(40)}, opens, range(10, 30))
        c = X.tranche_book({d: list(rng.choice(names[100:], 100, replace=False))
                            for d in range(40)}, opens, range(10, 30))
        cm = X.CostModel(CNC, capital_inr=10_000_000, half_spread_bps=5.0)
        gross = np.mean([b.ret for b in p]) - np.mean([b.ret for b in c])
        both_costed = np.mean(X.net_series(p, cm)) - np.mean(X.net_series(c, cm))
        assert gross == pytest.approx(0.0, abs=1e-12)
        assert both_costed > 0 > np.mean(X.net_series(p, cm))


# ── the experiment core (Amendment 2, PROPOSED) ────────────────────────────────────
def world(n=300, t=140, edge=0.0, seed=1):
    """Synthetic sessions and adjusted opens. The score is -ret_1d (P1 reversal);
    with edge > 0 a name's next-session return is edge * its standardised score."""
    rng = np.random.default_rng(seed)
    keys = [f"K{i:03d}" for i in range(n)]
    turn, atr = rng.lognormal(15, 1, n), rng.uniform(.01, .05, n)
    sessions, px = {}, np.full((n, t + 1), 100.0)
    ri = __import__("app.training.e1", fromlist=["CORE24"]).CORE24.index("ret_1d")
    for d in range(t):
        X = rng.normal(size=(n, 24))
        X[:, 23] = turn                                           # turnover_20
        X[:, 14] = atr                                            # atr_pct_14
        sessions[d] = {"keys": keys, "X": X, "turnover": turn, "atr": atr}
        r = edge * (-X[:, ri]) + rng.normal(0, 0.01, n)
        px[:, d + 1] = px[:, d] * (1 + r)
    opens = {k: px[i].tolist() for i, k in enumerate(keys)}
    return sessions, opens


def run(sessions, opens, sel, cm, *, perm=0, tests=((20, 40), (40, 60), (60, 80), (80, 100),
                                                    (100, 120))):
    from app.training import e1 as E1
    blocks = [(f, X.form_block(sessions, range(a, b), lambda s, u: E1.reversal(s), sel,
                               seed=7, perm_draws=perm)) for f, (a, b) in enumerate(tests)]
    return blocks, X.evaluate(blocks, opens, cm, b=500, seed=3)


CM10L = X.CostModel(X.Rates(**{**CNC.__dict__, "dp_per_scrip_sell_inr": 20.0}),
                    capital_inr=1_000_000, half_spread_bps=3.63)


class TestExperiment:
    def test_costs_enter_once_on_the_predictor_book_only(self):
        s, o = world()
        blocks, r = run(s, o, X.K100, CM10L)
        S = r["series"]
        P = [d for f, blk in blocks for d in X.tranche_book(blk["picks"]["P"], o, blk["test"])]
        cost = [CM10L.day_cost(d) for d in P]
        for prim, g, c in zip(S["primary_net_vs_c2_gross"], S["gross_vs_c2_gross"], cost,
                              strict=True):
            assert prim == pytest.approx(g - c, abs=1e-15)
        assert r["costs"]["net"] == pytest.approx(r["costs"]["gross"] - sum(
            r["costs"][p] for p in X.COST_PARTS))

    def test_no_edge_and_flat_prices_cannot_pass_through_a_control(self):
        s, _ = world()
        flat_opens = {k: flat(141) for k in s[0]["keys"]}
        _, r = run(s, flat_opens, X.K20, CM10L)
        assert r["results"]["gross_vs_c2_gross"]["mean"] == pytest.approx(0.0, abs=1e-15)
        assert r["results"]["primary_net_vs_c2_gross"]["mean"] < 0      # = -P's costs
        assert r["acceptance"]["A1"] == "FAIL" and r["acceptance"]["A2"] == "FAIL"

    def test_noise_world_is_not_a_pass(self):
        """One noise world (smoke). The false-rejection rate of the CI over many noise
        worlds is measured by ops/measure/e2_null_calibration.py, not asserted here."""
        s, o = world(edge=0.0)
        _, r = run(s, o, X.K100, X.CostModel(CNC, 5e7, 3.63))
        assert r["acceptance"]["A1"] != "PASS"
        assert abs(r["results"]["placebo_gross_vs_its_c2"]["mean"]) < 5e-4

    def test_a_planted_edge_above_costs_passes(self):
        s, o = world(edge=0.004, seed=2)       # seed 1's placebo draw is a 2.5%-tail one
        _, r = run(s, o, X.K100, X.CostModel(CNC, 5e7, 3.63), perm=20)
        a = r["acceptance"]
        assert a["A1"] == "PASS" and a["A2"] == "PASS" and a["A3"] == "PASS"
        assert a["A4"] == "PASS"
        assert r["c1"]["p_one_sided"] == pytest.approx(1 / 21)

    def test_selection_never_sees_later_sessions(self):
        s, _ = world()
        before = X.form_block(s, range(40, 60), lambda z, u: -z["X"][:, 0], X.K20, seed=1)
        for d in range(50, 140):                       # rewrite every later session
            s[d] = {**s[d], "X": -s[d]["X"]}
        after = X.form_block(s, range(40, 60), lambda z, u: -z["X"][:, 0], X.K20, seed=1)
        for a in X.ARMS:
            assert {d: v for d, v in after["picks"][a].items() if d < 50} == \
                {d: v for d, v in before["picks"][a].items() if d < 50}

    def test_arms_are_disjoint_and_sized_by_the_selection(self):
        s, _ = world(n=600)
        for sel, k in ((X.K100, 100), (X.K20, 20)):
            blk = X.form_block(s, range(40, 60), lambda z, u: -z["X"][:, 0], sel, seed=1)
            for d in range(36, 60):
                p, c2 = set(blk["picks"]["P"][d]), set(blk["picks"]["C2"][d])
                pl, plc = set(blk["picks"]["PL"][d]), set(blk["picks"]["PLC"][d])
                assert len(p) == k and not p & c2 and not p & pl and not p & plc
                assert len(blk["picks"]["C0"][d]) == 500           # the top-500 universe

    def test_k20_raises_the_order_size_fivefold_at_the_same_capital(self):
        s, o = world(n=600)
        size = {}
        for sel in (X.K100, X.K20):
            blk = X.form_block(s, range(40, 41), lambda z, u: -z["X"][:, 0], sel, seed=1)
            first = X.tranche_book(blk["picks"]["P"], o, range(36, 41))[0]   # ramp day
            size[sel.name] = np.mean(list(first.buys.values())) * 1_000_000
        assert size["k100-top-quintile"] == pytest.approx(2_000, rel=0.02)
        assert size["k20"] == pytest.approx(10_000, rel=0.02)


class TestRunnerDiscipline:
    """ops/measure/stage4_e2_hold.py: configuration identity and the one-look ledger
    (pure parts only; the runner itself is NOT RUN)."""

    @pytest.fixture
    def R(self, tmp_path, monkeypatch):
        import json
        import sys
        sys.path.insert(0, "ops/measure")
        import stage4_e2_hold as R
        f = tmp_path / "open_spread.json"
        f.write_text(json.dumps({"proxy_half_spread_bps": 3.6308,
                                 "first_quote_sensitivity_bps": 9.3393,
                                 "measured_half_spread_bps": {}}))
        monkeypatch.setattr(R, "SPREAD_FILE", f)
        return R

    def test_each_selection_and_level_is_its_own_configuration(self, R):
        shas = {R.cfg_sha(R.config(s, lv)) for s in ("k100", "k20") for lv in (0.975, 0.9875)}
        assert len(shas) == 4
        cfg = R.config("k20", 0.975)
        assert cfg["selection"]["n_picks"] == 20 and cfg["status"] == "EXPLORATORY"
        assert cfg["capital_inr"] == 1_000_000 and cfg["half_spread_proxy_bps"] == 5.0
        assert cfg["half_spread_sensitivity_bps"] == [3.6308, 9.3393]
        assert cfg["role"] == "PRIMARY" and R.config("k100")["role"] == "SENSITIVITY"
        assert cfg["rates"]["dp_per_scrip_sell_inr"] == 20.0 and cfg["block"] == 2 * X.H

    def test_one_look_is_enforced(self, R, tmp_path):
        import json
        sha = "ab" * 32
        with pytest.raises(SystemExit, match="dirty"):
            R.check_look(tmp_path, "validate", sha, dirty=True)
        R.check_look(tmp_path, "validate", sha, dirty=False)          # allowed
        with pytest.raises(SystemExit, match="validate phase"):
            R.check_look(tmp_path, "test", sha, dirty=False, confirm=f"E2-{sha[:12]}")
        (tmp_path / f"validate_{sha[:12]}.json").write_text(json.dumps({"config_sha256": "x"}))
        with pytest.raises(SystemExit, match="another configuration"):
            R.check_look(tmp_path, "test", sha, dirty=False, confirm=f"E2-{sha[:12]}")
        (tmp_path / f"validate_{sha[:12]}.json").write_text(json.dumps({"config_sha256": sha}))
        with pytest.raises(SystemExit, match="confirm-test-look"):
            R.check_look(tmp_path, "test", sha, dirty=False)
        cal, ok = tmp_path / "cal.json", f"E2-{sha[:12]}"
        with pytest.raises(SystemExit, match="no calibration file"):
            R.check_look(tmp_path, "test", sha, dirty=False, confirm=ok, calibration=cal)
        cal.write_text(json.dumps({"worlds": 100, "adequate": True}))
        with pytest.raises(SystemExit, match="< 1000"):
            R.check_look(tmp_path, "test", sha, dirty=False, confirm=ok, calibration=cal)
        cal.write_text(json.dumps({"worlds": 1000, "adequate": False}))
        with pytest.raises(SystemExit, match="not adequate"):
            R.check_look(tmp_path, "test", sha, dirty=False, confirm=ok, calibration=cal)
        cal.write_text(json.dumps({"worlds": 1000, "adequate": True}))
        R.check_look(tmp_path, "test", sha, dirty=False, confirm=ok, calibration=cal)
        (tmp_path / f"test_{sha[:12]}.json").write_text("{}")
        for phase in ("validate", "test"):
            with pytest.raises(SystemExit, match="single test look"):
                R.check_look(tmp_path, phase, sha, dirty=False, confirm=ok, calibration=cal)

    def test_calibration_must_be_of_the_current_code(self, R, tmp_path):
        import json
        cal = tmp_path / "cal.json"
        cal.write_text(json.dumps({"worlds": 1000, "adequate": True, "code_sha256": "old"}))
        assert R.calibration_ok(cal, "new") == (
            False, "calibration ran other e2 code: recalibrate (new file)")
        assert R.calibration_ok(cal, "old") == (True, "adequate")
        assert len(R.calibration_code_sha()) == 64

    def test_opens_matrix_leaves_missing_sessions_empty(self, R):
        m = R.opens_matrix({("A", 0): 10.0, ("A", 2): 11.0, ("B", 1): 5.0}, 3)
        assert m == {"A": [10.0, None, 11.0], "B": [None, 5.0, None]}


ALL_PASS = {"A1": "PASS", "A2": "PASS", "A3": "PASS", "A4": "PASS", "A5": None}


class TestCandidateStatus:


    def test_accepted_needs_newey_west_agreement(self):
        assert X.candidate_status(ALL_PASS, 3.0)["status"] == "ACCEPTED-EXPLORATORY"
        r = X.candidate_status(ALL_PASS, 1.5)
        assert r["status"] == "UNPROVEN" and r["nw_agrees"] is False

    def test_fail_unproven_blocked(self):
        assert X.candidate_status({**ALL_PASS, "A1": "FAIL"}, -3.0)["status"] == "FAIL"
        assert X.candidate_status({**ALL_PASS, "A3": "FAIL"}, 3.0)["status"] == "UNPROVEN"
        assert X.candidate_status({**ALL_PASS, "A1": "UNPROVEN"}, 0.5)["status"] == "UNPROVEN"
        assert X.candidate_status(ALL_PASS, None)["status"] == "BLOCKED"
        assert X.candidate_status(ALL_PASS, 3.0, is_p2=True)["status"] == "BLOCKED"  # no A5
        assert X.candidate_status({**ALL_PASS, "A5": "FAIL"}, 3.0,
                                  is_p2=True)["status"] == "UNPROVEN"

    def test_label_level_total_return_excess(self):
        lab = {("A", 0): 0.05, ("B", 0): 0.01, ("C", 0): 0.0, ("A", 1): 0.02}
        r = X.label_level_excess({0: ["A", "B"], 1: ["A"]}, {0: ["C"], 1: ["D"]}, lab,
                                 range(0, 2))
        assert r["mean"] == pytest.approx(0.03) and r["days"] == 1 and r["skipped_names"] == 1


class TestStudentizedCI:
    """Correction C-a: the moving-block bootstrap-t CI (coverage: e2_null_calibration)."""

    def test_constant_series_gives_a_point_interval(self):
        lo, hi = X.studentized_block_ci([-0.001] * 100, b=200, block=10, level=0.975, seed=1)
        assert lo == hi == pytest.approx(-0.001)

    def test_location_and_scale_equivariance(self):
        x = np.random.default_rng(3).normal(0, 0.01, 100).tolist()
        lo, hi = X.studentized_block_ci(x, b=2000, block=10, level=0.975, seed=4)
        lo2, hi2 = X.studentized_block_ci([2 * v + 0.5 for v in x], b=2000, block=10,
                                          level=0.975, seed=4)
        assert lo2 == pytest.approx(2 * lo + 0.5) and hi2 == pytest.approx(2 * hi + 0.5)
        assert lo < float(np.mean(x)) < hi

    def test_wider_than_the_percentile_interval_on_a_short_series(self):
        x = np.random.default_rng(5).normal(0, 0.01, 100).tolist()
        s = X.studentized_block_ci(x, b=4000, block=10, level=0.975, seed=6)
        p = X.E.block_bootstrap_ci(x, b=4000, block=10, level=0.975, seed=6)
        assert s[1] - s[0] > p[1] - p[0]

    def test_summarise_uses_the_studentized_interval_by_default(self):
        x = np.random.default_rng(7).normal(0, 0.01, 100).tolist()
        f = [i // 20 for i in range(100)]
        r = X.summarise(x, f, b=500, seed=1)
        assert r.ci == X.studentized_block_ci(x, b=500, block=10, level=0.975, seed=1)
        with pytest.raises(ValueError, match="ci_method"):
            X.summarise(x, f, ci_method="bca")


class TestCalibrationWaiver:
    """ops/measure/e2_calibration_waiver.py (option W): conservative-side only."""

    @staticmethod
    def W():
        import sys
        sys.path.insert(0, "ops/measure")
        import e2_calibration_waiver as W
        return W

    @staticmethod
    def src(two_sided, accepted_hi=0.013):
        return {"worlds": 1000, "ci_method": "studentized", "by_world": {
            kind: {"k20": {"accepted": {"wilson95": [0.003, accepted_hi]},
                           "ci_excludes_0": {"rate": r, "wilson95": w}}}
            for kind, (r, w) in two_sided.items()}}

    def test_conservative_failure_is_waivable(self):
        ok, problems, cons = self.W().evaluate(self.src(
            {"iid": (0.014, [0.0084, 0.0234]), "factor": (0.027, [0.0186, 0.039])}))
        assert ok and not problems and len(cons) == 1 and cons[0].startswith("iid")

    def test_anti_conservative_or_false_acceptance_is_never_waivable(self):
        W = self.W()
        assert not W.evaluate(self.src({"iid": (0.05, [0.04, 0.07])}))[0]
        assert not W.evaluate(self.src({"iid": (0.02, [0.01, 0.03])}, accepted_hi=0.026))[0]
        assert not W.evaluate({**self.src({"iid": (0.02, [0.01, 0.03])}), "worlds": 999})[0]

    def test_runner_rejects_a_waiver_whose_source_changed(self, tmp_path, monkeypatch):
        import hashlib
        import json
        import sys
        sys.path.insert(0, "ops/measure")
        import stage4_e2_hold as R
        src = tmp_path / "src.json"
        src.write_text("{}")
        w = tmp_path / "w.json"
        w.write_text(json.dumps({"worlds": 1000, "adequate": True, "code_sha256": "c",
                                 "source_file": "src.json",
                                 "source_sha256": hashlib.sha256(b"{}").hexdigest()}))
        assert R.calibration_ok(w, "c") == (True, "adequate")
        src.write_text('{"edited": 1}')
        assert R.calibration_ok(w, "c")[0] is False
