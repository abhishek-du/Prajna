"""E1 (pre-session stock selection, approved design 2026-10-12): the statistics, the
point-in-time selection, the matched controls, the acceptance rules, the one-look phase
guards and the read-only loader. Synthetic data and the test database only."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import numpy as np
import pytest
from sqlalchemy import text

from app.canon import process as CP
from app.core import clock
from app.features import snapshots as SN
from app.training import e1 as E
from app.training import labels as L
from app.training import policy as P
from app.training import replay as RP
from app.training import samples as SM
from tests.support import stage3_seed as W

sys.path.insert(0, "ops/measure")
import stage4_e1_selection as X

TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
STRICT = P.DATASETS["strict"]


def world(n_sessions=60, n=700, beta=0.0, seed=1):
    """Synthetic sessions: y = beta * (-ret_1d) + noise; 5 % masked; 3 % without a label."""
    rng = np.random.default_rng(seed)
    out = []
    for t in range(n_sessions):
        Xm = rng.normal(size=(n, len(E.CORE24)))
        Xm[:, E.CORE24.index("turnover_20")] = rng.lognormal(15, 2, n)
        Xm[:, E.CORE24.index("atr_pct_14")] = rng.uniform(0.01, 0.06, n)
        Xm[:, E.CORE24.index("sma_20")] = rng.lognormal(5, 1, n)
        ret1 = Xm[:, E.CORE24.index("ret_1d")] * 0.02
        Xm[:, E.CORE24.index("ret_1d")] = ret1
        y = beta * (-ret1) + rng.normal(0, 0.02, n)
        y[rng.random(n) < 0.03] = np.nan
        masked = rng.random(n) < 0.05
        ok = ~np.isnan(y)
        out.append({"date": t, "keys": [f"K{t}_{i:04d}" for i in range(n)], "X": Xm, "y": y,
                    "turnover": Xm[:, E.CORE24.index("turnover_20")],
                    "atr": Xm[:, E.CORE24.index("atr_pct_14")],
                    "price": Xm[:, E.CORE24.index("sma_20")],
                    "evaluable": ok & ~masked})
    return out


def run(sessions, score_fn, top=500, folds=5):
    per, fo = [], []
    for t, sess in enumerate(sessions):
        u = E.universe(sess, top)
        r = E.evaluate_session(sess, u, score_fn(sess, u), rng=np.random.default_rng([7, t]))
        per.append(r)
        fo.append(t * folds // len(sessions))
    return E.summarise(per, fo, b=2000, block=5, level=0.975, seed=3, perm_draws=200)


class TestStatistics:
    def test_rankdata_and_spearman(self):
        assert E.rankdata(np.array([3.0, 1.0, 3.0, 2.0])).tolist() == [3.5, 1.0, 3.5, 2.0]
        x = np.arange(10.0)
        assert E.spearman(x, x ** 3) == pytest.approx(1.0)
        assert E.spearman(x, -x) == pytest.approx(-1.0)
        assert E.spearman(x[:2], x[:2]) is None

    def test_nw_t_and_bootstrap_are_deterministic(self):
        v = list(np.random.default_rng(0).normal(0.1, 1, 400))
        t0 = float(np.mean(v) / (np.std(v) / np.sqrt(len(v))))
        assert E.nw_t(v, lags=0) == pytest.approx(t0, rel=1e-6)
        a = E.block_bootstrap_ci(v, b=500, block=5, level=0.95, seed=9)
        assert a == E.block_bootstrap_ci(v, b=500, block=5, level=0.95, seed=9)
        assert a[0] < np.mean(v) < a[1]

    def test_max_drawdown(self):
        assert E.max_drawdown([1, -2, 1, -3, 5]) == pytest.approx(4)


class TestSelection:
    def test_selection_is_point_in_time(self):
        """Universe and picks never read y or the masks (post-as_of information)."""
        s = world(1)[0]
        u = E.universe(s, 500)
        p = E.picks(s, u, E.reversal(s))
        s2 = {**s, "y": np.zeros_like(s["y"]), "evaluable": np.ones(len(s["y"]), bool)}
        assert np.array_equal(u, E.universe(s2, 500))
        assert np.array_equal(p, E.picks(s2, u, E.reversal(s2)))
        assert len(u) == 500 and len(p) == 100
        assert s["turnover"][u].min() >= np.sort(s["turnover"])[-500]

    def test_c2_control_is_the_cell_mean_of_non_picked(self):
        s = {"keys": list("abcdefghij"), "turnover": np.arange(10.0),
             "atr": np.zeros(10) + np.arange(10) * 0.0, "y": np.arange(10.0) / 100,
             "evaluable": np.array([True] * 9 + [False])}
        s["atr"] = np.arange(10.0)               # each name its own decile pair
        u = np.arange(10)
        d, unmatched = E.c2_excess(s, u, np.array([0]))
        assert d == [] and unmatched == 1       # no other name in its cell
        s["turnover"] = np.zeros(10)            # one turnover decile ...
        s["atr"] = np.zeros(10)                 # ... and one ATR decile: one cell
        d, unmatched = E.c2_excess(s, u, np.array([0, 1]))
        ctrl = np.mean(s["y"][2:9])             # j (not evaluable) is not a control
        assert unmatched == 0 and d == pytest.approx([0 - ctrl, 0.01 - ctrl])

    def test_ridge_recovers_the_planted_sign(self):
        ss = world(30, beta=1.0)
        rows = [E.ridge_rows(s, E.universe(s, 500)) for s in ss]
        w = E.ridge_fit(rows, 10.0)
        j = E.CORE24.index("ret_1d")
        assert w[j] < 0 and abs(w[j]) == max(abs(w))


class TestAcceptance:
    def test_planted_signal_passes_and_noise_does_not(self):
        sig = run(world(60, beta=0.8), lambda s, u: E.reversal(s))
        acc = E.acceptance(sig, folds_total=5, cost=None)
        assert sig["primary_mean_excess_c2"] > 0 and acc["A1"] == "PASS"
        assert acc["A2"].startswith("NOT_EVALUATED") and acc["A3"].startswith("PASS")
        assert acc["A4"] == "PASS" and sig["c1"]["p_one_sided"] < 0.05
        noise = run(world(60, beta=0.0, seed=2), lambda s, u: E.reversal(s))
        an = E.acceptance(noise, folds_total=5, cost=None)
        assert an["A1"] in ("UNPROVEN", "FAIL") and an["A4"] == "PASS"

    def test_costs_and_a5(self):
        prim = {"primary_ci": [0.001, 0.003], "primary_mean_excess_c2": 0.002,
                "fold_mean_excess": {"0": 1, "1": 1, "2": 1, "3": 1, "4": -1},
                "placebo_ci": [-0.001, 0.001], "pick_mean": 0.001}
        cheap = {"name": "c", "per_side_bps": 5, "approved_by": "t", "source": "t"}
        dear = {**cheap, "per_side_bps": 8}     # 0.002 - 1.5 x 0.0016 < 0
        assert E.acceptance(prim, folds_total=5, cost=cheap)["A2"] == "PASS"
        assert E.acceptance(prim, folds_total=5, cost=dear)["A2"] == "FAIL"
        assert E.acceptance(prim, folds_total=5, cost=None)["A3"].startswith("PASS (4/5")
        a = E.acceptance(prim, folds_total=5, cost=None, p1_mean=0.003, is_p2=True)
        assert a["A5"].startswith("FAIL")
        assert E.net_view(prim, 10)["net_excess_c2"] == pytest.approx(0.0)


class TestPhaseGuards:
    @pytest.fixture
    def out(self, tmp_path, monkeypatch):
        monkeypatch.setattr(X, "OUT", tmp_path)
        return tmp_path

    def _cfg(self):
        a = type("A", (), {"dataset": "asif", "labels": "label-v2", "top": 500,
                           "predictors": "reversal", "bootstrap": 100, "seed": 1})()
        cfg = X.config(a)
        return cfg, X.cfg_sha(cfg)

    def test_test_needs_validate_and_happens_once(self, out):
        cfg, sha = self._cfg()
        with pytest.raises(SystemExit, match="validate phase"):
            asyncio.run(X.test(cfg, sha, None))
        (out / f"validate_{sha[:12]}.json").write_text(json.dumps({"config_sha256": sha}))
        (out / f"test_{sha[:12]}.json").write_text("{}")
        with pytest.raises(SystemExit, match="single test look"):
            asyncio.run(X.test(cfg, sha, None))
        with pytest.raises(SystemExit, match="already had its test look"):
            asyncio.run(X.validate(cfg, sha))

    def test_config_hash_covers_every_choice(self):
        cfg, sha = self._cfg()
        assert X.cfg_sha({**cfg, "universe_top": 400}) != sha
        assert X.cfg_sha({**cfg, "seed": 2}) != sha

    def test_recost_needs_no_database(self, out):
        prim = {"primary_ci": [0.001, 0.003], "primary_mean_excess_c2": 0.002,
                "fold_mean_excess": {str(k): 1 for k in range(5)},
                "placebo_ci": [-0.001, 0.001], "pick_mean": 0.001}
        f = out / "test_x.json"
        f.write_text(json.dumps({"phase": "test", "config_sha256": "x" * 64, "folds_total": 5,
                                 "predictors": {"reversal": {"primary": prim}}}))
        r = X.recost(f, {"name": "c", "per_side_bps": 5, "approved_by": "t", "source": "t"})
        assert r["predictors"]["reversal"]["acceptance"]["A2"] == "PASS"


@pytest.mark.db
@pytest.mark.integration
@pytest.mark.isolation("REPEATABLE READ")
async def test_loader_is_point_in_time_and_label_aligned(db_session):
    clock.freeze(W.NOW)
    try:
        await W.seed(db_session)
        await CP.process(db_session, commit=True, token=TOKEN)
        days = W.history()[-12:]
        rid = await RP.open_run(db_session, STRICT, days[0], days[-1], None, "test",
                                code={"git_sha": "t", "dirty": False})
        for d in days:
            await RP.replay_snapshot(db_session, STRICT,
                                     await SN.resolve(db_session, d, "PRE_SESSION"), rid)
        await L.build_v2(db_session, days[0], days[-1], cutoff=W.NOW)
        await SM.build(db_session, STRICT.version, "label-v2")
        got = None
        for d in reversed(days):
            got = await X.load_session(db_session, STRICT.version, "label-v2", "ret_oc", d, 2)
            if got:
                break
        assert got is not None, "no feature-eligible session in the seed window"
        assert len(got["keys"]) <= 2 and list(got["turnover"]) == sorted(got["turnover"],
                                                                          reverse=True)
        lab = {r[0]: r[1] for r in (await db_session.execute(text("""select instrument_key,
            value from training_label where label_version = 'label-v2' and label_id = 'ret_oc'
              and status = 'VALID' and session_date = :d"""), {"d": got["date"]})).all()}
        for k, y in zip(got["keys"], got["y"], strict=True):
            assert (np.isnan(y) and k not in lab) or y == pytest.approx(lab[k])
        eligible = (await db_session.execute(text("""select count(*) from training_sample
            where dataset_version = :v and label_version = 'label-v2' and snapshot =
              'PRE_SESSION' and session_date = :d and feature_eligible"""),
            {"v": STRICT.version, "d": got["date"]})).scalar()
        assert len(got["keys"]) == min(2, eligible)
    finally:
        clock.unfreeze()
