"""E4b step 3: inference calibration on synthetic NULL worlds (no database, no real data,
no E4b outcome). Pre-registration docs/STAGE4_E4B_PREREGISTRATION_DRAFT.md section 6
(approved 2026-10-19); the criterion below was fixed there before this run.

  .venv/bin/python ops/measure/e4b_null_calibration.py --worlds 1000 [--jobs 24] [--write]

Null: every 15m bar return is independent of everything before it (the gap, the first
bar, the first hour, the 09:15 volume) and costs are zero, so each hypothesis' s_d has
true mean 0. The pre-registered machinery runs unchanged (app/training/e4b.py):
form_session -> e4.apply_mask -> primary -> summarise (C2 sign-flip, 10,000 sign vectors,
98.33%) -> acceptance (NW lag 19 agreement, A2-A4, A3 >= 3 of 5 years).

Worlds (120 names, 260 warm-up + 1,120 tested sessions of 25 15m bars; 1h bars are the
15m bars aggregated; the daily bar is the session's open/high/low/close/volume):
  iid     gaps N(0, 2%); bar returns N(0, 0.24%) x an intraday U-shaped volatility profile
  factor  a market factor on the gap and on every bar (t5), 10 sector factors, t5
          idiosyncratic noise, volatility regimes log-vol AR(1) phi 0.95, the same U shape
09:15 volumes: lognormal with a persistent name level, independent of every return.

Rates (Wilson 95%): accepted, a1_pass, ci_excludes_0 (two-sided at 98.33%), placebo_fail;
for B3 also delta_ci_excludes_0 and adopted (reported; adopted <= accepted by construction).
ADEQUATE: for EVERY hypothesis in EVERY world type, the Wilson 95% upper bound of
`accepted` <= 1.67% AND the Wilson 95% interval of `ci_excludes_0` contains 1.67%.
Otherwise INADEQUATE: stop and report; no alternative inference method is searched.
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
from app.training import e4 as E4  # noqa: E402
from app.training import e4b as X  # noqa: E402

OUT = ROOT / "var/stage4/experiments/e4b"
N_NAMES, WARM, TEST = 120, 261, 1120
SEED_BASE = 20261020
BOUND = 1 - X.LEVEL                              # 1.67%
SLOTS = X.M15_SLOTS
# intraday volatility U shape (high at the open and the close), mean square 1
_k = np.arange(SLOTS)
_u = 1.0 + 1.2 * np.exp(-_k / 2.0) + 0.5 * np.exp(-(SLOTS - 1 - _k) / 2.0)
U_SHAPE = _u / np.sqrt(np.mean(_u ** 2))


class Day:
    """One session's bars as a read-only sequence of (open, high, low, close, volume)
    tuples, backed by an array (a world of tuples would not fit 24 workers in memory)."""
    __slots__ = ("a",)

    def __init__(self, a: np.ndarray):
        self.a = a

    def __len__(self) -> int:
        return len(self.a)

    def __getitem__(self, i: int) -> tuple:
        return tuple(float(x) for x in self.a[i])


def t5(rng, size):
    return rng.standard_t(5, size) / math.sqrt(5 / 3)


def world(kind: str, seed: int) -> dict[str, dict]:
    rng = np.random.default_rng([SEED_BASE, seed, 0 if kind == "iid" else 1])
    n = WARM + TEST
    if kind == "iid":
        gaps = rng.normal(0, 0.02, (N_NAMES, n))
        rets = rng.normal(0, 0.0024, (N_NAMES, n, SLOTS)) * U_SHAPE
    else:
        logv = np.zeros(n)
        for d in range(1, n):
            logv[d] = 0.95 * logv[d - 1] + 0.3 * rng.normal()
        v = np.exp(logv)
        beta = rng.uniform(0.5, 1.5, N_NAMES)[:, None]
        sector = rng.integers(0, 10, N_NAMES)
        gaps = (beta * 0.008 * v * t5(rng, n) + 0.004 * v * rng.normal(size=(10, n))[sector]
                + 0.015 * v * t5(rng, (N_NAMES, n)))
        vb = (v[:, None] * U_SHAPE)[None]                         # (1, n, SLOTS)
        rets = vb * (beta[:, :, None] * 0.0014 * t5(rng, (n, SLOTS))[None]
                     + 0.0008 * rng.normal(size=(10, n, SLOTS))[sector]
                     + 0.0020 * t5(rng, (N_NAMES, n, SLOTS)))
    gaps, rets = np.clip(gaps, -0.2, 0.2), np.clip(rets, -0.05, 0.05)
    level = rng.lognormal(9.5, 0.5, N_NAMES)[:, None, None]
    vols = level * rng.lognormal(0, 0.5, (N_NAMES, n, SLOTS)) * U_SHAPE
    wick = np.abs(rng.normal(0, 0.0008, (N_NAMES, n, SLOTS, 2)))
    series = {}
    for j in range(N_NAMES):
        c = 100.0 * (1 + j / N_NAMES)
        s = {"open": [], "high": [], "low": [], "close": [], "volume": [], "m15": [], "h1": []}
        for d in range(n):
            o = c * (1 + gaps[j, d])
            closes = o * np.cumprod(1 + rets[j, d])
            opens = np.concatenate(([o], closes[:-1]))
            hi = np.maximum(opens, closes) * (1 + wick[j, d, :, 0])
            lo = np.minimum(opens, closes) * (1 - wick[j, d, :, 1])
            a = np.stack([opens, hi, lo, closes, vols[j, d]], axis=1)
            h = np.array([[a[k, 0], a[k:k + 4, 1].max(), a[k:k + 4, 2].min(),
                           a[min(k + 3, SLOTS - 1), 3], a[k:k + 4, 4].sum()]
                          for k in range(0, SLOTS, 4)])
            s["m15"].append(Day(a))
            s["h1"].append(Day(h))
            s["open"].append(float(o))
            s["close"].append(float(closes[-1]))
            s["high"].append(float(hi.max()))
            s["low"].append(float(lo.min()))
            s["volume"].append(float(vols[j, d].sum()))
            c = float(closes[-1])
        series[f"K{j:03d}"] = s
    return series


def years() -> list[int]:
    d, out = _dt.date(2022, 1, 3), []
    while len(out) < TEST:
        if d.weekday() < 5:
            out.append(d.year)
        d += _dt.timedelta(days=1)
    return out


YEARS = years()
REGULAR = [True] * (WARM + TEST)
ZERO = E4.SessionCost(1e12, half_spread_bps=0.0, rates=E4.X.Rates(
    0.0, None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "zero (calibration)", "-"))


def one(args) -> dict[str, dict]:
    kind, seed, b = args
    series = world(kind, seed)
    rows = {h: [] for h in X.HYPOTHESES}
    for i, d in enumerate(range(WARM, WARM + TEST)):
        base = E4.eligible(series, d, {})
        for h in X.HYPOTHESES:
            sess = X.form_session(series, d, {}, h, REGULAR, seed=seed, base=base)
            r = X.primary(E4.apply_mask(sess, series), series, ZERO)
            rows[h].append((YEARS[i], {**r, "unmatched": sess["unmatched"]}))
    out = {}
    for h, rr in rows.items():
        ok = [(y, r) for y, r in rr if r["s"] is not None]
        pl = [(y, r["placebo"]) for y, r in rr if r["placebo"] is not None]
        if len(ok) < 50 or len(pl) < 50:
            out[h] = {"skipped": True}
            continue
        prim = X.summarise([r["s"] for _, r in ok], [y for y, _ in ok], b=b, seed=seed)
        plac = X.summarise([v for _, v in pl], [y for y, _ in pl], b=b, seed=seed + 1)
        delta = (X.summarise([r["delta"] for _, r in ok], [y for y, _ in ok], b=b,
                             seed=seed + 2) if h == "B3" else None)
        acc = X.acceptance(prim, at_stress=prim.mean, placebo=plac, delta=delta)
        o = {"accepted": acc["candidate"]["status"] == "ACCEPTED-EXPLORATORY",
             "a1_pass": acc["A1"] == "PASS",
             "ci_excludes_0": not (prim.ci[0] <= 0 <= prim.ci[1]),
             "placebo_fail": acc["A4"] == "FAIL", "mean": prim.mean, "n": len(ok),
             "unmatched_per_session": float(np.mean([r["unmatched"] for _, r in rr]))}
        if delta is not None:
            o["delta_ci_excludes_0"] = not (delta.ci[0] <= 0 <= delta.ci[1])
            o["adopted"] = acc["adopt_target_stop"]
            o["delta_mean"] = delta.mean
        out[h] = o
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
                          + (ROOT / "app/training/e4b.py").read_bytes()
                          + pathlib.Path(__file__).read_bytes()).hexdigest()
    res: dict = {"worlds": a.worlds, "sign_vectors": a.b, "code_sha256": code,
                 "level": X.LEVEL, "seed_base": SEED_BASE,
                 "criterion": "every hypothesis, every world type: Wilson 95% upper of "
                              f"accepted <= {BOUND:.4f} and the Wilson 95% interval of "
                              f"ci_excludes_0 contains {BOUND:.4f}", "by_world": {}}
    adequate = True
    for kind in ("iid", "factor"):
        with ProcessPoolExecutor(a.jobs) as ex:
            rows = list(ex.map(one, [(kind, s, a.b) for s in range(a.worlds)], chunksize=1))
        print(f"[{now().astimezone(IST):%H:%M:%S}] {kind} done", flush=True)
        res["by_world"][kind] = {}
        for h in X.HYPOTHESES:
            rr = [r[h] for r in rows if not r[h].get("skipped")]
            st = {"worlds_used": len(rr)}
            names = ["accepted", "a1_pass", "ci_excludes_0", "placebo_fail"]
            names += ["delta_ci_excludes_0", "adopted"] if h == "B3" else []
            for k in names:
                c = sum(x[k] for x in rr)
                st[k] = {"count": c, "rate": c / len(rr) if rr else None,
                         "wilson95": wilson(c, len(rr))}
            ms = [x["mean"] for x in rr]
            st["mean_of_means_bps"] = round(float(np.mean(ms)) * 1e4, 4) if ms else None
            st["se_bps"] = round(float(np.std(ms) / np.sqrt(len(ms))) * 1e4, 4) if ms else None
            if h == "B3" and rr:
                dm = [x["delta_mean"] for x in rr]
                st["delta_mean_of_means_bps"] = round(float(np.mean(dm)) * 1e4, 4)
            res["by_world"][kind][h] = st
            lo, hi = st["ci_excludes_0"]["wilson95"]
            if st["accepted"]["wilson95"][1] > BOUND or not lo <= BOUND <= hi:
                adequate = False
    res["adequate"] = adequate if a.worlds >= 1000 else None
    res["at"] = now().astimezone(IST).isoformat()
    body = json.dumps(res, indent=1, sort_keys=True)
    if a.write:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "null_calibration.json"
        if path.exists():
            raise SystemExit(f"REFUSED: {path.name} exists; not overwritten")
        path.write_text(body)
        res["written"], res["sha256"] = str(path), hashlib.sha256(body.encode()).hexdigest()
    print(json.dumps(res, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
