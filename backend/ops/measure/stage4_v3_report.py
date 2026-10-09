"""Stage 4 builder v3: research report, baselines and export (READ-ONLY on the database;
writes only files).

  - counts, coverage, exclusion reasons, masks, class balance, survivorship, per dataset
    and snapshot type
  - fingerprints recomputed independently from the stored rows (label-v2 rows_sha256,
    sample build_sha256, per-session feature fingerprints)
  - BASELINES ONLY (no model; no profitability claim): target ret_oc; predictors zero,
    reversal (-ret_1d), momentum (ret_5d); per walk-forward TEST block: session rank IC
    (mean, t), sign hit rate, top/bottom-decile long-short gross and net of 0/10/20/40 bps
    per leg round trip; masked (no CA_WINDOW / EXTREME / AMBIGUOUS) and unmasked
  - calibration interface: Brier score and reliability bins (demo: the TRAIN base rate of
    hit_up_1 as a probability on TEST)
  - export: var/stage4/exports/<dataset>/<snapshot>.csv.gz (+ context, splits) + manifest

  .venv/bin/python ops/measure/stage4_v3_report.py [--labels label-v2] [--no-export]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import math
import pathlib
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.core.clock import IST, now
from app.db.engine import get_sessionmaker
from app.training import labels as L
from app.training import policy as P
from app.training import samples as SM

COSTS_BPS = (0, 10, 20, 40)
MASKS = ("CA_WINDOW", "EXTREME_UNEXPLAINED", "AMBIGUOUS_ORDER_1", "AMBIGUOUS_ORDER_2")
ROOT = pathlib.Path(__file__).resolve().parents[2]


def rank_ic(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation (average ranks for ties)."""
    n = len(xs)
    if n < 10:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else None


def calibration(probs: list[float], outcomes: list[float], bins: int = 10) -> dict:
    """Brier score and reliability bins for probability predictions (interface)."""
    n = len(probs)
    if not n:
        return {"n": 0}
    brier = sum((p - y) ** 2 for p, y in zip(probs, outcomes, strict=True)) / n
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if idx:
            table.append({"bin": [lo, hi], "n": len(idx),
                          "mean_p": sum(probs[i] for i in idx) / len(idx),
                          "observed": sum(outcomes[i] for i in idx) / len(idx)})
    return {"n": n, "brier": brier, "reliability": table}


def _mean_t(v: list[float]) -> dict:
    v = [x for x in v if x is not None]
    if len(v) < 2:
        return {"n": len(v), "mean": v[0] if v else None, "t": None}
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    return {"n": len(v), "mean": m, "t": m / sd * math.sqrt(len(v)) if sd else None}


async def load(s, dataset: str, lv: str, kind: str) -> dict:
    """session -> [(key, eligible, masks, ret_oc, hit_up_1, ret_1d, ret_5d)]"""
    rows = (await s.execute(text("""
        select sm.session_date, sm.instrument_key, sm.eligible, sm.masks,
          max(l.value) filter (where l.label_id = 'ret_oc' and l.status = 'VALID'),
          max(l.value) filter (where l.label_id = 'hit_up_1' and l.status = 'VALID'),
          max(f.value) filter (where f.feature_id = 'ret_1d' and f.status = 'VALID'),
          max(f.value) filter (where f.feature_id = 'ret_5d' and f.status = 'VALID')
        from training_sample sm
        left join training_label l on l.label_version = sm.label_version
         and l.session_date = sm.session_date and l.instrument_key = sm.instrument_key
         and l.label_id in ('ret_oc', 'hit_up_1')
        left join training_feature_value f on f.dataset_version = sm.dataset_version
         and f.session_date = sm.session_date and f.snapshot = sm.snapshot
         and f.instrument_key = sm.instrument_key and f.feature_id in ('ret_1d', 'ret_5d')
        where sm.dataset_version = :v and sm.label_version = :lv and sm.snapshot = :k
        group by 1, 2, 3, 4"""), {"v": dataset, "lv": lv, "k": kind})).all()
    by = defaultdict(list)
    for r in rows:
        by[r[0]].append(r[1:])
    return by


