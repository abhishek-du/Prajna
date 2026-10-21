"""E5 recipe: the members, the ensemble outputs and the hybrid selection rules. Every
hyperparameter is fixed here BEFORE any result (docs/STAGE4_E5_PREREGISTRATION.md); none is
tuned on a test block. Deterministic: fixed seeds, single-threaded torch, LightGBM
deterministic mode.

Members (inputs: unit ranks of the 24 core features within the session universe)
  ridge      ridge regression of ret_oc (winsorised), alpha 100          -> expected return
  lgbm_reg   LightGBM L2 regression of ret_oc (winsorised)               -> expected return
  lgbm_clf   LightGBM classifier of up = ret_oc > the round-trip cost    -> P(up)
  rf_clf     random forest classifier of up                              -> P(up)
  lstm_clf   LSTM over the last 10 sessions' ranks, classifier of up      -> P(up)
  lgbm_q10, lgbm_q90   LightGBM quantile regressions of ret_oc          -> predicted range
  lgbm_range LightGBM regression of the day's range high/open - low/open -> volatility
Outputs per name
  prob_up     mean of the three classifiers
  exp_return  mean of the two regressors (a fraction, open -> close)
  range_lo, range_hi  q10 / q90 (ordered)
  volatility  predicted intraday range (>= 0)
  confidence  1 - 2 x the standard deviation of the five members' unit ranks (agreement)
  score       weighted mean of the five members' unit ranks (the ensemble ranking);
              stacking weights from an INNER validation inside the training window: the
              members are fitted on its first sessions, each member's mean rank IC on its
              last INNER_SESSIONS (20) sessions gives weight max(IC, 0) (all <= 0: equal
              weights); then every member is refitted on the whole window (v2, 2026-10-21:
              in development the LSTM's IC was ~0 and diluted the equal-weight score)
Hybrid selection (ML + quant rules): within the universe (price >= 50, top 500 turnover),
exp_return > the round-trip cost and prob_up > 0.5, not a known results day (features-v5
results_today = 1 when available), then the top K = 10 by score.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.models import data as D
from app.training import e1 as E1

VERSION = "e5-recipe-v2"
SEED = 20261021
K = 10
CAPITAL_INR = 1_000_000.0                       # E4: Rs 10 L, Rs 1 L per name
TRAIN_SESSIONS = 120                            # rolling window
WINSOR = (0.01, 0.99)
RIDGE_ALPHA = 100.0
LGBM = {"n_estimators": 300, "learning_rate": 0.03, "num_leaves": 31,
        "min_child_samples": 200, "subsample": 0.8, "subsample_freq": 1,
        "colsample_bytree": 0.8, "reg_lambda": 1.0, "verbose": -1, "n_jobs": 8,
        "deterministic": True, "force_row_wise": True}
RF = {"n_estimators": 200, "max_depth": 8, "min_samples_leaf": 200, "max_features": 0.5,
      "n_jobs": 8}
LSTM = {"hidden": 32, "epochs": 3, "batch": 1024, "lr": 1e-3}
INNER_SESSIONS = 20
MEMBERS_RANKED = ("ridge", "lgbm_reg", "lgbm_clf", "rf_clf", "lstm_clf")


def round_trip_cost() -> float:
    """MIS round trip of one name in a K-name Rs 10 L book (E4 SessionCost: brokerage,
    statutory charges, 5 bps half-spread each side), as a fraction - the 'up' threshold."""
    from app.training import e4 as E4
    names = [f"n{i}" for i in range(K)]
    return E4.SessionCost(CAPITAL_INR).fraction(names, [0.0] * K)


@dataclass
class Bundle:
    """A fitted recipe: the members (the stored artefact) and the stacking weights."""
    members: dict[str, Any]
    winsor: tuple[float, float]
    cost: float
    trained_on: list[str]
    meta: dict = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)

    def __getstate__(self) -> dict:
        """Pickle the LSTM as its weights (the network class is built lazily, so torch is
        imported only where a model is used)."""
        st = dict(self.__dict__)
        mem = dict(st["members"])
        if "lstm_clf" in mem and not isinstance(mem["lstm_clf"], bytes):
            mem["lstm_clf"] = _dump(mem["lstm_clf"])
        st["members"] = mem
        return st

    def __setstate__(self, st: dict) -> None:
        mem = dict(st["members"])
        if isinstance(mem.get("lstm_clf"), bytes):
            import torch
            net = _LSTMNet()
            net.load_state_dict(torch.load(io.BytesIO(mem["lstm_clf"]), weights_only=True))
            mem["lstm_clf"] = net.eval()
        st["members"] = mem
        self.__dict__.update(st)

    def sha256(self) -> str:
        h = hashlib.sha256(json.dumps({"version": VERSION, "trained_on": self.trained_on,
                                       "winsor": self.winsor, "cost": self.cost,
                                       "weights": self.weights}, sort_keys=True).encode())
        for name in sorted(self.members):
            h.update(name.encode())
            h.update(_fingerprint(name, self.members[name]))
        return h.hexdigest()


def _probe() -> tuple[np.ndarray, np.ndarray]:
    """A fixed input (unit-rank-like values): the model's identity is what it computes."""
    g = np.random.default_rng(SEED)
    return (g.uniform(-0.5, 0.5, (512, len(D.CORE))),
            g.uniform(-0.5, 0.5, (512, D.SEQ_LEN, len(D.CORE))).astype(np.float32))


