"""E5 recipe on synthetic panels (no database): learns a planted signal, is deterministic,
never reads a later session, applies the hybrid rules, and evaluates as specified."""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("torch")

from app.models import data as D
from app.models import evaluate as EV
from app.models import recipe as R

N_NAMES = 300


def panel(n_sessions: int, *, signal: float, seed: int = 1) -> list[D.Session]:
    """Each session: random core features; ret_oc = -signal x rank(ret_1d) + noise."""
    rng = np.random.default_rng(seed)
    out = []
    keys = [f"NSE_EQ|S{i:04d}" for i in range(N_NAMES)]
    day = _dt.date(2025, 1, 1)
    for _ in range(n_sessions):
        X = rng.normal(size=(N_NAMES, len(D.CORE)))
        X[:, D.CORE.index("sma_20")] = rng.uniform(60, 2000, N_NAMES)       # price
        X[:, D.CORE.index("turnover_20")] = rng.lognormal(18, 1, N_NAMES)
        X[:, D.CORE.index("volatility_20")] = rng.uniform(0.1, 0.6, N_NAMES)
        r1 = X[:, D.CORE.index("ret_1d")]
        rank = (np.argsort(np.argsort(r1)) / (N_NAMES - 1)) - 0.5
        y = -signal * rank + rng.normal(0, 0.01, N_NAMES)
        hi = np.abs(rng.normal(0.01, 0.005, N_NAMES)) + np.maximum(y, 0)
        lo = -np.abs(rng.normal(0.01, 0.005, N_NAMES)) + np.minimum(y, 0)
        out.append(D.Session(day, keys, X, {"ret_oc": y, "high_exc": hi, "low_exc": lo},
                             np.zeros(N_NAMES, dtype=bool), "synthetic"))
        day += _dt.timedelta(days=1)
    return out


@pytest.fixture(scope="module")
def strong():
    p = panel(R.TRAIN_SESSIONS + 6, signal=0.04)
    return p, R.fit(p, list(range(R.TRAIN_SESSIONS)))


def test_it_learns_a_planted_signal(strong):
    p, b = strong
    per = []
    for t in range(R.TRAIN_SESSIONS + 1, len(p)):
        out = R.predict(b, p, t)
        per.append(EV.session(p[t], out, R.select(out, b.cost), b.cost))
    pooled = EV.pooled(per)
    assert pooled["auc"] > 0.7 and pooled["ic"] > 0.5
    assert pooled["s_mean"] > 0 and pooled["picks"] == R.K
    assert set(per[0]) >= {"auc", "accuracy", "brier", "ic", "hit_rate", "range_coverage",
                           "vol_ic", "precision", "recall", "s"}
    out = R.predict(b, p, len(p) - 1)
    assert set(R.OUTPUTS) <= set(out)
    assert np.all(out["range_lo"] <= out["range_hi"]) and np.all(out["volatility"] >= 0)
    assert np.all((out["confidence"] >= 0) & (out["confidence"] <= 1))
    assert np.all((out["prob_up"] >= 0) & (out["prob_up"] <= 1))


def test_deterministic(strong):
    p, b = strong
    again = R.fit(p, list(range(R.TRAIN_SESSIONS)))
    assert again.sha256() == b.sha256()
    a1, a2 = R.predict(b, p, len(p) - 1), R.predict(again, p, len(p) - 1)
    assert np.array_equal(a1["score"], a2["score"])


def test_no_later_session_is_read(strong):
    p, b = strong
    t = R.TRAIN_SESSIONS + 2
    before = R.predict(b, p, t)
    q = list(p)
    for j in range(t + 1, len(q)):                       # scramble every later session
        s = q[j]
        q[j] = D.Session(s.date, s.keys, s.X[::-1].copy(), s.y, s.masked, s.source)
    assert np.array_equal(R.predict(b, q, t)["score"], before["score"])
    # labels of the predicted session itself are never inputs
    s = q[t]
    q[t] = D.Session(s.date, s.keys, s.X, {k: v * 0 for k, v in s.y.items()}, s.masked,
                     s.source)
    assert np.array_equal(R.predict(b, q, t)["score"], before["score"])


def test_no_signal_no_edge():
    p = panel(R.TRAIN_SESSIONS + 6, signal=0.0, seed=7)
    b = R.fit(p, list(range(R.TRAIN_SESSIONS)))
    per = []
    for t in range(R.TRAIN_SESSIONS + 1, len(p)):
        out = R.predict(b, p, t)
        per.append(EV.session(p[t], out, R.select(out, b.cost), b.cost))
    pooled = EV.pooled(per)
    assert 0.4 < pooled["auc"] < 0.6
    assert pooled["cash_sessions"] >= 0


def test_hybrid_rules():
    out = {"keys": ["a", "b", "c", "d"], "exp_return": np.array([0.01, 0.01, 0.0001, 0.02]),
           "prob_up": np.array([0.6, 0.4, 0.9, 0.7]), "score": np.array([0.1, 0.4, 0.5, 0.2])}
    assert R.select(out, 0.0015) == [3, 0]                 # b: prob, c: return below cost
    assert R.select(out, 0.0015, results_today={"d"}) == [0]
    assert 0.0008 < R.round_trip_cost() < 0.003            # MIS + 5 bps half-spread x 2


def test_auc():
    assert EV.auc(np.array([0.1, 0.2, 0.8, 0.9]), np.array([0, 0, 1, 1])) == 1.0
    assert EV.auc(np.array([0.1, 0.2]), np.array([1, 1])) is None


def test_controls_are_positions_in_the_universe():
    """2026-10-21: controls came back as session row numbers while the caller indexed the
    universe by position (a crash on 3,000 names, silently wrong ones below 500)."""
    p = panel(2, signal=0.0, seed=3)
    sess = p[0]
    u = sess.universe()[::-1].copy()                    # positions != row numbers
    picks = [0, 1, 2]
    c = EV._controls(sess, u, picks, seed=1)
    assert c and all(0 <= j < len(u) for j in c) and not set(c) & set(picks)
    cells = [tuple(EV.E4.bins(sess.col(f)[u], n)[j] for f, n in (
        ("turnover_20", 3), ("volatility_20", 3), ("ret_5d", 5))) for j in range(len(u))]
    assert len(c) == len(picks) and [cells[j] for j in c] == [cells[j] for j in picks]


def test_bundle_round_trips_through_pickle(strong):
    import pickle
    p, b = strong
    back = pickle.loads(pickle.dumps(b, protocol=5))
    assert back.sha256() == b.sha256()
    t = len(p) - 1
    assert np.array_equal(R.predict(back, p, t)["score"], R.predict(b, p, t)["score"])
