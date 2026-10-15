"""Stage 4 E3: monthly, low-turnover selection. PURE computation only; no I/O, no
database, no run. Design: docs/STAGE4_E3_DESIGN_DRAFT.md (decisions D1-D6 approved by
the user 2026-10-15; step 1 = code + synthetic tests).

Timing (one convention): formation F = the last trading session of a calendar month;
signals use bars of sessions <= F only (knowable after F's close); the portfolio is
bought at the official open of F + 1 (the month's first session) and sold at the open
of the first session of the following month. Portfolios do not overlap: one inference
unit per month. Prices arrive split/bonus-adjusted (vendor basis before 2025-09,
assumption A-1); a residual unexplained jump marks a SUSPECT session.

  plan          month_plan: (formation, entry, exit) session indices
  signals       mom_12_1, high_52w_proximity
  universe      eligible(): history, price, liquidity, no suspect in the lookback
  book          month_book: equal weight, rebalanced with netting; costs via e2
  controls      e2.matched_controls (turnover decile x 60-session volatility decile)
  inference     studentized block bootstrap (e2) + Newey-West (e1), monthly
"""

from __future__ import annotations

import datetime as _dt
import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.training import e1 as E
from app.training import e2 as X

LOOKBACK, SKIP, MIN_HISTORY = 252, 21, 260
TURNOVER_WINDOW, VOL_WINDOW = 60, 60
MIN_PRICE, UNIVERSE_TOP, K = 20.0, 500, 10
SUSPECT_MOVE = 0.25
BLOCK_MONTHS, NW_LAG = 3, 2


# ── calendar ─────────────────────────────────────────────────────────────────────────
def month_plan(sessions: list[_dt.date]) -> list[tuple[int, int, int]]:
    """(formation, entry, exit) indices: formation = the last session of each month,
    entry = the next session (first of the next month), exit = the first session of the
    month after. A month without both a complete next month and its successor's first
    session is not planned."""
    firsts = [i for i in range(1, len(sessions))
              if (sessions[i].year, sessions[i].month)
              != (sessions[i - 1].year, sessions[i - 1].month)]
    return [(e - 1, e, x) for e, x in itertools.pairwise(firsts)]


# ── signals (past information only: indices <= f) ────────────────────────────────────
def _v(a: list[float | None], i: int) -> float | None:
    return a[i] if 0 <= i < len(a) and a[i] is not None and a[i] > 0 else None


def mom_12_1(close: list[float | None], f: int) -> float | None:
    """close(f - 21) / close(f - 252) - 1."""
    a, b = _v(close, f - LOOKBACK), _v(close, f - SKIP)
    return b / a - 1 if a and b else None


def high_52w_proximity(close: list[float | None], high: list[float | None],
                       f: int) -> float | None:
    """close(f) / max(high over f - 251 .. f)."""
    c = _v(close, f)
    hs = [h for h in high[max(0, f - LOOKBACK + 1):f + 1] if h is not None and h > 0]
    return c / max(hs) if c and hs and f - LOOKBACK + 1 >= 0 else None


PREDICTORS = {"mom_12_1": lambda s, f: mom_12_1(s["close"], f),
              "high_52w": lambda s, f: high_52w_proximity(s["close"], s["high"], f)}


# ── data quality ─────────────────────────────────────────────────────────────────────
def suspect_sessions(s: dict[str, list], exact_factor_days: set[int] | None = None,
                     threshold: float = SUSPECT_MOVE) -> set[int]:
    """Sessions with |close/prev close - 1| or |open/prev close - 1| > threshold and no
    EXACT split/bonus factor that day (an unrecorded corporate action on the vendor
    basis), plus sessions with a non-positive or malformed bar."""
    out, ex = set(), exact_factor_days or set()
    c, o = s["close"], s["open"]
    for i in range(1, len(c)):
        pc, ci, oi = _v(c, i - 1), c[i], o[i]
        if ci is None or oi is None:
            continue
        if ci <= 0 or oi <= 0:
            out.add(i)
            continue
        if pc and i not in ex and (abs(ci / pc - 1) > threshold or abs(oi / pc - 1) > threshold):
            out.add(i)
    return out


# ── universe (past only) ─────────────────────────────────────────────────────────────
def median_turnover(s: dict[str, list], f: int, n: int = TURNOVER_WINDOW) -> float | None:
    vals = [c * v for c, v in zip(s["close"][max(0, f - n + 1):f + 1],
                                  s["volume"][max(0, f - n + 1):f + 1], strict=True)
            if c is not None and v is not None and c > 0 and v >= 0]
    return float(np.median(vals)) if len(vals) >= n // 2 else None


