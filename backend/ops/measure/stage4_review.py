"""Stage 4 post-backfill review (READ-ONLY): KN-CA exposure, v1 -> v2 effect, the
0017 shadow views, dataset coverage for modelling, label availability, integrity.

Writes ../audit/evidence/stage4_post_backfill_review.json; persists nothing in the
database (one READ ONLY transaction per section).

  .venv/bin/python ops/measure/stage4_review.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import subprocess
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.core.clock import IST, now
from app.db.engine import get_sessionmaker
from app.features import registry as R
from app.training import availability as A

V1S, V1A = "stage4-ds-v1-strict", "stage4-ds-v1-asif"
V2S, V2A = "stage4-ds-v2-strict", "stage4-ds-v2-asif"
FAM = {f.id: "+".join(sorted({A.FAMILY.get(i, i) for i in f.inputs})) for f in R.FEATURES}


async def rows(s, sql, **kw):
    return [list(r) for r in (await s.execute(text(sql), kw)).all()]


async def one(s, sql, **kw):
    return list((await s.execute(text(sql), kw)).one())


# ── 1. KN-CA ───────────────────────────────────────────────────────────────────
async def kn_ca(s) -> dict:
    out: dict = {}
    out["stored_actions"] = await one(s, """select count(*),
        count(*) filter (where knowable_at < fetched_at),
        count(*) filter (where knowable_at < fetched_at - interval '1 day'),
        count(*) filter (where knowable_at = fetched_at),
        min(fetched_at - knowable_at), percentile_disc(0.5) within group
          (order by fetched_at - knowable_at), max(fetched_at - knowable_at)
        from corporate_action""")
    out["stored_actions_cols"] = ["actions", "knowable_before_fetch", "more_than_1d_before",
                                  "knowable_eq_fetch", "min_lag", "median_lag", "max_lag"]
    out["fetch_vs_ex_date"] = await rows(s, """select (fetched_at at time zone 'Asia/Kolkata')::date,
        count(*), min(ex_date), max(ex_date), min(announcement_date), max(announcement_date)
        from corporate_action group by 1 order by 1""")
    out["factor_vs_action"] = await one(s, """select count(*),
        count(*) filter (where f.knowable_at = c.knowable_at),
        count(*) filter (where f.ex_date is distinct from c.ex_date),
        count(*) filter (where f.derived_at > c.fetched_at), count(*) filter (where f.status='EXACT')
        from ca_factor f join corporate_action c on c.id = f.ca_id""")
    out["factor_vs_action_cols"] = ["factors", "knowable_equal_action", "ex_date_differs",
                                    "derived_after_fetch", "exact"]
    # A: production runs - actions stored after the snapshot instant but before the run
    # started (visible to the run's REPEATABLE READ snapshot, knowable_at < as_of by KN-CA)
    runs = await rows(s, """select run_id, request_params->>'session', request_params->>'snapshot',
        cast(request_params->>'as_of' as timestamptz), started_at, status
        from ingest_run where source = 'PRAJNA_STAGE3' order by started_at""")
    rr = []
    for rid, sess, kind, as_of, started, st in runs:
        exp = await rows(s, """select c.id, c.instrument_key, c.action_type, c.ex_date,
              c.knowable_at, c.fetched_at,
              exists (select 1 from ca_factor f where f.ca_id = c.id and f.status = 'EXACT')
            from corporate_action c where c.knowable_at < :a and c.fetched_at >= :a
              and c.fetched_at < :t order by c.id""", a=as_of, t=started)
        rr.append({"run_id": str(rid), "session": sess, "snapshot": kind, "status": st,
                   "as_of": as_of.isoformat(), "started_at": started.isoformat(),
                   "run_minus_as_of_min": round((started - as_of).total_seconds() / 60, 1),
                   "actions_fetched_between_as_of_and_run": len(exp),
                   "examples": [list(map(str, x)) for x in exp[:8]]})
    out["production_runs"] = rr
    # does feature_value carry such an action? (per committed snapshot)
    fv = []
    for d, kind, as_of, started in await rows(s, """select f.session_date, f.snapshot, f.as_of,
            min(r.started_at) from feature_value f join ingest_run r on r.run_id = f.run_id
            group by 1, 2, 3 order by 1, 2"""):
        n = await one(s, """select count(distinct c.instrument_key), count(*) from corporate_action c
            where c.knowable_at < :a and c.fetched_at >= :a and c.fetched_at < :t""",
                      a=as_of, t=started)
        fv.append({"session": str(d), "snapshot": kind, "rows_written_by_run_started":
                   started.isoformat(), "late_fetched_actions": n[1], "instruments": n[0]})
    out["feature_value_snapshots"] = fv
    # scheduled exposure: when are actions stored (IST time of day) on trading days?
    out["fetch_time_of_day"] = await rows(s, """select to_char(fetched_at at time zone
        'Asia/Kolkata', 'HH24:MI'), count(*) from corporate_action group by 1 order by 1""")
    out["factor_derived_time_of_day"] = await rows(s, """select to_char(derived_at at time zone
        'Asia/Kolkata', 'HH24'), count(*) from ca_factor group by 1 order by 1""")
    return out


async def v1_v2(s) -> dict:
    out = {}
    for a, b, name in ((V1S, V2S, "strict"), (V1A, V2A, "asif")):
        common = [r[0] for r in await rows(s, """select x.session_date from training_session_done x
            join training_session_done y using (session_date, snapshot)
            where x.dataset_version = :a and y.dataset_version = :b group by 1 order by 1""",
                                           a=a, b=b)]
        by = await rows(s, """select v1.feature_id, count(*),
              count(*) filter (where v1.value is distinct from v2.value
                               or v1.status <> v2.status),
              count(*) filter (where v1.inputs_sha256 <> v2.inputs_sha256),
              count(distinct v1.instrument_key) filter (where v1.value is distinct from v2.value
                               or v1.status <> v2.status),
              count(distinct v1.session_date) filter (where v1.value is distinct from v2.value
                               or v1.status <> v2.status)
            from training_feature_value v1 join training_feature_value v2
              using (session_date, snapshot, instrument_key, feature_id)
            where v1.dataset_version = :a and v2.dataset_version = :b
              and v1.session_date = any(:d)
            group by 1 having count(*) filter (where v1.value is distinct from v2.value
                               or v1.status <> v2.status) > 0 or count(*) filter (
                               where v1.inputs_sha256 <> v2.inputs_sha256) > 0
            order by 3 desc""", a=a, b=b, d=common)
        trans = await rows(s, """select v1.status, v2.status, count(*)
            from training_feature_value v1 join training_feature_value v2
              using (session_date, snapshot, instrument_key, feature_id)
            where v1.dataset_version = :a and v2.dataset_version = :b
              and v1.session_date = any(:d)
              and (v1.value is distinct from v2.value or v1.status <> v2.status)
            group by 1, 2 order by 3 desc""", a=a, b=b, d=common)
        ex = await rows(s, """select v1.session_date, v1.snapshot, v1.instrument_key, v1.feature_id,
              v1.value, v1.status, v2.value, v2.status
            from training_feature_value v1 join training_feature_value v2
              using (session_date, snapshot, instrument_key, feature_id)
            where v1.dataset_version = :a and v2.dataset_version = :b
              and v1.session_date = any(:d) and v1.feature_id not like 'ca_days%%'
              and (v1.value is distinct from v2.value or v1.status <> v2.status)
            order by md5(v1.instrument_key || v1.feature_id) limit 12""", a=a, b=b, d=common)
        out[name] = {"common_sessions": [str(x) for x in common], "by_feature": by,
                     "by_feature_cols": ["feature_id", "joined", "value_or_status_diff",
                                         "inputs_sha_diff", "instruments", "sessions"],
                     "status_transitions_v1_to_v2": trans,
                     "non_ca_examples": [list(map(str, x)) for x in ex]}
    return out


async def views_0017(s) -> dict:
    out = {}
    out["strict_ca"] = await one(s, """select count(*), count(*) filter (where t.knowable_at =
        greatest(p.knowable_at, p.fetched_at)) from train_strict.canon_corporate_action t
        join public.canon_corporate_action p using (id)""")
    out["strict_factor"] = await one(s, """select count(*), count(*) filter (where t.knowable_at =
        greatest(f.knowable_at, c.fetched_at)) from train_strict.ca_factor t join public.ca_factor f
        using (id) join public.corporate_action c on c.id = f.ca_id""")
    lag = await one(s, """select seconds from training_policy_param where policy = 'AS_IF_LIVE-v2'
        and family = 'corporate_action' and key = 'after_ex'""")
    out["asif_after_ex_seconds"] = lag[0]
    out["asif_ca"] = await one(s, """select count(*), count(*) filter (where t.knowable_at =
        case when p.ex_date is null then greatest(p.knowable_at, p.fetched_at)
             else least(greatest(p.knowable_at, p.fetched_at), greatest(p.knowable_at,
               (p.ex_date::timestamp at time zone 'Asia/Kolkata') + make_interval(secs => :l)))
        end), count(*) filter (where t.knowable_at < p.knowable_at),
        count(*) filter (where t.knowable_at > p.fetched_at)
        from train_asif2.canon_corporate_action t join public.canon_corporate_action p using (id)""",
                               l=lag[0])
    out["asif_ca_cols"] = ["rows", "formula_matches", "earlier_than_kn_ca", "later_than_fetch"]
    out["asif_factor_vs_action"] = await one(s, """select count(*), count(*) filter (where
        tf.knowable_at = ta.knowable_at) from train_asif2.ca_factor tf
        join train_asif2.canon_corporate_action ta on ta.id = tf.ca_id""")
    out["policy_params_per_dataset"] = await rows(s, """select dataset_version, knowability_policy,
        count(*), count(distinct policy_params::text), count(distinct registry_sha256),
        string_agg(distinct status, ',') from training_dataset_run group by 1, 2 order by 1""")
    out["param_rows"] = await rows(s, """select policy, count(*), min(measured_at), max(measured_at)
        from training_policy_param group by 1 order by 1""")
    # the unshadowed reads on the replay path (pit.bars_adjusted horizon)
    out["horizon_min_ex_date"] = str((await one(s, "select min(ex_date) from corporate_action"))[0])
    out["horizon_first_fetched"] = str((await one(s, """select min(fetched_at) from corporate_action
        where ex_date = (select min(ex_date) from corporate_action)"""))[0])
    return out


# ── 2. readiness ───────────────────────────────────────────────────────────────
async def readiness(s) -> dict:
    out: dict = {}
    for v in (V2S, V2A):
        feats = await rows(s, """select feature_id, snapshot, status, count(*) from
            training_feature_value where dataset_version = :v group by 1, 2, 3""", v=v)
        per: dict = defaultdict(lambda: defaultdict(int))
        for f, k, st, n in feats:
            per[f"{f}|{k}"][st] += n
        # per session x family: share VALID among applicable rows (PRE_SESSION)
        sess = await rows(s, """select session_date, feature_id,
              count(*) filter (where status <> 'NOT_APPLICABLE'),
              count(*) filter (where status = 'VALID')
            from training_feature_value where dataset_version = :v and snapshot = 'PRE_SESSION'
            group by 1, 2""", v=v)
        fam_day: dict = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        feat_day: dict = defaultdict(dict)
        for d, f, n, ok in sess:
            fam_day[FAM[f]][str(d)][0] += n
            fam_day[FAM[f]][str(d)][1] += ok
            feat_day[f][str(d)] = (ok / n) if n else None
        first80 = {}
        for f, days in feat_day.items():
            ds = sorted(days)
            first80[f] = next((d for i, d in enumerate(ds) if all(
                (days[x] or 0) >= 0.8 for x in ds[i:])), None)
        months = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for fam, days in fam_day.items():
            for d, (n, ok) in days.items():
                months[fam][d[:7]][0] += n
                months[fam][d[:7]][1] += ok
        # per symbol: share of VALID among bar-based instrument rows (price_technical)
        sym = await rows(s, """select instrument_key,
              count(*) filter (where status = 'VALID')::float / nullif(count(*), 0),
              count(distinct session_date)
            from training_feature_value where dataset_version = :v and snapshot = 'PRE_SESSION'
              and feature_id in ('ret_1d', 'ret_5d', 'ret_20d', 'sma_20', 'rsi_14', 'atr_pct_14',
                                 'volatility_20', 'avg_volume_20')
              and instrument_key like 'NSE_EQ|%%' group by 1""", v=v)
        shares = sorted(x[1] or 0 for x in sym)
        q = lambda p: round(shares[min(len(shares) - 1, int(p * len(shares)))], 4)  # noqa: E731
        universe = await rows(s, """select session_date, instruments from training_session_done
            where dataset_version = :v and snapshot = 'PRE_SESSION' order by 1""", v=v)
        out[v] = {"feature_status": {k: dict(x) for k, x in sorted(per.items())},
                  "first_session_valid_ge_80pct_thereafter": first80,
                  "family_valid_share_by_month": {f: {m: round(ok / n, 4) if n else None
                                                      for m, (n, ok) in sorted(ms.items())}
                                                  for f, ms in sorted(months.items())},
                  "symbol_valid_share_core8": {"symbols": len(shares), "p10": q(0.1),
                                               "p25": q(0.25), "p50": q(0.5), "p75": q(0.75),
                                               "p90": q(0.9),
                                               "below_50pct": sum(1 for x in shares if x < 0.5),
                                               "zero": sum(1 for x in shares if x == 0)},
                  "universe_by_session": [[str(d), n] for d, n in universe]}
    # PRE_SESSION vs PRE_OPEN (STRICT): same features, different value?
    out["strict_pre_session_vs_pre_open"] = await rows(s, """select a.feature_id, count(*),
          count(*) filter (where a.value is distinct from b.value or a.status <> b.status),
          count(*) filter (where a.inputs_sha256 <> b.inputs_sha256)
        from training_feature_value a join training_feature_value b
          on b.dataset_version = a.dataset_version and b.session_date = a.session_date
         and b.instrument_key = a.instrument_key and b.feature_id = a.feature_id
         and b.snapshot = 'PRE_OPEN'
        where a.dataset_version = :v and a.snapshot = 'PRE_SESSION'
        group by 1 having count(*) filter (where a.value is distinct from b.value
          or a.status <> b.status) > 0 order by 3 desc""", v=V2S)
    out["strict_pre_open_only"] = await rows(s, """select feature_id, count(*) from
        training_feature_value where dataset_version = :v and snapshot = 'PRE_OPEN'
          and feature_id like 'preopen_%%' group by 1 order by 1""", v=V2S)
    out["malformed"] = await rows(s, """select dataset_version, feature_id, count(*),
        round(100.0 * count(*) / sum(count(*)) over (partition by dataset_version), 3)
        from training_feature_value where status = 'INVALID' and dataset_version in (:a, :b)
        group by 1, 2 order by 1, 3 desc""", a=V2S, b=V2A)
    out["value_outliers_core"] = await rows(s, """select feature_id, min(value), max(value),
        percentile_cont(0.001) within group (order by value),
        percentile_cont(0.999) within group (order by value)
        from training_feature_value where dataset_version = :v and status = 'VALID'
          and feature_id in ('ret_1d', 'ret_20d', 'atr_pct_14', 'volatility_20', 'volume_spike_20',
                             'rsi_14', 'close_to_sma_20', 'beta_60')
        group by 1 order by 1""", v=V2A)
    return out


async def labels(s) -> dict:
    out = {}
    out["by_label"] = await rows(s, """select label_id, count(*), count(*) filter (where
        status = 'VALID'), round(avg(value)::numeric, 6), round(stddev(value)::numeric, 6),
        min(session_date), max(session_date)
        from training_label group by 1 order by 1""")
    out["join_with_features"] = await rows(s, """select d.dataset_version, count(distinct
        (d.session_date)), count(*) filter (where l.status = 'VALID')
        from training_session_done d join training_label l on l.session_date = d.session_date
          and l.label_id = 'ret_oc'
        where d.dataset_version in (:a, :b) and d.snapshot = 'PRE_SESSION' group by 1""",
                                       a=V2S, b=V2A)
    out["sessions_without_labels"] = await rows(s, """select d.dataset_version, d.session_date
        from training_session_done d where d.dataset_version in (:a, :b) and d.snapshot =
          'PRE_SESSION' and not exists (select 1 from training_label l
          where l.session_date = d.session_date) order by 1, 2""", a=V2S, b=V2A)
    out["both_hits_same_day"] = await one(s, """select count(*) filter (where u.value = 1
        and dn.value = 1), count(*) filter (where u.value = 1), count(*) filter (where dn.value = 1),
        count(*) from training_label u join training_label dn using (label_version, session_date,
        instrument_key) where u.label_id = 'hit_up_2' and dn.label_id = 'hit_dn_2'
        and u.status = 'VALID'""")
    out["extreme_ret_cc"] = await rows(s, """select session_date, instrument_key, value from
        training_label where label_id = 'ret_cc' and status = 'VALID' and abs(value) > 0.35
        order by abs(value) desc limit 15""")
    out["extreme_ret_cc_count"] = (await one(s, """select count(*) from training_label where
        label_id = 'ret_cc' and status = 'VALID' and abs(value) > 0.25"""))[0]
    out["intraday_1m_bars_from"] = str((await one(s, """select min(market_date) from
        canon_market_bar where timeframe = '1m'"""))[0])
    return out


# ── 4. integrity ───────────────────────────────────────────────────────────────
async def integrity(s) -> dict:
    out = {}
    out["alembic"] = (await one(s, "select version_num from alembic_version"))[0]
    out["runs"] = await rows(s, """select dataset_version, knowability_policy, status, count(*),
        sum(sessions_done), sum(row_count), string_agg(distinct registry_sha256, ',')
        from training_dataset_run group by 1, 2, 3 order by 1, 3""")
    out["done_markers"] = await rows(s, """select dataset_version, count(*), sum(rows)
        from training_session_done group by 1 order by 1""")
    out["rows_by_version"] = await rows(s, """select dataset_version, count(*) from
        training_feature_value group by 1 order by 1""")
    fp = await one(s, """select count(*), md5(string_agg(md5(concat_ws('|', instrument_key,
        session_date, snapshot, feature_id, value, reason, inputs_sha256)), '' order by id))
        from feature_value""")
    out["feature_value"] = {"count": fp[0], "md5": fp[1],
                            "baseline": [801434, "b45381f3c89664cdf3dbbfa95d70b1a5"],
                            "equal_baseline": fp == [801434, "b45381f3c89664cdf3dbbfa95d70b1a5"]}
    out["stage3_events_since_2026_10_09"] = await rows(s, """select id, at, event, mode,
        left(detail::text, 160) from stage3_event where id > 34 order by id""")
    out["registry"] = {"version": R.VERSION, "sha256": R.REGISTRY_SHA256,
                       "features": len(R.FEATURES)}
    return out


def files() -> dict:
    root = pathlib.Path(__file__).resolve().parents[3]
    cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout  # noqa: S607
    env = {}
    for line in (root / "backend/.env").read_text().splitlines():
        if line.startswith("PRAJNA_STAGE3_"):
            k, _, v = line.partition("=")
            env[k] = v
    rep = (root / "docs/STAGE4_TRAINING_DATASET_REPORT.md").read_text().splitlines()
    v1_refs = [[i + 1, x.strip()[:200]] for i, x in enumerate(rep)
               if "v1" in x.replace("label-v1", "").replace("features-v1", "")]
    return {"crontab_sha256": hashlib.sha256(cron.encode()).hexdigest(),
            "crontab_stage3_lines": [x for x in cron.splitlines() if "stage3" in x
                                     and not x.startswith("#")],
            "env_stage3_flags": env,
            "report_lines_mentioning_v1": v1_refs}


async def main() -> int:
    sm = get_sessionmaker()
    ev: dict = {"generated_at": now().astimezone(IST).isoformat(), "read_only": True}
    for name, fn in (("kn_ca", kn_ca), ("v1_vs_v2", v1_v2), ("views_0017", views_0017),
                     ("readiness", readiness), ("labels", labels), ("integrity", integrity)):
        async with sm() as s:
            await s.execute(text("set transaction isolation level repeatable read, read only"))
            ev[name] = await fn(s)
            await s.rollback()
        print(name, "done", flush=True)
    ev["files"] = files()
    out = pathlib.Path(__file__).resolve().parents[3] / "audit/evidence/stage4_post_backfill_review.json"
    out.write_text(json.dumps(ev, indent=1, default=str))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
