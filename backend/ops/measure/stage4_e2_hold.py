"""E2 - multi-session holding, staggered tranches (protocol: docs/STAGE4_E2_PREREGISTRATION.md
+ Amendment 2, PROPOSED; computation: app/training/e2.py). Research only: no model is
stored, nothing is written to the database (REPEATABLE READ, READ ONLY), no orders, no
profitability claim. Every result is EXPLORATORY (PC-2: 92 of the 100 TEST sessions
were E1 TEST sessions) and never an independent confirmation.

NOT RUN. It needs data that does not exist yet (separate approvals):
  labels  label-hold5-v1-asif: label ids `open_adj` (the split/bonus-adjusted official
          open of T at the recorded knowledge cutoff), `hold5_px`, `hold3_px`
  splits  training_split scheme wf-exp-120-20-20-e5 for stage4-ds-v3-asif /
          label-hold5-v1-asif / PRE_SESSION; checked against e2.make_folds
It refuses when either is missing.

Phases (every run is appended to var/stage4/experiments/e2/ledger.jsonl):
  validate  TRAIN and VALID only; freezes the configuration sha and, for ridge24, the
            penalty per fold (VALID mean rank IC on hold5_px). Reports NO metric.
  test      the single look per configuration: needs the validate file of the same
            sha, refuses when a test file of that sha exists or the tree is dirty, and
            needs --confirm-test-look E2-<sha12>.

  .venv/bin/python ops/measure/stage4_e2_hold.py config   --selection k100|k20   # prints sha, no DB
  .venv/bin/python ops/measure/stage4_e2_hold.py validate --selection k100|k20
  .venv/bin/python ops/measure/stage4_e2_hold.py test     --selection k100|k20 \
      --confirm-test-look E2-<sha12>
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
from app.training import e1 as E  # noqa: E402
from app.training import e2 as X  # noqa: E402

OUT = ROOT / "var/stage4/experiments/e2"
SPREAD_FILE = ROOT / "var/stage4/costs/open_spread_through_2026-10-14.json"
DATASET, LABELS, SCHEME = "stage4-ds-v3-asif", "label-hold5-v1-asif", "wf-exp-120-20-20-e5"
SAMPLES_LABELS = "label-v2"          # feature_eligible depends on features only
ALPHAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)
SELECTIONS = {"k100": X.K100, "k20": X.K20}
# delivery (CNC) rates: charges API 2026-10-13 + DP (C2, approved 2026-10-14)
RATES = dict(brokerage_flat_inr=20.0, brokerage_pct=None, stt_buy=0.001, stt_sell=0.001,
             stamp_buy=0.00015, exchange_txn=0.0000307, sebi=0.000001, gst=0.18,
             dp_per_scrip_sell_inr=20.0, source="Upstox GET /v2/charges/brokerage "
             "2026-10-13 + pricing page DP; NSE circular 2026-02-27",
             as_of="2026-10-13T09:36:18Z")
E1_TEST = ("2026-04-27", "2026-09-17")


def spread_file() -> tuple[dict[str, Any], str]:
    body = SPREAD_FILE.read_bytes()
    return json.loads(body), hashlib.sha256(body).hexdigest()


def config(selection: str, level: float) -> dict[str, Any]:
    sp, sp_sha = spread_file()
    sel = SELECTIONS[selection]
    return {
        "experiment": "E2", "status": "EXPLORATORY", "amendment": 2,
        "dataset": DATASET, "label_version": LABELS, "scheme": SCHEME,
        "snapshot": "PRE_SESSION", "h": X.H, "h_sensitivity": 3,
        "selection": {"name": sel.name, "universe_top": sel.universe_top,
                      "pick_frac": sel.pick_frac, "n_picks": sel.n_picks},
        "predictors": ["reversal", "ridge24"], "ridge_alphas": list(ALPHAS),
        "ridge_target": "unit rank of hold5_px (TRAIN), penalty by VALID mean rank IC",
        "primary": "mean daily (P_net - C2_gross), PC-1a",
        "reported": ["P_gross - C2_gross", "P_net - C2_net", "P_net absolute", "C0 gross",
                     "placebo gross vs its C2"],
        "capital_inr": 1_000_000, "capital_sensitivity_inr": [5_000_000, 10_000_000,
                                                                50_000_000],
        "rates": RATES, "half_spread_proxy_bps": sp["proxy_half_spread_bps"],
        "half_spread_file": SPREAD_FILE.name, "half_spread_file_sha256": sp_sha,
        "half_spread_sensitivity_bps": [5.0, sp["first_quote_sensitivity_bps"]],
        "slippage_bps": 0.0, "slippage_sensitivity_bps": [5.0, 10.0, 20.0],
        "stress": 1.5, "bootstrap": 10_000, "block": 2 * X.H, "block_sensitivity": 20,
        "ci_level": level, "perm_draws": 200, "seed": 20261014}


def cfg_sha(cfg: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


# ── the one-look discipline (pure; tested) ─────────────────────────────────────────────
def check_look(out: pathlib.Path, phase: str, sha: str, *, dirty: bool,
               confirm: str | None = None) -> None:
    if dirty:
        raise SystemExit("REFUSED: the working tree is dirty; commit first")
    vpath, tpath = out / f"validate_{sha[:12]}.json", out / f"test_{sha[:12]}.json"
    if tpath.exists():
        raise SystemExit(f"REFUSED: {tpath.name} exists - the single test look was taken")
    if phase == "test":
        if not vpath.exists():
            raise SystemExit("REFUSED: run the validate phase of this configuration first")
        if json.loads(vpath.read_text()).get("config_sha256") != sha:
            raise SystemExit("REFUSED: the validate file belongs to another configuration")
        if confirm != f"E2-{sha[:12]}":
            raise SystemExit(f"REFUSED: the test look needs --confirm-test-look E2-{sha[:12]}")


def ledger(out: pathlib.Path, entry: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "ledger.jsonl").open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ── database (read only) ───────────────────────────────────────────────────────────────
async def sessions_and_folds(s) -> tuple[list[_dt.date], dict[int, dict[str, range]]]:
    days = list((await s.execute(text("""select session_date from training_session_done
        where dataset_version = :v and snapshot = 'PRE_SESSION' order by 1"""),
        {"v": DATASET})).scalars())
    idx = {d: i for i, d in enumerate(days)}
    rows = (await s.execute(text("""select fold, role, session_from, session_to,
            embargo_sessions from training_split where dataset_version = :v
              and label_version = :lv and snapshot = 'PRE_SESSION' and scheme = :sc
            order by fold, role"""), {"v": DATASET, "lv": LABELS, "sc": SCHEME})).all()
    if not rows:
        raise SystemExit(f"REFUSED: no {SCHEME} splits for {DATASET} / {LABELS} (not built)")
    stored: dict[int, dict[str, range]] = {}
    for f, role, a, b, emb in rows:
        if emb < X.H:
            raise SystemExit(f"REFUSED: fold {f} embargo {emb} < H")
        stored.setdefault(f, {})[role.lower()] = range(idx[a], idx[b] + 1)
    expect = dict(enumerate(X.make_folds(len(days))))
    if stored != expect:
        raise SystemExit("REFUSED: stored splits differ from e2.make_folds")
    return days, stored


async def load_session(s, day: _dt.date, top: int) -> dict[str, Any] | None:
    cols = ", ".join(f"max(value) filter (where feature_id = '{f}') as f{i}"
                     for i, f in enumerate(E.CORE24))
    turn = E.CORE24.index("turnover_20")
    rows = (await s.execute(text(f"""
        with smp as (select instrument_key from training_sample where dataset_version = :v
              and label_version = :slv and snapshot = 'PRE_SESSION' and session_date = :d
              and feature_eligible),
        f as (select instrument_key, {cols} from training_feature_value
              where dataset_version = :v and snapshot = 'PRE_SESSION' and session_date = :d
                and status = 'VALID' and feature_id = any(:ids) group by 1)
        select * from (select *, row_number() over (order by f{turn} desc, instrument_key) rk
                       from smp join f using (instrument_key)) j
        where rk <= :top order by rk"""),  # noqa: S608 - identifiers are constants
        {"v": DATASET, "slv": SAMPLES_LABELS, "d": day, "ids": list(E.CORE24),
         "top": top})).mappings().all()
    rows = [r for r in rows if all(r[f"f{i}"] is not None for i in range(len(E.CORE24)))]
    if not rows:
        return None
    Xm = np.array([[float(r[f"f{i}"]) for i in range(len(E.CORE24))] for r in rows])
    return {"date": day, "keys": [r["instrument_key"] for r in rows], "X": Xm,
            "turnover": Xm[:, turn], "atr": Xm[:, E.CORE24.index("atr_pct_14")]}


async def labels(s, label_id: str, days: list[_dt.date]) -> dict[tuple[str, int], float]:
    idx = {d: i for i, d in enumerate(days)}
    rows = (await s.execute(text("""select instrument_key, session_date, value
        from training_label where label_version = :lv and label_id = :l
          and status = 'VALID' and session_date between :a and :b"""),
        {"lv": LABELS, "l": label_id, "a": days[0], "b": days[-1]})).all()
    if not rows:
        raise SystemExit(f"REFUSED: no {LABELS} / {label_id} labels (not built)")
    return {(k, idx[d]): float(v) for k, d, v in rows if d in idx}


def opens_matrix(lab: dict[tuple[str, int], float], n: int) -> dict[str, list[float | None]]:
    out: dict[str, list[float | None]] = {}
    for (k, i), v in lab.items():
        out.setdefault(k, [None] * n)[i] = v
    return out


def ridge_score_fn(w: np.ndarray):
    return lambda sess, u: E.ridge_score(sess, u, w)


def fit(sessions: dict[int, dict], y: dict[tuple[str, int], float], days: range,
        top: int, alpha: float) -> np.ndarray:
    rows = []
    for d in days:
        sess = sessions.get(d)
        if not sess:
            continue
        u = E.universe(sess, top)
        ok = [i for i in u.tolist() if (sess["keys"][i], d) in y]
        if len(ok) >= 3:
            ok = np.array(ok)
            rows.append((E.ranked_X(sess, ok),
                         E.unit_rank(np.array([y[(sess["keys"][i], d)] for i in ok]))))
    return E.ridge_fit(rows, alpha)


def valid_ic(sessions, y, days: range, top: int, w: np.ndarray) -> float:
    ics = []
    for d in days:
        sess = sessions.get(d)
        if not sess:
            continue
        u = E.universe(sess, top)
        ok = np.array([i for i in u.tolist() if (sess["keys"][i], d) in y])
        if len(ok) >= 3:
            ic = E.spearman(E.ridge_score(sess, u, w)[ok],
                            np.array([y[(sess["keys"][i], d)] for i in ok]))
            if ic is not None:
                ics.append(ic)
    return float(np.mean(ics)) if ics else -np.inf


async def load_all(s, cfg) -> tuple[list[_dt.date], dict, dict, dict, dict]:
    days, folds = await sessions_and_folds(s)
    top = cfg["selection"]["universe_top"]
    sessions = {}
    for i, d in enumerate(days):
        if (sess := await load_session(s, d, top)) is not None:
            sessions[i] = sess
    y = await labels(s, "hold5_px", days)
    opens = opens_matrix(await labels(s, "open_adj", days), len(days))
    return days, folds, sessions, y, opens


# ── phases ─────────────────────────────────────────────────────────────────────────────
async def validate(cfg, sha) -> dict[str, Any]:
    from app.db.engine import get_sessionmaker
    out = {"phase": "validate", "config_sha256": sha, "config": cfg, "chosen_alpha": {},
           "metrics": "none by design (each VALID block overlaps the previous TEST)"}
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        days, folds, sessions, y, _ = await load_all(s, cfg)
        await s.rollback()
    top = cfg["selection"]["universe_top"]
    out["folds"] = {str(f): {r: [str(days[v[r][0]]), str(days[v[r][-1]]), len(v[r])]
                             for r in v} for f, v in folds.items()}
    for f, v in folds.items():
        best = None
        for alpha in cfg["ridge_alphas"]:
            m = valid_ic(sessions, y, v["valid"], top, fit(sessions, y, v["train"], top, alpha))
            if best is None or m >= best[0]:
                best = (m, alpha)
        out["chosen_alpha"][str(f)] = best[1]
    return out


def cost_model(cfg, measured, *, capital=None, spread=None, slippage=None) -> X.CostModel:
    return X.CostModel(X.Rates(**cfg["rates"]), capital_inr=capital or cfg["capital_inr"],
                       half_spread_bps=spread if spread is not None
                       else cfg["half_spread_proxy_bps"],
                       slippage_bps=cfg["slippage_bps"] if slippage is None else slippage,
                       half_spread_measured=measured if spread is None else None)


def strip(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k not in ("series",)} | {
        "series_primary": r["series"]["primary_net_vs_c2_gross"]}


async def test(cfg, sha) -> dict[str, Any]:
    from app.db.engine import get_sessionmaker
    frozen = json.loads((OUT / f"validate_{sha[:12]}.json").read_text())
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        days, folds, sessions, y, opens = await load_all(s, cfg)
        await s.rollback()
    top, sel = cfg["selection"]["universe_top"], X.Selection(**cfg["selection"])
    sp, _ = spread_file()
    idx = {str(d): i for i, d in enumerate(days)}
    measured = {(idx[d], k): v for d, m in sp["measured_half_spread_bps"].items() if d in idx
                for k, v in m.items()}
    e1a, e1b = (idx.get(x) for x in E1_TEST)
    tests = sorted(i for v in folds.values() for i in v["test"])
    out: dict[str, Any] = {
        "phase": "test", "config_sha256": sha, "config": cfg, "status": "EXPLORATORY",
        "independent_confirmation": False, "chosen_alpha": frozen["chosen_alpha"],
        "test_sessions": [str(days[tests[0]]), str(days[tests[-1]]), len(tests)],
        "e1_test_overlap": sum(1 for i in tests if e1a is not None and e1a <= i <= e1b),
        "predictors": {}}
    fns = {"reversal": {f: (lambda z, u: E.reversal(z)) for f in folds},
           "ridge24": {f: ridge_score_fn(fit(sessions, y, v["train"], top,
                                             frozen["chosen_alpha"][str(f)]))
                       for f, v in folds.items()}}
    ev = dict(b=cfg["bootstrap"], level=cfg["ci_level"], seed=cfg["seed"],
              stress=cfg["stress"])
    for pred in cfg["predictors"]:
        def blocks(h, pred=pred):
            return [(f, X.form_block(sessions, v["test"], fns[pred][f], sel, seed=cfg["seed"],
                                     h=h, perm_draws=cfg["perm_draws"] if h == X.H else 0))
                    for f, v in sorted(folds.items())]
        b5 = blocks(X.H)
        p1 = (out["predictors"].get("reversal", {}).get("primary", {})
              .get("results", {}).get("primary_net_vs_c2_gross", {}).get("mean"))
        prim = X.evaluate(b5, opens, cost_model(cfg, measured), block=cfg["block"],
                          other_primary_mean=p1 if pred == "ridge24" else None, **ev)
        res = {"primary": strip(prim), "sensitivities": {}}
        b5 = [(f, {**blk, "perm": []}) for f, blk in b5]      # C1 only in the primary
        sens = res["sensitivities"]
        for c in cfg["capital_sensitivity_inr"]:
            sens[f"capital_{c}"] = X.evaluate(b5, opens, cost_model(cfg, measured, capital=c),
                                              **ev)["results"]["primary_net_vs_c2_gross"]
        for sl in cfg["slippage_sensitivity_bps"]:
            sens[f"slippage_{sl}"] = X.evaluate(
                b5, opens, cost_model(cfg, measured, slippage=sl),
                **ev)["results"]["primary_net_vs_c2_gross"]
        for spb in cfg["half_spread_sensitivity_bps"]:
            sens[f"half_spread_{spb}"] = X.evaluate(
                b5, opens, cost_model(cfg, measured, spread=spb),
                **ev)["results"]["primary_net_vs_c2_gross"]
        sens["block_20"] = X.evaluate(b5, opens, cost_model(cfg, measured),
                                      block=cfg["block_sensitivity"],
                                      **ev)["results"]["primary_net_vs_c2_gross"]
        sens["h_3"] = X.evaluate(blocks(cfg["h_sensitivity"]), opens, cost_model(cfg, measured),
                                 h=cfg["h_sensitivity"], **ev)["results"]["primary_net_vs_c2_gross"]
        out["predictors"][pred] = res
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("config", "validate", "test"))
    ap.add_argument("--selection", required=True, choices=sorted(SELECTIONS))
    ap.add_argument("--ci-level", type=float, default=0.975)
    ap.add_argument("--confirm-test-look")
    a = ap.parse_args()
    cfg = config(a.selection, a.ci_level)
    sha = cfg_sha(cfg)
    if a.phase == "config":
        print(json.dumps({"config_sha256": sha, "config": cfg}, indent=1))
        return 0
    from app.training import replay as RP
    code = RP.code_version()
    check_look(OUT, a.phase, sha, dirty=code["dirty"], confirm=a.confirm_test_look)
    stamp = {"at": now().astimezone(IST).isoformat(), "code_git_sha": code["git_sha"],
             "dirty": code["dirty"]}
    out = {**asyncio.run(validate(cfg, sha) if a.phase == "validate" else test(cfg, sha)),
           **stamp, "versions": {"numpy": np.__version__, "python": sys.version.split()[0]}}
    path = OUT / f"{a.phase}_{sha[:12]}.json"
    if a.phase == "validate" and path.exists():
        if json.loads(path.read_text()).get("chosen_alpha") != out["chosen_alpha"]:
            raise SystemExit("REFUSED: a rerun chose different penalties; not overwritten")
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, default=str))
    ledger(OUT, {"phase": a.phase, "file": path.name, "config_sha256": sha, **stamp})
    print(json.dumps({"written": str(path), "phase": a.phase, "config_sha256": sha}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
