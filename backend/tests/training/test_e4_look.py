"""ops/measure/e4_test_look.py: the one-look guard, the suspect-on-d mask and the
per-session book on synthetic worlds (no database, no frozen dataset)."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import pathlib

import pytest

from tests.training.test_e4 import world

BACKEND = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("e4_test_look",
                                              BACKEND / "ops/measure/e4_test_look.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def _cal(tmp_path, **over):
    c = {"worlds": 1000, "adequate": True, "code_sha256": "abc", **over}
    p = tmp_path / "null_calibration.json"
    p.write_text(json.dumps(c))
    return p


def _look(tmp_path, cal, *, dirty=False, confirm=None, sha="f" * 64):
    L.check_look(tmp_path, sha, dirty=dirty, confirm=confirm or f"E4-{sha[:12]}",
                 calibration=cal, code_sha="abc")


def test_the_look_needs_a_clean_tree_and_the_confirmation(tmp_path):
    cal = _cal(tmp_path)
    with pytest.raises(SystemExit, match="dirty"):
        _look(tmp_path, cal, dirty=True)
    with pytest.raises(SystemExit, match="confirm-test-look E4-ffffffffffff"):
        _look(tmp_path, cal, confirm="E4-wrong")
    _look(tmp_path, cal)                                     # all conditions met


def test_the_look_needs_an_adequate_calibration_of_the_current_code(tmp_path):
    for over, why in (({"adequate": False}, "not adequate"), ({"worlds": 999}, "< 1000"),
                      ({"code_sha256": "old"}, "other e4 code"),
                      ({"adequate": None}, "not adequate")):
        with pytest.raises(SystemExit, match=why):
            _look(tmp_path, _cal(tmp_path, **over))
    with pytest.raises(SystemExit, match="no calibration file"):
        _look(tmp_path, tmp_path / "missing.json")


def test_only_one_look(tmp_path):
    (tmp_path / "test_ffffffffffff.json").write_text("{}")
    with pytest.raises(SystemExit, match="single test look was taken"):
        _look(tmp_path, _cal(tmp_path))


def test_the_config_sha_is_stable_and_names_the_frozen_dataset():
    assert L.config_sha() == L.config_sha()
    assert L.CONFIG["dataset_content_sha256"] == L.CONTENT_SHA
    assert L.CONFIG["k"] == 10 and L.CONFIG["capital_inr"] == 1_000_000.0


def test_suspect_on_d_is_dropped_from_every_arm():
    sess = {"d": 7, "arms": {"P": ["A", "B"], "C2": ["C", "B"], "PL": ["B"], "PLC": [],
                             "C0": ["A", "B", "C"]}}
    out = L.mask_suspect_on_d(sess, {"B": {7}, "C": {6}})
    assert out["arms"] == {"P": ["A"], "C2": ["C"], "PL": [], "PLC": [], "C0": ["A", "C"]}
    assert out["masked_suspect"] == 1


def test_the_book_finds_a_planted_fade_and_not_a_null(monkeypatch):
    monkeypatch.setattr(L, "B", 500)
    for fade, expect_positive in ((0.6, True), (0.0, None)):
        series = world(n_names=80, n=420, fade=fade, seed=3)
        L._init(series, {k: set() for k in series})
        days = [_dt.date(2020, 1, 1) + _dt.timedelta(days=i) for i in range(420)]
        rows = [L.session(("gap_fade", d)) for d in range(270, 420)]
        r = L.evaluate(rows, days)["primary"]
        if expect_positive:
            assert r["ci_bps"][0] > 0                         # a strong planted edge is found
        else:
            assert r["ci_bps"][0] <= 0 or r["mean_bps"] < 50  # no edge is not "found" large
        assert 140 <= r["n"] <= 150                          # unmatched sessions drop out
