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
        cm = X.CostModel(CNC, 1_000_000, half_spread_bps=5.0, half_spread_by_name={"A": 12.0})
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
