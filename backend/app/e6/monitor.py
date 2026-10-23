"""E6 post-results drift: PAPER MONITOR (docs/STAGE4_E6_PREREGISTRATION.md; user decisions
2026-10-23: D1 (b) a two-season paper monitor whose gates are reported, not decisive, plus
(c) results features proposed for E5.1; D2-D5 as proposed). PAPER RESEARCH ONLY: nothing
here places, modifies or cancels an order, and nothing here is read by any other stage.

record   before the 09:15 open of each trading day: the events whose day 1 was the previous
         session get their CAR[0,1] and a class (PICK / CONTROL / OTHER), written to
         var/research/e6/signals/<entry day>.jsonl, append-only, never rewritten. The entry
         is that day's open; a record after the open is refused (it would see the entry).
status   counts only (no returns before the look).
look     once, after the last pick of the window has exited: weekly d_w, the sign-flip CI,
         gates B1-B4 (reported, not decisive under D1 (b)).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import random
import statistics
from typing import Any

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
DIR = pathlib.Path(__file__).resolve().parents[2] / "var" / "research" / "e6"

RULE: dict[str, Any] = {
    "version": "e6-rule-v1",
    "pick_min_car01": 0.0327,              # development 80th percentile (tv >= 5 cr, < 2026)
    "control_car01": [-0.0185, 0.0029],    # development 40th-60th percentiles, [lo, hi)
    "min_prev_close": 50.0,
    "min_median_traded_value": 5e7,        # Rs 5 crore, 20 sessions before day 0
    "max_lag_days": 75,                    # dissemination - period end
    "hold_sessions": 20,                   # entry = day-2 open, exit = close of the 20th
    "cost_round_trip": 0.0035,
    "cost_stress": 1.5,
    "dedupe_days": 30,                     # a second filing within 30 days is the same event
    "window_last_event": "2027-03-15",     # two seasons: Q2 FY27 and Q3 FY27
    "day0_cut": "15:30",
    "benchmark": "NSE_INDEX|Nifty 50",
}
RULE_SHA = hashlib.sha256(json.dumps(RULE, sort_keys=True).encode()).hexdigest()


# ── pure ──────────────────────────────────────────────────────────────────────────────
def day0(event_at: _dt.datetime, sessions: list[_dt.date]) -> _dt.date | None:
    """The first session whose close is after the dissemination."""
    t = event_at.astimezone(IST)
    cut = _dt.time(15, 30)
    for d in sessions:
        if d > t.date() or (d == t.date() and t.time() < cut):
            return d
    return None


def classify(car01: float) -> str:
    lo, hi = RULE["control_car01"]
    if car01 >= RULE["pick_min_car01"]:
        return "PICK"
    if lo <= car01 < hi:
        return "CONTROL"
    return "OTHER"


def car01(closes: list[float], bench: list[float]) -> float:
    """closes / bench: day -1, day 0, day 1. Sum of the two daily abnormal returns."""
    ar = [(closes[i] / closes[i - 1] - 1) - (bench[i] / bench[i - 1] - 1) for i in (1, 2)]
    return ar[0] + ar[1]


def outcome(entry_open: float, exit_close: float, b_open: float, b_close: float) -> dict:
    ex = (exit_close / entry_open - 1) - (b_close / b_open - 1)
    return {"excess": ex, "net": ex - RULE["cost_round_trip"],
            "net_stress": ex - RULE["cost_round_trip"] * RULE["cost_stress"]}


def week_of(d: _dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def sign_flip_ci(x: list[float], level: float = 0.975, n: int = 20000,
                 seed: int = 6) -> tuple[float, float]:
    """CI of the mean by inverting the sign-flip test (as E4 / E5): the set of mu whose
    centred values are not rejected; here by the percentile of flipped means around 0."""
    m = statistics.fmean(x)
    c = [v - m for v in x]
    rnd = random.Random(seed)  # noqa: S311 - a seeded resampling, not security
    flips = sorted(statistics.fmean(v if rnd.random() < 0.5 else -v for v in c)
                   for _ in range(n))
    a = (1 - level) / 2
    return m - flips[int((1 - a) * (n - 1))], m - flips[int(a * (n - 1))]


def look_stats(rows: list[dict]) -> dict:
    """rows: evaluated PICK / CONTROL rows with 'cls', 'entry' (date) and 'net' /
    'net_stress' / 'excess'."""
    by: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        by.setdefault(week_of(r["entry"]), {"PICK": [], "CONTROL": []})[r["cls"]].append(r)
    weeks = sorted(w for w, g in by.items() if g["PICK"] and g["CONTROL"])
    if len(weeks) < 2:
        return {"weeks": len(weeks), "status": "INSUFFICIENT"}
    def d_w(key: str, w: str) -> float:
        g = by[w]
        return (statistics.fmean(p[key] for p in g["PICK"])
                - statistics.fmean(c["excess"] for c in g["CONTROL"]))
    d = [d_w("net", w) for w in weeks]
    ds = [d_w("net_stress", w) for w in weeks]
    lo, hi = sign_flip_ci(d)
    half = len(d) // 2
    picks = [r for r in rows if r["cls"] == "PICK"]
    gates = {"B1_ci_above_0": lo > 0, "B2_stress_mean_ge_0": statistics.fmean(ds) >= 0,
             "B3_picks_net_gt_0": statistics.fmean(p["net"] for p in picks) > 0,
             "B4_both_halves_gt_0": statistics.fmean(d[:half]) > 0
             and statistics.fmean(d[half:]) > 0}
    return {"weeks": len(weeks), "picks": len(picks),
            "controls": sum(r["cls"] == "CONTROL" for r in rows),
            "mean_d_w": statistics.fmean(d), "ci_975": [lo, hi], "gates": gates,
            "verdict": "MONITOR_POSITIVE" if all(gates.values()) else "MONITOR_NOT_POSITIVE",
            "note": "D1 (b): a paper monitor; the gates are reported, not decisive"}
