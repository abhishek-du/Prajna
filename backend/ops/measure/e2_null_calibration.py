"""E2 inference calibration on synthetic NULL worlds (no database, no real data, no E2
outcome). Pre-look requirement of Amendment 2 rev 2 (PROPOSED).

  .venv/bin/python ops/measure/e2_null_calibration.py --worlds 1000 [--jobs 8] [--write]
      [--ci-method studentized|percentile]   (default studentized: correction C-a)

Null: the score carries no information about future returns, and costs are zero, so
the primary series s_t equals the gross matched selection excess with true mean 0.
The full pre-registered machinery runs unchanged (k20 primary, k100 sensitivity;
form_block -> tranche books -> evaluate: moving-block bootstrap, block 2H = 10,
10,000 draws, 97.5% two-sided; Newey-West lag 2H - 1; A1-A4; candidate_status).

Worlds (600 names, 140 sessions, 5 TEST blocks of 20):
  iid     independent normal returns (sd 1%), independent scores
  factor  market factor (t5, volatility regimes: log-vol AR(1)), 20 sector factors,
          t5 idiosyncratic noise, scores AR(1) with rho 0.9 (persistent picks, like
          ridge24's 14.5% daily turnover) and still independent of returns

Rates reported with Wilson 95% intervals:
  a1_pass        A1 PASS (CI lower bound > 0)                     nominal 1.25%
  accepted       candidate ACCEPTED-EXPLORATORY (A1 PASS, NW agrees, A2-A4) <= 1.25%
  ci_excludes_0  two-sided                                         nominal 2.5%
  placebo_fail   A4 FAIL (placebo CI excludes 0)                  nominal 2.5%
ADEQUATE (fixed before the run): for the PRIMARY configuration (k20), in EVERY world
type, the Wilson 95% upper bound of `accepted` is <= 2.5% (at most twice the nominal
one-sided 1.25%); for --ci-method studentized (C-a) ALSO the Wilson 95% interval of
`ci_excludes_0` contains the nominal 2.5%. Otherwise INADEQUATE: stop and propose a
correction; never tune on E2 outcomes. Each method writes its own file (never
overwritten): null_calibration.json (percentile, 2026-10-14, INADEQUATE) and
null_calibration_studentized.json.
"""

from __future__ import annotations

import argparse
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
from app.training import e1 as E  # noqa: E402
from app.training import e2 as X  # noqa: E402

OUT = ROOT / "var/stage4/experiments/e2"
N, T = 600, 140
TESTS = ((20, 40), (40, 60), (60, 80), (80, 100), (100, 120))
RI = E.CORE24.index("ret_1d")
ZERO = X.CostModel(X.Rates(0, None, 0, 0, 0, 0, 0, 0, 0, "zero (calibration)", "-"),
                   capital_inr=1e9, half_spread_bps=0.0)
BOUND = 0.025


def world(kind: str, seed: int):
    rng = np.random.default_rng([20261014, seed, 0 if kind == "iid" else 1])
    keys = [f"K{i:03d}" for i in range(N)]
    turn, atr = rng.lognormal(15, 1, N), rng.uniform(.01, .05, N)
    px = np.full((N, T + 1), 100.0)
    score = rng.normal(size=N)
    sector, beta = rng.integers(0, 20, N), rng.uniform(0.5, 1.5, N)
    logv, sessions = 0.0, {}
    for d in range(T):
        X_ = rng.normal(size=(N, 24))
        X_[:, 23], X_[:, 14] = turn, atr
        if kind == "iid":
            X_[:, RI] = rng.normal(size=N)
            r = rng.normal(0, 0.01, N)
        else:
            score = 0.9 * score + math.sqrt(1 - 0.81) * rng.normal(size=N)
            X_[:, RI] = -score
            logv = 0.95 * logv + 0.3 * rng.normal()
            v = math.exp(logv)
            m = 0.01 * v * rng.standard_t(5) / math.sqrt(5 / 3)
            sec = 0.006 * v * rng.normal(size=20)
            r = beta * m + sec[sector] + 0.012 * v * rng.standard_t(5, N) / math.sqrt(5 / 3)
        sessions[d] = {"keys": keys, "X": X_, "turnover": turn, "atr": atr}
        px[:, d + 1] = px[:, d] * np.maximum(1 + r, 0.05)
    return sessions, {k: px[i].tolist() for i, k in enumerate(keys)}