def baselines(data: dict, folds: list[dict]) -> dict:
    out = {}
    for masked in (False, True):
        res = {}
        for name, pred in (("zero", lambda r: 0.0),
                           ("reversal_neg_ret_1d", lambda r: -r[5] if r[5] is not None else None),
                           ("momentum_ret_5d", lambda r: r[6])):
            per_fold = []
            for f in folds:
                if f["role"] != "TEST":
                    continue
                ics, hits, ls = [], [], []
                for d, rows in data.items():
                    if not (f["session_from"] <= d <= f["session_to"]):
                        continue
                    use = [r for r in rows if r[1] and r[3] is not None
                           and (not masked or not set(r[2]) & set(MASKS))]
                    xs = [(pred(r), r[3]) for r in use if pred(r) is not None]
                    if name != "zero":
                        ic = rank_ic([x for x, _ in xs], [y for _, y in xs])
                        if ic is not None:
                            ics.append(ic)
                        srt = sorted(xs)
                        k = len(srt) // 10
                        if k >= 5:
                            ls.append(sum(y for _, y in srt[-k:]) / k
                                      - sum(y for _, y in srt[:k]) / k)
                    hits += [(x > 0) == (y > 0) for x, y in xs if x != 0 and y != 0]
                    if name == "zero":
                        hits += [abs(y) for _, y in xs]       # MAE of the zero forecast
                per_fold.append({
                    "fold": f["fold"], "sessions": f["sessions"],
                    "rank_ic": _mean_t(ics) if name != "zero" else None,
                    "sign_hit_rate": (sum(hits) / len(hits) if hits else None)
                    if name != "zero" else None,
                    "mae_zero": (sum(hits) / len(hits) if hits else None)
                    if name == "zero" else None,
                    "long_short_top_bottom_decile": None if name == "zero" else {
                        f"net_{c}bps": _mean_t([g - 2 * c / 1e4 for g in ls]) for c in COSTS_BPS}})
            res[name] = per_fold
        out["masked" if masked else "unmasked"] = res
    return out


def calibration_demo(data: dict, folds: list[dict]) -> list[dict]:
    out = []
    for k in sorted({f["fold"] for f in folds}):
        tr = next(f for f in folds if f["fold"] == k and f["role"] == "TRAIN")
        te = next(f for f in folds if f["fold"] == k and f["role"] == "TEST")
        ys_tr = [r[4] for d, rows in data.items() if tr["session_from"] <= d <= tr["session_to"]
                 for r in rows if r[1] and r[4] is not None]
        if not ys_tr:
            continue
        p = sum(ys_tr) / len(ys_tr)
        ys = [r[4] for d, rows in data.items() if te["session_from"] <= d <= te["session_to"]
              for r in rows if r[1] and r[4] is not None]
        out.append({"fold": k, "train_base_rate": p, **calibration([p] * len(ys), ys)})
    return out


async def label_fingerprint(s, lv: str) -> dict:
    run = (await s.execute(text("""select run_id, rows_sha256, rows, knowledge_cutoff,
        start_date, end_date from training_label_run where label_version = :v
        order by started_at desc limit 1"""), {"v": lv})).one()
    digests, n = [], 0
    for (k,) in (await s.execute(text("""select distinct instrument_key from training_label
            where label_version = :v and session_date between :a and :b order by 1"""),
            {"v": lv, "a": run[4], "b": run[5]})).all():
        rows = [dict(r) for r in (await s.execute(text("""select session_date, instrument_key,
            label_id, value, status, reason, inputs_sha256, flags from training_label
            where label_version = :v and instrument_key = :k and session_date between :a and :b
            """), {"v": lv, "k": k, "a": run[4], "b": run[5]})).mappings().all()]
        digests.append(L._digest(rows))
        n += len(rows)
    sha = hashlib.sha256("".join(digests).encode()).hexdigest()
    return {"run_id": str(run[0]), "cutoff": run[3].isoformat(), "recorded_sha256": run[1],
            "recomputed_sha256": sha, "rows": n, "match": sha == run[1] and n == run[2]}


