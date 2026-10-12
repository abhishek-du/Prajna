"""Shadow log for E1 (approved by the user 2026-10-12): forward, point-in-time evidence
and real opening spreads. LOGGING ONLY - no order, no position, no broker call, no
database write. Pure computation; the I/O lives in ops/measure/shadow_e1.py.

Each trading day D (NORMAL session):
  picks     (cron 09:06 IST, before the 09:15 open) from the PRODUCTION PRE_SESSION
            feature_value rows of D (registry must equal the active one): the universe
            (top 500 by turnover_20 among names with all 24 core features VALID), every
            universe member's P1 and P2 score, and the top-quintile picks of each.
  open      (cron 09:45, after the pre-open capture's replay) the real level-1 quote of
            every universe member from preopen_tick/preopen_book: the first two-sided
            quote at or after 09:15:00 and the median spread over 09:15-09:20.
  outcomes  (same cron, for earlier days whose daily bar is canonical) open-to-close
            return of every universe member and the E1 session metrics (C2 excess,
            placebo, IC) with the same code as E1.
P1 = reversal. P2 = the E1 fold-4 ridge (TRAIN 2025-09-24..2026-07-20, alpha 100, from
config 82e828c8...), frozen once; P2 was dropped in E1 (A5) and is logged for forward
evidence only.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import numpy as np

from app.training import e1 as E

OPEN_FROM, OPEN_FIRST_UNTIL, OPEN_UNTIL = _dt.time(9, 15), _dt.time(9, 16), _dt.time(9, 20)
MARKET_OPEN = _dt.time(9, 15)


def session_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """rows: {instrument_key, feature_id, value} of one session -> the E1 session dict of
    the names with all 24 core features VALID (no label: y unknown at pick time)."""
    by: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["value"] is not None:
            by.setdefault(r["instrument_key"], {})[r["feature_id"]] = float(r["value"])
    keys = sorted(k for k, f in by.items() if len(f) == len(E.CORE24))
    if not keys:
        return None
    X = np.array([[by[k][f] for f in E.CORE24] for k in keys])
    n = len(keys)
    return {"keys": keys, "X": X, "y": np.full(n, np.nan),
            "turnover": X[:, E.CORE24.index("turnover_20")],
            "atr": X[:, E.CORE24.index("atr_pct_14")], "price": X[:, E.CORE24.index("sma_20")],
            "evaluable": np.zeros(n, bool)}


def make_picks(sess: dict[str, Any], w: np.ndarray, *, top: int = 500,
               frac: float = 0.2) -> dict[str, Any]:
    u = E.universe(sess, top)
    p1 = E.reversal(sess)
    p2 = E.ridge_score(sess, u, w)
    keys = sess["keys"]
    return {
        "eligible": len(keys), "universe_size": len(u),
        "universe": [{"key": keys[i], "turnover_20": float(sess["turnover"][i]),
                      "atr_pct_14": float(sess["atr"][i]), "sma_20": float(sess["price"][i]),
                      "p1": float(p1[i]), "p2": float(p2[i])} for i in u.tolist()],
        "picks": {"p1_reversal": [keys[i] for i in E.picks(sess, u, p1, frac).tolist()],
                  "p2_ridge24": [keys[i] for i in E.picks(sess, u, p2, frac).tolist()]},
    }


def open_quotes(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """rows: {key, ist_time, bid, ask, ltp} level-1 ticks of 09:15-09:20 (any order)
    -> per key: first two-sided quote in [09:15, 09:16), its spread in bps of mid, the
    median spread over two-sided ticks in [09:15, 09:20], and the first LTP."""
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["key"], []).append(r)
    out = {}
    for k, rs in by.items():
        rs.sort(key=lambda r: r["ist_time"])
        two = [r for r in rs if r["bid"] and r["ask"] and r["bid"] > 0 and r["ask"] >= r["bid"]
               and OPEN_FROM <= r["ist_time"] <= OPEN_UNTIL]
        first = next((r for r in two if r["ist_time"] < OPEN_FIRST_UNTIL), None)
        bps = [float((r["ask"] - r["bid"]) / ((r["ask"] + r["bid"]) / 2) * 10000) for r in two]
        ltp = next((r["ltp"] for r in rs if r["ltp"] and r["ist_time"] >= OPEN_FROM), None)
        out[k] = {"first_bid": float(first["bid"]) if first else None,
                  "first_ask": float(first["ask"]) if first else None,
                  "first_time": first["ist_time"].isoformat() if first else None,
                  "first_spread_bps": (float((first["ask"] - first["bid"])
                                             / ((first["ask"] + first["bid"]) / 2) * 10000)
                                       if first else None),
                  "median_spread_bps_0915_0920": float(np.median(bps)) if bps else None,
                  "two_sided_ticks": len(two),
                  "first_ltp": float(ltp) if ltp is not None else None}
    return out


def evaluate_day(picks_doc: dict[str, Any], y: dict[str, float], *,
                 seed: int, day: _dt.date) -> dict[str, Any]:
    """E1 session metrics of one logged day from its stored universe and the realised
    open-to-close returns (missing -> not evaluable). No masks: corporate-action windows
    are not known at pick time; they are reported, never used to select."""
    uni = picks_doc["universe"]
    keys = [u["key"] for u in uni]
    yy = np.array([y.get(k, np.nan) for k in keys], dtype=float)
    sess = {"keys": keys, "X": np.zeros((len(keys), 1)), "y": yy,
            "turnover": np.array([u["turnover_20"] for u in uni]),
            "atr": np.array([u["atr_pct_14"] for u in uni]),
            "price": np.array([u["sma_20"] for u in uni]), "evaluable": ~np.isnan(yy)}
    u = np.arange(len(keys))
    out = {}
    for name, col in (("p1_reversal", "p1"), ("p2_ridge24", "p2")):
        score = np.array([x[col] for x in uni])
        r = E.evaluate_session(sess, u, score,
                               rng=np.random.default_rng([seed, day.toordinal()]))
        assert r["picks"] == picks_doc["picks"][name], "stored picks differ from the recompute"
        out[name] = {k: v for k, v in r.items() if not k.startswith("_")}
    out["evaluable"] = int((~np.isnan(yy)).sum())
    return out
