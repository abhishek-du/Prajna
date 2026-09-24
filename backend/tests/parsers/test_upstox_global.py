"""Global instruments: the file parser and the global daily-bar completion rule,
on REAL Upstox responses (2026-09-24)."""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import json
import pathlib

import pytest

from app.contracts import candles as C
from app.core.clock import IST
from app.ingest.global_instruments import GlobalMasterError, parse_global
from app.parsers.upstox_candles import Endpoint, parse_candles

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_global"
MAN = {m["file"]: m for m in json.loads((FIX / "manifest.json").read_text())}
D = _dt.date


def test_fixture_hashes():
    for f, m in MAN.items():
        assert hashlib.sha256((FIX / f).read_bytes()).hexdigest() == m["sha256"]


def test_global_file_has_the_13_measured_instruments():
    rows = parse_global((FIX / "global.json.gz").read_bytes())
    keys = {r["instrument_key"] for r in rows}
    assert len(rows) == 13
    assert {"GLOBAL_INDEX|^GSPC", "GLOBAL_INDEX|^DJI", "GLOBAL_INDICATOR|USDINR",
            "GLOBAL_INDICATOR|BZUSD", "GLOBAL_INDEX|SGX NIFTY"} <= keys
    assert all(r["exchange"] == "GLOBAL" for r in rows)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(bond_yield=1),                     # an unmeasured field
    lambda r: r.update(segment="NSE_EQ"),                 # not a global segment
    lambda r: r.update(instrument_key="NSE_EQ|X"),        # key not under its segment
])
def test_global_file_contract_breaches_fail(mutate):
    rows = json.loads(gzip.decompress((FIX / "global.json.gz").read_bytes()))
    mutate(rows[0])
    with pytest.raises(GlobalMasterError):
        parse_global(gzip.compress(json.dumps(rows).encode()))


@pytest.mark.parametrize("fetched,state", [
    ("2026-09-24T00:30", C.BarState.FORMING),     # US session of 09-23 still open
    ("2026-09-24T03:00", C.BarState.FORMING),
    ("2026-09-24T11:59", C.BarState.FORMING),
    ("2026-09-24T12:00", C.BarState.COMPLETE),
])
def test_global_daily_bar_completion(fetched, state):
    f = _dt.datetime.fromisoformat(fetched).replace(tzinfo=IST)
    assert C.daily_state(D(2026, 9, 23), f, "GLOBAL_INDEX") is state
    assert C.daily_state(D(2026, 9, 23), f, "NSE_EQ") is C.BarState.COMPLETE


def _parse(name, key, fetched):
    return parse_candles((FIX / f"{name}.json").read_bytes(), http_status=200,
                         endpoint=Endpoint.HISTORICAL, instrument_key=key, timeframe="1d",
                         fetched_at=fetched, window=C.Window(D(2020, 1, 1), D(2026, 9, 23)))


def test_dow_bar_of_d_is_not_persistable_before_d_plus_1_noon():
    early = _dt.datetime(2026, 9, 24, 1, 0, tzinfo=IST)
    pc = _parse("hist_1d_DJI_2020_2026-09-23", "GLOBAL_INDEX|^DJI", early)
    last = [r for r in pc.rows if r.session_date == D(2026, 9, 23)]
    assert last and last[0].state is C.BarState.FORMING
    assert D(2026, 9, 23) not in {r.session_date for r in pc.complete}
    later = _parse("hist_1d_DJI_2020_2026-09-23", "GLOBAL_INDEX|^DJI",
                   _dt.datetime(2026, 9, 24, 13, 0, tzinfo=IST))
    assert D(2026, 9, 23) in {r.session_date for r in later.complete}
    # Vendor data defect, measured 2026-09-24: 15 of 1,653 Dow bars have an open
    # (or close) outside [low, high]. They are INVALID and fail the window; the
    # contract is not loosened for globals (decision pending, see acceptance doc).
    assert later.coverage.invalid == 15 and len(later.complete) == 1638
    assert all(i.kind.value == "PARSE_REJECT" for i in later.issues)


def test_usdinr_history_zero_volume_and_invalid_bars():
    pc = _parse("hist_1d_USDINR_2020_2026-09-23", "GLOBAL_INDICATOR|USDINR",
                _dt.datetime(2026, 9, 24, 13, 0, tzinfo=IST))
    assert pc.complete[0].session_date == D(2020, 4, 3)
    assert all(r.volume == 0 for r in pc.complete)        # indicators carry no volume
    assert pc.coverage.invalid == 85                      # 76 with open 83.214 in 2023


def test_nikkei_flat_bar_on_a_japanese_holiday_is_kept_as_sent():
    pc = _parse("hist_1d_N225_2020_2026-09-23", "GLOBAL_INDEX|^N225",
                _dt.datetime(2026, 9, 24, 13, 0, tzinfo=IST))
    last = pc.complete[-1]
    assert last.session_date == D(2026, 9, 23)            # Autumnal Equinox Day, Japan
    assert last.open == last.high == last.low == last.close
