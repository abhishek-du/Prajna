"""E6 paper monitor (docs/STAGE4_E6_PREREGISTRATION.md): the pure rule - day 0, the class,
CAR[0,1], the outcome, the weekly look - and the record's refusals. No network."""

from __future__ import annotations

import datetime as _dt
import json

import pytest

from app.e6 import monitor as M
from app.e6 import store as S

IST = M.IST
SESS = [_dt.date(2026, 10, d) for d in (19, 20, 21, 22, 23, 26, 27)]


def test_day0_cut_at_1530():
    assert M.day0(_dt.datetime(2026, 10, 21, 13, 0, tzinfo=IST), SESS) == _dt.date(2026, 10, 21)
    assert M.day0(_dt.datetime(2026, 10, 21, 15, 30, tzinfo=IST), SESS) == _dt.date(2026, 10, 22)
    assert M.day0(_dt.datetime(2026, 10, 23, 22, 0, tzinfo=IST), SESS) == _dt.date(2026, 10, 26)
    assert M.day0(_dt.datetime(2026, 10, 24, 10, 0, tzinfo=IST), SESS) == _dt.date(2026, 10, 26)
    assert M.day0(_dt.datetime(2026, 10, 28, 10, 0, tzinfo=IST), SESS) is None


def test_classify_and_car01():
    assert M.classify(0.0327) == "PICK" and M.classify(0.0326) == "OTHER"
    assert M.classify(-0.0185) == "CONTROL" and M.classify(0.0029) == "OTHER"
    assert M.classify(-0.0186) == "OTHER"
    # stock +5 % then +2 %, Nifty +1 % then 0 % -> AR 4 % + 2 %
    assert M.car01([100, 105, 107.1], [100, 101, 101]) == pytest.approx(0.06)


def test_outcome_costs():
    o = M.outcome(100, 110, 100, 102)
    assert o["excess"] == pytest.approx(0.08)
    assert o["net"] == pytest.approx(0.08 - 0.0035)
    assert o["net_stress"] == pytest.approx(0.08 - 0.0035 * 1.5)


def _row(cls, day, net, excess=None):
    return {"cls": cls, "entry": day, "net": net, "net_stress": net - 0.002,
            "excess": net + 0.0035 if excess is None else excess}


def test_look_stats_weekly_and_gates():
    rows = []
    for w in range(8):
        d = _dt.date(2026, 11, 2) + _dt.timedelta(weeks=w)
        rows += [_row("PICK", d, 0.03 + 0.001 * w), _row("CONTROL", d, 0, excess=0.0)]
    rows.append(_row("PICK", _dt.date(2027, 3, 1), 0.5))    # no control that week: not counted
    r = M.look_stats(rows)
    assert r["weeks"] == 8 and r["picks"] == 9
    assert r["ci_975"][0] > 0 and all(r["gates"].values())
    assert r["verdict"] == "MONITOR_POSITIVE"
    assert M.look_stats(rows[:2])["status"] == "INSUFFICIENT"


def test_sign_flip_ci_contains_zero_for_noise():
    lo, hi = M.sign_flip_ci([0.01, -0.012, 0.008, -0.009, 0.011, -0.01])
    assert lo < 0 < hi


def test_rule_sha_is_stable():
    assert len(M.RULE_SHA) == 64 and M.RULE["version"] == "e6-rule-v1"


def test_freeze_mismatch_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DIR", tmp_path)
    with pytest.raises(RuntimeError, match="not frozen"):
        S.load_freeze()
    (tmp_path / "freeze.json").write_text(json.dumps({"rule_sha256": "0" * 64,
                                                      "frozen_at": "2026-10-23T10:00:00+00:00"}))
    with pytest.raises(RuntimeError, match="rule changed"):
        S.load_freeze()
