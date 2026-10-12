"""E1 shadow log (approved 2026-10-12): eligibility, picks equal to E1's selection, the
opening-quote spreads, the day evaluation, write-once files, and the production
feature reader on the seed world (registry guard). Logging only; test database only."""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from decimal import Decimal as D

import numpy as np
import pytest

from app.canon import process as CP
from app.core import clock
from app.core.config import get_settings
from app.features import engine as FE
from app.features import locks
from app.features import registry as R
from app.features import snapshots as SN
from app.features.decisions import DECISIONS
from app.training import e1 as E
from app.training import shadow as SH
from tests.support import stage3_seed as W

sys.path.insert(0, "ops/measure")
import shadow_e1 as X

TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]


def rows_for(n=700, seed=0, drop=()):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        k = f"NSE_EQ|K{i:04d}"
        for f in E.CORE24:
            v = (rng.lognormal(15, 2) if f == "turnover_20" else rng.uniform(0.01, 0.06)
                 if f == "atr_pct_14" else rng.normal())
            out.append({"instrument_key": k, "feature_id": f,
                        "value": None if (i, f) in drop else v})
    return out


def t(h, m, s=0):
    return _dt.time(h, m, s)


class TestPure:
    def test_eligibility_needs_all_24_core_features(self):
        sess = SH.session_from_rows(rows_for(5, drop={(2, "rsi_14")}))
        assert sess["keys"] == [f"NSE_EQ|K{i:04d}" for i in (0, 1, 3, 4)]
        assert SH.session_from_rows([]) is None

    def test_picks_are_e1s_selection(self):
        sess = SH.session_from_rows(rows_for())
        w = np.random.default_rng(1).normal(size=24)
        doc = SH.make_picks(sess, w)
        u = E.universe(sess, 500)
        assert doc["eligible"] == 700 and doc["universe_size"] == 500
        want = [sess["keys"][i] for i in E.picks(sess, u, E.reversal(sess)).tolist()]
        assert doc["picks"]["p1_reversal"] == want and len(want) == 100
        p2 = [sess["keys"][i] for i in E.picks(sess, u, E.ridge_score(sess, u, w)).tolist()]
        assert doc["picks"]["p2_ridge24"] == p2
        assert {x["key"] for x in doc["universe"]} >= set(want) | set(p2)

    def test_open_quotes(self):
        rows = [
            {"key": "A", "ist_time": t(9, 15, 1), "bid": None, "ask": D("101"), "ltp": None},
            {"key": "A", "ist_time": t(9, 15, 2), "bid": D("99.9"), "ask": D("100.1"),
             "ltp": D("100")},
            {"key": "A", "ist_time": t(9, 17), "bid": D("99.8"), "ask": D("100.2"),
             "ltp": D("100")},
            {"key": "B", "ist_time": t(9, 16, 30), "bid": D("50"), "ask": D("50.5"),
             "ltp": D("50.2")},
        ]
        q = SH.open_quotes(rows)
        assert q["A"]["first_bid"] == 99.9 and q["A"]["first_spread_bps"] == pytest.approx(20)
        assert q["A"]["median_spread_bps_0915_0920"] == pytest.approx(30)
        assert q["A"]["two_sided_ticks"] == 2 and q["A"]["first_ltp"] == 100
        assert q["B"]["first_bid"] is None                 # no two-sided quote before 09:16
        assert q["B"]["median_spread_bps_0915_0920"] == pytest.approx(10000 * 0.5 / 50.25)

    def test_evaluate_day_matches_e1_and_detects_tampering(self):
        sess = SH.session_from_rows(rows_for())
        doc = SH.make_picks(sess, np.ones(24))
        rng = np.random.default_rng(3)
        y = {u["key"]: float(rng.normal(0, 0.02)) for u in doc["universe"][:-10]}
        m = SH.evaluate_day(doc, y, seed=1, day=_dt.date(2026, 10, 13))
        assert m["evaluable"] == 490 and m["p1_reversal"]["n_picks"] == 100
        assert m["p1_reversal"]["excess_c2"] is not None
        bad = {**doc, "picks": {**doc["picks"], "p1_reversal": doc["picks"]["p1_reversal"][::-1]}}
        with pytest.raises(AssertionError, match="stored picks differ"):
            SH.evaluate_day(bad, y, seed=1, day=_dt.date(2026, 10, 13))


class TestFiles:
    def test_write_once_and_ledger(self, tmp_path, monkeypatch):
        monkeypatch.setattr(X, "OUT", tmp_path)
        monkeypatch.setattr(X, "ROOT", tmp_path)
        p = tmp_path / "2026-10-13" / "picks.json"
        sha = X.write_once(p, {"phase": "picks", "session_date": "2026-10-13", "status": "OK"})
        with pytest.raises(SystemExit, match="written once"):
            X.write_once(p, {"phase": "picks"})
        led = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
        assert led == [{"file": "2026-10-13/picks.json", "sha256": sha, "phase": "picks",
                        "session_date": "2026-10-13", "status": "OK", "written_at": None,
                        "code_git_sha": None}]

    def test_summary_needs_days(self, tmp_path, monkeypatch):
        monkeypatch.setattr(X, "OUT", tmp_path)
        assert X.summary()["note"].startswith("fewer than 6 days")


@pytest.mark.db
@pytest.mark.integration
@pytest.mark.isolation("REPEATABLE READ")
async def test_picks_from_production_features(db_session, monkeypatch, tmp_path):
    clock.freeze(W.NOW)
    try:
        await W.seed(db_session)
        await CP.process(db_session, commit=True, token=TOKEN)

        st = get_settings()                        # every lock condition (as Stage 3 tests)
        monkeypatch.setattr(st, "PRAJNA_STAGE3_ENABLED", True)
        monkeypatch.setattr(st, "PRAJNA_STAGE3_BACKFILL_ENABLED", False)
        monkeypatch.setitem(DECISIONS["FEATURE-PARAMS"], "status", "APPROVED")
        monkeypatch.setattr(locks, "KILL_FILE", tmp_path / "stage3.kill")

        async def s1(_s):
            return True, "COMPLETE (test)"
        monkeypatch.setattr(locks, "stage1_status", s1)
        monkeypatch.setattr(locks, "stage2_status", lambda *a, **k: (True, "PASS (test)"))
        sn = await SN.resolve(db_session, W.SESSION, "PRE_SESSION")
        await FE.run_snapshot(db_session, sn, keys=None, mode="RUN", token=TOKEN,
                              operator="pytest")
        rows, meta = await X.feature_rows(db_session, W.SESSION)
        await db_session.rollback()
        assert rows and meta["registry_sha256"] == [R.REGISTRY_SHA256]
        doc = await X.picks_in(db_session, W.SESSION, np.zeros(24))
        assert doc["status"] in ("OK", "NO_ELIGIBLE")
        if doc["status"] == "OK":
            assert set(doc["picks"]["p1_reversal"]) <= {u["key"] for u in doc["universe"]}
        monkeypatch.setattr(R, "REGISTRY_SHA256", "0" * 64)
        bad = await X.picks_in(db_session, W.SESSION, np.zeros(24))
        assert bad["status"] == "REGISTRY_MISMATCH"
        none = await X.picks_in(db_session, W.SESSION - _dt.timedelta(days=400), np.zeros(24))
        assert none["status"] in ("NO_FEATURES", "SKIP_NOT_NORMAL_SESSION")
    finally:
        clock.unfreeze()

