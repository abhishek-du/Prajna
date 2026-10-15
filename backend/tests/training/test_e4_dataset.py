"""E4 step 2 dataset builder: the pure parts (no database)."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import pathlib

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    "e4_build_dataset",
    pathlib.Path(__file__).resolve().parents[2] / "ops" / "measure" / "e4_build_dataset.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
D = [_dt.date(2026, 10, 12), _dt.date(2026, 10, 13), _dt.date(2026, 10, 14)]


def bar(d, o):
    return {"market_date": d, "open": o, "high": o + 1, "low": o - 1, "close": o + 0.5,
            "volume": 1000}


def test_missing_sessions_are_nan_never_shifted():
    a = B.assemble(["A", "B"], D, {"A": [bar(D[0], 10), bar(D[2], 12)], "B": [bar(D[1], 20)]})
    assert np.isnan(a["open"][0, 1]) and a["open"][0, 2] == 12
    assert np.isnan(a["close"][1, 0]) and a["close"][1, 1] == 20.5


def test_bars_outside_the_calendar_are_ignored():
    a = B.assemble(["A"], D, {"A": [bar(_dt.date(2026, 10, 11), 9), bar(D[0], 10)]})
    assert np.isfinite(a["open"]).sum() == 1


def test_content_hash_is_deterministic_and_sensitive():
    rows = {"A": [bar(D[0], 10)]}
    h1 = B.content_sha256(["A"], D, B.assemble(["A"], D, rows))
    h2 = B.content_sha256(["A"], D, B.assemble(["A"], D, rows))
    h3 = B.content_sha256(["A"], D, B.assemble(["A"], D, {"A": [bar(D[0], 10.000001)]}))
    assert h1 == h2 != h3
