"""B1/B2 timing verdicts (ops/measure/analyze_timing.py) under decision TIMING-B2,
and the regression cases A-G of the 2026-09-25 finding.

Timing finality (bar_end + margin) and point-in-time knowledge (the fetch
time) are separate: nothing here may move a knowable_at earlier.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import pathlib

from app.contracts import knowable as K
from app.contracts import timing as T
from app.contracts.revision import classify

SPEC = importlib.util.spec_from_file_location(
    "analyze_timing",
    pathlib.Path(__file__).resolve().parents[2] / "ops" / "measure" / "analyze_timing.py")
AT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AT)
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
UTC = _dt.UTC
KIND = {"1m": "1m", "5m": "5m_intraday", "15m": "15m_intraday", "1h": "1h_intraday"}
WIDTH = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
N = {"1m": 300, "5m": 60, "15m": 20, "1h": 5}


def _session(day: _dt.date, *, tf: str = "1m", revise_first_at: float | None = None,
             key: str = "NSE_INDEX|Nifty 50") -> list[dict]:
    """N bars of `tf`, each first listed 20 s after its end; optionally the first
    bar is seen with a different close `revise_first_at` s after its end."""
    out = []
    for i in range(N[tf]):
        start = (_dt.datetime.combine(day, _dt.time(9, 15), IST)
                 + _dt.timedelta(seconds=i * WIDTH[tf]))
        end = start + _dt.timedelta(seconds=WIDTH[tf])
        bar = [start.isoformat(), 100.0, 101.0, 99.0, 100.5, 10, 0]
        out.append({"kind": KIND[tf], "key": key,
                    "fetched_at": (end + _dt.timedelta(seconds=20)).isoformat(), "newest": [bar]})
        if revise_first_at is not None and i == 0:
            out.append({"kind": KIND[tf], "key": key,
                        "fetched_at": (end + _dt.timedelta(seconds=revise_first_at)).isoformat(),
                        "newest": [[*bar[:4], 100.4, 10, 0]]})
    return out


def _full(day, **kw):
    """a full session (>= 300 measured 1m bars) plus the given timeframe's bars"""
    tf = kw.get("tf", "1m")
    return _session(day, **kw) + ([] if tf == "1m" else _session(day))


def _run(tmp_path, lines):
    p = tmp_path / "candle_timing_x.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines))
    return AT.analyze([str(p)])


D24, D25 = _dt.date(2026, 9, 24), _dt.date(2026, 9, 25)


# ── the unchanged sufficiency rule ──────────────────────────────────────────
def test_agreeing_sessions_below_the_minimum_stay_unverified(tmp_path):
    b2 = _run(tmp_path, _full(D24))["B2"]
    assert b2["status"] == "UNVERIFIED" and b2["sessions_disagreeing"] == {}


def test_three_agreeing_sessions_verify(tmp_path):
    lines = [x for d in (21, 22, 23) for x in _full(_dt.date(2026, 9, d))]
    assert _run(tmp_path, lines)["B2"]["status"] == "VERIFIED"


# ── A. 1m revised at +95.6 s (the real finding) ─────────────────────────────
def test_a_revision_inside_the_margin_satisfies_revised_b2_not_the_original(tmp_path):
    rep = _run(tmp_path, _full(D24) + _full(D25, revise_first_at=95.6))
    assert rep["B2_original"]["status"] == "CONTRADICTED"          # recorded, not hidden
    assert rep["B2"]["status"] == "UNVERIFIED"                     # 2 sessions: never PASS
    assert rep["B2"]["late_revisions"] == []
    assert rep["B2"]["per_timeframe"]["1m"]["revision_latency_s"]["max"] == 95.6
    assert rep["B2"]["per_timeframe"]["1m"]["headroom_s"] == 24.4
    start = _dt.datetime(2026, 9, 25, 3, 45, tzinfo=UTC)
    end = start + _dt.timedelta(minutes=1)
    assert not T.is_final(start, "1m", end + _dt.timedelta(seconds=60))   # not final at +60 s
    assert T.is_final(start, "1m", end + _dt.timedelta(seconds=120))      # final at +120 s


