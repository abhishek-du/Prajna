"""Candle parser on the REAL 2026-09-23 Upstox responses, plus the ways a
response can be wrong."""

from __future__ import annotations

import datetime as _dt
import itertools
import json
import pathlib
from decimal import Decimal
from typing import ClassVar

import pytest

from app.contracts import candles as C
from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.clock import IST, UTC
from app.parsers.upstox_candles import CandleDecodeError, Endpoint, parse_candles

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_candles"
MANIFEST = {m["file"]: m for m in json.loads((FIX / "manifest.json").read_text())}
D, T = _dt.date, _dt.time


def _parse(name, *, data=None, fetched_at=None, status=None, window="manifest", **kw):
    m = MANIFEST[f"{name}.json"]
    ep = Endpoint(m["endpoint"])
    if window == "manifest":
        window = (C.Window(D.fromisoformat(m["from"]), D.fromisoformat(m["to"]))
                  if ep is Endpoint.HISTORICAL else None)
    return parse_candles(
        data if data is not None else (FIX / m["file"]).read_bytes(),
        http_status=status if status is not None else m["http_status"], endpoint=ep,
        instrument_key=m["instrument_key"], timeframe=m["timeframe"],
        fetched_at=fetched_at or _dt.datetime.fromisoformat(m["fetched_at"]),
        window=window, payload_sha256=m["sha256"], **kw)


def _mutate(name, fn) -> bytes:
    body = json.loads((FIX / f"{name}.json").read_bytes())
    fn(body)
    return json.dumps(body).encode()


def _fails(pc, kind=AnomalyKind.PARSE_REJECT):
    return [i for i in pc.issues if i.severity is AnomalySeverity.FAIL and i.kind is kind]


# ── every real response ────────────────────────────────────────────────────
# (fixture, outcome, returned, complete, forming, settling, vendor code)
EXPECTED = [
    ("hist_1d_2000s", "DATA", 2496, 2496, 0, 0, None),
    ("hist_1d_2026-09-08_22", "DATA", 10, 10, 0, 0, None),
    ("hist_1d_sme_listing_label", "DATA", 594, 594, 0, 0, None),
    ("hist_5m_2026-09-22", "DATA", 75, 75, 0, 0, None),
    ("hist_1m_sme_sparse", "DATA", 1719, 1719, 0, 0, None),
    ("empty_200", "EMPTY", 0, 0, 0, 0, None),
    ("err_400_udapi1148", "VENDOR_ERROR", 0, 0, 0, 0, "UDAPI1148"),
    ("err_400_udapi100011", "VENDOR_ERROR", 0, 0, 0, 0, "UDAPI100011"),
    ("intraday_1m_1500", "DATA", 344, 343, 0, 1, None),
    ("intraday_5m_1500", "DATA", 69, 68, 0, 1, None),
    ("intraday_15m_1500", "DATA", 23, 22, 0, 1, None),
    ("intraday_1h_1500", "DATA", 6, 5, 1, 0, None),
    ("intraday_1d_1500", "DATA", 1, 0, 1, 0, None),
]


@pytest.mark.parametrize("name, outcome, ret, comp, form, settl, code", EXPECTED)
def test_every_real_response(name, outcome, ret, comp, form, settl, code):
    pc = _parse(name)
    cv = pc.coverage
    assert (cv.outcome.value, cv.returned, cv.complete, cv.forming, cv.settling, cv.invalid,
            cv.vendor_error_code) == (outcome, ret, comp, form, settl, 0, code)
    assert pc.issues == [] and len(pc.rows) == ret
    assert cv.payload_sha256 == MANIFEST[f"{name}.json"]["sha256"]


def test_fixtures_are_byte_identical_to_the_archive():
    import hashlib
    for m in MANIFEST.values():
        assert hashlib.sha256((FIX / m["file"]).read_bytes()).hexdigest() == m["sha256"]


def test_rows_come_out_oldest_first():
    rows = _parse("hist_1d_2000s").rows
    assert rows[0].session_date == D(2000, 1, 3) and rows[-1].session_date == D(2009, 12, 31)
    assert all(a.bar_start_utc < b.bar_start_utc for a, b in itertools.pairwise(rows))


