"""Frame -> rows. Pure, deterministic, and loud about anything it cannot keep."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.parsers.upstox_feed_v3 import FrameDecodeError, parse_frame
from app.vendor.upstox.proto import MarketDataFeed_pb2 as pb
from tests.support.upstox_frames import (
    NIFTYBEES,
    RELIANCE,
    SESSION,
    frame,
    ist,
    market_ff,
    status_frame,
    varint,
)

AT = ist(9, 7, 30, 250)
FETCHED = AT + _dt.timedelta(milliseconds=40)


def _parse(data, *, fetched=FETCHED, session=SESSION, seq=7):
    return parse_frame(data, frame_seq=seq, fetched_at=fetched, session_date=session)


def _kinds(pf):
    return {(i.severity, i.kind) for i in pf.issues}


class TestMarketFullFeed:
    def test_protobuf_fields_map_to_columns(self):
        pf = _parse(frame({RELIANCE: market_ff()}, AT))
        assert pf.issues == [] and pf.feed_type == "live_feed"
        (t,) = pf.ticks
        assert t.instrument_key == RELIANCE and t.session_date == SESSION
        assert t.frame_seq == 7 and t.vendor_ts == AT and t.request_mode == "full_d5"
        assert (t.iep, t.ieq, t.iiq_total, t.iiq_m) == (Decimal("2458.1"), 12000, 3400, 150)
        assert (t.rp, t.tbq, t.tsq, t.cas_eligible) == (
            Decimal("2440.0"), Decimal("150000.0"), Decimal("120000.0"), True)
        assert t.ltp == Decimal("2440.0") and t.ltpc_iep == Decimal("2458.1")

    def test_book_rungs_pair_bid_and_ask(self):
        (t,) = _parse(frame({RELIANCE: market_ff(rungs=5)}, AT)).ticks
        assert [b.rung_no for b in t.book] == [0, 1, 2, 3, 4]
        top = t.book[0]
        assert (top.bid_qty, top.bid_price, top.ask_qty, top.ask_price) == (
            100, Decimal("2458.05"), 90, Decimal("2458.15"))

    def test_full_d30_mode_is_read_from_the_wire(self):
        (t,) = _parse(frame({RELIANCE: market_ff(rungs=30, mode=pb.full_d30)}, AT)).ticks
        assert t.request_mode == "full_d30" and len(t.book) == 30

    def test_knowable_at_is_vendor_time_and_verified(self):
        (t,) = _parse(frame({RELIANCE: market_ff()}, AT)).ticks
        p = t.provenance
        assert p.knowable_at == AT and p.knowable_at_verified is True
        assert p.fetched_at == FETCHED and p.knowable_at <= p.fetched_at
        assert p.source == "UPSTOX_WS_V3" and len(p.payload_sha256) == 64


class TestPresenceSemantics:
    def test_ltpc_iep_absent_is_null_but_zero_is_zero(self):
        absent = _parse(frame({RELIANCE: market_ff(ltpc_iep=None)}, AT)).ticks[0]
        zero = _parse(frame({RELIANCE: market_ff(ltpc_iep=0.0)}, AT)).ticks[0]
        assert absent.ltpc_iep is None
        assert zero.ltpc_iep == Decimal("0.0")

    def test_ltt_zero_is_no_trade_time_not_1970(self):
        (t,) = _parse(frame({RELIANCE: market_ff(ltt=None)}, AT)).ticks
        assert t.ltt is None
        (t2,) = _parse(frame({RELIANCE: market_ff(ltt=ist(9, 5))}, AT)).ticks
        assert t2.ltt == ist(9, 5)


class TestDeterminism:
    def test_same_bytes_same_rows(self):
        data = frame({RELIANCE: market_ff(), NIFTYBEES: market_ff(iep=285.4)}, AT)
        assert _parse(data).ticks == _parse(data).ticks

    def test_rows_are_ordered_by_instrument_key(self):
        a = frame({RELIANCE: market_ff(), NIFTYBEES: market_ff()}, AT)
        b = frame({NIFTYBEES: market_ff(), RELIANCE: market_ff()}, AT)
        keys = [t.instrument_key for t in _parse(a).ticks]
        assert keys == sorted(keys) == [t.instrument_key for t in _parse(b).ticks]

    def test_isin_prefix_does_not_filter(self):
        """Finding 1: an INF-ISIN ETF is a row like any other."""
        pf = _parse(frame({NIFTYBEES: market_ff(iep=285.4)}, AT))
        assert [t.instrument_key for t in pf.ticks] == [NIFTYBEES]


class TestFailsLoud:
    def test_undecodable_bytes_raise(self):
        with pytest.raises(FrameDecodeError):
            _parse(b"\xff\xff\xff")

    def test_unknown_field_is_schema_drift(self):
        f = market_ff()
        raw = f.fullFeed.marketFF.SerializeToString() + varint(17 << 3) + varint(5)
        f.fullFeed.marketFF.Clear()
        f.fullFeed.marketFF.MergeFromString(raw)
        pf = _parse(frame({RELIANCE: f}, AT))
        drift = [i for i in pf.issues if i.kind is AnomalyKind.SCHEMA_DRIFT]
        assert drift and drift[0].severity is AnomalySeverity.FAIL
        assert any("marketFF#17" in u for u in drift[0].detail["unknown"])

    def test_unknown_request_mode_is_drift_and_named(self):
        f = pb.Feed.FromString(market_ff().SerializeToString() + varint(4 << 3) + varint(9))
        pf = _parse(frame({RELIANCE: f}, AT))
        assert (AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT) in _kinds(pf)
        assert pf.ticks[0].request_mode == "UNKNOWN_9"

    def test_frame_from_another_session_is_rejected(self):
        pf = _parse(frame({RELIANCE: market_ff()}, ist(9, 7, day=_dt.date(2026, 9, 23))))
        assert (AnomalySeverity.FAIL, AnomalyKind.SESSION_MISMATCH) in _kinds(pf)
        assert pf.ticks == []

    def test_vendor_clock_ahead_never_overclaims(self):
        early_fetch = AT - _dt.timedelta(milliseconds=500)
        pf = _parse(frame({RELIANCE: market_ff()}, AT), fetched=early_fetch)
        (t,) = pf.ticks
        assert t.provenance.knowable_at == early_fetch
        assert t.provenance.knowable_at_verified is False
        assert (AnomalySeverity.WARN, AnomalyKind.CLOCK_SKEW) in _kinds(pf)

    def test_book_deeper_than_schema_fails(self):
        pf = _parse(frame({RELIANCE: market_ff(rungs=31)}, AT))
        assert (AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT) in _kinds(pf)

    def test_non_finite_price_fails(self):
        pf = _parse(frame({RELIANCE: market_ff(iep=float("nan"))}, AT))
        assert (AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT) in _kinds(pf)
        assert pf.ticks[0].iep is None

    def test_precision_beyond_column_scale_is_reported(self):
        pf = _parse(frame({RELIANCE: market_ff(iep=2458.123456)}, AT))
        rej = [i for i in pf.issues if i.kind is AnomalyKind.PARSE_REJECT]
        assert rej and rej[0].severity is AnomalySeverity.WARN and rej[0].detail["field"] == "iep"

    def test_unmodelled_feed_kind_is_reported_not_dropped(self):
        f = pb.Feed(requestMode=pb.option_greeks)
        f.firstLevelWithGreeks.ltpc.ltp = 1.0
        pf = _parse(frame({RELIANCE: f}, AT))
        assert pf.ticks == []
        assert pf.issues[0].subject == RELIANCE and pf.issues[0].severity is AnomalySeverity.WARN


class TestOtherFeedsAndStatus:
    def test_ltpc_only_feed_keeps_its_fields(self):
        f = pb.Feed(requestMode=pb.ltpc)
        f.ltpc.ltp, f.ltpc.cp = 101.5, 100.0
        (t,) = _parse(frame({RELIANCE: f}, AT)).ticks
        assert t.request_mode == "ltpc" and t.ltp == Decimal("101.5") and t.iep is None

    def test_preopen_status_keeps_vendor_strings(self):
        """PRE_OPEN_M_END is not in the MarketStatus enum; it must survive."""
        when = ist(9, 7, 0)
        pf = _parse(status_frame(AT, {"NSE_EQ": ("PRE_OPEN_M_END", when)},
                                 segment_status={"NSE_EQ": pb.PRE_OPEN_START}))
        assert pf.feed_type == "market_info" and pf.ticks == [] and pf.issues == []
        (s,) = pf.statuses
        assert (s.segment, s.status, s.vendor_updated_at) == ("NSE_EQ", "PRE_OPEN_M_END", when)
        assert s.provenance.knowable_at == when and s.provenance.knowable_at_verified
        assert pf.segment_status == {"NSE_EQ": "PRE_OPEN_START"}
