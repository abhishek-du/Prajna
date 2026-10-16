"""E4a step 3: inference calibration on synthetic NULL worlds (no database, no real data,
no E4 outcome). Pre-look requirement, as E2 Amendment 2 rev 2 section 6.

  .venv/bin/python ops/measure/e4_null_calibration.py --worlds 1000 [--jobs 24] [--write]

Null: open -> close returns are independent of the gap and of the volume spike, and costs
are zero, so s_d = P gross - C2 gross has true mean 0. The full pre-registered machinery
runs unchanged: e4.form_session (09:15 signals, matched controls incl. the gap cell) ->
apply_mask -> primary -> summarise (studentized moving-block bootstrap, block 5 sessions,
10,000 draws, 97.5%) -> acceptance (Newey-West lag 4 agreement, A2-A4, A3 by calendar year).

Worlds (120 names, 1,660 sessions: 260 of warm-up + 1,400 tested, the E4a test length):
  iid     independent gaps N(0, 2%) and returns N(0, 1.2%)
  factor  a market factor on both the gap and the return (t5, volatility regimes: log-vol
          AR(1)), 10 sector factors, t5 idiosyncratic noise; gap and return still
          independent of each other at the name level beyond the shared factors

Rates (Wilson 95%): accepted (the decision rule), a1_pass, ci_excludes_0 (two-sided),
placebo_fail. ADEQUATE (fixed before the run): for BOTH predictors, in EVERY world type,
the Wilson 95% upper bound of `accepted` <= 2.5% AND the Wilson 95% interval of
`ci_excludes_0` contains 2.5%. Otherwise INADEQUATE: stop and propose a correction; never
tune on E4 outcomes.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.clock import IST, now  # noqa: E402
from app.training import e4 as X  # noqa: E402

OUT = ROOT / "var/stage4/experiments/e4"
N_NAMES, WARM, TEST = 120, 260, 1400
BOUND = 0.025


def world(kind: str, seed: int) -> dict[str, dict]:
    rng = np.random.default_rng([20261017, seed, 0 if kind == "iid" else 1])
    n = WARM + TEST
    if kind == "iid":
        gaps = rng.normal(0, 0.02, (N_NAMES, n))
        rets = rng.normal(0, 0.012, (N_NAMES, n))
    else:
        logv = np.zeros(n)
        for d in range(1, n):
            logv[d] = 0.95 * logv[d - 1] + 0.3 * rng.normal()
        v = np.exp(logv)
        beta = rng.uniform(0.5, 1.5, N_NAMES)[:, None]
        sector = rng.integers(0, 10, N_NAMES)
        tg = rng.standard_t(5, n) / math.sqrt(5 / 3)
        tr = rng.standard_t(5, n) / math.sqrt(5 / 3)
        sg, sr = rng.normal(size=(10, n)), rng.normal(size=(10, n))
        gaps = (beta * 0.008 * v * tg + 0.004 * v * sg[sector]
                + 0.015 * v * rng.standard_t(5, (N_NAMES, n)) / math.sqrt(5 / 3))
        rets = (beta * 0.007 * v * tr + 0.004 * v * sr[sector]
                + 0.010 * v * rng.standard_t(5, (N_NAMES, n)) / math.sqrt(5 / 3))
    gaps, rets = np.clip(gaps, -0.2, 0.2), np.clip(rets, -0.3, 0.3)
    series = {}
    for j in range(N_NAMES):
        c = 100.0 * (1 + j / N_NAMES)
        o_, h_, l_, c_ = [], [], [], []
        for d in range(n):
            o = c * (1 + gaps[j, d])
            c = o * (1 + rets[j, d])
            o_.append(o)
            c_.append(c)
            h_.append(max(o, c) * 1.004)
            l_.append(min(o, c) * 0.996)
        series[f"K{j:03d}"] = {"open": o_, "high": h_, "low": l_, "close": c_,
                               "volume": list(rng.uniform(5e4, 2e5, n))}
    return series


def years() -> list[int]:
    d, out = _dt.date(2021, 1, 1), []
    while len(out) < TEST:
        if d.weekday() < 5:
            out.append(d.year)
        d += _dt.timedelta(days=1)
    return out


YEARS = years()
ZERO = X.SessionCost(1e12, half_spread_bps=0.0, rates=X.X.Rates(
    0.0, None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "zero (calibration)", "-"))


def one(args) -> dict[str, dict]:
    kind, seed, b = args
    series = world(kind, seed)
    out = {}
    for pred in X.PREDICTORS:
        s, pl, yrs, pyrs = [], [], [], []
        for i, d in enumerate(range(WARM, WARM + TEST)):
            sess = X.apply_mask(X.form_session(series, d, {}, pred, seed=seed), series)
            r = X.primary(sess, series, ZERO)
            if r["s"] is not None:
                s.append(r["s"])
                yrs.append(YEARS[i])
            if r["placebo"] is not None:
                pl.append(r["placebo"])
                pyrs.append(YEARS[i])
        if len(s) < 50 or len(pl) < 50:
            out[pred] = {"skipped": True}
            continue
        prim = X.summarise(s, yrs, b=b, seed=seed)
        plac = X.summarise(pl, pyrs, b=b, seed=seed + 1)
        acc = X.acceptance(prim, at_stress=prim.mean, placebo=plac)
        out[pred] = {"accepted": acc["candidate"]["status"] == "ACCEPTED-EXPLORATORY",
                     "a1_pass": acc["A1"] == "PASS",
                     "ci_excludes_0": not (prim.ci[0] <= 0 <= prim.ci[1]),
                     "placebo_fail": acc["A4"] == "FAIL", "mean": prim.mean, "n": len(s)}
    return out


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=1000)
    ap.add_argument("--b", type=int, default=10_000)
    ap.add_argument("--jobs", type=int, default=24)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    code = hashlib.sha256((ROOT / "app/training/e4.py").read_bytes()
                          + pathlib.Path(__file__).read_bytes()).hexdigest()
    res: dict = {"worlds": a.worlds, "bootstrap_draws": a.b, "code_sha256": code,
                 "criterion": "both predictors, every world type: Wilson 95% upper of accepted "
                              f"<= {BOUND} and the Wilson 95% interval of ci_excludes_0 "
                              "contains 0.025", "by_world": {}}
    adequate = True
    for kind in ("iid", "factor"):
        with ProcessPoolExecutor(a.jobs) as ex:
            rows = list(ex.map(one, [(kind, s, a.b) for s in range(a.worlds)], chunksize=2))
        res["by_world"][kind] = {}
        for pred in X.PREDICTORS:
            rr = [r[pred] for r in rows if not r[pred].get("skipped")]
            st = {"worlds_used": len(rr)}
            for k in ("accepted", "a1_pass", "ci_excludes_0", "placebo_fail"):
                c = sum(x[k] for x in rr)
                st[k] = {"count": c, "rate": c / len(rr) if rr else None,
                         "wilson95": wilson(c, len(rr))}
            ms = [x["mean"] for x in rr]
            st["mean_of_means_bps"] = round(float(np.mean(ms)) * 1e4, 4) if ms else None
            st["se_bps"] = round(float(np.std(ms) / np.sqrt(len(ms))) * 1e4, 4) if ms else None
            res["by_world"][kind][pred] = st
            lo, hi = st["ci_excludes_0"]["wilson95"]
            if st["accepted"]["wilson95"][1] > BOUND or not lo <= BOUND <= hi:
                adequate = False
    res["adequate"] = adequate if a.worlds >= 1000 else None
    res["at"] = now().astimezone(IST).isoformat()
    body = json.dumps(res, indent=1, sort_keys=True)
    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "null_calibration_c2.json"   # C2 (sign-flip); earlier files stay
        if path.exists():
            raise SystemExit(f"REFUSED: {path.name} exists; not overwritten")
        path.write_text(body)
        res["written"], res["sha256"] = str(path), hashlib.sha256(body.encode()).hexdigest()
    print(json.dumps(res, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