# ── B. 1m revised at +121 s: contradiction, never a silent pass ─────────────
def test_b_a_late_1m_revision_contradicts_revised_b2(tmp_path):
    lines = [x for d in (21, 22, 23) for x in _full(_dt.date(2026, 9, d))]
    lines += _full(D24, revise_first_at=121.0)
    b2 = _run(tmp_path, lines)["B2"]
    assert b2["status"] == "CONTRADICTED"                       # more sessions don't clear it
    (late,) = b2["late_revisions"]
    assert late["timeframe"] == "1m" and late["seconds_after_end"] == 121.0
    assert "revised 121.0 s after the end (margin 120 s)" in b2["sessions_disagreeing"]["2026-09-24"][0]


# ── C / D. 15m at +110.9 s, 1h at +111.0 s: inside the margin, headroom shown ─
def test_c_15m_at_110_9_passes_the_margin(tmp_path):
    b2 = _run(tmp_path, _full(D25, tf="15m", revise_first_at=110.9))["B2"]
    assert b2["late_revisions"] == [] and b2["per_timeframe"]["15m"]["headroom_s"] == 9.1


def test_d_1h_at_111_0_passes_with_its_headroom_reported(tmp_path):
    b2 = _run(tmp_path, _full(D25, tf="1h", revise_first_at=111.0))["B2"]
    assert b2["late_revisions"] == []
    assert b2["per_timeframe"]["1h"]["revision_latency_s"]["max"] == 111.0
    assert b2["per_timeframe"]["1h"]["headroom_s"] == 9.0


# ── E. 5m at +145.9 s: out of scope, does not affect X ──────────────────────
def test_e_5m_is_out_of_scope_and_does_not_contradict(tmp_path):
    rep = _run(tmp_path, _full(D25, tf="5m", revise_first_at=145.9))
    b2 = rep["B2"]
    assert b2["late_revisions"] == [] and b2["status"] == "UNVERIFIED"
    five = b2["per_timeframe"]["5m"]
    assert five["in_scope"] is False and five["late_revisions"] == 1   # measured, reported
    assert rep["B2_original"]["status"] == "CONTRADICTED"               # the old wording counted it


# ── F. fetched at 16:05, bar ended 10:00: final, but knowable at 16:05 ──────
def test_f_timing_finality_never_moves_knowable_at_earlier():
    start = _dt.datetime(2026, 9, 25, 9, 59, tzinfo=IST).astimezone(UTC)
    fetched = _dt.datetime(2026, 9, 25, 16, 5, tzinfo=IST).astimezone(UTC)
    assert T.is_final(start, "1m", fetched)
    for verified in (False, True):
        k = K.for_intraday_bar(start, "1m", fetched, publication_lag_verified=verified)
        assert k.at == fetched                                   # never bar_end, never +margin


def test_f_daily_bar_knowable_stays_the_fetch_even_when_b1_is_verified():
    fetched = _dt.datetime(2026, 9, 26, 7, 0, tzinfo=IST).astimezone(UTC)
    k = K.for_daily_bar(_dt.date(2026, 9, 25), fetched, settlement_lag_verified=True)
    assert k.at == fetched


# ── G. revised after timing-finality ────────────────────────────────────────
def test_g_a_revision_after_finality_is_recorded_and_fails_closed(tmp_path):
    rep = _run(tmp_path, _full(D25, revise_first_at=300.0))       # 5 min after the end
    (late,) = rep["B2"]["late_revisions"]
    assert late["seconds_after_end"] == 300.0 and late["first_seen"]  # acceptance evidence
    assert rep["B2"]["status"] == "CONTRADICTED"
    # ingestion: a different later observation of a stored intraday bar is never
    # written over it (its knowable_at is untouched); unexplained -> fails closed
    stored = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10,
              "open_interest": 0}
    new = {**stored, "close": 100.4}
    v = classify(stored, new, bar_date=D25, fetch_date=D25, tick=None, events=[])
    assert v.classification == "UNEXPLAINED" and v.fails