def one(args) -> dict[str, dict]:
    kind, seed, b, method = args
    s, o = world(kind, seed)
    out = {}
    for sel in (X.K20, X.K100):
        blocks = [(f, X.form_block(s, range(a, z), lambda q, u: E.reversal(q), sel, seed=seed))
                  for f, (a, z) in enumerate(TESTS)]
        r = X.evaluate(blocks, o, ZERO, b=b, seed=seed, ci_method=method)
        R, acc = r["results"]["primary_net_vs_c2_gross"], r["acceptance"]
        out[sel.name] = {"a1_pass": acc["A1"] == "PASS",
                         "accepted": r["candidate"]["status"] == "ACCEPTED-EXPLORATORY",
                         "ci_excludes_0": not (R["ci"][0] <= 0 <= R["ci"][1]),
                         "placebo_fail": acc["A4"] == "FAIL", "mean": R["mean"]}
    return out


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=1000)
    ap.add_argument("--b", type=int, default=10_000)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--ci-method", default="studentized", choices=X.CI_METHODS)
    a = ap.parse_args()
    code = hashlib.sha256((ROOT / "app/training/e2.py").read_bytes()
                          + pathlib.Path(__file__).read_bytes()).hexdigest()
    crit = f"k20: Wilson 95% upper bound of `accepted` <= {BOUND} in every world type"
    if a.ci_method == "studentized":
        crit += "; and the Wilson 95% interval of `ci_excludes_0` contains 0.025"
    res: dict = {"worlds": a.worlds, "bootstrap_draws": a.b, "criterion": crit,
                 "ci_method": a.ci_method,
                 "code_sha256": code, "by_world": {}}
    adequate = True
    for kind in ("iid", "factor"):
        with ProcessPoolExecutor(a.jobs) as ex:
            rows = list(ex.map(one, [(kind, s, a.b, a.ci_method) for s in range(a.worlds)],
                               chunksize=4))
        res["by_world"][kind] = {}
        for name in (X.K20.name, X.K100.name):
            stat = {}
            for k in ("a1_pass", "accepted", "ci_excludes_0", "placebo_fail"):
                n = sum(r[name][k] for r in rows)
                stat[k] = {"count": n, "rate": n / a.worlds, "wilson95": wilson(n, a.worlds)}
            ms = [r[name]["mean"] for r in rows]
            stat["mean_of_means_bps"] = round(float(np.mean(ms)) * 1e4, 4)
            stat["se_bps"] = round(float(np.std(ms) / np.sqrt(len(ms))) * 1e4, 4)
            res["by_world"][kind][name] = stat
        k20 = res["by_world"][kind][X.K20.name]
        if k20["accepted"]["wilson95"][1] > BOUND:
            adequate = False
        lo, hi = k20["ci_excludes_0"]["wilson95"]
        if a.ci_method == "studentized" and not lo <= 0.025 <= hi:
            adequate = False
    res["adequate"] = adequate if a.worlds >= 1000 else None
    res["at"] = now().astimezone(IST).isoformat()
    body = json.dumps(res, indent=1, sort_keys=True)
    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / ("null_calibration_studentized.json" if a.ci_method == "studentized"
                      else "null_calibration.json")
        if path.exists():
            raise SystemExit(f"REFUSED: {path.name} exists; not overwritten")
        path.write_text(body)
        res["written"] = str(path)
        res["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    print(json.dumps(res, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
