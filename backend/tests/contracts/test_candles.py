"""M4.0 candle contract. The cases are the vendor behaviour MEASURED on
2026-09-23 (accepted/rejected ranges, labels seen, forming bars)."""

from __future__ import annotations

import datetime as _dt
import itertools
import random
from typing import ClassVar

import pytest

from app.contracts import candles as C
from app.contracts.knowable import for_daily_bar, for_intraday_bar
from app.core.clock import IST, UTC

D, T = _dt.date, _dt.time


def ist(y, mo, d, h=0, mi=0, s=0):
    return _dt.datetime(y, mo, d, h, mi, s, tzinfo=IST).astimezone(UTC)


class TestWindows:
    # (timeframe, from, to, accepted by Upstox on 2026-09-23?)
    MEASURED: ClassVar[list] = [
        ("1d", D(2000, 1, 1), D(2009, 12, 31), True),
        ("1d", D(2016, 9, 24), D(2026, 9, 23), True),
        ("1d", D(2000, 1, 1), D(2026, 9, 23), False),     # 400 UDAPI1148
        ("1m", D(2022, 1, 1), D(2022, 1, 31), True),
        ("1m", D(2026, 8, 1), D(2026, 8, 31), True),
        ("1m", D(2026, 7, 1), D(2026, 8, 31), False),     # 400 UDAPI1148
        ("5m", D(2022, 1, 1), D(2022, 1, 31), True),
        ("15m", D(2022, 1, 1), D(2022, 1, 31), True),
        ("15m", D(2026, 7, 1), D(2026, 8, 31), False),    # 400 UDAPI1148
        ("1h", D(2026, 6, 1), D(2026, 8, 31), True),
        ("1h", D(2026, 5, 1), D(2026, 8, 31), False),     # 400 UDAPI1148
    ]

    @pytest.mark.parametrize("tf, frm, to, accepted", MEASURED)
    def test_measured_ranges(self, tf, frm, to, accepted):
        """A range the vendor accepted fits one window; a rejected one never does.
        (2016-09-24..2026-09-23 was accepted as a rolling decade; the planner
        still splits it on decade boundaries, which is also accepted.)"""
        n = len(C.plan_windows(tf, frm, to).windows)
        if accepted and not (tf == "1d" and frm.year % 10):
            assert n == 1
        if not accepted:
            assert n > 1

    def test_months_are_calendar_months(self):
        p = C.plan_windows("1m", D(2022, 1, 1), D(2022, 3, 15))
        assert p.windows == (C.Window(D(2022, 1, 1), D(2022, 1, 31)),
                             C.Window(D(2022, 2, 1), D(2022, 2, 28)),
                             C.Window(D(2022, 3, 1), D(2022, 3, 15)))

    def test_quarters_are_three_months_from_the_first_day(self):
        p = C.plan_windows("1h", D(2026, 5, 10), D(2026, 9, 23))
        assert p.windows == (C.Window(D(2026, 5, 10), D(2026, 7, 31)),
                             C.Window(D(2026, 8, 1), D(2026, 9, 23)))

    def test_decades_split_on_years_ending_in_zero(self):
        p = C.plan_windows("1d", D(2000, 1, 1), D(2026, 9, 23))
        assert [(w.from_date.year, w.to_date.year) for w in p.windows] == [
            (2000, 2009), (2010, 2019), (2020, 2026)]

    def test_range_before_availability_is_reported_not_requested(self):
        p = C.plan_windows("5m", D(2021, 11, 15), D(2022, 1, 10))
        assert p.unavailable == C.Window(D(2021, 11, 15), D(2021, 12, 31))
        assert p.windows == (C.Window(D(2022, 1, 1), D(2022, 1, 10)),)

    def test_wholly_unavailable_range(self):
        p = C.plan_windows("1d", D(1995, 1, 1), D(1999, 12, 31))
        assert p.windows == () and p.unavailable == C.Window(D(1995, 1, 1), D(1999, 12, 31))

    @pytest.mark.parametrize("tf", C.M4_TIMEFRAMES)
    def test_windows_are_contiguous_and_cover_the_range(self, tf):
        rnd = random.Random(tf)
        for _ in range(200):
            a = D(2000, 1, 1) + _dt.timedelta(days=rnd.randrange(9700))
            b = a + _dt.timedelta(days=rnd.randrange(900))
            p = C.plan_windows(tf, a, b)
            ws = p.windows
            covered_from = p.unavailable.from_date if p.unavailable else ws[0].from_date
            assert covered_from == a and (ws[-1].to_date if ws else p.unavailable.to_date) == b
            for x, y in itertools.pairwise(ws):
                assert y.from_date == x.to_date + _dt.timedelta(days=1)
            assert C.plan_windows(tf, a, b) == p          # deterministic

    def test_reversed_range_is_refused(self):
        with pytest.raises(ValueError):
            C.plan_windows("1m", D(2026, 9, 2), D(2026, 9, 1))

    def test_unsupported_timeframe_is_refused(self):
        with pytest.raises(ValueError):
            C.request_limit("7m")


