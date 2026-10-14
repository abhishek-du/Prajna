"""Stage 4 E2: multi-session holding with staggered tranches. PURE computation only;
no I/O, no database, no run. The protocol is docs/STAGE4_E2_PREREGISTRATION.md
(DRAFT: not approved to run; cost decisions C1-C4 approved 2026-10-14, Amendment 1).

Timing (one convention everywhere): a tranche is formed from the PRE_SESSION features
of session d, bought at the official open of d and sold at the official open of
d + H, where the next tranche is bought - so sells and buys of the same name net out
at one price and no capital sits idle overnight. Every return is open-to-open on
corporate-action-adjusted prices (the DB layer reads pit.bars_adjusted at a recorded
knowledge cutoff; here prices arrive adjusted).

  label        hold_label: open[t+H] / open[t] - 1 (price only); with_dividends adds
               the cash of every dividend whose ex-date is in (t, t+H]
  splits       make_folds: walk-forward blocks with an H-session embargo, so no TRAIN
               label window reaches a VALID/TEST session (purged by construction)
  book         tranche_book: H tranches of 1/H, equal weight within a tranche, weights
               drift with prices, trades netted per name at the open
  costs        Rates (dated, sourced) -> per-order INR charges; half-spread and
               slippage separately (never double counted)
  controls     matched_controls (turnover decile x ATR decile cell), placebo picks
  inference    moving-block bootstrap of the daily book excess (block >= 2H)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from app.training import e1 as E

H = 5


# ── labels ───────────────────────────────────────────────────────────────────────────
def back_adjust(raw: list[float | None], factors: dict[int, float]) -> list[float | None]:
    """Prices before an ex-date index i multiplied by factors[i] (e.g. 0.5 for a 2:1
    split), cumulatively - the convention of pit.bars_adjusted for a fixed cutoff."""
    out = list(raw)
    for i, f in factors.items():
        for j in range(min(i, len(out))):
            if out[j] is not None:
                out[j] = out[j] * f
    return out


def hold_label(opens: list[float | None], t: int, h: int = H, *,
               dividends: dict[int, float] | None = None) -> tuple[float | None, str | None]:
    """(return, reason). dividends: cash per share (on the adjusted basis) by ex-date
    index; counted when t < ex <= t + h (the holder of record)."""
    if t + h >= len(opens):
        return None, "NO_EXIT_SESSION"
    a, b = opens[t], opens[t + h]
    if a is None or b is None:
        return None, "SESSION_MISSING"
    if a <= 0 or b <= 0:
        return None, "MALFORMED_PRICE"
    cash = sum(v for i, v in (dividends or {}).items() if t < i <= t + h)
    return (b + cash) / a - 1, None


# ── splits ───────────────────────────────────────────────────────────────────────────
def make_folds(n: int, *, train_min: int = 120, valid: int = 20, test: int = 20,
               embargo: int = H, roll: int = 20, h: int = H) -> list[dict[str, range]]:
    """Session-index folds: TRAIN [0, a), embargo, VALID, embargo, TEST, rolling by
    `roll`. A TEST session t needs the open of t + h, so the last h sessions of the
    data are never TEST. With embargo >= h no TRAIN (or VALID) label window
    [t, t + h] reaches the next block."""
    if embargo < h:
        raise ValueError(f"embargo {embargo} < horizon {h}: TRAIN labels would leak")
    folds, a = [], train_min
    while True:
        v0 = a + embargo
        t0 = v0 + valid + embargo
        t1 = t0 + test
        if t1 + h > n:
            break
        folds.append({"train": range(0, a), "valid": range(v0, v0 + valid),
                      "test": range(t0, t1)})
        a += roll
    return folds


# ── the book ─────────────────────────────────────────────────────────────────────────
@dataclass
class BookDay:
    day: int
    ret: float | None              # open(day) -> open(day + 1), after the day's trades
    buys: dict[str, float]         # traded value per name, fraction of book value
    sells: dict[str, float]
    positions: int
    missing_marks: int             # held names without an open at day + 1 (marked flat)


def tranche_book(picks: dict[int, list[str]], opens: dict[str, list[float | None]],
                 days: range, *, h: int = H) -> list[BookDay]:
    """Staggered tranches over `days` (formation days are days.start - h + 1 ..
    days.stop - 1: the h - 1 warm-up formations before the first evaluated day are
    traded, not evaluated). A pick without an open on its formation day is skipped
    (the tranche is equal weight over the rest); a held name without an open at the
    next session is marked flat for that day and counted."""
    first = days.start - h + 1
    tranches: deque[dict[str, float]] = deque()
    cash = 1.0                                          # the book starts in cash
    out: list[BookDay] = []
    for d in range(first, days.stop):
        before = _holdings(tranches)
        if len(tranches) == h:
            freed = sum(tranches.popleft().values())
        else:
            freed = min(cash, 1.0 / h)
            cash -= freed
        names = [k for k in picks.get(d, []) if _px(opens, k, d)]
        new = {k: freed / len(names) for k in names} if names else {}
        if not names:
            cash += freed                               # nothing buyable: stays cash
        tranches.append(new)
        after = _holdings(tranches)
        total = sum(after.values()) + cash
        buys = {k: (after.get(k, 0) - before.get(k, 0)) / total for k in after
                if after.get(k, 0) > before.get(k, 0) + 1e-15}
        sells = {k: (before[k] - after.get(k, 0)) / total for k in before
                 if before[k] > after.get(k, 0) + 1e-15}
        miss = 0
        for tr in tranches:                             # drift to the next open
            for k in tr:
                # from the last open seen (not the open of d): a move across a
                # suspension is booked on the day the name reopens, never lost
                a, b = _last_px(opens, k, d), _px(opens, k, d + 1)
                if a and b:
                    tr[k] *= b / a
                else:
                    miss += 1
        end = sum(_holdings(tranches).values()) + cash
        if d >= days.start:
            out.append(BookDay(d, end / total - 1, buys, sells,
                               sum(1 for _ in after), miss))
    return out


def _holdings(tranches: deque[dict[str, float]]) -> dict[str, float]:
    agg: dict[str, float] = {}
    for tr in tranches:
        for k, v in tr.items():
            agg[k] = agg.get(k, 0.0) + v
    return agg


def _px(opens: dict[str, list[float | None]], k: str, d: int) -> float | None:
    s = opens.get(k)
    return s[d] if s is not None and 0 <= d < len(s) and s[d] and s[d] > 0 else None


def _last_px(opens: dict[str, list[float | None]], k: str, d: int) -> float | None:
    """The last valid open at or before d (a held name was bought at a valid open)."""
    for j in range(d, -1, -1):
        if (p := _px(opens, k, j)) is not None:
            return p
    return None


# ── costs ────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Rates:
    """One product's charges. Every rate carries its source and date; nothing here
    is a default - a Rates object is built from the approved, dated table."""
    brokerage_flat_inr: float          # per executed order
    brokerage_pct: float | None        # if set: min(flat, pct * value) (intraday plans)
    stt_buy: float
    stt_sell: float
    stamp_buy: float
    exchange_txn: float
    sebi: float
    gst: float                         # on brokerage + exchange + SEBI
    dp_per_scrip_sell_inr: float       # delivery sells, per scrip per day
    source: str
    as_of: str
    notes: str = ""


COST_PARTS = ("brokerage", "statutory", "dp", "spread", "slippage")


def order_cost_parts(value: float, side: str, r: Rates) -> dict[str, float]:
    """One order's charges in INR: brokerage (+ its GST), statutory (STT, stamp,
    exchange, SEBI, + GST on exchange and SEBI) and DP (+ GST, delivery sells)."""
    if value <= 0:
        return {"brokerage": 0.0, "statutory": 0.0, "dp": 0.0}
    brok = r.brokerage_flat_inr if r.brokerage_pct is None else \
        min(r.brokerage_flat_inr, r.brokerage_pct * value)
    txn, sebi = r.exchange_txn * value, r.sebi * value
    stt = (r.stt_buy if side == "BUY" else r.stt_sell) * value
    stamp = r.stamp_buy * value if side == "BUY" else 0.0
    dp = r.dp_per_scrip_sell_inr * (1 + r.gst) if side == "SELL" else 0.0
    return {"brokerage": brok * (1 + r.gst),
            "statutory": txn + sebi + stt + stamp + (txn + sebi) * r.gst, "dp": dp}


def order_cost_inr(value: float, side: str, r: Rates) -> float:
    return sum(order_cost_parts(value, side, r).values())


@dataclass(frozen=True)
class CostModel:
    """Spread and slippage are separate parts: the half-spread is paid once per traded
    side (measured where `half_spread_measured` has the (session, name), else the
    frozen `half_spread_bps` proxy: C3 / PC-4), slippage is impact BEYOND it
    (C4 sweep) - never double counted."""
    rates: Rates
    capital_inr: float                 # book value the fractions refer to
    half_spread_bps: float             # fallback proxy (C3 / PC-4, frozen)
    slippage_bps: float = 0.0          # impact BEYOND the half-spread (swept)
    multiplier: float = 1.0            # A2: 1.5
    half_spread_measured: dict[tuple[int, str], float] | None = None  # (day, name): bps

    def half_spread(self, day: int, k: str) -> tuple[float, bool]:
        """(bps, measured?) for name k traded at the open of session index `day`."""
        m = self.half_spread_measured or {}
        return (m[(day, k)], True) if (day, k) in m else (self.half_spread_bps, False)

    def day_cost_parts(self, day: BookDay) -> dict[str, float]:
        """One day's costs by part, each a fraction of book value (multiplier applied)."""
        inr = dict.fromkeys(COST_PARTS, 0.0)
        for side, trades in (("BUY", day.buys), ("SELL", day.sells)):
            for k, w in trades.items():
                v = w * self.capital_inr
                for p, x in order_cost_parts(v, side, self.rates).items():
                    inr[p] += x
                inr["spread"] += v * self.half_spread(day.day, k)[0] / 10_000
                inr["slippage"] += v * self.slippage_bps / 10_000
        return {p: self.multiplier * x / self.capital_inr for p, x in inr.items()}

    def day_cost(self, day: BookDay) -> float:
        """Cost of one day's trades as a fraction of book value."""
        return sum(self.day_cost_parts(day).values())

    def spread_coverage(self, book: list[BookDay]) -> dict[str, int]:
        """Traded sides priced with a measured half-spread vs the proxy (C3 report)."""
        n = {"measured": 0, "proxy": 0}
        for day in book:
            for k in (*day.buys, *day.sells):
                n["measured" if self.half_spread(day.day, k)[1] else "proxy"] += 1
        return n


