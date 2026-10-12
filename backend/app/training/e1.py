"""E1 - pre-session stock selection in the tradable universe (design approved by the user
2026-10-12). Pure computation (numpy only); the database loader and the phases live in
ops/measure/stage4_e1_selection.py.

Question   do the top-ranked names of a liquid universe earn more from the official open
           to the official close than liquidity- and volatility-matched controls, by more
           than realistic costs? (as-if-live v3, PRE_SESSION; research only, no
           profitability claim)
Selection  point-in-time only: universe = top N by turnover_20 among the session's
           feature-eligible samples (all 24 core features VALID at as_of); picks = the top
           quintile of the predictor score inside the universe (long-only, equal weight).
           Masks and label validity are evaluation exclusions applied AFTER selection to
           every arm alike (they depend on information after as_of).
Predictors P1 reversal = -ret_1d. P2 ridge24 = ridge on the 24 core features, each
           ranked cross-sectionally to [-0.5, 0.5]; target the session rank of y; fit on
           TRAIN sessions only; the penalty is chosen per fold on VALID by mean rank IC.
Controls   C0 universe equal-weight; C1 permutation null (random same-size picks from the
           evaluable universe, pooled); C2 per pick the mean y of the non-picked evaluable
           names in the same (turnover_20 decile, atr_pct_14 decile) cell of the universe;
           placebo = random non-picked names against their own C2 controls.
Primary    mean per-session gross excess over C2, pooled over the TEST blocks; moving-block
           bootstrap over sessions (block 5) for the CI.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

CORE24 = ('ret_1d', 'ret_5d', 'ret_20d', 'sma_20', 'sma_50', 'close_to_sma_20',
          'close_to_sma_50', 'ema_12', 'ema_26', 'macd_line', 'macd_trigger', 'macd_histogram',
          'rsi_14', 'atr_14', 'atr_pct_14', 'volatility_20', 'beta_60', 'dist_high_20',
          'dist_low_20', 'breakout_20', 'breakdown_20', 'avg_volume_20', 'volume_spike_20',
          'turnover_20')
EVAL_MASKS = ('CA_WINDOW', 'EXTREME_UNEXPLAINED')
EVAL_FLAG_PREFIXES = ('PRICE_LEVEL_VENDOR_ADJUSTED',)


# ── statistics ─────────────────────────────────────────────────────────────────────────
def rankdata(x: np.ndarray) -> np.ndarray:
    """Average ranks (1..n), ties averaged (scipy.stats.rankdata 'average')."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ranks = np.empty(len(x), dtype=float)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def unit_rank(x: np.ndarray) -> np.ndarray:
    """Cross-sectional rank scaled to [-0.5, 0.5]."""
    n = len(x)
    return np.zeros(n) if n < 2 else (rankdata(x) - 1) / (n - 1) - 0.5


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = rankdata(a), rankdata(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def nw_t(x: list[float], lags: int = 5) -> float | None:
    """Newey-West t statistic of the mean (Bartlett weights)."""
    v = np.asarray([z for z in x if z is not None], dtype=float)
    n = len(v)
    if n < 3:
        return None
    d = v - v.mean()
    var = d @ d / n
    for j in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - j / (lags + 1)) * (d[j:] @ d[:-j]) / n
    return float(v.mean() / math.sqrt(var / n)) if var > 0 else None