# ── daily ──────────────────────────────────────────────────────────────────
class TestDaily:
    def test_label_is_a_session_date_and_the_key_is_ist_midnight(self):
        r = _parse("hist_1d_2026-09-08_22").rows[-1]
        assert r.session_date == D(2026, 9, 22) and r.vendor_ts_raw == "2026-09-22T00:00:00+05:30"
        assert r.bar_start_utc == _dt.datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
        assert (r.open, r.high, r.low, r.close, r.volume) == (
            Decimal("1247.6"), Decimal("1251.9"), Decimal("1237.4"), Decimal("1240.4"),
            Decimal(10684376))

    def test_sme_labels_with_a_time_keep_their_date_and_raw_string(self):
        rows = _parse("hist_1d_sme_listing_label").rows
        timed = [r for r in rows if not r.vendor_ts_raw.endswith("T00:00:00+05:30")]
        assert len(timed) == 44
        first = rows[0]
        assert first.vendor_ts_raw == "2018-07-18T09:45:00+05:30"
        assert first.session_date == D(2018, 7, 18)
        assert first.bar_start_utc == C.daily_bar_start(D(2018, 7, 18))
        assert len({r.bar_start_utc for r in rows}) == len(rows)

    def test_a_same_day_historical_daily_bar_is_forming(self):
        fetched = _dt.datetime(2026, 9, 22, 17, 0, tzinfo=IST)
        pc = _parse("hist_1d_2026-09-08_22", fetched_at=fetched)
        assert pc.rows[-1].state is C.BarState.FORMING and pc.coverage.forming == 1

    def test_the_intraday_daily_bar_is_always_forming(self):
        next_day = _dt.datetime(2026, 9, 24, 9, 0, tzinfo=IST)
        pc = _parse("intraday_1d_1500", fetched_at=next_day,
                    data=(FIX / "intraday_1d_1500.json").read_bytes(), window=None)
        # fetched on another day, the bar is now outside the intraday window as well
        assert pc.rows == [] and _fails(pc)

    def test_knowable_is_the_fetch_not_the_label(self):
        pc = _parse("hist_1d_2026-09-08_22")
        f = _dt.datetime.fromisoformat(MANIFEST["hist_1d_2026-09-08_22.json"]["fetched_at"])
        for r in pc.rows:
            assert r.knowable.at == f and r.knowable.verified is False


# ── intraday ───────────────────────────────────────────────────────────────
class TestIntraday:
    def test_states_at_1500_ist(self):
        last = {tf: _parse(n).rows[-1] for tf, n in (
            ("1m", "intraday_1m_1500"), ("5m", "intraday_5m_1500"),
            ("15m", "intraday_15m_1500"), ("1h", "intraday_1h_1500"))}
        assert last["1m"].bar_start_utc.astimezone(IST).time() == T(14, 58)
        assert last["1m"].state is C.BarState.SETTLING
        assert last["5m"].state is C.BarState.SETTLING      # ended 15:00:00, +31 s
        assert last["15m"].state is C.BarState.SETTLING
        assert last["1h"].state is C.BarState.FORMING       # 14:15 bar runs to 15:15

    def test_grid_check_passes_on_real_data_when_the_open_is_known(self):
        opens = {D(2026, 9, 23): T(9, 15), D(2026, 9, 22): T(9, 15)}
        for n in ("intraday_1m_1500", "intraday_5m_1500", "intraday_15m_1500",
                  "intraday_1h_1500", "hist_5m_2026-09-22"):
            pc = _parse(n, session_opens=opens)
            assert pc.issues == [] and pc.grid_unchecked == 0, n

    def test_sparse_sme_minutes_are_on_the_grid(self):
        opens = {D(2026, 8, d): T(9, 15) for d in range(1, 32)}
        pc = _parse("hist_1m_sme_sparse", session_opens=opens)
        assert pc.issues == [] and len(pc.rows) == 1719

    def test_grid_is_unchecked_without_opens_and_says_so(self):
        assert _parse("intraday_5m_1500").grid_unchecked == 69

    def test_off_grid_bar_fails(self):
        def shift(b):
            b["data"]["candles"][0][0] = "2026-09-23T14:57:00+05:30"   # a 5m bar at :57
        pc = _parse("intraday_5m_1500", data=_mutate("intraday_5m_1500", shift),
                    session_opens={D(2026, 9, 23): T(9, 15)})
        assert pc.coverage.invalid == 1 and "off the session grid" in str(_fails(pc))

    def test_knowable_never_precedes_the_bar_end_or_the_fetch(self):
        pc = _parse("hist_5m_2026-09-22")
        f = _dt.datetime.fromisoformat(MANIFEST["hist_5m_2026-09-22.json"]["fetched_at"])
        for r in pc.rows:
            assert r.knowable.at >= r.bar_start_utc + _dt.timedelta(minutes=5)
            assert r.knowable.at == f and not r.knowable.verified

    def test_offsets_are_honoured(self):
        """18:45 UTC on the 22nd is 00:15 IST on the 23rd."""
        def utc(b):
            b["data"]["candles"] = [["2026-09-22T18:45:00+00:00", 1, 1, 1, 1, 1, 0]]
        pc = _parse("hist_5m_2026-09-22", data=_mutate("hist_5m_2026-09-22", utc),
                    window=C.Window(D(2026, 9, 22), D(2026, 9, 23)))
        assert pc.rows[0].session_date == D(2026, 9, 23)


