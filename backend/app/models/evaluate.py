"""E5 evaluation of out-of-sample predictions, one session at a time, then pooled.

Per session (rows: the universe, evaluable = label known and not masked)
  classification  AUC of prob_up for up (ret_oc > cost), accuracy at 0.5, Brier score
  ranking         rank IC of exp_return with ret_oc; hit rate = sign agreement
  range           share of ret_oc inside [range_lo, range_hi] (target 80 %); rank
                  correlation of volatility with the realised range
  picks           precision = share of picks that were up; recall = share of up names
                  picked (in the universe)
  book (E4 machinery)  s = picks' gross open -> close - their MIS cost - the gross of
                  matched controls (same turnover tercile x volatility tercile x ret_5d
                  quintile cell, untraded); no pick -> cash (s = 0, cost 0)
Pooled: means, the sign-flip CI of s (level 0.975), annualised Sharpe of the net book
(picks' net return) and of s, maximum drawdown. Not a profitability claim.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.models import data as D
from app.training import e1 as E1
from app.training import e4 as E4


def auc(score: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return None
    r = E1.rankdata(score)
    return float((r[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum()))


def _controls(sess: D.Session, u: np.ndarray, picks: list[int], seed: int) -> list[int]:
    """Matched controls of the picks; picks and the result are POSITIONS within u."""
    rows = [(str(j), sess.col("turnover_20")[i], sess.col("volatility_20")[i],
             sess.col("ret_5d")[i]) for j, i in enumerate(u)]
    rng = np.random.default_rng([seed, sess.date.toordinal()])
    c, _ = E4.matched_controls(rows, [str(j) for j in picks], rng)
    return [int(x) for x in c]


def session(sess: D.Session, out: dict[str, Any], picks: list[int], cost: float,
            seed: int = 0) -> dict[str, Any]:
    u = out["idx"]
    y = sess.y["ret_oc"][u]
    ev = ~np.isnan(y) & ~sess.masked[u]
    r: dict[str, Any] = {"date": str(sess.date), "universe": len(u), "evaluable": int(ev.sum()),
                         "picks": len(picks)}
    if ev.sum() < 20:
        return {**r, "skipped": "fewer than 20 evaluable names"}
    ye, up = y[ev], (y[ev] > cost).astype(int)
    p = out["prob_up"][ev]
    r["auc"] = auc(p, up)
    r["accuracy"] = float(((p > 0.5).astype(int) == up).mean())
    r["brier"] = float(np.mean((p - up) ** 2))
    r["ic"] = E1.spearman(out["exp_return"][ev], ye)
    r["hit_rate"] = float((np.sign(out["exp_return"][ev]) == np.sign(ye)).mean())
    lo, hi = out["range_lo"][ev], out["range_hi"][ev]
    r["range_coverage"] = float(((ye >= lo) & (ye <= hi)).mean())
    real = (sess.y["high_exc"][u] - sess.y["low_exc"][u])[ev]
    r["vol_ic"] = E1.spearman(out["volatility"][ev], real)
    ev_picks = [j for j in picks if ev[j]]
    up_all = (y > cost) & ev
    r["precision"] = (float(np.mean([y[j] > cost for j in ev_picks])) if ev_picks else None)
    r["recall"] = (float(sum(1 for j in ev_picks if up_all[j]) / up_all.sum())
                   if up_all.sum() else None)
    if not ev_picks:
        return {**r, "p_gross": 0.0, "p_cost": 0.0, "c2_gross": 0.0, "s": 0.0, "cash": True}
    rp = [float(y[j]) for j in ev_picks]
    names = [str(j) for j in ev_picks]
    c = E4.SessionCost(1_000_000.0).fraction(names, rp)
    ctrl = [j for j in _controls(sess, u, ev_picks, seed) if ev[j]]
    gc = float(np.mean([y[j] for j in ctrl])) if ctrl else None
    gp = float(np.mean(rp))
    return {**r, "p_gross": gp, "p_cost": c, "c2_gross": gc,
            "s": None if gc is None else gp - c - gc, "cash": False}


def _mean(x: list) -> float | None:
    v = [a for a in x if a is not None]
    return float(np.mean(v)) if v else None


def pooled(per: list[dict[str, Any]], *, level: float = 0.975, seed: int = 0) -> dict[str, Any]:
    rows = [p for p in per if "skipped" not in p]
    s = [p["s"] for p in rows if p.get("s") is not None]
    net = [p["p_gross"] - p["p_cost"] for p in rows if p.get("s") is not None]
    out: dict[str, Any] = {"sessions": len(rows), "skipped": len(per) - len(rows),
                           "cash_sessions": sum(1 for p in rows if p.get("cash"))}
    for k in ("auc", "accuracy", "brier", "ic", "hit_rate", "range_coverage", "vol_ic",
              "precision", "recall", "picks"):
        out[k] = _mean([p.get(k) for p in rows])
    ic = [p["ic"] for p in rows if p.get("ic") is not None]
    out["ic_t"] = (float(np.mean(ic) / (np.std(ic, ddof=1) / math.sqrt(len(ic))))
                   if len(ic) > 2 and np.std(ic) > 0 else None)
    if len(s) >= 2:
        out["s_mean"] = float(np.mean(s))
        out["s_ci"] = list(E4.signflip_ci(s, level=level, seed=seed))
        out["s_sharpe_ann"] = _sharpe(s)
        out["net_mean"] = float(np.mean(net))
        out["net_sharpe_ann"] = _sharpe(net)
        out["net_max_drawdown"] = E1.max_drawdown(net)
        out["minimum_detectable"] = E4.minimum_detectable(float(np.std(s, ddof=1)), len(s))
    return out


def _sharpe(x: list[float]) -> float | None:
    sd = float(np.std(x, ddof=1))
    return float(np.mean(x) / sd * math.sqrt(252)) if sd > 0 else None