def _fingerprint(name: str, m: Any) -> bytes:
    """The member's outputs on the probe, 12 significant digits (serialisation-free: a
    pickled and restored model has the same fingerprint)."""
    X, seq = _probe()
    if isinstance(m, np.ndarray):
        v = np.column_stack([np.ones(len(X)), X]) @ m
    elif name == "lstm_clf":
        import torch
        with torch.no_grad():
            v = torch.sigmoid(m(torch.from_numpy(seq))).numpy()
    elif hasattr(m, "predict_proba"):
        v = m.predict_proba(X)[:, 1]
    else:
        v = m.predict(X)
    return json.dumps([float(f"{x:.12g}") for x in np.asarray(v, dtype=float)]).encode()


def _dump(m: Any) -> bytes:
    if isinstance(m, np.ndarray):
        return m.tobytes()
    try:
        import torch
        if isinstance(m, torch.nn.Module):
            buf = io.BytesIO()
            torch.save({k: v.cpu() for k, v in m.state_dict().items()}, buf)
            return buf.getvalue()
    except ImportError:                               # pragma: no cover
        pass
    if hasattr(m, "booster_"):                        # LightGBM sklearn API
        return m.booster_.model_to_string().encode()
    import pickle
    return pickle.dumps(m, protocol=5)


# ── training matrices ───────────────────────────────────────────────────────────────
@dataclass
class Matrix:
    X: np.ndarray
    seq: np.ndarray
    y: np.ndarray                                    # ret_oc
    rng: np.ndarray                                  # high_exc - low_exc
    sessions: np.ndarray                             # session index per row


def matrix(panel: list[D.Session], which: list[int], *, labelled: bool = True) -> Matrix:
    xs, ss, ys, rs, ws = [], [], [], [], []
    for t in which:
        sess = panel[t]
        u = sess.universe()
        if labelled:
            ok = ~np.isnan(sess.y["ret_oc"][u]) & ~sess.masked[u]
        else:
            ok = np.ones(len(u), dtype=bool)
        if not ok.any():
            continue
        r = sess.universe_ranks()                   # ranks within the full universe
        seq, _ = D.sequences(panel[max(0, t - D.SEQ_LEN + 1):t], sess, u)
        xs.append(r[ok])
        ss.append(seq[ok])
        ys.append(sess.y["ret_oc"][u][ok])
        rs.append((sess.y["high_exc"][u] - sess.y["low_exc"][u])[ok])
        ws.append(np.full(int(ok.sum()), t))
    if not xs:
        z = np.zeros((0, len(D.CORE)))
        return Matrix(z, np.zeros((0, D.SEQ_LEN, len(D.CORE)), np.float32), z[:, 0], z[:, 0],
                      z[:, 0].astype(int))
    return Matrix(np.vstack(xs), np.concatenate(ss), np.concatenate(ys), np.concatenate(rs),
                  np.concatenate(ws))


# ── members ─────────────────────────────────────────────────────────────────────────
def _ridge(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(X)), X])
    reg = RIDGE_ALPHA * np.eye(A.shape[1])
    reg[0, 0] = 0.0
    return np.linalg.solve(A.T @ A + reg, A.T @ y)


def _lstm_fit(seq: np.ndarray, up: np.ndarray):
    import torch
    torch.manual_seed(SEED)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    net = _LSTMNet()
    opt = torch.optim.Adam(net.parameters(), lr=LSTM["lr"])
    x, y = torch.from_numpy(seq), torch.from_numpy(up.astype(np.float32))
    g = torch.Generator().manual_seed(SEED)
    loss_f = torch.nn.BCEWithLogitsLoss()
    for _ in range(LSTM["epochs"]):
        perm = torch.randperm(len(x), generator=g)
        for i in range(0, len(x), LSTM["batch"]):
            b = perm[i:i + LSTM["batch"]]
            opt.zero_grad()
            loss = loss_f(net(x[b]), y[b])
            loss.backward()
            opt.step()
    return net.eval()


def _LSTMNet():
    import torch

    class Net(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = torch.nn.LSTM(len(D.CORE), LSTM["hidden"], batch_first=True)
            self.head = torch.nn.Linear(LSTM["hidden"], 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :]).squeeze(-1)
    return Net()


