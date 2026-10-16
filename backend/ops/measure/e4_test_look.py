"""E4a step 4: the SINGLE test look (design docs/STAGE4_E4_INTRADAY_DESIGN_DRAFT.md,
D1-D6 approved 2026-10-15; the look approved by the user 2026-10-15, conditional on an
ADEQUATE null calibration). Research only: reads the frozen step-2 dataset (no database,
no vendor), writes one result file, no orders, no profitability claim.

  .venv/bin/python ops/measure/e4_test_look.py config                     # prints the sha
  .venv/bin/python ops/measure/e4_test_look.py test --confirm-test-look E4-<sha12> [--jobs 30]

Refuses unless: the dataset's content sha equals the frozen manifest; the working tree is
clean; var/stage4/experiments/e4/null_calibration_c1.json is a >= 1,000-world calibration of
the CURRENT e4.py + calibration script and marked adequate; no test file of this
configuration exists; the confirmation string matches.

Pre-registered machinery (unchanged, app/training/e4.py): 09:15 signals, the universe,
matched controls (turnover x volatility x gap cells), the locked-day mask, MIS costs on a
full round trip at Rs 10 L (K = 10, Rs 1 L orders), half-spread 5 bps, untraded control,
studentized block bootstrap (block 5) at 97.5 % with Newey-West lag 4, A1-A4 (A2 at 1.5x
costs, A3 by calendar year). TEST: every session 2021-01-01 .. 2026-09-30.

Data-quality mask (design section 2): the E3 suspect_sessions rule on the frozen arrays
(|close or open / prev close - 1| > 25 %, or a malformed bar). With no exact-factor
exemption: the arrays are already split/bonus-adjusted, so a genuine action leaves no
jump and the rule is the conservative superset of E2 Amendment 3's EXTREME_UNEXPLAINED.
A suspect session in the past year removes a name from the universe (e4.eligible); a
suspect session ON d removes the name from every arm after selection (as E2 Amendment 3).

Sensitivities (reported, never acceptance): K = 5 (Rs 2 L orders); slippage 5 / 10 / 20 bps;
the E1 TEST sessions (2026-04-27 .. 2026-09-17) excluded.
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
from typing import Any

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.clock import IST, now  # noqa: E402
from app.training import e3 as E3  # noqa: E402
from app.training import e4 as X  # noqa: E402

DATA = ROOT / "var/stage4/e4/e4_daily_20261015T1545+0530.npz"
MANIFEST = DATA.with_suffix(".json")
CONTENT_SHA = "85840092d77e630305ae06f21e85e328b808fe09fa7b5361791f3605a9bc5310"
OUT = ROOT / "var/stage4/experiments/e4"
CALIBRATION = OUT / "null_calibration_c1.json"   # C1 (block 20)
TEST = (_dt.date(2021, 1, 1), _dt.date(2026, 9, 30))
E1_TEST = (_dt.date(2026, 4, 27), _dt.date(2026, 9, 17))
CAPITAL, HALF_SPREAD, STRESS, B, SEED = 1_000_000.0, 5.0, 1.5, 10_000, 0
SLIPPAGES, K_SENS = (5.0, 10.0, 20.0), 5

CONFIG = {"design": "STAGE4_E4_INTRADAY_DESIGN_DRAFT D1-D6",
          "dataset_content_sha256": CONTENT_SHA,
          "predictors": list(X.PREDICTORS), "k": X.K, "k_sensitivity": K_SENS,
          "capital_inr": CAPITAL, "half_spread_bps": HALF_SPREAD, "stress_multiplier": STRESS,
          "slippage_sensitivity_bps": list(SLIPPAGES), "bootstrap_draws": B, "seed": SEED,
          "level": 0.975, "block": X.BLOCK, "nw_lag": X.NW_LAG,
          "test": [str(d) for d in TEST], "e1_excluded_sensitivity": [str(d) for d in E1_TEST],
          "mask": "e3.suspect_sessions (no exact-factor exemption) + e4 locked day",
          "rates": X.MIS.source + " @ " + X.MIS.as_of}


def config_sha() -> str:
    return hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()


def calibration_code_sha() -> str:
    """As ops/measure/e4_null_calibration.py records it: e4.py + the calibration script."""
    return hashlib.sha256((ROOT / "app/training/e4.py").read_bytes()
                          + (ROOT / "ops/measure/e4_null_calibration.py").read_bytes()).hexdigest()


def calibration_ok(path: pathlib.Path, code_sha: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"no calibration file {path.name}"
    c = json.loads(path.read_text())
    if c.get("code_sha256") != code_sha:
        return False, "the calibration ran other e4 code: recalibrate (new file)"
    if c.get("worlds", 0) < 1000:
        return False, f"calibration has {c.get('worlds')} worlds < 1000"
    if c.get("adequate") is not True:
        return False, "calibration is not adequate: propose a correction (do not tune)"
    return True, "adequate"


def check_look(out: pathlib.Path, sha: str, *, dirty: bool, confirm: str | None,
               calibration: pathlib.Path, code_sha: str) -> None:
    if dirty:
        raise SystemExit("REFUSED: the working tree is dirty; commit first")
    if (out / f"test_{sha[:12]}.json").exists():
        raise SystemExit(f"REFUSED: test_{sha[:12]}.json exists - the single test look was taken")
    if confirm != f"E4-{sha[:12]}":
        raise SystemExit(f"REFUSED: the test look needs --confirm-test-look E4-{sha[:12]}")
    ok, why = calibration_ok(calibration, code_sha)
    if not ok:
        raise SystemExit(f"REFUSED: {why}")


# ── data ─────────────────────────────────────────────────────────────────────────────
def load() -> tuple[list[_dt.date], dict[str, dict[str, list]]]:
    z = np.load(DATA)
    import importlib.util
    spec = importlib.util.spec_from_file_location("e4_build_dataset",
                                                  ROOT / "ops/measure/e4_build_dataset.py")
    bd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bd)
    FIELDS, content_sha256 = bd.FIELDS, bd.content_sha256
    keys = [str(k) for k in z["keys"]]
    days = [_dt.date.fromisoformat(str(d)) for d in z["sessions"]]
    arrays = {f: z[f] for f in FIELDS}
    if content_sha256(keys, days, arrays) != CONTENT_SHA:
        raise SystemExit("REFUSED: the dataset content differs from the frozen manifest")
    series = {k: {f: [None if not math.isfinite(v) else float(v) for v in arrays[f][j]]
                  for f in FIELDS} for j, k in enumerate(keys)}
    return days, series


def mask_suspect_on_d(sess: dict[str, Any], suspect: dict[str, set[int]]) -> dict[str, Any]:
    """Drop names whose session d is suspect from every arm, after selection."""
    d = sess["d"]

    def f(names: list[str]) -> list[str]:
        return [n for n in names if d not in suspect.get(n, ())]
    return {**sess, "arms": {a: f(v) for a, v in sess["arms"].items()},
            "masked_suspect": len(sess["arms"]["P"]) - len(f(sess["arms"]["P"]))}


# ── the per-session book (worker) ────────────────────────────────────────────────────
_S: dict[str, Any] = {}


def _init(series, suspect):
    _S["series"], _S["suspect"] = series, suspect


COSTS = {"primary": X.SessionCost(CAPITAL, HALF_SPREAD),
         "stress": X.SessionCost(CAPITAL, HALF_SPREAD, multiplier=STRESS),
         **{f"slip{int(s)}": X.SessionCost(CAPITAL, HALF_SPREAD, slippage_bps=s)
            for s in SLIPPAGES}}


def session(args: tuple[str, int]) -> dict[str, Any]:
    pred, d = args
    series, suspect = _S["series"], _S["suspect"]
    out: dict[str, Any] = {"d": d}
    for tag, k in (("k10", X.K), ("k5", K_SENS)):
        s = X.form_session(series, d, suspect, pred, k=k, seed=SEED)
        s = mask_suspect_on_d(X.apply_mask(s, series), suspect)
        names = ("primary", "stress", *(f"slip{int(x)}" for x in SLIPPAGES)) if tag == "k10" \
            else ("primary",)
        for c in names:
            r = X.primary(s, series, COSTS[c])
            out[f"{tag}_{c}"] = r["s"]
            if c == "primary":
                out[f"{tag}_placebo"] = r["placebo"]
                if tag == "k10":
                    out.update(p_gross=r["p_gross"], c2_gross=r["c2_gross"], cost=r["cost"],
                               c0_gross=r["c0_gross"], picks=r["picks"],
                               unmatched=s["unmatched"], universe=s["universe"],
                               masked_locked=s["masked_picks"],
                               masked_suspect=s["masked_suspect"])
    return out


def _res(r: E3.Result) -> dict[str, Any]:
    return {"mean_bps": round(r.mean * 1e4, 3), "ci_bps": [round(v * 1e4, 3) for v in r.ci],
            "n": r.n, "nw_t": None if r.nw_t is None else round(r.nw_t, 3),
            "year_means_bps": {str(y): round(v * 1e4, 3) for y, v in r.year_means.items()},
            "max_drawdown": r.max_drawdown}


def evaluate(rows: list[dict[str, Any]], days: list[_dt.date]) -> dict[str, Any]:
    def series_of(field: str, keep=lambda d: True) -> tuple[list[float], list[int]]:
        xs = [(r[field], days[r["d"]].year) for r in rows
              if r.get(field) is not None and keep(days[r["d"]])]
        return [x for x, _ in xs], [y for _, y in xs]

    s, y = series_of("k10_primary")
    pl, py = series_of("k10_placebo")
    prim, plac = X.summarise(s, y, b=B, seed=SEED), X.summarise(pl, py, b=B, seed=SEED + 1)
    st, _ = series_of("k10_stress")
    acc = X.acceptance(prim, at_stress=float(np.mean(st)), placebo=plac)
    sens = {}
    for f in ("k5_primary", *(f"k10_slip{int(x)}" for x in SLIPPAGES)):
        xs, ys = series_of(f)
        sens[f] = _res(X.summarise(xs, ys, b=B, seed=SEED))
    xs, ys = series_of("k10_primary", lambda d: not E1_TEST[0] <= d <= E1_TEST[1])
    sens["k10_primary_e1_excluded"] = _res(X.summarise(xs, ys, b=B, seed=SEED))

    def avg(f):
        v = [r[f] for r in rows if r.get(f) is not None]
        return round(float(np.mean(v)), 6) if v else None
    return {"primary": _res(prim), "placebo": _res(plac),
            "stress_mean_bps": round(float(np.mean(st)) * 1e4, 3), "acceptance": acc,
            "status": acc["candidate"]["status"], "sensitivities": sens,
            "mde_bps": round(X.minimum_detectable(float(np.std(s)), len(s)) * 1e4, 3),
            "diagnostics": {"sessions": len(rows), "with_s": len(s),
                            **{f"mean_{f}": avg(f) for f in
                               ("p_gross", "c2_gross", "c0_gross", "cost", "picks", "unmatched",
                                "universe", "masked_locked", "masked_suspect")}}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("config", "test"))
    ap.add_argument("--confirm-test-look")
    ap.add_argument("--jobs", type=int, default=30)
    a = ap.parse_args()
    sha = config_sha()
    if a.phase == "config":
        print(json.dumps({"config_sha256": sha, "confirm": f"E4-{sha[:12]}", **CONFIG}, indent=1))
        return 0
    from app.training import replay as RP
    code = RP.code_version()
    check_look(OUT, sha, dirty=code["dirty"], confirm=a.confirm_test_look,
               calibration=CALIBRATION, code_sha=calibration_code_sha())
    started = now().astimezone(IST).isoformat()
    days, series = load()
    suspect = {k: E3.suspect_sessions(s) for k, s in series.items()}
    idx = [i for i, d in enumerate(days) if TEST[0] <= d <= TEST[1]]
    res: dict[str, Any] = {"config_sha256": sha, "config": CONFIG, "code": code,
                           "calibration_sha256":
                               hashlib.sha256(CALIBRATION.read_bytes()).hexdigest(),
                           "started": started, "test_sessions": len(idx),
                           "label": "EXPLORATORY research result; no profitability claim",
                           "by_predictor": {}}
    with ProcessPoolExecutor(a.jobs, initializer=_init, initargs=(series, suspect)) as ex:
        for pred in X.PREDICTORS:
            rows = list(ex.map(session, [(pred, d) for d in idx], chunksize=8))
            res["by_predictor"][pred] = evaluate(rows, days)
    res["finished"] = now().astimezone(IST).isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"test_{sha[:12]}.json"
    if path.exists():
        raise SystemExit(f"REFUSED: {path.name} appeared during the run; not overwritten")
    body = json.dumps(res, indent=1, sort_keys=True, default=str)
    path.write_text(body)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