# ── failures ───────────────────────────────────────────────────────────────
class TestFailsLoud:
    @pytest.mark.parametrize("data", [b"<html>", b"[1, 2]", b'{"status": "error"}',
                                      b'{"status": "success", "data": {"candles": 5}}'])
    def test_not_a_candle_response(self, data):
        with pytest.raises(CandleDecodeError):
            _parse("hist_5m_2026-09-22", data=data)

    def test_unknown_envelope_field_is_schema_drift(self):
        def add(b):
            b["meta"] = {"x": 1}
            b["data"]["next_page"] = None
        pc = _parse("hist_5m_2026-09-22", data=_mutate("hist_5m_2026-09-22", add))
        (drift,) = _fails(pc, AnomalyKind.SCHEMA_DRIFT)
        assert drift.detail["unknown"] == ["meta"] and drift.detail["unknown_in_data"] == [
            "next_page"]

    def test_wrong_candle_width_is_schema_drift(self):
        def widen(b):
            b["data"]["candles"][0].append(99)
        pc = _parse("hist_5m_2026-09-22", data=_mutate("hist_5m_2026-09-22", widen))
        assert _fails(pc, AnomalyKind.SCHEMA_DRIFT) and pc.coverage.invalid == 1
        assert len(pc.rows) == 74

    @pytest.mark.parametrize("i, value, reason", [
        (1, "1247.6", "not a number"), (5, True, "not a number"),
        (5, 10.5, "not an integer"), (1, 1247.61234, "precision"),
        (0, "2026-09-22T09:15:00", "offset"), (0, "yesterday", "ISO")])
    def test_bad_values_are_invalid_and_counted(self, i, value, reason):
        """Structural defects (type, precision, timestamp) FAIL the window."""
        def poke(b):
            b["data"]["candles"][0][i] = value
        pc = _parse("hist_5m_2026-09-22", data=_mutate("hist_5m_2026-09-22", poke))
        assert pc.coverage.invalid == 1 and len(pc.rows) == 74
        assert reason in str(_fails(pc))

    @pytest.mark.parametrize("i, value, reason", [
        (5, -1, "negative volume"), (2, 1.0, "insane OHLC")])
    def test_value_insane_bars_are_quarantined_not_failed(self, i, value, reason):
        """Decision Q1 (user, 2026-09-24): skipped, recorded, window kept."""
        def poke(b):
            b["data"]["candles"][0][i] = value
        pc = _parse("hist_5m_2026-09-22", data=_mutate("hist_5m_2026-09-22", poke))
        assert pc.coverage.quarantined == 1 and pc.coverage.invalid == 0
        assert len(pc.rows) == 74 and not _fails(pc)
        (q,) = [x for x in pc.issues if x.kind is AnomalyKind.QUARANTINED]
        assert reason in q.detail["reason"]

    def test_nan_is_refused(self):
        data = (FIX / "hist_5m_2026-09-22.json").read_bytes().replace(b"1240.4", b"NaN", 1)
        pc = _parse("hist_5m_2026-09-22", data=data)
        assert "non-finite" in str(_fails(pc)) and pc.coverage.invalid == 1

    def test_candle_outside_the_requested_window_fails(self):
        pc = _parse("hist_5m_2026-09-22", window=C.Window(D(2026, 9, 23), D(2026, 9, 23)))
        assert pc.coverage.invalid == 75 and pc.rows == []
        assert "outside the requested window" in str(_fails(pc)[0].detail)

    def test_identical_duplicate_is_one_row_and_a_warning(self):
        def dup(b):
            b["data"]["candles"].append(list(b["data"]["candles"][0]))
        pc = _parse("hist_5m_2026-09-22", data=_mutate("hist_5m_2026-09-22", dup))
        assert len(pc.rows) == 75 and pc.coverage.returned == 75 and not _fails(pc)
        assert [i.kind for i in pc.issues] == [AnomalyKind.DUPLICATE_KEY]

    def test_conflicting_duplicate_drops_both_and_fails(self):
        def dup(b):
            c = list(b["data"]["candles"][0])
            c[5] += 1
            b["data"]["candles"].append(c)
        pc = _parse("hist_5m_2026-09-22", data=_mutate("hist_5m_2026-09-22", dup))
        assert len(pc.rows) == 74 and pc.coverage.invalid == 2
        assert "different values" in str(_fails(pc))

    def test_argument_contract(self):
        with pytest.raises(ValueError):
            _parse("hist_5m_2026-09-22", window=None)
        with pytest.raises(ValueError):
            parse_candles(b"{}", http_status=200, endpoint=Endpoint.INTRADAY,
                          instrument_key="NSE_EQ|X", timeframe="1m",
                          fetched_at=_dt.datetime.now(UTC),
                          window=C.Window(D(2026, 9, 23), D(2026, 9, 23)))
        with pytest.raises(ValueError):
            parse_candles(b"{}", http_status=200, endpoint=Endpoint.INTRADAY,
                          instrument_key="NSE_EQ|X", timeframe="7m",
                          fetched_at=_dt.datetime.now(UTC))

    def test_error_envelope_drift_is_reported(self):
        body = json.loads((FIX / "err_400_udapi1148.json").read_bytes())
        body["hint"] = "new"
        pc = _parse("err_400_udapi1148", data=json.dumps(body).encode())
        assert _fails(pc, AnomalyKind.SCHEMA_DRIFT)
        assert pc.coverage.outcome is C.WindowOutcome.VENDOR_ERROR

    def test_error_without_codes_still_names_the_status(self):
        pc = _parse("err_400_udapi1148", data=b'{"status": "error", "errors": []}', status=503)
        assert pc.coverage.vendor_error_code == "HTTP503"


