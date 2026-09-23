"""FII/DII parser on the REAL 2026-09-23 Upstox responses, plus mutations."""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
from decimal import Decimal

import pytest

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.clock import IST
from app.parsers import upstox_institutional as P

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_institutional"
MAN = {m["file"][:-5]: m for m in json.loads((FIX / "manifest.json").read_text())}
FETCHED = _dt.datetime(2026, 9, 23, 19, 15, tzinfo=IST)
DRIFT = (AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT)
REJECT = (AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT)
CASH = "NSE_EQ|CASH"


def _parse(name, data=None, *, side=None, types=None, fetched=FETCHED, status=200):
    m = MAN[name]
    return P.parse_institutional(
        data if data is not None else (FIX / m["file"]).read_bytes(), http_status=status,
        side=side or m["side"], interval="1D", data_types=tuple(types or m["data_types"]),
        fetched_at=fetched)


def _mutate(name, fn) -> bytes:
    b = json.loads((FIX / MAN[name]["file"]).read_bytes())
    fn(b)
    return json.dumps(b).encode()


def _kinds(p):
    return {(i.severity, i.kind) for i in p.issues}


class TestRealResponses:
    def test_manifest_hashes_match_the_bytes(self):
        import hashlib
        for m in MAN.values():
            assert hashlib.sha256((FIX / m["file"]).read_bytes()).hexdigest() == m["sha256"]

    def test_fii_cash_latest(self):
        p = _parse("fii_cash_latest")
        assert not p.issues
        ps = p.series["NSE_EQ|CASH"]
        assert len(ps.dates) == 30
        assert ps.dates == sorted(ps.dates)                       # oldest first
        assert (ps.dates[0], ps.dates[-1]) == (_dt.date(2026, 8, 11), _dt.date(2026, 9, 22))
        assert len(ps.rows) == 60                                  # buy + sell only
        codes = {r.series_code for r in ps.rows}
        assert codes == {"FII|NSE_EQ|CASH|1D|buy_amt", "FII|NSE_EQ|CASH|1D|sell_amt"}
        last = [r for r in ps.rows if r.observation_date == _dt.date(2026, 9, 22)]
        assert {r.series_code.split("|")[-1]: r.value for r in last} == {
            "buy_amt": Decimal("9845.81"), "sell_amt": Decimal("13655.8")}
        assert all(r.unit == "INR_vendor" for r in ps.rows)

    def test_values_are_exact_decimals_and_payload_is_verbatim(self):
        p = _parse("fii_cash_latest")
        r = p.rows[-1]
        assert isinstance(r.value, Decimal)
        raw = json.loads((FIX / "fii_cash_latest.json").read_bytes())["data"]["NSE_EQ|CASH"][0]
        assert r.vendor_payload["time_stamp"] == raw["time_stamp"]
        assert Decimal(r.vendor_payload["buy_amount"]) == Decimal(str(raw["buy_amount"]))

    def test_knowable_is_fetched_at_and_unverified(self):
        for r in _parse("fii_cash_latest").rows:
            assert r.knowable.at == FETCHED
            assert r.knowable.verified is False
            assert "no announcement time" in r.knowable.basis
            assert len(r.knowable.basis) <= 200

    @pytest.mark.parametrize("name,dtype,n_fields", [
        ("fii_fo_latest", "NSE_FO|INDEX_FUTURES", 8),
        ("fii_fo_latest", "NSE_FO|INDEX_OPTIONS", 10),
        ("fii_stock_fo_latest", "NSE_FO|STOCK_FUTURES", 8),
        ("fii_stock_fo_latest", "NSE_FO|STOCK_OPTIONS", 10),
        ("dii_cash_latest", "NSE_EQ|CASH", 2),
    ])
    def test_every_real_series_parses_to_its_applicable_fields(self, name, dtype, n_fields):
        p = _parse(name)
        assert not p.issues
        ps = p.series[dtype]
        assert len(ps.dates) == 30
        assert len(ps.rows) == 30 * n_fields

    def test_from_is_the_window_end(self):
        ps = _parse("fii_cash_to_2026-06-15").series["NSE_EQ|CASH"]
        assert (ps.dates[0], ps.dates[-1]) == (_dt.date(2026, 5, 4), _dt.date(2026, 6, 15))
        assert _parse("fii_cash_to_2026-04-01").series["NSE_EQ|CASH"].dates == [P.DATA_START]

    def test_before_availability_is_an_empty_list_not_an_error(self):
        p = _parse("fii_cash_to_2026-03-02_empty")
        assert not p.issues and p.series["NSE_EQ|CASH"].dates == []

    def test_every_series_code_fits_the_column(self):
        for side, types in P.DATA_TYPES.items():
            for t in types:
                for f in P.APPLICABLE[t]:
                    assert len(P.series_code(side, t, "1D", f)) <= 48