def net_series(book: list[BookDay], cm: CostModel | None) -> list[float]:
    return [(b.ret or 0.0) - (cm.day_cost(b) if cm else 0.0) for b in book]


def cost_summary(book: list[BookDay], cm: CostModel) -> dict[str, float]:
    """Mean daily gross return, each cost part and net (fractions of book value):
    net = gross - sum(parts), each part counted exactly once."""
    parts = [cm.day_cost_parts(b) for b in book]
    out = {"gross": float(np.mean([b.ret or 0.0 for b in book])) if book else 0.0}
    out |= {p: float(np.mean([x[p] for x in parts])) if parts else 0.0 for p in COST_PARTS}
    out["net"] = out["gross"] - sum(out[p] for p in COST_PARTS)
    return out


def turnover(book: list[BookDay]) -> float:
    """Mean one-sided traded fraction of book value per day."""
    return float(np.mean([sum(b.buys.values()) for b in book])) if book else 0.0


# ── controls ─────────────────────────────────────────────────────────────────────────
def matched_controls(keys: list[str], turnover_: np.ndarray, atr: np.ndarray,
                     chosen: list[str], rng: np.random.Generator,
                     exclude: set[str] | None = None) -> tuple[list[str], int]:
    """One control per chosen name: a random not-chosen, not-excluded universe name of
    the same (turnover decile, ATR decile) cell, without replacement. -> (controls,
    unmatched)."""
    cell = dict(zip(keys, zip(E.deciles(turnover_).tolist(), E.deciles(atr).tolist(),
                              strict=True), strict=True))
    taken = set(chosen) | (exclude or set())
    pool: dict[tuple[int, int], list[str]] = {}
    for k in keys:
        if k not in taken:
            pool.setdefault(cell[k], []).append(k)
    out, unmatched = [], 0
    for k in chosen:
        cand = pool.get(cell[k], [])
        if not cand:
            unmatched += 1
            continue
        out.append(cand.pop(int(rng.integers(len(cand)))))
    return out, unmatched


