"""Stage 2.2-2.4 pure rules: validation, timestamps, NSE filter, coverage."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import ClassVar

import pytest

from app.canon import coverage as COV
from app.canon import time as T
from app.canon import universe as U
from app.canon.validate import validate_bar_row, validate_identifiers
from app.core.clock import IST

D = _dt.date
UTC = _dt.UTC


def _bar(**kw):
    base = {"instrument_key": "NSE_EQ|INE002A01018", "timeframe": "1d",
            "open": Decimal(100), "high": Decimal(110), "low": Decimal(95),
            "close": Decimal(105), "volume": Decimal(1000),
            "knowable_at": _dt.datetime(2026, 9, 24, 3, tzinfo=UTC),
            "fetched_at": _dt.datetime(2026, 9, 24, 3, tzinfo=UTC)}
    return {**base, **kw}


class TestValidation:
    def test_valid_bar(self):
        assert validate_bar_row(_bar()) == []

    @pytest.mark.parametrize("kw,rule", [
        ({"open": Decimal(120)}, "ohlc_sanity"), ({"close": Decimal(90)}, "ohlc_sanity"),
        ({"high": Decimal(90)}, "ohlc_sanity"), ({"volume": Decimal(-1)}, "ohlc_sanity"),
        ({"low": Decimal(0), "open": Decimal(0)}, "price_nonpositive"),
        ({"timeframe": "7m"}, "timeframe"), ({"instrument_key": "RELIANCE"}, "instrument"),
        ({"knowable_at": _dt.datetime(2026, 9, 25, tzinfo=UTC)}, "knowable_after_fetched"),
        ({"fetched_at": _dt.datetime(2026, 9, 24)}, "timestamp"),
        ({"close": None}, "ohlcv_null")])
    def test_each_rule(self, kw, rule):
        assert rule in {v.rule for v in validate_bar_row(_bar(**kw))}

    def test_identifiers(self):
        assert validate_identifiers({"trading_symbol": "X", "segment": "NSE_EQ",
                                     "isin": "INE002A01018"}) == []
        assert {v.rule for v in validate_identifiers(
            {"trading_symbol": "", "segment": "NSE_EQ", "isin": "BAD"})} == {"symbol", "isin"}


class TestTime:
    def test_market_date_is_ist(self):
        assert T.market_date(_dt.datetime(2026, 9, 23, 20, 0, tzinfo=UTC)) == D(2026, 9, 24)

    def test_daily_event_is_the_session_not_09_15_label(self):
        s, e = T.event_window("1d", session_date=D(2026, 9, 23), bar_start=None,
                              open_ist=_dt.time(9, 15), close_ist=_dt.time(15, 30))
        assert s.astimezone(IST).time() == _dt.time(9, 15)
        assert e.astimezone(IST).time() == _dt.time(15, 30)
        assert T.event_window("1d", session_date=D(2020, 2, 1), bar_start=None,
                              open_ist=None, close_ist=None) == (None, None)

    def test_last_hour_bar_is_capped_at_the_close(self):
        start = _dt.datetime(2026, 9, 23, 15, 15, tzinfo=IST)
        _, e = T.event_window("1h", session_date=D(2026, 9, 23), bar_start=start,
                              open_ist=_dt.time(9, 15), close_ist=_dt.time(15, 30))
        assert e.astimezone(IST).time() == _dt.time(15, 30)

    def test_knowable_is_strictly_before(self):
        t = _dt.datetime(2026, 9, 24, 3, tzinfo=UTC)
        assert not T.is_knowable(t, t) and T.is_knowable(t, t + _dt.timedelta(microseconds=1))
        with pytest.raises(T.LookAheadViolation):
            T.assert_all_knowable([{"knowable_at": t}], t, "x")


class TestUniverse:
    @pytest.mark.parametrize("inst,included", [
        ({"instrument_key": "NSE_EQ|INE002A01018", "segment": "NSE_EQ",
          "instrument_type": "EQ", "isin": "INE002A01018", "trading_symbol": "R"}, True),
        ({"instrument_key": "NSE_EQ|X", "segment": "NSE_EQ", "instrument_type": "RR",
          "isin": "INE002A01018", "trading_symbol": "R"}, False),
        ({"instrument_key": "NSE_EQ|X", "segment": "NSE_EQ", "instrument_type": "EQ",
          "isin": "BAD", "trading_symbol": "R"}, False),
        ({"instrument_key": "NSE_INDEX|Nifty 50", "segment": "NSE_INDEX"}, True),
        ({"instrument_key": "NSE_INDEX|Nifty IT", "segment": "NSE_INDEX"}, False),
        ({"instrument_key": "GLOBAL_INDEX|^GSPC", "segment": "GLOBAL_INDEX"}, False),
        ({"instrument_key": "BSE_EQ|X", "segment": "BSE_EQ"}, False),
        ({"instrument_key": "NSE_FO|1", "segment": "NSE_FO"}, False)])
    def test_decisions_have_reasons(self, inst, included):
        d = U.decide(inst)
        assert d.included is included and d.reason

    def test_rules_and_content_hash_are_deterministic(self):
        assert len(U.RULES_SHA256) == 64
        a = {"x": 1, "d": D(2026, 1, 1), "run_id": "r1"}
        assert U.content_sha256(a) == U.content_sha256({**a, "run_id": "r2"})
        assert U.content_sha256(a) != U.content_sha256({**a, "x": 2})


class TestCoverage:
    S: ClassVar[list] = [D(2026, 9, d) for d in (14, 15, 16, 17, 18, 21)]
    T0 = _dt.datetime(2026, 9, 24, tzinfo=UTC)

    def test_every_state(self):
        wins = [COV.Window(D(2026, 9, 14), D(2026, 9, 16), "COMPLETE", self.T0),
                COV.Window(D(2026, 9, 17), D(2026, 9, 17), "FAILED", self.T0)]
        rs = COV.ranges(self.S, bars={D(2026, 9, 14): 1}, quarantined={D(2026, 9, 15): 1},
                        windows=wins, checkpoint=(D(2026, 9, 14), D(2026, 9, 18)))
        assert [(r.from_date.day, r.to_date.day, r.state) for r in rs] == [
            (14, 14, "DATA"), (15, 15, "QUARANTINED"), (16, 16, "EMPTY"),
            (17, 17, "VENDOR_ERROR"), (18, 18, "MISSING"), (21, 21, "PENDING_BACKFILL")]

    def test_consecutive_states_merge_and_count(self):
        rs = COV.ranges(self.S, bars=dict.fromkeys(self.S, 2), quarantined={},
                        windows=[], checkpoint=None)
        assert len(rs) == 1 and rs[0].sessions == 6 and rs[0].bars == 12

    def test_retry_after_failure_is_not_vendor_error(self):
        wins = [COV.Window(D(2026, 9, 14), D(2026, 9, 14), "FAILED", self.T0),
                COV.Window(D(2026, 9, 14), D(2026, 9, 14), "ABORTED",
                           self.T0 + _dt.timedelta(hours=1))]
        assert COV.session_state(D(2026, 9, 14), bars=0, quarantined=0, windows=wins,
                                 checkpoint=None) == "PENDING_BACKFILL"

    def test_nothing_is_filled(self):
        rs = COV.ranges(self.S, bars={}, quarantined={}, windows=[], checkpoint=None)
        assert rs[0].state == "PENDING_BACKFILL" and rs[0].bars == 0