def block_bootstrap_ci(x: list[float], *, b: int, block: int, level: float,
                       seed: int) -> tuple[float, float]:
    """Moving-block bootstrap CI of the mean of a chronological series."""
    v = np.asarray(x, dtype=float)
    n = len(v)
    rng = np.random.default_rng(seed)
    nb = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(b, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(b, -1)[:, :n]
    means = v[idx].mean(axis=1)
    a = (1 - level) / 2
    return float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


def max_drawdown(x: list[float]) -> float:
    c = np.cumsum(np.asarray(x, dtype=float))
    peak = np.maximum.accumulate(np.concatenate([[0.0], c]))[1:]
    return float((peak - c).max()) if len(c) else 0.0


# ── one session ────────────────────────────────────────────────────────────────────────
def universe(sess: dict[str, Any], top: int, tier: tuple[int, int] | None = None,
             low_price_q: float | None = None) -> np.ndarray:
    """Indices of the PIT universe: rank by turnover_20 (desc, key as tie-break), keep
    ranks [a, b) of the tier (default [0, top)); optionally drop the bottom low_price_q
    of sma_20 inside it (a survivorship sensitivity, never an acceptance input)."""
    order = np.lexsort((np.asarray(sess["keys"]), -sess["turnover"]))
    a, b = tier if tier else (0, top)
    u = order[a:b]
    if low_price_q:
        cut = np.quantile(sess["price"][u], low_price_q)
        u = u[sess["price"][u] > cut]
    return u


def picks(sess: dict[str, Any], u: np.ndarray, score: np.ndarray,
          frac: float = 0.2) -> np.ndarray:
    k = int(len(u) * frac)
    order = np.lexsort((np.asarray(sess["keys"])[u], -score[u]))
    return u[order[:k]]


def deciles(x: np.ndarray) -> np.ndarray:
    return np.minimum((unit_rank(x) + 0.5) * 10, 9.999).astype(int)


def c2_excess(sess: dict[str, Any], u: np.ndarray, sel: np.ndarray,
              exclude: np.ndarray | None = None) -> tuple[list[float], int]:
    """Per evaluable selected name: y - mean y of the non-selected (and non-excluded)
    evaluable names of its (turnover decile, ATR decile) cell. -> (diffs, unmatched)."""
    ev = sess["evaluable"]
    cell = dict(zip(u.tolist(), zip(deciles(sess["turnover"][u]).tolist(),
                                    deciles(sess["atr"][u]).tolist(), strict=True),
                    strict=True))
    taken = set(sel.tolist()) | (set(exclude.tolist()) if exclude is not None else set())
    pool: dict[tuple, list[float]] = {}
    for i in u.tolist():
        if i not in taken and ev[i]:
            pool.setdefault(cell[i], []).append(sess["y"][i])
    diffs, unmatched = [], 0
    for i in sel.tolist():
        if not ev[i]:
            continue
        c = pool.get(cell[i])
        if c:
            diffs.append(sess["y"][i] - float(np.mean(c)))
        else:
            unmatched += 1
    return diffs, unmatched


def evaluate_session(sess: dict[str, Any], u: np.ndarray, score: np.ndarray, *,
                     rng: np.random.Generator, frac: float = 0.2) -> dict[str, Any]:
    ev = sess["evaluable"]
    sel = picks(sess, u, score, frac)
    diffs, unmatched = c2_excess(sess, u, sel)
    rest = np.setdiff1d(u, sel)
    pseudo = rng.choice(rest, size=min(len(sel), len(rest)), replace=False)
    pdiffs, _ = c2_excess(sess, u, pseudo, exclude=sel)
    ue = u[ev[u]]
    se = sel[ev[sel]]
    return {"picks": [sess["keys"][i] for i in sel.tolist()], "n_universe": len(u),
            "n_picks": len(sel), "n_picks_evaluable": len(se), "unmatched": unmatched,
            "excess_c2": float(np.mean(diffs)) if diffs else None,
            "placebo_c2": float(np.mean(pdiffs)) if pdiffs else None,
            "pick_mean": float(sess["y"][se].mean()) if len(se) else None,
            "universe_mean": float(sess["y"][ue].mean()) if len(ue) else None,
            "ic": spearman(score[ue], sess["y"][ue]),
            "_universe_y": sess["y"][ue], "_k": len(se)}


# ── predictors ─────────────────────────────────────────────────────────────────────────
def reversal(sess: dict[str, Any]) -> np.ndarray:
    return -sess["X"][:, CORE24.index("ret_1d")]


def ranked_X(sess: dict[str, Any], u: np.ndarray) -> np.ndarray:
    return np.column_stack([unit_rank(sess["X"][u, j]) for j in range(sess["X"].shape[1])])


def ridge_fit(train: list[tuple[np.ndarray, np.ndarray]], alpha: float) -> np.ndarray:
    """No intercept: ranked features and ranked targets are centred per session."""
    X = np.vstack([t[0] for t in train])
    y = np.concatenate([t[1] for t in train])
    return np.linalg.solve(X.T @ X + alpha * np.eye(X.shape[1]), X.T @ y)


def ridge_rows(sess: dict[str, Any], u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Training rows of one session: ranked features and the rank of y, evaluable only."""
    e = u[sess["evaluable"][u]]
    if len(e) < 3:
        return np.empty((0, sess["X"].shape[1])), np.empty(0)
    return ranked_X(sess, e), unit_rank(sess["y"][e])


def ridge_score(sess: dict[str, Any], u: np.ndarray, w: np.ndarray) -> np.ndarray:
    s = np.full(len(sess["keys"]), -np.inf)
    s[u] = ranked_X(sess, u) @ w
    return s


# ── pooled results and acceptance ──────────────────────────────────────────────────────
def c1_permutation(per: list[dict[str, Any]], *, draws: int, seed: int) -> dict[str, Any]:
    """Pooled pick mean vs random same-size draws from each session's evaluable
    universe. p = (1 + #null >= observed) / (draws + 1)."""
    rng = np.random.default_rng(seed)
    rows = [p for p in per if p["_k"] and len(p["_universe_y"]) >= p["_k"]]
    if not rows:
        return {"observed": None, "null_mean": None, "p_one_sided": None}
    obs = float(np.mean([p["pick_mean"] for p in rows]))
    null = np.zeros(draws)
    for p in rows:
        uy, k = p["_universe_y"], p["_k"]
        null += np.array([rng.choice(uy, size=k, replace=False).mean() for _ in range(draws)])
    null /= len(rows)
    return {"observed": obs, "null_mean": float(null.mean()),
            "p_one_sided": float((1 + (null >= obs).sum()) / (draws + 1))}


def summarise(per: list[dict[str, Any]], folds: list[int], *, b: int, block: int,
              level: float, seed: int, perm_draws: int) -> dict[str, Any]:
    """per: chronological session results (one per TEST session); folds: their fold."""
    ex = [p["excess_c2"] for p in per]
    ok = [(e, f) for e, f in zip(ex, folds, strict=True) if e is not None]
    series = [e for e, _ in ok]
    pl = [p["placebo_c2"] for p in per if p["placebo_c2"] is not None]
    ics = [p["ic"] for p in per if p["ic"] is not None]
    by_fold: dict[int, list[float]] = {}
    for e, f in ok:
        by_fold.setdefault(f, []).append(e)
    turn = []
    for a, z in itertools.pairwise(per):
        if z["picks"]:
            turn.append(1 - len(set(a["picks"]) & set(z["picks"])) / len(z["picks"]))
    lo, hi = block_bootstrap_ci(series, b=b, block=block, level=level, seed=seed)
    plo, phi = (block_bootstrap_ci(pl, b=b, block=block, level=level, seed=seed + 1)
                if len(pl) > block else (None, None))
    return {
        "sessions": len(per), "sessions_with_excess": len(series),
        "primary_mean_excess_c2": float(np.mean(series)) if series else None,
        "primary_ci": [lo, hi], "ci_level": level,
        "placebo_mean": float(np.mean(pl)) if pl else None, "placebo_ci": [plo, phi],
        "fold_mean_excess": {str(f): float(np.mean(v)) for f, v in sorted(by_fold.items())},
        "hit_rate_sessions": float(np.mean([e > 0 for e in series])) if series else None,
        "rank_ic_mean": float(np.mean(ics)) if ics else None, "rank_ic_nw_t": nw_t(ics),
        "c0_universe_mean": float(np.mean([p["universe_mean"] for p in per
                                           if p["universe_mean"] is not None])),
        "pick_mean": float(np.mean([p["pick_mean"] for p in per
                                    if p["pick_mean"] is not None])),
        "c1": c1_permutation(per, draws=perm_draws, seed=seed + 2),
        "trades": int(sum(p["n_picks"] for p in per)),
        "trades_evaluable": int(sum(p["n_picks_evaluable"] for p in per)),
        "unmatched": int(sum(p["unmatched"] for p in per)),
        "turnover_mean": float(np.mean(turn)) if turn else None,
        "max_drawdown_excess": max_drawdown(series),
        "daily_excess": series,
    }


def acceptance(primary: dict[str, Any], *, folds_total: int,
               cost: dict[str, Any] | None, p1_mean: float | None = None,
               is_p2: bool = False) -> dict[str, str]:
    lo, hi = primary["primary_ci"]
    a1 = "PASS" if lo > 0 else ("FAIL" if hi < 0 else "UNPROVEN")
    if cost is None:
        a2 = "NOT_EVALUATED (no approved cost model)"
    else:
        rt = 2 * float(cost["per_side_bps"]) / 1e4
        m = primary["primary_mean_excess_c2"]
        a2 = "PASS" if m - rt > 0 and m - 1.5 * rt >= 0 else "FAIL"
    need = math.ceil(0.8 * folds_total)
    pos = sum(1 for v in primary["fold_mean_excess"].values() if v > 0)
    a3 = "PASS" if pos >= need else "FAIL"
    plo, phi = primary["placebo_ci"]
    a4 = ("UNPROVEN (too few placebo sessions)" if plo is None
          else "PASS" if plo <= 0 <= phi else "FAIL")
    out = {"A1": a1, "A2": a2, "A3": f"{a3} ({pos}/{folds_total} folds > 0, need {need})",
           "A4": a4}
    if is_p2:
        out["A5"] = ("PASS" if p1_mean is not None
                     and primary["primary_mean_excess_c2"] > p1_mean else "FAIL (P2 dropped)")
    return out


def net_view(primary: dict[str, Any], per_side_bps: float) -> dict[str, float]:
    rt = 2 * per_side_bps / 1e4
    return {"per_side_bps": per_side_bps,
            "net_excess_c2": primary["primary_mean_excess_c2"] - rt,
            "net_long_abs": primary["pick_mean"] - rt}
