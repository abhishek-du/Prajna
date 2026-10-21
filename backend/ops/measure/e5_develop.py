"""E5 development: walk-forward out-of-sample evaluation of the recipe on the AS_IF_LIVE v3
dataset (2025-09-24 .. 2026-10-09). EXPLORATORY - these sessions overlap the spent E1/E2/E4
test windows, so nothing here is a confirmatory result; the confirmatory test is the
pre-registered forward window (docs/STAGE4_E5_PREREGISTRATION.md). Read only; no database
write; no model is stored.

Folds: train on the TRAIN_SESSIONS (120) sessions ending 2 sessions before the block
(1-session embargo), predict the next 20 sessions, roll by 20. Every fit sees only sessions
before its block (labels of session d are known at its close, before d + 1).

  .venv/bin/python ops/measure/e5_develop.py [--refresh-cache] [--folds N]
Writes var/stage4/experiments/e5/develop_<recipe sha>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import pathlib
import pickle
import sys
import time

import numpy as np
from sqlalchemy import text

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.clock import now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.models import data as D  # noqa: E402
from app.models import evaluate as EV  # noqa: E402
from app.models import recipe as R  # noqa: E402

OUT = ROOT / "var/stage4/experiments/e5"
CACHE = OUT / "panel_asif_v3.pkl"
BLOCK, EMBARGO = 20, 1


async def load_panel() -> list[D.Session]:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        days = await D.training_sessions(s)
        panel = []
        for d in days:
            sess = await D.training_session(s, d)
            if sess is not None:
                panel.append(sess)
        await s.rollback()
    return panel


def recipe_sha() -> str:
    src = (ROOT / "app/models/recipe.py").read_bytes() + (ROOT / "app/models/data.py").read_bytes()
    return hashlib.sha256(src).hexdigest()


def folds(n: int, limit: int | None) -> list[tuple[list[int], list[int]]]:
    out, start = [], R.TRAIN_SESSIONS + EMBARGO
    while start < n:
        train = list(range(start - EMBARGO - R.TRAIN_SESSIONS, start - EMBARGO))
        out.append((train, list(range(start, min(start + BLOCK, n)))))
        start += BLOCK
    return out[:limit] if limit else out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-cache", action="store_true")
    ap.add_argument("--folds", type=int)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    if CACHE.exists() and not a.refresh_cache:
        panel = pickle.loads(CACHE.read_bytes())  # noqa: S301 - our own cache file
    else:
        panel = asyncio.run(load_panel())
        CACHE.write_bytes(pickle.dumps(panel, protocol=5))
    load_s = time.monotonic() - t0
    per, fold_rep = [], []
    for f, (train, test) in enumerate(folds(len(panel), a.folds)):
        t1 = time.monotonic()
        b = R.fit(panel, train)
        rows = []
        for t in test:
            out = R.predict(b, panel, t)
            picks = R.select(out, b.cost)
            ev = EV.session(panel[t], out, picks, b.cost, seed=R.SEED)
            ev["fold"] = f
            members = {}
            u = out["idx"]
            y = panel[t].y["ret_oc"][u]
            ok = ~np.isnan(y) & ~panel[t].masked[u]
            for k, v in out["members"].items():
                members[k] = EV.E1.spearman(v[ok], y[ok]) if ok.sum() > 20 else None
            ev["member_ic"] = members
            rows.append(ev)
        per += rows
        fold_rep.append({"fold": f, "train": [str(panel[train[0]].date),
                                              str(panel[train[-1]].date)],
                         "test": [str(panel[test[0]].date), str(panel[test[-1]].date)],
                         "bundle_sha256": b.sha256(), "meta": b.meta,
                         "seconds": round(time.monotonic() - t1, 1),
                         "pooled": EV.pooled(rows, seed=R.SEED)})
        print(json.dumps({"fold": f, **{k: fold_rep[-1]["pooled"].get(k) for k in
                                        ("auc", "ic", "s_mean", "picks", "cash_sessions")}}),
              flush=True)
    mic = {k: EV._mean([p["member_ic"].get(k) for p in per if "member_ic" in p])
           for k in per[0]["member_ic"]} if per else {}
    rep = {"experiment": "E5", "phase": "develop", "status": "EXPLORATORY",
           "recipe": R.VERSION, "recipe_sha256": recipe_sha(), "generated_at": now().isoformat(),
           "dataset": D.TRAIN_DATASET, "labels": D.TRAIN_LABELS, "sessions": len(panel),
           "panel": [str(panel[0].date), str(panel[-1].date)], "load_seconds": round(load_s, 1),
           "round_trip_cost": R.round_trip_cost(), "folds": fold_rep,
           "pooled": EV.pooled(per, seed=R.SEED), "member_ic": mic, "per_session": per}
    path = OUT / f"develop_{rep['recipe_sha256'][:12]}.json"
    path.write_text(json.dumps(rep, indent=1, default=str) + "\n")
    print(json.dumps({"pooled": rep["pooled"], "member_ic": mic}, default=str))
    print(f"written {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
