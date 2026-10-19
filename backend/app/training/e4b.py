"""Stage 4 E4b: intraday-bar (1h / 15m) selection. PURE computation only; no I/O, no
database, no run. Pre-registration: docs/STAGE4_E4B_PREREGISTRATION_DRAFT.md (decisions
D1-D6 approved by the user 2026-10-19; step 1 = code + synthetic tests).

Bars of session d, per name: s["m15"][d] = 25 slots (09:15 ... 15:15) and s["h1"][d] =
7 slots (09:15, 10:15, ... 15:15), each slot (open, high, low, close, volume) or None;
the slot is the bar START. Daily lists (open, high, low, close, volume) as e4.

  B1  ORB "stocks in play" (15m), signal 09:30: candidates whose 09:15 bar closed above
      its open; score = relative volume V(09:15) / mean V(09:15) of the previous 14
      regular sessions (>= 10 present); no corporate action ex in those sessions or on d.
      Entry: open of the 09:30 bar.
  B2  first-hour momentum (1h), signal 10:15: score = C/O - 1 of the 09:15 1h bar (the
      gap excluded). Entry: open of the 10:15 bar.
  B3  gap fade (picks = e4 P1) with a target/stop exit, entry the official open:
      target = entry (1 + sigma), stop = entry (1 - sigma), sigma = e3.volatility at
      d - 1; the first 15m bar (09:15 ... 15:00) touching either decides, both in one
      bar = the stop; fill at the level, or at the bar open when it opens beyond it.
  exit  open of the 15:15 bar (primary; the official close is a sensitivity); a missing
        exit bar falls back to the close of the last earlier bar of d
  fills an unfilled pick (no entry bar) returns 0 and costs nothing; the selection never
        requires a later bar to exist (no look-ahead)
  sessions  regular only: the reference index has all 25 15m bars
  controls  e4.matched_controls; third axis = the first-bar return (B1), the first-hour
            return (B2), the gap (B3); held over the pick's entry -> exit instants, untraded
  inference e4 C2 sign-flip at 98.33% (Bonferroni over B1, B2, B3); A3 >= 3 of 5 years;
            B3 is adopted only if A1-A4 pass AND the CI of delta (target/stop minus the
            same picks' time exit) lies above 0
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.training import e3 as E3
from app.training import e4 as E4

HYPOTHESES = ("B1", "B2", "B3")
LEVEL = 1 - 0.05 / len(HYPOTHESES)            # two-sided 98.33% per hypothesis
NEED_YEARS = 3                                # of the 5 calendar years 2022-2026
K = E4.K
M15_SLOTS, H1_SLOTS = 25, 7
EXIT_M15, EXIT_H1 = 24, 6                     # the 15:15 bar
RV_WINDOW, RV_MIN = 14, 10
OPEN_TOL = 0.01                               # 09:15 15m open vs the official open
SIGMA_MULT = 1.0
IO, IH, IL, IC, IV = range(5)             # slot tuple fields


# ── sessions and bars ────────────────────────────────────────────────────────────────
def regular_sessions(index: dict[str, list]) -> list[bool]:
    """A session is regular when the reference index has every 15m bar (special and
    Muhurat sessions are short)."""
    return [bool(b) and len(b) == M15_SLOTS and all(x is not None for x in b)
            for b in index["m15"]]


def bar(s: dict[str, list], tf: str, d: int, slot: int) -> tuple | None:
    day = s.get(tf, [])
    b = day[d] if 0 <= d < len(day) else None
    x = b[slot] if b and 0 <= slot < len(b) else None
    return x if x is not None and x[IO] and x[IO] > 0 else None


def open_consistent(s: dict[str, list], d: int) -> bool:
    """The 09:15 15m open agrees with the official open (known at 09:15)."""
    b, o = bar(s, "m15", d, 0), E4._v(s["open"], d)
    return bool(b and o and abs(b[IO] / o - 1) <= OPEN_TOL)


# ── signals ──────────────────────────────────────────────────────────────────────────
def first_bar_return(s: dict[str, list], tf: str, d: int) -> float | None:
    b = bar(s, tf, d, 0)
    return b[IC] / b[IO] - 1 if b and b[IC] and b[IC] > 0 else None


def relative_volume(s: dict[str, list], d: int, regular: list[bool],
                    ca_ex: set[int] = frozenset()) -> float | None:
    """V(09:15 of d) / mean V(09:15) of the previous RV_WINDOW regular sessions; None
    when fewer than RV_MIN are present or a CA ex-date falls in that window or on d."""
    prev = [i for i in range(d - 1, -1, -1) if i < len(regular) and regular[i]][:RV_WINDOW]
    if len(prev) < RV_WINDOW or any(min(prev) <= e <= d for e in ca_ex):
        return None
    b = bar(s, "m15", d, 0)
    vols = [x[IV] for i in prev if (x := bar(s, "m15", i, 0)) is not None and x[IV] is not None]
    if not b or b[IV] is None or len(vols) < RV_MIN or np.mean(vols) <= 0:
        return None
    return float(b[IV] / np.mean(vols))


def axis(s: dict[str, list], hyp: str, d: int) -> float | None:
    """The control-matching third axis (and B2's score)."""
    if hyp == "B1":
        return first_bar_return(s, "m15", d)
    if hyp == "B2":
        return first_bar_return(s, "h1", d)
    return E4.gap(s, d)


def score(s: dict[str, list], hyp: str, d: int, regular: list[bool],
          ca_ex: set[int] = frozenset()) -> float | None:
    if hyp == "B1":
        f = first_bar_return(s, "m15", d)
        return relative_volume(s, d, regular, ca_ex) if f is not None and f > 0 else None
    if hyp == "B2":
        return first_bar_return(s, "h1", d)
    return E4.gap_fade(s, d)


# ── universe and arms ────────────────────────────────────────────────────────────────
def eligible(series: dict[str, dict], d: int, suspect: dict[str, set[int]], hyp: str, *,
             top: int = E4.UNIVERSE_TOP) -> list[tuple[str, float, float, float]]:
    """e4.eligible (daily rules at d - 1, |gap| <= 25%), then open-consistent names whose
    signal bar exists: [(key, turnover, volatility, axis)], turnover order kept."""
    out = []
    for k, t, v, _ in E4.eligible(series, d, suspect, top=top):
        if not open_consistent(series[k], d):
            continue
        a = axis(series[k], hyp, d)
        if a is not None:
            out.append((k, t, v, a))
    return out


def form_session(series: dict[str, dict], d: int, suspect: dict[str, set[int]], hyp: str,
                 regular: list[bool], ca_ex: dict[str, set[int]] | None = None, *,
                 k: int = K, seed: int = 0) -> dict[str, Any]:
    """Every arm at the signal instant of hyp. Reads daily bars < d, the open of d and
    the signal bar of d only."""
    ca_ex = ca_ex or {}
    u = eligible(series, d, suspect, hyp)
    keys = [r[0] for r in u]
    ok = sorted(((sc, key) for key in keys
                 if (sc := score(series[key], hyp, d, regular, ca_ex.get(key, set())))
                 is not None), key=lambda x: (-x[0], x[1]))
    p = [key for _, key in ok[:k]]
    rng = np.random.default_rng([seed, d, HYPOTHESES.index(hyp)])
    c2, unmatched = E4.matched_controls(u, p, rng)
    rest = [x for x in keys if x not in set(p)]
    pl = [rest[i] for i in sorted(rng.choice(len(rest), size=min(len(p), len(rest)),
                                             replace=False))] if rest and p else []
    plc, _ = E4.matched_controls(u, pl, rng, exclude=set(p)) if pl else ([], 0)
    return {"d": d, "hyp": hyp, "arms": dict(zip(E4.ARMS, (p, c2, pl, plc, keys), strict=True)),
            "perm": [], "unmatched": unmatched, "universe": len(keys)}


# ── entry, exit, path ────────────────────────────────────────────────────────────────
def entry_price(s: dict[str, list], hyp: str, d: int) -> float | None:
    if hyp == "B1":
        b = bar(s, "m15", d, 1)
    elif hyp == "B2":
        b = bar(s, "h1", d, 1)
    else:
        return E4._v(s["open"], d)
    return b[IO] if b else None


def time_exit(s: dict[str, list], hyp: str, d: int, *, official_close: bool = False
              ) -> float | None:
    """The 15:15 bar open, else the close of the last earlier bar after the entry."""
    if official_close:
        return E4._v(s["close"], d)
    tf, last, first = ("h1", EXIT_H1, 1) if hyp == "B2" else ("m15", EXIT_M15,
                                                             1 if hyp == "B1" else 0)
    b = bar(s, tf, d, last)
    if b:
        return b[IO]
    for slot in range(last - 1, first - 1, -1):
        x = bar(s, tf, d, slot)
        if x and x[IC] and x[IC] > 0:
            return x[IC]
    return None


def target_stop_exit(s: dict[str, list], d: int, entry: float, sigma: float, *,
                     mult: float = SIGMA_MULT, official_close: bool = False
                     ) -> tuple[float | None, str]:
    """B3: the first 15m bar 09:15 ... 15:00 touching target or stop decides (both in one
    bar -> stop); fill at the level, or the bar open when it opened beyond the level."""
    tgt, stp = entry * (1 + mult * sigma), entry * (1 - mult * sigma)
    for slot in range(EXIT_M15):
        b = bar(s, "m15", d, slot)
        if not b or b[IH] is None or b[IL] is None:
            continue
        hit_s, hit_t = b[IL] <= stp, b[IH] >= tgt
        if hit_s:
            return (min(stp, b[IO]), "both" if hit_t else "stop")
        if hit_t:
            return (max(tgt, b[IO]), "target")
    return (time_exit(s, "B3", d, official_close=official_close), "time")


def trade_return(s: dict[str, list], hyp: str, d: int, *, use_levels: bool = False,
                 mult: float = SIGMA_MULT, official_close: bool = False
                 ) -> tuple[float | None, str]:
    """(return, how) entry -> exit; (None, 'unfilled') without an entry bar."""
    e = entry_price(s, hyp, d)
    if not e:
        return (None, "unfilled")
    if use_levels:
        sig = E3.volatility(s, d - 1)
        if sig is None:
            return (None, "no_sigma")
        x, how = target_stop_exit(s, d, e, sig, mult=mult, official_close=official_close)
    else:
        x, how = time_exit(s, hyp, d, official_close=official_close), "time"
    return (x / e - 1, how) if x and x > 0 else (None, "no_exit")


def arm_return(names: list[str], series: dict[str, dict], hyp: str, d: int, **kw
               ) -> float | None:
    """Untraded arms: equal-weight time-exit return; names without one are dropped."""
    rs = [r for n in names if (r := trade_return(series[n], hyp, d, **kw)[0]) is not None]
    return float(np.mean(rs)) if rs else None


def primary(sess: dict[str, Any], series: dict[str, dict], cost: E4.SessionCost, *,
            mult: float = SIGMA_MULT, official_close: bool = False) -> dict[str, Any]:
    """s_d = P gross - cost(filled picks) - C2 gross. An unfilled pick holds cash (0, no
    cost): the book keeps 1/K per pick, so cost is charged at the same order size. For
    B3 also delta = (target/stop - cost) - (the same picks' time exit - its cost)."""
    d, hyp, arms = sess["d"], sess["hyp"], sess["arms"]
    p = arms["P"]
    kw = {"official_close": official_close}
    lev = hyp == "B3"
    got = [trade_return(series[n], hyp, d, use_levels=lev, mult=mult, **kw) for n in p]
    filled = [(n, r) for n, (r, _) in zip(p, got, strict=True) if r is not None]
    hows = [h for _, h in got]

    def gross_cost(fl: list[tuple[str, float]]) -> tuple[float | None, float]:
        if not p:
            return (None, 0.0)
        g = float(sum(r for _, r in fl) / len(p))
        if not fl:
            return (g, 0.0)
        part = E4.SessionCost(cost.capital_inr * len(fl) / len(p), cost.half_spread_bps,
                              cost.slippage_bps, cost.multiplier, cost.rates)
        return (g, part.fraction([n for n, _ in fl], [r for _, r in fl]) * len(fl) / len(p))

    gp, c = gross_cost(filled)
    gc = arm_return(arms["C2"], series, hyp, d, **kw)
    gpl, gplc = (arm_return(arms["PL"], series, hyp, d, **kw),
                 arm_return(arms["PLC"], series, hyp, d, **kw))
    out = {"d": d, "hyp": hyp, "p_gross": gp, "c2_gross": gc, "cost": c,
           "s": None if gp is None or gc is None else gp - c - gc,
           "placebo": None if gpl is None or gplc is None else gpl - gplc,
           "c0_gross": arm_return(arms["C0"], series, hyp, d, **kw),
           "picks": len(p), "unfilled": hows.count("unfilled"),
           "exits": {h: hows.count(h) for h in sorted(set(hows))}}
    if lev:
        tf = [(n, r) for n in p if (r := trade_return(series[n], hyp, d, **kw)[0]) is not None]
        gt, ct = gross_cost(tf)
        out["delta"] = None if gp is None or gt is None else (gp - c) - (gt - ct)
    return out


# ── inference and acceptance ─────────────────────────────────────────────────────────
def summarise(x: list[float], years: list[int], *, b: int = 10_000, seed: int = 0
              ) -> E3.Result:
    return E4.summarise(x, years, b=b, level=LEVEL, seed=seed)


def acceptance(prim: E3.Result, *, at_stress: float, placebo: E3.Result,
               delta: E3.Result | None = None) -> dict[str, Any]:
    """A1-A4 (A3 >= 3 of 5 years). B3 (delta given): adopt the target/stop exit only if
    the candidate is accepted AND delta's CI lies above 0."""
    acc = E4.acceptance(prim, at_stress=at_stress, placebo=placebo, need_years=NEED_YEARS)
    if delta is not None:
        acc["delta"] = {"mean": delta.mean, "ci": list(delta.ci)}
        acc["adopt_target_stop"] = bool(
            acc["candidate"]["status"] == "ACCEPTED-EXPLORATORY" and delta.ci[0] > 0)
    return acc


def minimum_detectable(sd: float, n: int) -> float:
    """80% power at the two-sided Bonferroni level (z 2.394)."""
    return E3.minimum_detectable(sd, n, z_alpha=2.394)
