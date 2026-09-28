"""Pure feature functions: hand-computed reference values, missing/malformed
inputs, and the reason contract (exactly one of value / reason)."""

from __future__ import annotations

import datetime as _dt
import math
from typing import ClassVar

import pytest

from app.features.compute import (
    DIVISION_UNDEFINED,
    INSUFFICIENT_HISTORY,
    MALFORMED_INPUT,
    MISSING_INPUT,
    REASONS,
    Bar,
    miss,
    ok,
)
from app.features.compute import context as CX
from app.features.compute import event as EV
from app.features.compute import fundamental as FU
from app.features.compute import liquidity as LQ
from app.features.compute import preopen as PO
from app.features.compute import price as PR

D0 = _dt.date(2026, 1, 1)


def bars(closes, vols=None, spread=1.0):
    return [Bar(D0 + _dt.timedelta(days=i), c, c + spread, c - spread, c,
                (vols[i] if vols else 100.0)) for i, c in enumerate(closes)]


class TestContract:
    def test_ok_normalises_to_12_significant_digits(self):
        assert ok(1 / 3) == (0.333333333333, None)
        assert ok(0.1 + 0.2) == (0.3, None)

    @pytest.mark.parametrize("x", [math.inf, -math.inf, math.nan])
    def test_non_finite_is_never_a_value(self, x):
        assert ok(x) == (None, DIVISION_UNDEFINED)

    def test_unknown_reason_is_refused(self):
        with pytest.raises(AssertionError):
            miss("ZERO")
        assert all(miss(r) == (None, r) for r in REASONS)


class TestPrice:
    def test_returns(self):
        b = bars([100, 110, 99])
        assert PR.ret(b, 1) == ok(99 / 110 - 1)
        assert PR.ret(b, 2) == (-0.01, None)
        assert PR.ret(b, 3) == (None, INSUFFICIENT_HISTORY)
        assert PR.ret(bars([0, 5]), 1) == (None, DIVISION_UNDEFINED)

    def test_sma_and_distance(self):
        b = bars([1, 2, 3, 4])
        assert PR.sma(b, 4) == (2.5, None)
        assert PR.sma(b, 5) == (None, INSUFFICIENT_HISTORY)
        assert PR.close_to_sma(b, 4) == (0.6, None)

    def test_ema_seeded_with_sma(self):
        # n=3, k=0.5: seed mean(1,2,3)=2; then 4 -> 3; 5 -> 4
        assert PR.ema_series([1, 2, 3, 4, 5], 3) == [2, 3, 4]
        assert PR.ema(bars([1, 2]), 3) == (None, INSUFFICIENT_HISTORY)

    def test_rsi_wilder(self):
        # changes +1,-1,+2 with n=2: seed gain (1+0)/2=.5, loss (0+1)/2=.5;
        # then gain (.5*1+2)/2=1.25, loss (.5*1+0)/2=.25 -> RS 5 -> 100-100/6
        assert PR.rsi(bars([10, 11, 10, 12]), 2) == ok(100 - 100 / 6)
        assert PR.rsi(bars([1, 2, 3]), 2) == (100.0, None)
        assert PR.rsi(bars([5, 5, 5]), 2) == (None, DIVISION_UNDEFINED)

    def test_macd_of_a_linear_series(self):
        # a linear series: every EMA lags by (n-1)/2 steps -> line = (26-12)/2 = 7
        # and the trigger (EMA of a constant line) = 7, histogram exactly 0
        line, trig, hist = PR.macd(bars([100 + i for i in range(60)]))
        assert line == (7.0, None) and trig == (7.0, None) and hist == (0.0, None)
        assert PR.macd(bars([1] * 20))[0] == (None, INSUFFICIENT_HISTORY)

    def test_atr(self):
        # constant spread 1 around a flat close: true range = 2 every day
        assert PR.atr(bars([50] * 16), 14) == (2.0, None)
        assert PR.atr_pct(bars([50] * 16), 14) == (0.04, None)
        assert PR.atr(bars([50] * 14), 14) == (None, INSUFFICIENT_HISTORY)

    def test_realised_vol(self):
        # alternating +/- log returns of equal size r: sample stdev = r*sqrt(n/(n-1))
        r = 0.01
        closes = [100 * math.exp(r * (i % 2)) for i in range(21)]
        v, why = PR.realised_vol(bars(closes), 20)
        assert why is None and v == pytest.approx(r * math.sqrt(20 / 19) * math.sqrt(252))
        assert PR.realised_vol(bars([1] * 20), 20) == (None, INSUFFICIENT_HISTORY)

    def test_beta(self):
        idx = [100 * (1.01 if i % 2 else 0.99) ** 1 * (1 + i / 1000) for i in range(62)]
        stock = [2 * x for x in idx]           # identical returns: beta 1
        assert PR.beta(bars(stock), bars(idx), 60) == (1.0, None)
        assert PR.beta(bars(stock[:30]), bars(idx), 60) == (None, INSUFFICIENT_HISTORY)
        assert PR.beta(bars([5] * 62), bars([7] * 62), 60) == (None, DIVISION_UNDEFINED)

    def test_beta_uses_common_dates_only(self):
        idx = bars([100 + (i % 3) for i in range(70)])
        stock = [b for i, b in enumerate(bars([100 + (i % 3) for i in range(70)])) if i != 40]
        assert PR.beta(stock, idx, 60)[1] is None      # a missing stock day is skipped

    def test_range_and_breakout(self):
        b = bars([10] * 20 + [12], spread=1.0)
        hi, lo = PR.range_position(b, 20)
        assert hi == ok(12 / 13 - 1) and lo == ok(12 / 9 - 1)
        assert PR.breakout(b, 20) == ((1.0, None), (0.0, None))
        assert PR.breakout(bars([10] * 20 + [8]), 20) == ((0.0, None), (1.0, None))