class TestContractBreaches:
    def test_unknown_record_field_is_schema_drift(self):
        d = _mutate("fii_cash_latest", lambda b: b["data"][CASH][0].update(net=1))
        p = _parse("fii_cash_latest", d)
        assert DRIFT in _kinds(p)
        assert _dt.date(2026, 9, 22) not in p.series["NSE_EQ|CASH"].dates

    def test_missing_record_field_is_schema_drift(self):
        d = _mutate("fii_cash_latest", lambda b: b["data"][CASH][0].pop("sell_amount"))
        assert DRIFT in _kinds(_parse("fii_cash_latest", d))

    def test_missing_data_type_is_schema_drift(self):
        p = _parse("fii_cash_latest", types=["NSE_EQ|CASH", "NSE_FO|INDEX_FUTURES"])
        assert DRIFT in _kinds(p)

    def test_extra_envelope_key_is_schema_drift(self):
        d = _mutate("fii_cash_latest", lambda b: b.update(meta={}))
        assert DRIFT in _kinds(_parse("fii_cash_latest", d))

    def test_label_off_midnight_is_schema_drift(self):
        d = _mutate("fii_cash_latest",
                    lambda b: b["data"][CASH][0].update(time_stamp=1790015400000 + 60_000))
        assert DRIFT in _kinds(_parse("fii_cash_latest", d))

    def test_nonzero_in_a_not_applicable_field_is_schema_drift(self):
        d = _mutate("fii_cash_latest",
                    lambda b: b["data"][CASH][0].update(buy_contracts=5))
        p = _parse("fii_cash_latest", d)
        assert DRIFT in _kinds(p)

    @pytest.mark.parametrize("bad", ["12.5", None, True, 1.2345678])
    def test_unstorable_number_is_rejected(self, bad):
        d = _mutate("fii_cash_latest", lambda b: b["data"][CASH][0].update(buy_amount=bad))
        p = _parse("fii_cash_latest", d)
        assert REJECT in _kinds(p)
        assert len(p.series["NSE_EQ|CASH"].dates) == 29

    def test_duplicate_date_is_rejected(self):
        def dup(b):
            b["data"]["NSE_EQ|CASH"].insert(1, dict(b["data"]["NSE_EQ|CASH"][0]))
        p = _parse("fii_cash_latest", _mutate("fii_cash_latest", dup))
        assert REJECT in _kinds(p)

    def test_date_after_the_fetch_is_rejected(self):
        p = _parse("fii_cash_latest", fetched=_dt.datetime(2026, 9, 21, 12, tzinfo=IST))
        assert REJECT in _kinds(p)

    def test_non_200_and_non_json_raise(self):
        with pytest.raises(P.InstitutionalDecodeError):
            _parse("fii_cash_latest", status=401)
        with pytest.raises(P.InstitutionalDecodeError):
            _parse("fii_cash_latest", b"<html>")
        with pytest.raises(P.InstitutionalDecodeError):
            _parse("fii_cash_latest", b'{"status":"error","errors":[]}')


class TestRequestPath:
    def test_path(self):
        assert P.request_path("FII", ("NSE_EQ|CASH",), "1D", _dt.date(2026, 6, 15)) == \
            "/v2/market/fii?data_type=NSE_EQ|CASH&interval=1D&from=2026-06-15"
        assert P.request_path("DII", ("NSE_EQ|CASH",), "1D", None) == \
            "/v2/market/dii?data_type=NSE_EQ|CASH&interval=1D"

    @pytest.mark.parametrize("side,types,interval", [
        ("DII", ("NSE_FO|INDEX_FUTURES",), "1D"),     # DII has cash only
        ("FII", ("NSE_EQ|CASH",), "1M"),              # 1M semantics unmeasured
        ("FPI", ("NSE_EQ|CASH",), "1D"),
        ("FII", (), "1D"),
    ])
    def test_unsupported_requests_are_refused(self, side, types, interval):
        with pytest.raises(ValueError):
            P.request_path(side, types, interval, None)