class TestCompleteness:
    def test_1m_states_around_its_end(self):
        s = ist(2026, 9, 23, 14, 33)          # ends 14:34:00
        assert C.intraday_state(s, "1m", ist(2026, 9, 23, 14, 33, 30)) is C.BarState.FORMING
        assert C.intraday_state(s, "1m", ist(2026, 9, 23, 14, 34, 36)) is C.BarState.SETTLING
        assert C.intraday_state(s, "1m", ist(2026, 9, 23, 14, 36, 0)) is C.BarState.COMPLETE

    def test_the_5m_bar_that_changed_31s_after_its_end_is_not_complete(self):
        s = ist(2026, 9, 23, 15, 0)           # ends 15:05:00; seen changing at +30.9 s
        assert C.intraday_state(s, "5m", ist(2026, 9, 23, 15, 5, 31)) is C.BarState.SETTLING

    def test_a_forming_1h_bar_is_never_complete(self):
        """Seen 14:23 IST: the 14:15 1h bar held only 14:15-14:21 of data."""
        assert C.intraday_state(ist(2026, 9, 23, 14, 15), "1h",
                                ist(2026, 9, 23, 14, 23)) is C.BarState.FORMING

    def test_daily_same_day_is_forming_next_day_is_complete(self):
        assert C.daily_state(D(2026, 9, 23), ist(2026, 9, 23, 17, 30)) is C.BarState.FORMING
        assert C.daily_state(D(2026, 9, 23), ist(2026, 9, 23, 23, 59)) is C.BarState.FORMING
        assert C.daily_state(D(2026, 9, 23), ist(2026, 9, 24, 0, 1)) is C.BarState.COMPLETE

    def test_daily_uses_the_ist_date_not_utc(self):
        # 2026-09-23 20:00 UTC is already 2026-09-24 01:30 IST
        fetched = _dt.datetime(2026, 9, 23, 20, 0, tzinfo=UTC)
        assert C.daily_state(D(2026, 9, 23), fetched) is C.BarState.COMPLETE

    def test_margin_is_marked_unverified(self):
        assert C.COMPLETION_MARGIN == _dt.timedelta(seconds=120)
        assert "UNVERIFIED" in C.COMPLETION_MARGIN_BASIS
        assert "UNVERIFIED" in C.DAILY_COMPLETION_BASIS

    def test_daily_has_no_fixed_width(self):
        with pytest.raises(ValueError):
            C.bar_width("1d")


class TestTimestamps:
    def test_daily_label_is_a_date_not_an_instant(self):
        raw = "2026-09-22T00:00:00+05:30"
        assert C.daily_session_date(raw) == D(2026, 9, 22)    # not 2026-09-21 (UTC)

    def test_listing_day_label_with_a_time(self):
        assert C.daily_session_date("2018-07-18T09:45:00+05:30") == D(2018, 7, 18)

    def test_a_utc_labelled_daily_maps_to_its_ist_date(self):
        assert C.daily_session_date("2026-09-21T18:30:00+00:00") == D(2026, 9, 22)

    def test_d4_key_is_ist_midnight(self):
        assert C.daily_bar_start(D(2026, 9, 22)) == _dt.datetime(2026, 9, 21, 18, 30,
                                                                tzinfo=UTC)
        assert "D4" in C.D4_DAILY_KEY_BASIS

    def test_intraday_start_and_session(self):
        start, day = C.intraday_bar_start("2026-09-23T09:15:00+05:30")
        assert start == _dt.datetime(2026, 9, 23, 3, 45, tzinfo=UTC) and day == D(2026, 9, 23)

    @pytest.mark.parametrize("raw", ["2026-09-22T00:00:00", "22/09/2026", "", None])
    def test_bad_labels_are_refused(self, raw):
        with pytest.raises(C.CandleTimestampError):
            C.daily_session_date(raw)

    @pytest.mark.parametrize("hh, mm, tf, ok", [
        (10, 15, "1h", True), (10, 0, "1h", False), (9, 20, "5m", True),
        (9, 22, "5m", False), (9, 30, "15m", True), (9, 16, "1m", True), (9, 14, "1m", False)])
    def test_alignment_to_the_regular_session(self, hh, mm, tf, ok):
        assert C.aligned(ist(2026, 9, 23, hh, mm), tf, T(9, 15)) is ok

    def test_alignment_follows_the_session_open_not_0915(self):
        """Muhurat opens 18:00: its 1h bar at 19:00 is on-grid for that
        session, and would be off-grid if 09:15 were assumed."""
        assert C.aligned(ist(2026, 11, 8, 19, 0), "1h", T(18, 0))
        assert not C.aligned(ist(2026, 11, 8, 19, 0), "1h", T(9, 15))


