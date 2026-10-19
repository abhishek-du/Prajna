"""Fundamentals F2 / F5b parsing and F3 / F5a ratios (pure; docs/STAGE1_FUNDAMENTALS_RND.md)."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.fundamentals import events as E
from app.fundamentals import ratios as R

D = _dt.date


class TestAnnouncements:
    def test_intimation_gives_the_results_calendar(self):
        ev = E.classify_announcement(
            "Board Meeting Intimation",
            "TATA CONSUMER PRODUCTS LIMITED has informed the Exchange about Board Meeting to "
            "be held on 26-Oct-2026 to consider and approve the Quarterly Unaudited Financial "
            "results of the Company for the period ended September 2026 and Other business. "
            "|SUBJECT: Board Meeting Intimation", D(2026, 10, 19))
        assert ev == E.Event("INTIMATION", meeting_date=D(2026, 10, 26),
                             period_end=D(2026, 9, 30), period_kind="Q")

    @pytest.mark.parametrize(("frag", "want"), [
        ("September 2026", D(2026, 9, 30)), ("September 30, 2026", D(2026, 9, 30)),
        ("30th September, 2026", D(2026, 9, 30)), ("30.09.2026", D(2026, 9, 30)),
        ("Sept. 30 2026", D(2026, 9, 30)), ("June 2026", D(2026, 6, 30)),
        ("31-Mar-2026", D(2026, 3, 31)), ("no date", None)])
    def test_period_end_formats(self, frag, want):
        assert E.parse_period_end(frag) == want

    def test_half_year_and_kind(self):
        ev = E.classify_announcement(
            "Board Meeting Intimation", "X Ltd has informed the Exchange about Board Meeting "
            "to be held on 28-Oct-2026 to inter-alia consider and approve the Unaudited "
            "Financial results of the Company for the Half Yearly ended September 2026 .")
        assert ev.period_kind == "H" and ev.period_end == D(2026, 9, 30)

    def test_a_period_after_the_meeting_is_dropped_not_guessed(self):
        ev = E.classify_announcement(
            "Board Meeting Intimation", "RENTOMOJO LIMITED has informed the Exchange about "
            "Board Meeting to be held on 05-Oct-2026 to inter-alia consider and approve the "
            "Unaudited Financial results of the Company for the Quarterly ended June 2027 .",
            D(2026, 9, 30))
        assert ev.period_end is None and ev.flags == ("PERIOD_AFTER_MEETING",)
        assert ev.meeting_date == D(2026, 10, 5)

    def test_non_results_meetings_are_not_events(self):
        assert E.classify_announcement(
            "Board Meeting Intimation", "X Ltd has informed the Exchange about Board Meeting "
            "to be held on 02-Nov-2026 to consider Fund raising.") is None
        assert E.classify_announcement(
            "Outcome of Board Meeting-XBRL", "Y Ltd has informed the Exchange regarding "
            "Outcome of Board Meeting held on 29-Sep-2026 for Buy-back") is None
        assert E.classify_announcement("Declaration of NAV", "financial results") is None

    def test_outcomes(self):
        ev = E.classify_announcement(
            "Outcome of Board Meeting", "Waaree Renewable Technologies Limited has submitted "
            "to the Exchange, the financial results for the period ended September 30, 2026.",
            D(2026, 10, 19))
        assert ev == E.Event("OUTCOME", period_end=D(2026, 9, 30))
        bare = E.classify_announcement("Financial Results Updates",
                                       "Financial Results Updates |SUBJECT: Financial Results "
                                       "Updates")
        assert bare.kind == "OUTCOME" and bare.period_end is None


class TestEstimateNews:
    @pytest.mark.parametrize(("title", "want"), [
        ("LTTS Q2 results: Net profit jumps 54% to ₹548 crore, beats estimates", "BEAT"),
        ("Tata Technologies Q2: Profit declines 5%, misses estimates; revenue grows 28%", "MISS"),
        ("HCLTech Q2 misses Street", "MISS"),
        ("Infosys Q2 profit in line with estimates", "INLINE"),
        ("ICICI Life Q2: VNB beats estimates but APE misses expectations", "MIXED"),
        ("Trent surges 10% as Q2 revenue beat lifts D-Street mood", None),
        ("US inflation comes in below estimates", None),       # no results context ... GDP
        ("Jio Financial shares drop 2.5% as Q2 PAT halves; MOFSL cuts FY27 estimates", None)])
    def test_verdicts(self, title, want):
        assert E.estimate_verdict(title) == want

    def test_fiscal_quarter_end(self):
        assert E.fiscal_quarter_end(2, D(2026, 10, 19)) == D(2026, 9, 30)
        assert E.fiscal_quarter_end(4, D(2026, 5, 2)) == D(2026, 3, 31)
        assert E.fiscal_quarter_end(3, D(2026, 2, 1)) == D(2025, 12, 31)
        ev = E.classify_news("LTTS Q2 results: profit beats estimates", D(2026, 10, 19))
        assert ev.period_end == D(2026, 9, 30) and ev.verdict == "BEAT"


def q_payload(values: dict[str, float]):
    return {"income_statement": [{"category": "net_profit",
                                  "history": [{"period": p, "value": v}
                                              for p, v in values.items()]}]}


def y_payload(pat: dict[str, float], eps: dict[str, float]):
    return {"full_statement": [
        {"particular": "Profit After Tax", "history": [{"period": p, "value": v}
                                                       for p, v in pat.items()]},
        {"particular": "EPS - Basic", "history": [{"period": p, "value": v}
                                                  for p, v in eps.items()]}]}


T1 = _dt.datetime(2026, 9, 24, tzinfo=_dt.UTC)
T2 = _dt.datetime(2026, 10, 20, tzinfo=_dt.UTC)


class TestRatios:
    def snaps(self):
        return {
            "income:consolidated:quarterly": [
                (T1, q_payload({"Jun 2026": 130, "Mar 2026": 120, "Dec 2025": 110,
                                "Sep 2025": 100})),
                (T2, q_payload({"Sep 2026": 150, "Jun 2026": 131, "Mar 2026": 120,
                                "Dec 2025": 110}))],
            "income:consolidated:yearly": [(T1, y_payload({"Mar 2026": 520}, {"Mar 2026": 6.0}))],
            "income:standalone:yearly": [(T1, y_payload({"Mar 2026": 400}, {"Mar 2026": 4.0}))],
            "balance_sheet:consolidated": [(T1, {"history": [
                {"period": "Mar 2026", "total_asset": 9000, "total_liability": 4000}]})]}

    def test_later_snapshot_wins_and_history_accumulates(self):
        f = R.build(self.snaps())
        assert f.basis == "consolidated"
        assert f.quarterly_np[D(2026, 6, 30)] == 131          # restated in the later snapshot
        assert f.quarterly_np[D(2025, 9, 30)] == 100          # kept from the earlier one

    def test_shares_from_standalone_and_the_ratios(self):
        r = R.ratios(R.build(self.snaps()), price=200.0)
        assert r["shares_basis"] == "standalone"
        assert r["shares"] == pytest.approx(400 * 1e7 / 4.0)   # 1e9 shares
        assert r["ttm_net_profit_cr"] == 150 + 131 + 120 + 110
        eps = 511 * 1e7 / 1e9
        assert r["ttm_eps"] == pytest.approx(eps)
        assert r["pe"] == pytest.approx(200 / eps)
        assert r["pb"] == pytest.approx(200 * 1e9 / (5000 * 1e7))

    def test_seasonal_random_walk_surprise(self):
        r = R.ratios(R.build(self.snaps()), price=200.0)
        assert r["surprise_quarter"] == D(2026, 9, 30)
        assert r["surprise_growth"] == pytest.approx((150 - 100) / 100)
        assert r["surprise_per_price"] == pytest.approx(50 * 1e7 / 1e9 / 200)

    def test_point_in_time_is_the_callers_filter(self):
        early = {k: [x for x in v if x[0] <= T1] for k, v in self.snaps().items()}
        r = R.ratios(R.build(early), price=200.0)
        assert r["latest_quarter"] == D(2026, 6, 30)
        assert r["surprise_growth"] is None                    # Jun 2025 never seen

    def test_gaps_and_losses(self):
        s = self.snaps()
        s["income:consolidated:quarterly"] = [(T1, q_payload({"Jun 2026": -50, "Dec 2025": 10,
                                                              "Sep 2025": 5, "Mar 2026": 1}))]
        r = R.ratios(R.build(s), price=200.0)
        assert r["ttm_net_profit_cr"] == -34 and r["pe"] is None
        assert r["earnings_yield"] < 0
        s["income:consolidated:quarterly"] = [(T1, q_payload({"Jun 2026": 5, "Dec 2025": 5}))]
        assert R.ratios(R.build(s), price=200.0)["ttm_net_profit_cr"] is None

    def test_nothing_known_is_none(self):
        assert R.build({}) is None
        assert R.period_end("Q1 FY27") is None and R.period_end("Sep 2026") == D(2026, 9, 30)