def placebo_picks(keys: list[str], chosen: list[str], rng: np.random.Generator) -> list[str]:
    """Same number of names drawn at random from the universe, excluding the picks."""
    rest = [k for k in keys if k not in set(chosen)]
    n = min(len(chosen), len(rest))
    return [rest[i] for i in sorted(rng.choice(len(rest), size=n, replace=False))]


# ── inference and acceptance ─────────────────────────────────────────────────────────
@dataclass
class Result:
    mean: float
    ci: tuple[float, float]
    n: int
    nw_t: float | None
    fold_means: list[float] = field(default_factory=list)
    max_drawdown: float = 0.0


def summarise(excess: list[float], folds: list[int], *, block: int = 2 * H,
              b: int = 10_000, level: float = 0.975, seed: int = 0) -> Result:
    if block < 2 * H:
        raise ValueError(f"block {block} < 2H: overlapping tranches are autocorrelated")
    lo, hi = E.block_bootstrap_ci(excess, b=b, block=block, level=level, seed=seed)
    by: dict[int, list[float]] = {}
    for x, f in zip(excess, folds, strict=True):
        by.setdefault(f, []).append(x)
    return Result(float(np.mean(excess)), (lo, hi), len(excess),
                  E.nw_t(excess, lags=2 * H - 1),
                  [float(np.mean(by[f])) for f in sorted(by)], E.max_drawdown(excess))


