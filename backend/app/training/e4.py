"""Stage 4 E4a: intraday (same-day, MIS) gap selection. PURE computation only; no I/O,
no database, no run. Design: docs/STAGE4_E4_INTRADAY_DESIGN_DRAFT.md (decisions D1-D6
approved by the user 2026-10-15; step 1 = code + synthetic tests).

Timing (one convention): the signal instant is 09:15 IST of session d, when the official
open (the final pre-open equilibrium price) is known. Signals use the open of d and
bars of sessions < d only. Every position is bought at the open of d and sold at the
close of d (MIS: no position crosses the night). Entry at the official open is an
ASSUMPTION for daily data (design A-3): costs add a half-spread and a slippage sweep.

  signals     gap(d) = open(d) / close(d - 1) - 1;  P1 gap_fade = -gap;
              P2 gap_and_go = +gap when volume(d - 1) > 1.5 x mean volume(d - 21 .. d - 2)
  universe    past-only: history, price, liquidity (e3), no suspect session in the
              lookback, and today's gap itself not a data error (|gap| > 25% unexplained)
  controls    matched by turnover tercile x volatility tercile x gap quintile (a gap-fade
              pick is compared with names that gapped alike)
  mask        after selection, every arm: a name whose day d is locked (high == low,
              no tradable range: a circuit) is dropped
  costs       MIS rates (e2.Rates) on a full round trip every session, plus half-spread
              and slippage on both sides; the control is untraded (E2 PC-1a)
  inference   studentized block bootstrap (block 5 sessions) + Newey-West (lag 4); A3 by
              calendar year
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.training import e1 as E1
from app.training import e2 as X
from app.training import e3 as E3

UNIVERSE_TOP, K, MIN_PRICE = 500, 10, 50.0
VOLUME_SPIKE, VOLUME_WINDOW = 1.5, 20
# correction C1 (user-approved 2026-10-16; docs/STAGE4_E4_CALIBRATION_RESULT.md): block 5
# under-covered the factor worlds (volatility half-life ~14 sessions); fixed, not searched
BLOCK, NW_LAG = 20, 19
GAP_ERROR = 0.25
MIS = X.Rates(brokerage_flat_inr=20.0, brokerage_pct=0.0006, stt_buy=0.0, stt_sell=0.00025,
              stamp_buy=0.00003, exchange_txn=0.0000307, sebi=0.000001, gst=0.18,
              dp_per_scrip_sell_inr=0.0,
              source="Upstox GET /v2/charges/brokerage, product I (intraday)",
              as_of="2026-10-13T09:36:18Z")


# ── signals (knowable at 09:15 of d) ─────────────────────────────────────────────────
def _v(a: list[float | None], i: int) -> float | None:
    return a[i] if 0 <= i < len(a) and a[i] is not None and a[i] > 0 else None


def gap(s: dict[str, list], d: int) -> float | None:
    o, pc = _v(s["open"], d), _v(s["close"], d - 1)
    return o / pc - 1 if o and pc else None


def volume_spike(s: dict[str, list], d: int) -> bool:
    """volume(d - 1) > 1.5 x mean volume(d - 21 .. d - 2): sessions before d only."""
    last = s["volume"][d - 1] if d >= 1 else None
    prev = [v for v in s["volume"][max(0, d - 1 - VOLUME_WINDOW):d - 1] if v is not None]
    return bool(last is not None and len(prev) >= VOLUME_WINDOW // 2
                and last > VOLUME_SPIKE * float(np.mean(prev)))


def gap_fade(s: dict[str, list], d: int) -> float | None:
    g = gap(s, d)
    return None if g is None else -g


def gap_and_go(s: dict[str, list], d: int) -> float | None:
    g = gap(s, d)
    return g if g is not None and volume_spike(s, d) else None


PREDICTORS = {"gap_fade": gap_fade, "gap_and_go": gap_and_go}


# ── universe (past only, plus today's open) ──────────────────────────────────────────
def eligible(series: dict[str, dict], d: int, suspect: dict[str, set[int]], *,
             top: int = UNIVERSE_TOP) -> list[tuple[str, float, float, float]]:
    """[(key, turnover, volatility, gap)] at 09:15 of d, ranked by turnover (desc, key):
    the e3 history/liquidity rules evaluated at d - 1, close(d - 1) >= MIN_PRICE, no
    suspect session in the lookback (sessions < d), and |gap(d)| <= GAP_ERROR."""
    rows = []
    for k, s in series.items():
        pc = _v(s["close"], d - 1)
        g = gap(s, d)
        if not pc or pc < MIN_PRICE or g is None or abs(g) > GAP_ERROR:
            continue
        if sum(1 for x in s["close"][:d] if x is not None and x > 0) < E3.MIN_HISTORY:
            continue
        if any(d - E3.LOOKBACK < x < d for x in suspect.get(k, ())):
            continue
        t, v = E3.median_turnover(s, d - 1), E3.volatility(s, d - 1)
        if t is not None and v is not None:
            rows.append((k, t, v, g))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows[:top]


def bins(x: np.ndarray, n: int) -> np.ndarray:
    """Cross-sectional rank bins 0 .. n - 1 (ties averaged, as e1.deciles)."""
    return np.minimum((E1.unit_rank(x) + 0.5) * n, n - 1e-9).astype(int)


def matched_controls(u: list[tuple[str, float, float, float]], chosen: list[str],
                     rng: np.random.Generator,
                     exclude: set[str] | None = None) -> tuple[list[str], int]:
    """One control per chosen name: a random not-chosen universe name of the same
    (turnover tercile, volatility tercile, gap quintile) cell, without replacement."""
    if not u:
        return [], len(chosen)
    keys = [r[0] for r in u]
    cells = list(zip(bins(np.array([r[1] for r in u]), 3).tolist(),
                     bins(np.array([r[2] for r in u]), 3).tolist(),
                     bins(np.array([r[3] for r in u]), 5).tolist(), strict=True))
    cell = dict(zip(keys, cells, strict=True))
    taken = set(chosen) | (exclude or set())
    pool: dict[tuple, list[str]] = {}
    for k in keys:
        if k not in taken:
            pool.setdefault(cell[k], []).append(k)
    out, unmatched = [], 0
    for k in chosen:
        cand = pool.get(cell.get(k), [])
        if not cand:
            unmatched += 1
            continue
        out.append(cand.pop(int(rng.integers(len(cand)))))
    return out, unmatched


ARMS = ("P", "C2", "PL", "PLC", "C0")


def form_session(series: dict[str, dict], d: int, suspect: dict[str, set[int]],
                 predictor: str, *, k: int = K, seed: int = 0,
                 perm_draws: int = 0) -> dict[str, Any]:
    """Every arm at 09:15 of d. Reads opens up to d and other fields before d only."""
    u = eligible(series, d, suspect)
    keys = [r[0] for r in u]
    scores = {r[0]: PREDICTORS[predictor](series[r[0]], d) for r in u}
    ok = sorted(((sc, key) for key, sc in scores.items() if sc is not None),
                key=lambda x: (-x[0], x[1]))
    p = [key for _, key in ok[:k]]
    rng = np.random.default_rng([seed, d])
    c2, unmatched = matched_controls(u, p, rng)
    rest = [x for x in keys if x not in set(p)]
    pl = [rest[i] for i in sorted(rng.choice(len(rest), size=min(len(p), len(rest)),
                                             replace=False))] if rest and p else []
    plc, _ = matched_controls(u, pl, rng, exclude=set(p)) if pl else ([], 0)
    perms = []
    for j in range(perm_draws):
        r = np.random.default_rng([seed, d, j + 1])
        perms.append([keys[i] for i in sorted(r.choice(len(keys), size=min(len(p), len(keys)),
                                                       replace=False))] if keys else [])
    return {"d": d, "arms": dict(zip(ARMS, (p, c2, pl, plc, keys), strict=True)),
            "perm": perms, "unmatched": unmatched, "universe": len(keys)}


def locked(s: dict[str, list], d: int) -> bool:
    """No tradable range on d (high == low): a circuit-locked day."""
    h, lo = _v(s["high"], d), _v(s["low"], d)
    return h is None or lo is None or h == lo


def apply_mask(sess: dict[str, Any], series: dict[str, dict]) -> dict[str, Any]:
    """After selection, drop locked names from every arm and permutation alike."""
    d = sess["d"]

    def f(names: list[str]) -> list[str]:
        return [n for n in names if not locked(series[n], d)]
    return {**sess, "arms": {a: f(v) for a, v in sess["arms"].items()},
            "perm": [f(pp) for pp in sess["perm"]],
            "masked_picks": len(sess["arms"]["P"]) - len(f(sess["arms"]["P"]))}


# ── the session book ─────────────────────────────────────────────────────────────────
def oc_return(s: dict[str, list], d: int) -> float | None:
    o, c = _v(s["open"], d), _v(s["close"], d)
    return c / o - 1 if o and c else None


def arm_return(names: list[str], series: dict[str, dict], d: int) -> float | None:
    """Equal-weight open -> close return of the arm on d (names without a valid
    open/close on d are dropped from the arm)."""
    rs = [r for n in names if (r := oc_return(series[n], d)) is not None]
    return float(np.mean(rs)) if rs else None


@dataclass(frozen=True)
class SessionCost:
    capital_inr: float
    half_spread_bps: float = 5.0
    slippage_bps: float = 0.0
    multiplier: float = 1.0
    rates: X.Rates = MIS

    def fraction(self, names: list[str], returns: list[float]) -> float:
        """A full MIS round trip on every pick, as a fraction of the book: buy 1/n at
        the open, sell the drifted value at the close; spread and slippage both sides."""
        n = len(names)
        if n == 0:
            return 0.0
        cm = X.CostModel(self.rates, self.capital_inr, self.half_spread_bps,
                         self.slippage_bps, self.multiplier)
        day = X.BookDay(0, 0.0, {k: 1.0 / n for k in names},
                        {k: (1.0 + r) / n for k, r in zip(names, returns, strict=True)}, n, 0)
        return sum(cm.day_cost_parts(day).values())


def primary(sess: dict[str, Any], series: dict[str, dict], cost: SessionCost) -> dict[str, Any]:
    """s_d = P gross - cost(P) - C2 gross (the control is untraded); the placebo is gross."""
    d, arms = sess["d"], sess["arms"]
    p = [n for n in arms["P"] if oc_return(series[n], d) is not None]
    rp = [oc_return(series[n], d) for n in p]
    gp = float(np.mean(rp)) if rp else None
    gc = arm_return(arms["C2"], series, d)
    gpl, gplc = arm_return(arms["PL"], series, d), arm_return(arms["PLC"], series, d)
    c = cost.fraction(p, rp)
    return {"d": d, "p_gross": gp, "c2_gross": gc, "cost": c,
            "s": None if gp is None or gc is None else gp - c - gc,
            "placebo": None if gpl is None or gplc is None else gpl - gplc,
            "c0_gross": arm_return(arms["C0"], series, d), "picks": len(p)}


# ── inference and acceptance (E3 machinery, session unit) ────────────────────────────
def summarise(x: list[float], years: list[int], *, b: int = 10_000, level: float = 0.975,
              seed: int = 0) -> E3.Result:
    ci = X.studentized_block_ci(x, b=b, block=BLOCK, level=level, seed=seed)
    by: dict[int, list[float]] = {}
    for v, y in zip(x, years, strict=True):
        by.setdefault(y, []).append(v)
    return E3.Result(float(np.mean(x)), ci, len(x), E1.nw_t(x, lags=NW_LAG),
                     {y: float(np.mean(v)) for y, v in sorted(by.items())},
                     E1.max_drawdown(x))


def acceptance(prim: E3.Result, *, at_stress: float, placebo: E3.Result,
               need_years: int = 4) -> dict[str, Any]:
    """E4 gates; P1 and P2 are independent hypotheses (no A5)."""
    return E3.acceptance(prim, at_stress=at_stress, placebo=placebo, other_mean=None,
                         need_years=need_years)


def minimum_detectable(sd: float, n: int) -> float:
    return (1.96 + 0.84) * sd / math.sqrt(n) if n > 0 else float("inf")
