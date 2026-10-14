"""E2 inference calibration on synthetic NOISE worlds (no database, no real data):
how often the pre-registered 97.5% moving-block bootstrap CI (block 2H = 10) excludes 0
when the true edge is 0, for the matched gross excess and the placebo; also block 20
and the Newey-West t (|t| > 2.2414). Nominal rate: 2.5%.

  .venv/bin/python ops/measure/e2_null_calibration.py [--worlds 100] [--b 500]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.training import e1 as E  # noqa: E402
from app.training import e2 as X  # noqa: E402
from tests.training.test_e2 import CNC, world  # noqa: E402

TESTS = ((20, 40), (40, 60), (60, 80), (80, 100), (100, 120))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=100)
    ap.add_argument("--b", type=int, default=500)
    a = ap.parse_args()
    cm = X.CostModel(CNC, 5e7, 3.63)
    rej = dict.fromkeys(("placebo_b10", "gross_b10", "gross_b20", "placebo_nw", "gross_nw"), 0)
    pl_means = []
    for seed in range(100, 100 + a.worlds):
        s, o = world(edge=0.0, seed=seed)
        blocks = [(f, X.form_block(s, range(x, y), lambda z, u: E.reversal(z), X.K100, seed=7))
                  for f, (x, y) in enumerate(TESTS)]
        r = X.evaluate(blocks, o, cm, b=a.b, seed=3)
        for k, name in (("placebo", "placebo_gross_vs_its_c2"), ("gross", "gross_vs_c2_gross")):
            R = r["results"][name]
            rej[f"{k}_b10"] += not (R["ci"][0] <= 0 <= R["ci"][1])
            rej[f"{k}_nw"] += abs(R["nw_t"] or 0) > 2.2414
        lo, hi = E.block_bootstrap_ci(r["series"]["gross_vs_c2_gross"], b=a.b, block=20,
                                      level=0.975, seed=3)
        rej["gross_b20"] += not (lo <= 0 <= hi)
        pl_means.append(r["results"]["placebo_gross_vs_its_c2"]["mean"])
    se = 1.96 * np.sqrt(0.025 * 0.975 / a.worlds)
    print(json.dumps({"worlds": a.worlds, "bootstrap_draws": a.b, "nominal": 0.025,
                      "nominal_95pct_band": [round(0.025 - se, 4), round(0.025 + se, 4)],
                      "false_rejection_rate": {k: v / a.worlds for k, v in rej.items()},
                      "placebo_mean_bps": round(float(np.mean(pl_means)) * 1e4, 3),
                      "placebo_mean_se_bps": round(float(np.std(pl_means) /
                                                         np.sqrt(a.worlds)) * 1e4, 3)},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
