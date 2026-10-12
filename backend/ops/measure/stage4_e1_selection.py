"""E1 - pre-session stock selection in the tradable universe (design approved 2026-10-12;
the computation is app/training/e1.py). Research only: no model is stored, nothing is
written to the database (REPEATABLE READ, READ ONLY), no profitability claim.

Phases (every run is appended to var/stage4/experiments/e1/ledger.jsonl):
  validate  loads TRAIN and VALID sessions only; freezes the configuration and, for
            ridge24, the penalty chosen per fold on VALID (mean rank IC). It reports NO
            performance metric: each fold's VALID block overlaps the previous fold's TEST
            block, so a VALID result would be an early look at the test period.
  test      the single look at the TEST blocks: requires the validate file of the same
            configuration and refuses when a test file for it exists. Writes the pooled
            metrics, the controls, the sensitivities and acceptance A1-A5.
  recost    no database: applies an approved cost model to a stored test result (A2).
            Costs never feed back into selection, so this is not a second look.

  .venv/bin/python ops/measure/stage4_e1_selection.py validate [--predictors reversal,ridge24]
  .venv/bin/python ops/measure/stage4_e1_selection.py test     [same options]
  .venv/bin/python ops/measure/stage4_e1_selection.py recost --result <test json> \
      --cost-model <json: {"name", "per_side_bps", "approved_by", "source"}>
Running ridge24 fits a model (needs the separate approval for P2).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import sys
from typing import Any

import numpy as np
from sqlalchemy import text

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.clock import IST, now  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.training import e1 as E  # noqa: E402
from app.training import policy as P  # noqa: E402
from app.training import quarantine as QR  # noqa: E402
from app.training import replay as RP  # noqa: E402

OUT = ROOT / "var/stage4/experiments/e1"
TARGETS = {"label-v2": "ret_oc", "label-tsl-long-v1-asif": "tsl_l_k1p5_gross_ret"}
ALPHAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)
SWEEP_BPS = (0, 10, 20, 30, 40)


def config(a: argparse.Namespace) -> dict[str, Any]:
    return {"experiment": "E1", "dataset": P.DATASETS[a.dataset].version,
            "label_version": a.labels, "target": TARGETS[a.labels], "snapshot": "PRE_SESSION",
            "universe_top": a.top, "tiers": [[0, 200], [200, a.top]], "pick_frac": 0.2,
            "predictors": a.predictors.split(","), "ridge_alphas": list(ALPHAS),
            "ridge_selection": "VALID mean rank IC per fold, ties to the larger penalty",
            "controls": ["C0", "C1", "C2", "placebo"], "c2_cells": "turnover_20 decile x "
            "atr_pct_14 decile within the session universe",
            "eval_masks": list(E.EVAL_MASKS), "eval_flag_prefixes": list(E.EVAL_FLAG_PREFIXES),
            "sensitivities": ["unmasked", "tier_1_200", "tier_201_top", "low_price_q20"],
            "bootstrap": a.bootstrap, "block": 5, "ci_level": 0.975, "perm_draws": 2000,
            "seed": a.seed, "cost_sweep_bps_per_side": list(SWEEP_BPS)}


def cfg_sha(cfg: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def ledger(entry: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "ledger.jsonl").open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ── database (read only) ───────────────────────────────────────────────────────────────
async def folds(s, dataset: str, lv: str) -> dict[int, dict[str, list[_dt.date]]]:
    sessions = list((await s.execute(text("""select session_date from training_session_done
        where dataset_version = :v and snapshot = 'PRE_SESSION' order by 1"""),
        {"v": dataset})).scalars())
    out: dict[int, dict[str, list[_dt.date]]] = {}
    for f, role, a, b in (await s.execute(text("""select fold, role, session_from, session_to
            from training_split where dataset_version = :v and label_version = :lv
              and snapshot = 'PRE_SESSION' order by fold, role"""),
            {"v": dataset, "lv": lv})).all():
        out.setdefault(f, {})[role] = [d for d in sessions if a <= d <= b]
    if not out:
        raise SystemExit(f"REFUSED: no PRE_SESSION splits for {dataset} / {lv}")
    return out


async def load_session(s, dataset: str, lv: str, target: str, day: _dt.date,
                       top: int) -> dict[str, Any] | None:
    """The PIT universe candidates of one session: feature-eligible samples, ranked by
    turnover_20 (desc, key) in SQL and cut at `top`; their 24 core features, masks,
    label flags and the target label (NaN unless VALID)."""
    cols = ", ".join(f"max(value) filter (where feature_id = '{f}') as f{i}"
                     for i, f in enumerate(E.CORE24))
    TURN = E.CORE24.index("turnover_20")
    rows = (await s.execute(text(f"""
        with smp as (select instrument_key, masks, label_flags from training_sample
              where dataset_version = :v and label_version = :lv and snapshot = 'PRE_SESSION'
                and session_date = :d and feature_eligible),
        f as (select instrument_key, {cols} from training_feature_value
              where dataset_version = :v and snapshot = 'PRE_SESSION' and session_date = :d
                and status = 'VALID' and feature_id = any(:ids) group by 1),
        j as (select *, row_number() over (order by f{TURN} desc, instrument_key) as rk
              from smp join f using (instrument_key))
        select j.*, l.value as y, l.status as ystatus from j
        left join training_label l on l.label_version = :lv and l.label_id = :t
          and l.session_date = :d and l.instrument_key = j.instrument_key
        where j.rk <= :top order by j.rk"""),  # noqa: S608 - identifiers are constants
        {"v": dataset, "lv": lv, "d": day, "ids": list(E.CORE24), "t": target,
         "top": top})).mappings().all()
    rows = [r for r in rows if all(r[f"f{i}"] is not None for i in range(len(E.CORE24)))]
    if not rows:
        return None
    X = np.array([[float(r[f"f{i}"]) for i in range(len(E.CORE24))] for r in rows])
    y = np.array([float(r["y"]) if r["ystatus"] == "VALID" and r["y"] is not None
                  else np.nan for r in rows])
    masked = np.array([any(m in E.EVAL_MASKS for m in (r["masks"] or []))
                       or any(fl.startswith(E.EVAL_FLAG_PREFIXES) for fl in
                              (r["label_flags"] or [])) for r in rows])
    ok = ~np.isnan(y)
    return {"date": day, "keys": [r["instrument_key"] for r in rows], "X": X, "y": y,
            "turnover": X[:, E.CORE24.index("turnover_20")],
            "atr": X[:, E.CORE24.index("atr_pct_14")], "price": X[:, E.CORE24.index("sma_20")],
            "ev_masked": ok & ~masked, "ev_unmasked": ok}


class Loader:
    def __init__(self, s, cfg: dict[str, Any]):
        self.s, self.cfg, self.cache = s, cfg, {}

    async def get(self, day: _dt.date) -> dict[str, Any] | None:
        if day not in self.cache:
            self.cache[day] = await load_session(self.s, self.cfg["dataset"],
                                                 self.cfg["label_version"], self.cfg["target"],
                                                 day, self.cfg["universe_top"])
        return self.cache[day]


def view(sess: dict[str, Any], masked: bool = True) -> dict[str, Any]:
    return {**sess, "evaluable": sess["ev_masked"] if masked else sess["ev_unmasked"]}


async def fit_ridge(L: Loader, days: list[_dt.date], top: int, alpha: float) -> np.ndarray:
    rows = []
    for d in days:
        sess = await L.get(d)
        if sess:
            v = view(sess)
            rows.append(E.ridge_rows(v, E.universe(v, top)))
    return E.ridge_fit([r for r in rows if len(r[1])], alpha)


# ── phases ─────────────────────────────────────────────────────────────────────────────
async def guard(s, cfg: dict[str, Any]) -> None:
    if "PRE_SESSION" in await QR.snapshots(s, cfg["dataset"], cfg["label_version"]):
        raise SystemExit("REFUSED: the PRE_SESSION slice is quarantined")


async def validate(cfg: dict[str, Any], sha: str) -> dict[str, Any]:
    if (OUT / f"test_{sha[:12]}.json").exists():
        raise SystemExit("REFUSED: this configuration already had its test look")
    out: dict[str, Any] = {"phase": "validate", "config_sha256": sha, "config": cfg,
                           "chosen_alpha": {}, "metrics": "none by design (see docstring)"}
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        await guard(s, cfg)
        fs = await folds(s, cfg["dataset"], cfg["label_version"])
        out["folds"] = {str(k): {r: [str(v[r][0]), str(v[r][-1]), len(v[r])] for r in v}
                        for k, v in fs.items()}
        if "ridge24" in cfg["predictors"]:
            L, top = Loader(s, cfg), cfg["universe_top"]
            for k, f in fs.items():
                best = None
                for alpha in cfg["ridge_alphas"]:
                    w = await fit_ridge(L, f["TRAIN"], top, alpha)
                    ics = []
                    for d in f["VALID"]:
                        sess = await L.get(d)
                        if sess:
                            v = view(sess)
                            u = E.universe(v, top)
                            ue = u[v["evaluable"][u]]
                            ic = E.spearman(E.ridge_score(v, u, w)[ue], v["y"][ue])
                            if ic is not None:
                                ics.append(ic)
                    m = float(np.mean(ics)) if ics else -np.inf
                    if best is None or m >= best[0]:
                        best = (m, alpha)
                out["chosen_alpha"][str(k)] = best[1]
        await s.rollback()
    return out


async def test(cfg: dict[str, Any], sha: str, cost: dict[str, Any] | None) -> dict[str, Any]:
    vpath, tpath = OUT / f"validate_{sha[:12]}.json", OUT / f"test_{sha[:12]}.json"
    if not vpath.exists():
        raise SystemExit("REFUSED: run the validate phase of this configuration first")
    if tpath.exists():
        raise SystemExit(f"REFUSED: {tpath.name} exists - the single test look was taken")
    frozen = json.loads(vpath.read_text())
    if frozen["config_sha256"] != sha:
        raise SystemExit("REFUSED: the validate file belongs to another configuration")
    top = cfg["universe_top"]
    variants = {"primary": dict(masked=True, tier=None, lowp=None),
                "unmasked": dict(masked=False, tier=None, lowp=None),
                "tier_1_200": dict(masked=True, tier=tuple(cfg["tiers"][0]), lowp=None),
                "tier_201_top": dict(masked=True, tier=tuple(cfg["tiers"][1]), lowp=None),
                "low_price_q20": dict(masked=True, tier=None, lowp=0.2)}
    out: dict[str, Any] = {"phase": "test", "config_sha256": sha, "config": cfg,
                           "chosen_alpha": frozen["chosen_alpha"], "predictors": {},
                           "folds_total": None}
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        await guard(s, cfg)
        fs = await folds(s, cfg["dataset"], cfg["label_version"])
        out["folds_total"] = len(fs)
        L = Loader(s, cfg)
        weights = {}
        if "ridge24" in cfg["predictors"]:
            for k, f in fs.items():
                weights[k] = await fit_ridge(L, f["TRAIN"], top, frozen["chosen_alpha"][str(k)])
        for pred in cfg["predictors"]:
            res: dict[str, Any] = {}
            for name, vv in variants.items():
                per, fold_of = [], []
                for k, f in sorted(fs.items()):
                    for d in f["TEST"]:
                        sess = await L.get(d)
                        if not sess:
                            continue
                        v = view(sess, vv["masked"])
                        u = E.universe(v, top, vv["tier"], vv["lowp"])
                        score = (E.reversal(v) if pred == "reversal"
                                 else E.ridge_score(v, u, weights[k]))
                        rng = np.random.default_rng([cfg["seed"], d.toordinal()])
                        r = E.evaluate_session(v, u, score, rng=rng, frac=cfg["pick_frac"])
                        r["date"] = str(d)
                        per.append(r)
                        fold_of.append(k)
                summ = E.summarise(per, fold_of, b=cfg["bootstrap"], block=cfg["block"],
                                   level=cfg["ci_level"], seed=cfg["seed"],
                                   perm_draws=cfg["perm_draws"])
                summ["dates"] = [p["date"] for p in per if p["excess_c2"] is not None]
                res[name] = summ
            res["cost_sweep_illustrative"] = [E.net_view(res["primary"], b)
                                              for b in cfg["cost_sweep_bps_per_side"]]
            out["predictors"][pred] = res
        await s.rollback()
    p1 = out["predictors"].get("reversal", {}).get("primary", {}).get("primary_mean_excess_c2")
    for pred, res in out["predictors"].items():
        res["acceptance"] = E.acceptance(res["primary"], folds_total=len(fs), cost=cost,
                                         p1_mean=p1, is_p2=pred == "ridge24")
    out["cost_model"] = cost
    return out


def recost(result: pathlib.Path, cost: dict[str, Any]) -> dict[str, Any]:
    r = json.loads(result.read_text())
    if r.get("phase") != "test":
        raise SystemExit("REFUSED: not a test result")
    p1 = r["predictors"].get("reversal", {}).get("primary", {}).get("primary_mean_excess_c2")
    out = {"phase": "recost", "config_sha256": r["config_sha256"], "cost_model": cost,
           "predictors": {}}
    for pred, res in r["predictors"].items():
        out["predictors"][pred] = {
            "net": E.net_view(res["primary"], float(cost["per_side_bps"])),
            "acceptance": E.acceptance(res["primary"], folds_total=r["folds_total"],
                                       cost=cost, p1_mean=p1, is_p2=pred == "ridge24")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("validate", "test", "recost"))
    ap.add_argument("--dataset", default="asif")
    ap.add_argument("--labels", default="label-v2", choices=sorted(TARGETS))
    ap.add_argument("--top", type=int, default=500)
    ap.add_argument("--predictors", default="reversal,ridge24")
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20261012)
    ap.add_argument("--cost-model")
    ap.add_argument("--result")
    a = ap.parse_args()
    bad = set(a.predictors.split(",")) - {"reversal", "ridge24"}
    if bad:
        raise SystemExit(f"unknown predictors {sorted(bad)}")
    cost = json.loads(pathlib.Path(a.cost_model).read_text()) if a.cost_model else None
    if cost is not None and not {"name", "per_side_bps", "approved_by", "source"} <= set(cost):
        raise SystemExit("REFUSED: the cost model needs name, per_side_bps, approved_by, source")
    code = RP.code_version()
    stamp = {"at": now().astimezone(IST).isoformat(), "code_git_sha": code["git_sha"],
             "dirty": code["dirty"]}
    OUT.mkdir(parents=True, exist_ok=True)
    if a.phase == "recost":
        if not (a.result and cost):
            raise SystemExit("recost needs --result and --cost-model")
        out = {**recost(pathlib.Path(a.result), cost), **stamp}
        path = OUT / f"recost_{out['config_sha256'][:12]}_{cost['name']}.json"
    else:
        cfg = config(a)
        sha = cfg_sha(cfg)
        if code["dirty"]:
            raise SystemExit("REFUSED: the working tree is dirty; commit first")
        out = {**asyncio.run(validate(cfg, sha) if a.phase == "validate"
                             else test(cfg, sha, cost)), **stamp}
        path = OUT / f"{a.phase}_{sha[:12]}.json"
        if a.phase == "validate" and path.exists():
            prev = json.loads(path.read_text())
            if prev.get("chosen_alpha") != out["chosen_alpha"]:
                raise SystemExit("REFUSED: a rerun chose different penalties; not overwritten")
    path.write_text(json.dumps(out, indent=1, default=str))
    ledger({"phase": a.phase, "file": path.name, "config_sha256": out["config_sha256"],
            **stamp})
    print(json.dumps({"written": str(path), "phase": a.phase,
                      "config_sha256": out["config_sha256"],
                      **({"acceptance": {p: v["acceptance"] for p, v in
                                         out["predictors"].items()}}
                         if a.phase != "validate" else {"chosen_alpha": out["chosen_alpha"]})},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