def volatility(s: dict[str, list], f: int, n: int = VOL_WINDOW) -> float | None:
    c = [x for x in s["close"][max(0, f - n):f + 1] if x is not None and x > 0]
    if len(c) < n // 2:
        return None
    r = np.diff(np.log(c))
    return float(r.std()) if len(r) > 1 else None


def eligible(series: dict[str, dict], f: int, suspect: dict[str, set[int]], *,
             top: int = UNIVERSE_TOP) -> list[tuple[str, float, float]]:
    """[(key, turnover, volatility)] of the PIT universe at f, ranked by turnover
    (desc, key): >= MIN_HISTORY valid closes up to f, close >= MIN_PRICE, and no suspect
    session in (f - LOOKBACK, f]."""
    rows = []
    for k, s in series.items():
        c = _v(s["close"], f)
        if not c or c < MIN_PRICE:
            continue
        if sum(1 for x in s["close"][:f + 1] if x is not None and x > 0) < MIN_HISTORY:
            continue
        if any(f - LOOKBACK < x <= f for x in suspect.get(k, ())):
            continue
        t, v = median_turnover(s, f), volatility(s, f)
        if t is not None and v is not None:
            rows.append((k, t, v))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows[:top]


def pick(universe: list[tuple[str, float, float]], scores: dict[str, float | None],
         k: int = K) -> list[str]:
    """Top k by score (desc, key); names without a score are never picked."""
    ok = [(scores[u[0]], u[0]) for u in universe if scores.get(u[0]) is not None]
    ok.sort(key=lambda x: (-x[0], x[1]))
    return [key for _, key in ok[:k]]


# ── formation of every arm (no label or future price is read) ────────────────────────
ARMS = ("P", "C2", "PL", "PLC", "C0")


def form_month(series: dict[str, dict], f: int, suspect: dict[str, set[int]], predictor: str,
               *, k: int = K, seed: int = 0, perm_draws: int = 0) -> dict[str, Any]:
    u = eligible(series, f, suspect)
    keys = [r[0] for r in u]
    scores = {key: PREDICTORS[predictor](series[key], f) for key in keys}
    p = pick(u, scores, k)
    rng = np.random.default_rng([seed, f])
    turn = np.array([r[1] for r in u])
    vol = np.array([r[2] for r in u])
    c2, unmatched = X.matched_controls(keys, turn, vol, p, rng) if keys else ([], 0)
    pl = X.placebo_picks(keys, p, rng) if len(keys) > len(p) else []
    plc, _ = X.matched_controls(keys, turn, vol, pl, rng, exclude=set(p)) if pl else ([], 0)
    perms = []
    for j in range(perm_draws):
        r = np.random.default_rng([seed, f, j + 1])
        perms.append([keys[i] for i in sorted(r.choice(len(keys), size=min(len(p), len(keys)),
                                                       replace=False))])
    return {"f": f, "arms": dict(zip(ARMS, (p, c2, pl, plc, keys), strict=True)),
            "perm": perms, "unmatched": unmatched, "universe": len(keys)}


def masked(suspect: dict[str, set[int]], key: str, entry: int, exit_: int) -> bool:
    """A suspect session inside the holding window [entry, exit]."""
    return any(entry <= x <= exit_ for x in suspect.get(key, ()))


def apply_mask(month: dict[str, Any], suspect: dict[str, set[int]], entry: int,
               exit_: int) -> dict[str, Any]:
    """Drop masked names from EVERY arm and permutation after selection (E2 Amendment 3)."""
    def f(names: list[str]) -> list[str]:
        return [n for n in names if not masked(suspect, n, entry, exit_)]
    return {**month, "arms": {a: f(v) for a, v in month["arms"].items()},
            "perm": [f(pp) for pp in month["perm"]],
            "masked_picks": len(month["arms"]["P"]) - len(f(month["arms"]["P"]))}


# ── the monthly book ─────────────────────────────────────────────────────────────────
def _last_open(s: dict[str, list], i: int, floor: int) -> float | None:
    for j in range(i, floor - 1, -1):
        if (v := _v(s["open"], j)) is not None:
            return v
    return None


@dataclass
class Month:
    f: int
    gross: float
    buys: dict[str, float]          # traded value as a fraction of book value
    sells: dict[str, float]
    names: int
    missing_exit: int