class TestQ1Quarantine:
    """Decision Q1 (user, 2026-09-24): value-insane vendor bars are quarantined,
    structural defects still fail."""

    def _parse(self, candles, key="NSE_EQ|INE669E01016"):
        import datetime as dt
        import json as js

        from app.contracts.candles import Window
        from app.core.clock import IST
        from app.parsers.upstox_candles import Endpoint, parse_candles
        body = js.dumps({"status": "success", "data": {"candles": candles}}).encode()
        return parse_candles(body, http_status=200, endpoint=Endpoint.HISTORICAL,
                             instrument_key=key, timeframe="1d",
                             fetched_at=dt.datetime(2026, 9, 24, 12, tzinfo=IST),
                             window=Window(dt.date(2020, 1, 1), dt.date(2026, 9, 23)))

    GOOD: ClassVar[list] = ["2024-08-29T00:00:00+05:30", 15.0, 15.5, 14.8, 15.2, 1000, 0]
    NEG_VOL: ClassVar[list] = ["2024-08-30T00:00:00+05:30", 15.2, 15.4, 14.9, 15.0, -81259413, 0]  # IDEA

    def test_negative_volume_is_quarantined_and_the_rest_kept(self):
        pc = self._parse([self.NEG_VOL, self.GOOD])
        assert [r.session_date.isoformat() for r in pc.complete] == ["2024-08-29"]
        (i,) = pc.issues
        assert (i.severity.value, i.kind.value) == ("WARN", "QUARANTINED")
        assert i.detail["session_date"] == "2024-08-30" and "-81259413" in i.detail["reason"]
        assert pc.coverage.quarantined == 1 and pc.coverage.invalid == 0

    def test_open_outside_range_and_zero_open_are_quarantined(self):
        bad1 = ["2024-08-28T00:00:00+05:30", 16.0, 15.5, 14.8, 15.2, 10, 0]
        bad2 = ["2024-08-27T00:00:00+05:30", 0.0, 15.5, 14.8, 15.2, 10, 0]
        pc = self._parse([bad1, bad2, self.GOOD])
        assert pc.coverage.quarantined == 2 and len(pc.complete) == 1
        assert all(i.kind.value == "QUARANTINED" for i in pc.issues)

    def test_negative_open_interest_is_quarantined(self):
        bad = ["2024-08-28T00:00:00+05:30", 15.0, 15.5, 14.8, 15.2, 10, -1]
        assert self._parse([bad]).coverage.quarantined == 1

    def test_structural_defects_still_fail(self):
        frac_vol = ["2024-08-28T00:00:00+05:30", 15.0, 15.5, 14.8, 15.2, 10.5, 0]
        pc = self._parse([frac_vol, self.GOOD])
        assert any(i.severity.value == "FAIL" for i in pc.issues)
        assert pc.coverage.invalid == 1 and pc.coverage.quarantined == 0

    def test_quarantine_is_deterministic(self):
        a, b = self._parse([self.NEG_VOL, self.GOOD]), self._parse([self.NEG_VOL, self.GOOD])
        assert [i.detail for i in a.issues] == [i.detail for i in b.issues]