def fit(panel: list[D.Session], train: list[int]) -> Bundle:
    """Stacking weights from the inner validation, then the members on the whole window."""
    w = {k: 1.0 / len(MEMBERS_RANKED) for k in MEMBERS_RANKED}
    inner_ic: dict[str, float | None] = {}
    if len(train) > INNER_SESSIONS + 40:
        inner = _fit_members(panel, train[:-INNER_SESSIONS])
        ics: dict[str, list[float]] = {k: [] for k in MEMBERS_RANKED}
        for t in train[-INNER_SESSIONS:]:
            out = predict(inner, panel, t)
            u = out["idx"]
            y = panel[t].y["ret_oc"][u]
            ok = ~np.isnan(y) & ~panel[t].masked[u]
            if ok.sum() > 20:
                for k in MEMBERS_RANKED:
                    ic = E1.spearman(out["members"][k][ok], y[ok])
                    if ic is not None:
                        ics[k].append(ic)
        inner_ic = {k: float(np.mean(v)) if v else None for k, v in ics.items()}
        pos = {k: max(v or 0.0, 0.0) for k, v in inner_ic.items()}
        if sum(pos.values()) > 0:
            w = {k: v / sum(pos.values()) for k, v in pos.items()}
    b = _fit_members(panel, train)
    b.weights = {k: float(f"{v:.12g}") for k, v in w.items()}
    b.meta["inner_ic"] = inner_ic
    return b


def _fit_members(panel: list[D.Session], train: list[int]) -> Bundle:
    import lightgbm as lgb
    from sklearn.ensemble import RandomForestClassifier

    m = matrix(panel, train)
    if len(m.y) < 1000:
        raise ValueError(f"too few training rows ({len(m.y)})")
    lo, hi = np.quantile(m.y, WINSOR)
    yw = np.clip(m.y, lo, hi)
    cost = round_trip_cost()
    up = (m.y > cost).astype(int)
    mem: dict[str, Any] = {"ridge": _ridge(m.X, yw)}
    mem["lgbm_reg"] = lgb.LGBMRegressor(**LGBM, random_state=SEED).fit(m.X, yw)
    mem["lgbm_clf"] = lgb.LGBMClassifier(**LGBM, random_state=SEED).fit(m.X, up)
    mem["lgbm_q10"] = lgb.LGBMRegressor(**LGBM, objective="quantile", alpha=0.1,
                                        random_state=SEED).fit(m.X, m.y)
    mem["lgbm_q90"] = lgb.LGBMRegressor(**LGBM, objective="quantile", alpha=0.9,
                                        random_state=SEED).fit(m.X, m.y)
    mem["lgbm_range"] = lgb.LGBMRegressor(**LGBM, random_state=SEED).fit(
        m.X, np.clip(m.rng, 0, np.quantile(m.rng, WINSOR[1])))
    mem["rf_clf"] = RandomForestClassifier(**RF, random_state=SEED).fit(m.X, up)
    mem["lstm_clf"] = _lstm_fit(m.seq, up)
    return Bundle(mem, (float(lo), float(hi)), cost,
                  [str(panel[t].date) for t in train],
                  {"rows": len(m.y), "up_share": float(up.mean())})


# ── outputs ─────────────────────────────────────────────────────────────────────────
OUTPUTS = ("prob_up", "exp_return", "range_lo", "range_hi", "volatility", "confidence",
           "score")


def predict(b: Bundle, panel: list[D.Session], t: int) -> dict[str, Any]:
    """Outputs for the universe of panel[t] (inputs of sessions <= t only)."""
    import torch

    sess = panel[t]
    u = sess.universe()
    X = sess.universe_ranks()
    seq, present = D.sequences(panel[max(0, t - D.SEQ_LEN + 1):t], sess, u)
    m = b.members
    raw = {"ridge": np.column_stack([np.ones(len(X)), X]) @ m["ridge"],
           "lgbm_reg": m["lgbm_reg"].predict(X),
           "lgbm_clf": m["lgbm_clf"].predict_proba(X)[:, 1],
           "rf_clf": m["rf_clf"].predict_proba(X)[:, 1]}
    with torch.no_grad():
        raw["lstm_clf"] = torch.sigmoid(m["lstm_clf"](torch.from_numpy(seq))).numpy()
    ranks = np.column_stack([E1.unit_rank(raw[k]) for k in MEMBERS_RANKED])
    q = np.sort(np.column_stack([m["lgbm_q10"].predict(X), m["lgbm_q90"].predict(X)]), axis=1)
    out = {"keys": [sess.keys[i] for i in u], "idx": u,
           "prob_up": (raw["lgbm_clf"] + raw["rf_clf"] + raw["lstm_clf"]) / 3,
           "exp_return": (raw["ridge"] + raw["lgbm_reg"]) / 2,
           "range_lo": q[:, 0], "range_hi": q[:, 1],
           "volatility": np.maximum(m["lgbm_range"].predict(X), 0.0),
           "confidence": np.clip(1 - 2 * ranks.std(axis=1), 0.0, 1.0),
           "score": ranks @ np.array([b.weights.get(k, 1 / len(MEMBERS_RANKED))
                                      for k in MEMBERS_RANKED]),
           "members": raw, "seq_present": present}
    return out


def select(out: dict[str, Any], cost: float, *, results_today: set[str] | None = None,
           k: int = K) -> list[int]:
    """Hybrid rules, then the top k by score: positions within out['keys']."""
    bad = results_today or set()
    ok = [j for j, key in enumerate(out["keys"])
          if out["exp_return"][j] > cost and out["prob_up"][j] > 0.5 and key not in bad]
    return sorted(ok, key=lambda j: (-out["score"][j], out["keys"][j]))[:k]