@dataclass
class Book:
    months: list[Month] = field(default_factory=list)


def month_book(arm_by_month: list[tuple[int, int, int, list[str]]],
               series: dict[str, dict]) -> Book:
    """Equal-weight monthly portfolios bought at the entry open, valued at the exit open
    (a name without an exit open is valued at its last open in the window and counted).
    Rebalancing nets: a held name re-picked trades only the difference between its
    drifted weight and the new target; turnover is what is actually traded."""
    book, held = Book(), {}
    for f, entry, exit_, names in arm_by_month:
        names = [n for n in names if _v(series[n]["open"], entry)]
        target = {n: 1.0 / len(names) for n in names} if names else {}
        buys = {n: w - held.get(n, 0.0) for n, w in target.items() if w > held.get(n, 0.0) + 1e-15}
        sells = {n: held[n] - target.get(n, 0.0) for n in held
                 if held[n] > target.get(n, 0.0) + 1e-15}
        gross, drift, miss = 0.0, {}, 0
        for n, w in target.items():
            a = _v(series[n]["open"], entry)
            b = _v(series[n]["open"], exit_)
            if b is None:
                miss += 1
                b = _last_open(series[n], exit_ - 1, entry)
            r = b / a - 1
            gross += w * r
            drift[n] = w * (1 + r)
        tot = sum(drift.values())
        held = {n: v / tot for n, v in drift.items()} if tot > 0 else {}
        book.months.append(Month(f, gross if target else 0.0, buys, sells, len(target), miss))
    return book


def month_costs(m: Month, cm: X.CostModel) -> dict[str, float]:
    """One rebalance's costs by part as a fraction of book value (e2's cost model; the
    spread uses the formation index as the session key)."""
    day = X.BookDay(m.f, m.gross, m.buys, m.sells, m.names, m.missing_exit)
    return cm.day_cost_parts(day)


def primary_series(p: Book, c2: Book, cm: X.CostModel) -> list[float]:
    """s_m = P_gross - cost(P) - C2_gross (E2 PC-1a; the control is untraded)."""
    return [a.gross - sum(month_costs(a, cm).values()) - b.gross
            for a, b in zip(p.months, c2.months, strict=True)]


# ── inference and acceptance ─────────────────────────────────────────────────────────
@dataclass
class Result:
    mean: float
    ci: tuple[float, float]
    n: int
    nw_t: float | None
    year_means: dict[int, float]
    max_drawdown: float


def summarise(x: list[float], years: list[int], *, b: int = 10_000, level: float = 0.975,
              seed: int = 0, block: int = BLOCK_MONTHS) -> Result:
    ci = X.studentized_block_ci(x, b=b, block=block, level=level, seed=seed)
    by: dict[int, list[float]] = {}
    for v, y in zip(x, years, strict=True):
        by.setdefault(y, []).append(v)
    return Result(float(np.mean(x)), ci, len(x), E.nw_t(x, lags=NW_LAG),
                  {y: float(np.mean(v)) for y, v in sorted(by.items())}, E.max_drawdown(x))


def acceptance(primary: Result, *, at_stress: float, placebo: Result,
               other_mean: float | None = None, need_years: int = 4) -> dict[str, Any]:
    pos = sum(1 for v in primary.year_means.values() if v > 0)
    acc = {"A1": X.verdict(primary.ci),
           "A2": "PASS" if at_stress >= 0 else "FAIL",
           "A3": "PASS" if pos >= need_years else "FAIL",
           "A3_positive_years": f"{pos}/{len(primary.year_means)}",
           "A4": "PASS" if placebo.ci[0] <= 0 <= placebo.ci[1] else "FAIL",
           "A5": None if other_mean is None else ("PASS" if primary.mean > other_mean
                                                   else "FAIL"),
           "A6": {"max_drawdown": primary.max_drawdown}}
    return {**acc, "candidate": X.candidate_status(acc, primary.nw_t,
                                                   is_p2=other_mean is not None)}


def years_of(sessions: list[_dt.date], plan: list[tuple[int, int, int]]) -> list[int]:
    """The calendar year of each holding month (the entry session's year)."""
    return [sessions[e].year for _, e, _ in plan]


def minimum_detectable(sd: float, n: int, z_alpha: float = 1.96, z_power: float = 0.84) -> float:
    return (z_alpha + z_power) * sd / math.sqrt(n) if n > 0 else float("inf")