def verdict(ci: tuple[float, float]) -> str:
    return "PASS" if ci[0] > 0 else ("FAIL" if ci[1] < 0 else "UNPROVEN")


def acceptance(net: Result, *, net_at_1p5: float, placebo: Result, gross: Result,
               folds_total: int, other_net_mean: float | None = None) -> dict[str, Any]:
    """The pre-registered criteria A1-A6 for one predictor (other_net_mean: P1's
    primary metric, for A5 of P2)."""
    pos = sum(1 for m in net.fold_means if m > 0)
    return {
        "A1": verdict(net.ci),
        "A2": "PASS" if net_at_1p5 >= 0 else "FAIL",
        "A3": "PASS" if pos >= math.ceil(0.8 * folds_total) else "FAIL",
        "A3_positive_folds": f"{pos}/{folds_total}",
        "A4": "PASS" if placebo.ci[0] <= 0 <= placebo.ci[1] else "FAIL",
        "A5": None if other_net_mean is None else
              ("PASS" if net.mean > other_net_mean else "FAIL"),
        "A6": {"max_drawdown_net": net.max_drawdown, "max_drawdown_gross": gross.max_drawdown},
    }


# ── the experiment (Amendment 2, PROPOSED): pure, in memory ──────────────────────────
@dataclass(frozen=True)
class Selection:
    """A versioned selection design. K100 is the 2026-10-13 pre-registration (top
    quintile of the top 500); K20 (PC-3) keeps the universe and costs and picks 20
    names per tranche. Each is its own configuration with its own sha and test look."""
    name: str
    universe_top: int = 500
    pick_frac: float | None = 0.2
    n_picks: int | None = None

    def k(self, n_universe: int) -> int:
        return self.n_picks if self.n_picks is not None else int(n_universe * self.pick_frac)


K100 = Selection("k100-top-quintile", pick_frac=0.2)
K20 = Selection("k20", pick_frac=None, n_picks=20)


def choose(sess: dict[str, Any], u: np.ndarray, score: np.ndarray, k: int) -> np.ndarray:
    """The top k of score inside u (desc, instrument key as tie-break) - e1.picks with
    a count instead of a fraction."""
    order = np.lexsort((np.asarray(sess["keys"])[u], -score[u]))
    return u[order[:min(k, len(u))]]


ARMS = ("P", "C2", "PL", "PLC", "C0")


def form_block(sessions: dict[int, dict[str, Any]], test: range, score_fn, sel: Selection,
               *, seed: int, h: int = H, perm_draws: int = 0) -> dict[str, Any]:
    """Formation for one TEST block: every formation day d in [test.start - h + 1,
    test.stop) (the h - 1 warm-up days are embargo sessions: features only).
      P    the k best of score_fn(sess, u) in the PIT universe u
      C2   per pick, a random non-picked universe name of its (turnover, ATR) cell
      PL   placebo: k random non-picked names;  PLC: their own C2 controls (excluding P)
      C0   the whole universe, equal weight
      perm C1: perm_draws books of k random universe names per day
    Selection reads only the session's features (sess: keys, X, turnover, atr); no
    label is passed in."""
    picks: dict[str, dict[int, list[str]]] = {a: {} for a in ARMS}
    perm: list[dict[int, list[str]]] = [{} for _ in range(perm_draws)]
    unmatched = 0
    for d in range(test.start - h + 1, test.stop):
        sess = sessions.get(d)
        if not sess:
            continue
        u = E.universe(sess, sel.universe_top)
        k = sel.k(len(u))
        keys = [sess["keys"][i] for i in u.tolist()]
        p = [sess["keys"][i] for i in choose(sess, u, score_fn(sess, u), k).tolist()]
        rng = np.random.default_rng([seed, d])
        c2, un = matched_controls(keys, sess["turnover"][u], sess["atr"][u], p, rng)
        pl = placebo_picks(keys, p, rng)
        plc, _ = matched_controls(keys, sess["turnover"][u], sess["atr"][u], pl, rng,
                                  exclude=set(p))
        unmatched += un
        for a, v in zip(ARMS, (p, c2, pl, plc, keys), strict=True):
            picks[a][d] = v
        for j in range(perm_draws):
            r = np.random.default_rng([seed, d, j + 1])
            perm[j][d] = [keys[i] for i in sorted(r.choice(len(keys), size=min(k, len(keys)),
                                                           replace=False))]
    return {"test": test, "picks": picks, "perm": perm, "unmatched": unmatched}