class TestLiquidity:
    def test_average_spike_turnover(self):
        v = [100.0] * 20 + [300.0]
        b = bars([10] * 21, vols=v)
        assert LQ.avg_volume(b, 20) == (110.0, None)
        assert LQ.volume_spike(b, 20) == (3.0, None)
        assert LQ.turnover(b, 20) == (1100.0, None)
        assert LQ.volume_spike(bars([1] * 21, vols=[0.0] * 21), 20) == (None, DIVISION_UNDEFINED)


class TestFundamental:
    KR: ClassVar = [{"name": "P/E", "company_value": "19.14", "sector_value": "16.1"},
          {"name": "ROE", "company_value": "8.94%", "sector_value": "-"}]

    def test_parsers(self):
        assert FU.parse_number("1,234.5") == 1234.5 and FU.parse_number("8.94%") == 8.94
        assert FU.parse_number("-") is None and FU.parse_number(True) is None
        assert FU.parse_period("Mar 2026") == _dt.date(2026, 3, 1)
        assert FU.parse_period("FY26") is None

    def test_key_ratios(self):
        assert FU.key_ratio(self.KR, "P/E") == (19.14, None)
        assert FU.ratio_to_sector(self.KR, "P/E") == ok(19.14 / 16.1)
        assert FU.ratio_to_sector(self.KR, "ROE") == (None, MALFORMED_INPUT)   # sector "-"
        assert FU.key_ratio(self.KR, "P/B") == (None, MISSING_INPUT)
        assert FU.key_ratio(None, "P/E") == (None, MISSING_INPUT)
        assert FU.key_ratio("oops", "P/E") == (None, MALFORMED_INPUT)
        assert FU.key_ratio([{"name": "P/E", "company_value": "n/a"}], "P/E") == \
            (None, MALFORMED_INPUT)

    @staticmethod
    def stmt(hist, particular="Revenue"):
        return {"full_statement": [{"particular": particular, "history": [
            {"period": p, "value": v} for p, v in hist]}]}

    def test_growth_yearly(self):
        assert FU.growth(self.stmt([("Mar 2026", 120), ("Mar 2025", 100)]), "Revenue") == \
            (0.2, None)
        assert FU.growth(self.stmt([("Mar 2026", 5), ("Mar 2025", -10)]), "Revenue") == \
            (None, DIVISION_UNDEFINED)                    # growth from a loss: undefined
        assert FU.growth(self.stmt([("Mar 2026", 5)]), "Revenue") == (None, INSUFFICIENT_HISTORY)
        assert FU.growth(self.stmt([("Mar 2026", 5)]), "PAT") == (None, MISSING_INPUT)
        assert FU.growth({"full_statement": "x"}, "Revenue") == (None, MALFORMED_INPUT)
        assert FU.growth({"full_statement": [{"particular": "Revenue", "history": ["x"]}]},
                         "Revenue") == (None, MALFORMED_INPUT)

    def test_growth_quarterly(self):
        q = self.stmt([("Jun 2026", 130), ("Mar 2026", 120), ("Jun 2025", 100)])
        assert FU.growth(q, "Revenue", quarterly=True) == (0.3, None)
        q = self.stmt([("Jun 2026", 130), ("Mar 2026", 120)])
        assert FU.growth(q, "Revenue", quarterly=True) == (None, INSUFFICIENT_HISTORY)

    def test_annual_periods_labelled_quarterly_are_refused(self):
        # the vendor's "quarterly" statement usually carries March periods only
        q = self.stmt([("Mar 2026", 120), ("Mar 2025", 100)])
        assert FU.growth(q, "Revenue", quarterly=True) == (None, MALFORMED_INPUT)

    def test_liabilities_to_assets(self):
        bs = {"full_statement": [
            {"particular": "Current Liabilities", "history": [{"period": "Mar 2026", "value": 3}]},
            {"particular": "Non-Current Liabilities",
             "history": [{"period": "Mar 2026", "value": 2}]},
            {"particular": "Total Assets", "history": [{"period": "Mar 2026", "value": 10}]}]}
        assert FU.liabilities_to_assets(bs) == (0.5, None)
        assert FU.liabilities_to_assets({"full_statement": []}) == (None, MISSING_INPUT)
        assert FU.liabilities_to_assets(None) == (None, MISSING_INPUT)