class TestKnowableReuse:
    def test_complete_intraday_bar_is_knowable_at_fetch_unverified(self):
        s, f = ist(2026, 9, 22, 15, 25), ist(2026, 9, 23, 10, 0)
        assert C.intraday_state(s, "5m", f) is C.BarState.COMPLETE
        k = for_intraday_bar(s, "5m", f)
        assert k.at == f and k.verified is False

    def test_complete_daily_bar_is_knowable_at_fetch_not_at_its_label(self):
        f = ist(2026, 9, 23, 10, 0)
        k = for_daily_bar(D(2026, 9, 22), f)
        assert k.at == f and k.at > C.daily_bar_start(D(2026, 9, 22)) and not k.verified


class TestCoverage:
    W = C.Window(D(2026, 8, 1), D(2026, 8, 31))

    def test_data_record_adds_up(self):
        r = C.CoverageRecord("NSE_EQ|X", "1m", self.W, C.WindowOutcome.DATA, returned=10,
                             complete=8, forming=1, settling=1)
        assert r.returned == 10

    def test_counts_that_do_not_add_up_are_refused(self):
        with pytest.raises(ValueError):
            C.CoverageRecord("NSE_EQ|X", "1m", self.W, C.WindowOutcome.DATA, returned=10,
                             complete=8)

    def test_empty_means_zero_candles(self):
        C.CoverageRecord("NSE_EQ|X", "1d", self.W, C.WindowOutcome.EMPTY)
        with pytest.raises(ValueError):
            C.CoverageRecord("NSE_EQ|X", "1d", self.W, C.WindowOutcome.EMPTY, returned=1,
                             complete=1)

    def test_vendor_error_carries_its_code(self):
        C.CoverageRecord("NSE_EQ|X", "1m", self.W, C.WindowOutcome.VENDOR_ERROR,
                         vendor_error_code="UDAPI1148")
        with pytest.raises(ValueError):
            C.CoverageRecord("NSE_EQ|X", "1m", self.W, C.WindowOutcome.VENDOR_ERROR)
        with pytest.raises(ValueError):
            C.CoverageRecord("NSE_EQ|X", "1m", self.W, C.WindowOutcome.EMPTY,
                             vendor_error_code="UDAPI1148")

    def test_every_outcome_is_named(self):
        assert {o.value for o in C.WindowOutcome} == {
            "DATA", "EMPTY", "BEFORE_AVAILABILITY", "VENDOR_ERROR", "NOT_ATTEMPTED"}


class TestIdentity:
    def test_same_values_in_different_types_are_the_same_observation(self):
        a = {"open": 1247.6, "high": 1251.9, "low": 1237.4, "close": 1240.4,
             "volume": 10684376, "open_interest": 0}
        from decimal import Decimal
        b = {"open": Decimal("1247.6000"), "high": Decimal("1251.9"), "low": Decimal("1237.40"),
             "close": Decimal("1240.4"), "volume": Decimal("10684376"),
             "open_interest": Decimal("0")}
        assert C.same_observation(a, b)

    def test_any_value_difference_is_a_conflict(self):
        a = {"open": 1, "high": 2, "low": 1, "close": 2, "volume": 10, "open_interest": 0}
        for f in C.BAR_VALUE_FIELDS:
            b = dict(a, **{f: (a[f] or 0) + 1})
            assert not C.same_observation(a, b), f

    def test_watermark_stream_fits_every_loaded_key(self):
        assert C.watermark_stream("1m", "NSE_EQ|INE002A01018") == "ohlcv.1m.NSE_EQ|INE002A01018"
        assert len(C.watermark_stream("15m", "NSE_INDEX|India VIX")) <= C.STREAM_MAX
        with pytest.raises(ValueError):
            C.watermark_stream("15m", "NSE_EQ|" + "X" * 60)
        with pytest.raises(ValueError):
            C.watermark_stream("7m", "NSE_EQ|X")