def primary_series(p: list[BookDay], c2: list[BookDay], cm: CostModel) -> list[float]:
    """PC-1a: P net of P's own costs minus the UNTRADED C2 book (gross). Costs enter
    once, on the predictor's book only, so a control can never supply a cost advantage."""
    return [a - (b.ret or 0.0) for a, b in zip(net_series(p, cm), c2, strict=True)]


def gross_excess(a: list[BookDay], b: list[BookDay]) -> list[float]:
    return [(x.ret or 0.0) - (y.ret or 0.0) for x, y in zip(a, b, strict=True)]


def evaluate(blocks: list[tuple[int, dict[str, Any]]], opens: dict[str, list[float | None]],
             cm: CostModel, *, h: int = H, stress: float = 1.5, block: int = 2 * H,
             b: int = 10_000, level: float = 0.975, seed: int = 0,
             other_primary_mean: float | None = None) -> dict[str, Any]:
    """blocks: (fold, form_block output) in chronological order; other_primary_mean:
    P1's primary mean under the same configuration, for A5 of P2.
    Every series is daily, over the TEST days only. Primary = PC-1a; the placebo uses
    the same matched construction on GROSS returns (A4: the pipeline must not make an
    effect out of nothing - costs would make any traded arm negative by construction)."""
    days, fold_of = [], []
    books = {a: [] for a in ARMS}
    perm_gross: list[list[float]] = []
    for f, blk in blocks:
        for a in ARMS:
            books[a] += tranche_book(blk["picks"][a], opens, blk["test"], h=h)
        for j, pp in enumerate(blk["perm"]):
            g = [x.ret or 0.0 for x in tranche_book(pp, opens, blk["test"], h=h)]
            if j < len(perm_gross):
                perm_gross[j] += g
            else:
                perm_gross.append(g)
        days += list(blk["test"])
        fold_of += [f] * len(blk["test"])
    stressed = CostModel(**{**cm.__dict__, "multiplier": cm.multiplier * stress})
    P, C2 = books["P"], books["C2"]
    prim = primary_series(P, C2, cm)
    S = {"primary_net_vs_c2_gross": prim,
         "gross_vs_c2_gross": gross_excess(P, C2),
         "net_vs_c2_net": [x - y for x, y in zip(net_series(P, cm), net_series(C2, cm),
                                                 strict=True)],
         "p_net_absolute": net_series(P, cm),
         "c0_gross": [x.ret or 0.0 for x in books["C0"]],
         "placebo_gross_vs_its_c2": gross_excess(books["PL"], books["PLC"])}
    R = {k: summarise(v, fold_of, block=block, b=b, level=level, seed=seed)
         for k, v in S.items()}
    obs = float(np.mean([x.ret or 0.0 for x in P]))
    null = [float(np.mean(g)) for g in perm_gross]
    out = {
        "days": days, "folds": fold_of, "n_days": len(days),
        "series": S, "results": {k: asdict(v) for k, v in R.items()},
        "primary_mean_at_stress": float(np.mean(primary_series(P, C2, stressed))),
        "stress": stress,
        "costs": cost_summary(P, cm), "turnover": turnover(P),
        "turnover_c2": turnover(C2),
        "spread_coverage": cm.spread_coverage(P),
        "missing_marks": sum(x.missing_marks for x in P),
        "unmatched": sum(blk["unmatched"] for _, blk in blocks),
        "positions_mean": float(np.mean([x.positions for x in P])) if P else 0.0,
        "c1": {"observed_gross": obs, "draws": len(null),
               "null_mean": float(np.mean(null)) if null else None,
               "p_one_sided": float((1 + sum(n >= obs for n in null)) / (len(null) + 1))
               if null else None}}
    out["acceptance"] = acceptance(R["primary_net_vs_c2_gross"],
                                   net_at_1p5=out["primary_mean_at_stress"],
                                   placebo=R["placebo_gross_vs_its_c2"],
                                   gross=R["gross_vs_c2_gross"],
                                   folds_total=len({f for f, _ in blocks}),
                                   other_net_mean=other_primary_mean)
    return out