class TestEvent:
    CA: ClassVar = [{"action_type": "DIVIDEND", "ex_date": _dt.date(2026, 9, 1)},
          {"action_type": "BONUS", "ex_date": _dt.date(2026, 9, 24)},
          {"action_type": "SPLIT", "ex_date": _dt.date(2026, 10, 10)}]

    def test_ca_days(self):
        s = _dt.date(2026, 9, 24)
        assert EV.ca_days_since(self.CA, s, "any") == (0.0, None)       # ex today counts
        assert EV.ca_days_since(self.CA, s, "dividend") == (23.0, None)
        assert EV.ca_days_to(self.CA, s, "split") == (16.0, None)
        assert EV.ca_days_to(self.CA, s, "bonus") == (None, MISSING_INPUT)

    def test_news_window_is_half_open_before_as_of(self):
        at = _dt.datetime(2026, 9, 24, 3, 30, tzinfo=_dt.UTC)
        pub = [at - _dt.timedelta(hours=24), at - _dt.timedelta(hours=1), at,
               at + _dt.timedelta(minutes=1)]
        assert EV.news_count(pub, at, 24) == (2.0, None)     # at/after as_of never counted
        assert EV.news_hours_since(pub, at) == (1.0, None)
        assert EV.news_hours_since([], at) == (None, MISSING_INPUT)


class TestContext:
    def rows(self, who, days):
        out = []
        for d, (b, s) in days.items():
            out += [{"series_code": f"{who}|NSE_EQ|CASH|1D|buy_amt", "observation_date": d,
                     "value": b},
                    {"series_code": f"{who}|NSE_EQ|CASH|1D|sell_amt", "observation_date": d,
                     "value": s}]
        return out

    def test_flows(self):
        r = self.rows("FII", {_dt.date(2026, 9, 22): (10, 4), _dt.date(2026, 9, 23): (5, 8)})
        assert CX.flow(r, "FII", 1) == (-3.0, None)
        assert CX.flow(r, "FII", 2) == (3.0, None)
        assert CX.flow(r, "FII", 5) == (None, INSUFFICIENT_HISTORY)
        assert CX.flow(r, "DII", 1) == (None, MISSING_INPUT)
        assert CX.flow(r[:1], "FII", 1) == (None, MALFORMED_INPUT)        # one side only

    def test_vix_global_sector(self):
        assert CX.vix_change([10, 11, 12, 13, 14, 15.5], 5) == (5.5, None)
        assert CX.global_ret([100, 101]) == (0.01, None)
        assert CX.global_ret([100]) == (None, INSUFFICIENT_HISTORY)
        assert CX.sector_rs(0.1, [0.0, 0.02, 0.5]) == (0.08, None)
        assert CX.sector_rs(0.1, [0.0, 0.02]) == (None, INSUFFICIENT_HISTORY)


class TestPreopen:
    T: ClassVar = {"iep": "101.5", "tbq": 300, "tsq": 100, "ieq": 50}

    def test_values(self):
        assert PO.gap_pct(self.T, 100.0) == (0.015, None)
        assert PO.imbalance(self.T) == (0.5, None)
        assert PO.ieq(self.T) == (50.0, None)
        assert PO.ieq_to_avg_volume(self.T, 200.0) == (0.25, None)

    def test_missing_and_malformed_ticks(self):
        assert PO.gap_pct(None, 100.0) == (None, MISSING_INPUT)
        assert PO.gap_pct({"iep": "abc"}, 100.0) == (None, MISSING_INPUT)
        assert PO.gap_pct({"iep": 0}, 100.0) == (None, MISSING_INPUT)   # no discovered price
        assert PO.imbalance({"tbq": 0, "tsq": 0}) == (None, DIVISION_UNDEFINED)
        assert PO.ieq_to_avg_volume(self.T, None) == (None, MISSING_INPUT)