async def export(s, dataset: str, lv: str, kind: str, out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{kind}.csv.gz"
    feats = list(SM.CORE_INSTRUMENT)
    head = (["session_date", "snapshot", "as_of", "instrument_key", "eligible",
             "exclusion_reasons", "masks", "label_flags"]
            + [f"{f}" for f in feats] + [f"{f}__status" for f in feats]
            + list(L.LABELS) + [f"{x}__status" for x in L.LABELS])
    sessions = list((await s.execute(text("""select distinct session_date from training_sample
        where dataset_version = :v and label_version = :lv and snapshot = :k order by 1"""),
        {"v": dataset, "lv": lv, "k": kind})).scalars())
    n = 0
    with gzip.open(path, "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for d in sessions:
            fv = defaultdict(dict)
            for k, f, v, st in (await s.execute(text("""select instrument_key, feature_id, value,
                    status from training_feature_value where dataset_version = :v
                    and session_date = :d and snapshot = :k and feature_id = any(:f)"""),
                    {"v": dataset, "d": d, "k": kind, "f": feats})).all():
                fv[k][f] = (v, st)
            lb = defaultdict(dict)
            for k, lid, v, st in (await s.execute(text("""select instrument_key, label_id, value,
                    status from training_label where label_version = :lv and session_date = :d
                    """), {"lv": lv, "d": d})).all():
                lb[k][lid] = (v, st)
            for r in (await s.execute(text("""select session_date, snapshot, as_of,
                    instrument_key, eligible, exclusion_reasons, masks, label_flags
                    from training_sample where dataset_version = :v and label_version = :lv
                    and snapshot = :k and session_date = :d order by instrument_key"""),
                    {"v": dataset, "lv": lv, "k": kind, "d": d})).all():
                k = r[3]
                w.writerow([r[0], r[1], r[2].isoformat(), k, r[4], "|".join(r[5]),
                            "|".join(r[6]), "|".join(r[7])]
                           + [fv[k].get(f, (None, ""))[0] for f in feats]
                           + [fv[k].get(f, (None, "ABSENT"))[1] for f in feats]
                           + [lb[k].get(x, (None, ""))[0] for x in L.LABELS]
                           + [lb[k].get(x, (None, "ABSENT"))[1] for x in L.LABELS])
                n += 1
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    ctx = out_dir / f"{kind}_context.csv.gz"
    with gzip.open(ctx, "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["session_date", "instrument_key", "feature_id", "value", "status"])
        for row in (await s.execute(text("""select session_date, instrument_key, feature_id,
                value, status from training_feature_value where dataset_version = :v
                and snapshot = :k and feature_id = any(:f) and scope = 'CONTEXT'
                order by 1, 2, 3"""), {"v": dataset, "k": kind, "f": list(SM.CORE_CONTEXT)})).all():
            w.writerow(row)
    return {"file": str(path.relative_to(ROOT.parent)), "rows": n, "sha256": sha,
            "context_file": str(ctx.relative_to(ROOT.parent)),
            "context_sha256": hashlib.sha256(ctx.read_bytes()).hexdigest(),
            "columns": head, "missing_values": "empty cell + the *__status column (never 0)"}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=L.VERSION2)
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--out", default="../audit/evidence/stage4_dataset_v3.json")
    a = ap.parse_args()
    ev: dict = {"generated_at": now().astimezone(IST).isoformat(), "label_version": a.labels,
                "read_only_database": True, "datasets": {}}
    sm = get_sessionmaker()
    async with sm() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        ev["label_fingerprint"] = await label_fingerprint(s, a.labels)
        ev["label_run"] = dict((await s.execute(text("""select run_id::text, knowledge_cutoff,
            registry_sha256, code_git_sha, start_date, end_date, instruments, rows, rows_sha256,
            source_fingerprints, summary from training_label_run where label_version = :v
            order by started_at"""), {"v": a.labels})).mappings().all()[-1])
        for name, ds in P.DATASETS.items():
            d: dict = {"version": ds.version, "policy": ds.policy,
                       "registry_version": ds.registry_version}
            d["runs"] = [dict(r) for r in (await s.execute(text("""select run_id::text, status,
                registry_sha256, code_git_sha, sessions_done, row_count, started_at, completed_at
                from training_dataset_run where dataset_version = :v order by started_at"""),
                {"v": ds.version})).mappings().all()]
            stored = (await s.execute(text("""select count(distinct build_sha256), max(build_sha256)
                from training_sample where dataset_version = :v and label_version = :lv"""),
                {"v": ds.version, "lv": a.labels})).one()
            srows = [dict(r) for r in (await s.execute(text("""select session_date, snapshot,
                instrument_key, core_not_valid, labels_valid, label_flags, masks,
                exclusion_reasons from training_sample where dataset_version = :v
                and label_version = :lv"""), {"v": ds.version, "lv": a.labels})).mappings().all()]
            d["sample_fingerprint"] = {"builds": stored[0], "recorded": stored[1],
                                       "recomputed": SM.digest(srows),
                                       "match": SM.digest(srows) == stored[1]}
            d["feature_fingerprint"] = (await s.execute(text("""select sum(n), md5(string_agg(h, ''
                order by session_date, snapshot)) from (select session_date, snapshot, count(*) n,
                md5(string_agg(md5(concat_ws('|', instrument_key, feature_id, feature_version,
                value, status, inputs_sha256)), '' order by id)) h from training_feature_value
                where dataset_version = :v group by 1, 2) x"""), {"v": ds.version})).one()
            d["feature_fingerprint"] = list(map(str, d["feature_fingerprint"]))
            d["snapshots"] = {}
            for kind in ds.snapshots:
                k: dict = {}
                q = await s.execute(text("""select count(*), count(*) filter (where eligible),
                    count(distinct session_date), count(distinct instrument_key),
                    min(session_date), max(session_date)
                    from training_sample where dataset_version = :v and label_version = :lv
                      and snapshot = :k"""), {"v": ds.version, "lv": a.labels, "k": kind})
                c = q.one()
                k["counts"] = {"samples": c[0], "eligible": c[1], "sessions": c[2],
                               "instruments": c[3], "first": str(c[4]), "last": str(c[5])}
                k["exclusions"] = dict((await s.execute(text("""select e, count(*) from
                    training_sample, unnest(exclusion_reasons) e where dataset_version = :v
                    and label_version = :lv and snapshot = :k group by 1 order by 2 desc"""),
                    {"v": ds.version, "lv": a.labels, "k": kind})).all())
                k["masks_among_eligible"] = dict((await s.execute(text("""select m, count(*) from
                    training_sample, unnest(masks) m where dataset_version = :v
                    and label_version = :lv and snapshot = :k and eligible group by 1
                    order by 2 desc"""), {"v": ds.version, "lv": a.labels, "k": kind})).all())
                k["class_balance_eligible"] = dict((await s.execute(text("""select l.label_id,
                    round(avg(l.value)::numeric, 4) from training_sample sm join training_label l
                    on l.label_version = sm.label_version and l.session_date = sm.session_date
                    and l.instrument_key = sm.instrument_key and l.status = 'VALID'
                    and l.label_id like 'hit_%%' where sm.dataset_version = :v
                    and sm.label_version = :lv and sm.snapshot = :k and sm.eligible
                    group by 1 order by 1"""), {"v": ds.version, "lv": a.labels, "k": kind})).all())
                k["class_balance_eligible"] = {x: float(y) for x, y in
                                               k["class_balance_eligible"].items()}
                k["universe_by_session"] = [[str(x), n] for x, n in (await s.execute(text("""
                    select session_date, count(*) from training_sample where dataset_version = :v
                    and label_version = :lv and snapshot = :k group by 1 order by 1"""),
                    {"v": ds.version, "lv": a.labels, "k": kind})).all()]
                folds = [dict(r) for r in (await s.execute(text("""select fold, role,
                    session_from, session_to, sessions, embargo_sessions from training_split
                    where dataset_version = :v and label_version = :lv and snapshot = :k
                    order by fold, role"""), {"v": ds.version, "lv": a.labels, "k": kind})
                    ).mappings().all()]
                k["splits"] = [{**f, "session_from": str(f["session_from"]),
                                "session_to": str(f["session_to"])} for f in folds]
                if folds:
                    data = await load(s, ds.version, a.labels, kind)
                    k["baselines"] = baselines(data, folds)
                    k["calibration_demo_hit_up_1"] = calibration_demo(data, folds)
                else:
                    k["baselines"] = "NOT RUN: no walk-forward fold (too few sessions)"
                if not a.no_export:
                    k["export"] = await export(s, ds.version, a.labels, kind,
                                               ROOT / "var/stage4/exports" / ds.version)
                d["snapshots"][kind] = k
            ev["datasets"][name] = d
        await s.rollback()
    ev["notes"] = ["BASELINES ONLY: zero / reversal / momentum heuristics, no trained model; "
                   "no profitability is claimed. Costs are illustrative bps per leg round trip "
                   "(the Upstox/NSE fee schedule is not asserted).",
                   "AS_IF_LIVE rows carry ASSUMED knowability (research only).",
                   "Stage 3 criterion E is PENDING: full Stage 3 readiness is not claimed."]
    pathlib.Path(a.out).write_text(json.dumps(ev, indent=1, default=str))
    man = {k: {kind: v["snapshots"][kind].get("export") for kind in v["snapshots"]}
           for k, v in ev["datasets"].items()}
    (ROOT / "var/stage4/exports/manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "var/stage4/exports/manifest.json").write_text(json.dumps(
        {"generated_at": ev["generated_at"], "label_fingerprint": ev["label_fingerprint"],
         "exports": man, "samples": {k: v["sample_fingerprint"] for k, v in ev["datasets"].items()},
         "features": {k: v["feature_fingerprint"] for k, v in ev["datasets"].items()}},
        indent=1, default=str))
    print(json.dumps({"label": ev["label_fingerprint"],
                      "samples": {k: v["sample_fingerprint"] for k, v in ev["datasets"].items()}},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
