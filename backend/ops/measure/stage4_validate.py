"""Stage 4 training dataset: independent validation and the dataset report (READ-ONLY).

Checks, per dataset (STRICT_PIT, AS_IF_LIVE-v1) and for label-v1:
  completeness       every calendar snapshot of the window has a done marker
  duplicates         feature rows / snapshots / labels
  orphans            instrument keys that are not instruments (MARKET excepted)
  invalid values     NaN / inf, value-status inconsistency (also DB CHECKs)
  PIT                input_max_knowable_at >= as_of; as_of = the calendar instant
  non-trading dates, future timestamps, registry hash mismatch
  label leakage      label_start_at <= any snapshot as_of of its session
  replay             STRICT vs production feature_value (same sessions); a fresh
                     read-only recompute of random sessions x random instruments
                     (AS_IF_LIVE through its shadow views); raw-SQL recomputation
                     of ret_1d / sma_20 / avg_volume_20 and the ret_cc label for
                     instruments without corporate-action factors
  scenarios          late bars, delayed fundamentals / FII-DII, missing news,
                     corporate actions knowable later, lifecycle
  survivorship       universe size per session, removed / new / vanished symbols
  coverage table     per feature: family, earliest / latest VALID, coverage,
                     missingness by status, PIT status
Production is read only: feature_value is fingerprinted (count + md5) and
compared with the Phase-0 baseline.

  .venv/bin/python ops/measure/stage4_validate.py [--baseline-md5 ...] [--seed 7]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import random
import sys
from collections import defaultdict

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.core.clock import IST, now
from app.db.engine import get_sessionmaker
from app.features import engine as E
from app.features import registry as R
from app.features import snapshots as SN
from app.training import availability as A
from app.training import labels as L
from app.training import policy as P

FP_SQL = """select count(*), md5(string_agg(md5(concat_ws('|', instrument_key, session_date,
    snapshot, feature_id, value, reason, inputs_sha256)), '' order by id)) from feature_value"""


async def one(s, sql, **kw):
    return (await s.execute(text(sql), kw)).one()


async def val(s, sql, **kw):
    return (await s.execute(text(sql), kw)).scalar()


async def dataset_checks(s, ds) -> dict:
    v = ds.version
    c: dict = {}
    w = await one(s, """select min(session_date), max(session_date), count(*), sum(rows),
        sum(instruments) from training_session_done where dataset_version = :v""", v=v)
    c["window"] = {"first": str(w[0]), "last": str(w[1]), "snapshots_done": w[2],
                   "rows_by_markers": int(w[3] or 0)}
    expected = []
    for d in await SN.sessions_between(s, w[0], w[1]):
        for k in ds.snapshots:
            try:
                expected.append((d, k, (await SN.resolve(s, d, k)).as_of))
            except SN.NoSnapshot:
                pass
    done = {(r[0], r[1]): r[2] for r in (await s.execute(text("""select session_date, snapshot,
        as_of from training_session_done where dataset_version = :v"""), {"v": v})).all()}
    c["completeness"] = {"expected": len(expected), "done": len(done),
                         "missing": [f"{d} {k}" for d, k, _ in expected if (d, k) not in done],
                         "as_of_not_calendar": [f"{d} {k}" for d, k, a in expected
                                                if (d, k) in done and done[(d, k)] != a]}
    c["sessions"] = len({d for d, _ in done})
    r = await one(s, """select count(*), count(distinct (session_date, snapshot, instrument_key,
            feature_id)), count(distinct instrument_key) filter (where scope = 'INSTRUMENT'
              and instrument_key like 'NSE_EQ|%%'),
          count(*) filter (where input_max_knowable_at >= as_of),
          count(*) filter (where value::text in ('NaN', 'Infinity', '-Infinity')),
          count(*) filter (where (status = 'VALID') <> (value is not null)),
          count(*) filter (where as_of > now() or input_max_knowable_at > now()),
          count(*) filter (where registry_sha256_ok is false)
        from (select t.*, true as registry_sha256_ok from training_feature_value t
              where dataset_version = :v) x""", v=v)
    c["rows"] = r[0]
    c["duplicates"] = r[0] - r[1]
    c["symbols"] = r[2]
    c["pit_violations"] = r[3]
    c["nan_inf_values"] = r[4]
    c["value_status_inconsistent"] = r[5]
    c["future_timestamps"] = r[6]
    c["rows_match_markers"] = r[0] == c["window"]["rows_by_markers"]
    c["duplicate_snapshots"] = await val(s, """select count(*) - count(distinct (session_date,
        snapshot)) from training_session_done where dataset_version = :v""", v=v)
    c["orphan_instruments"] = await val(s, """select count(distinct t.instrument_key)
        from training_feature_value t where t.dataset_version = :v and t.instrument_key <> 'MARKET'
          and not exists (select 1 from instrument i where i.instrument_key = t.instrument_key)""",
                                        v=v)
    c["non_trading_dates"] = await val(s, """select count(*) from training_session_done d
        where d.dataset_version = :v and not exists (select 1 from trading_session t
          where t.session_date = d.session_date and t.is_trading_day)""", v=v)
    runs = (await s.execute(text("""select run_id, status, registry_sha256, registry_version,
        feature_count, started_at, completed_at, sessions_done, row_count, policy_params
        from training_dataset_run where dataset_version = :v order by started_at"""),
        {"v": v})).all()
    c["runs"] = [{"run_id": str(x[0]), "status": x[1], "registry": x[3], "sessions_done": x[7],
                  "rows": x[8], "started_at": x[5].isoformat(),
                  "completed_at": x[6].isoformat() if x[6] else None} for x in runs]
    c["registry_hash_mismatch"] = sum(1 for x in runs if x[2] != R.REGISTRY_SHA256)
    c["registry"] = {"version": R.VERSION, "sha256": R.REGISTRY_SHA256,
                     "features": len(R.FEATURES)}
    c["policy_params"] = runs[-1][9] if runs else {}
    c["runtime_s"] = round(sum(((x[6] or now()) - x[5]).total_seconds() for x in runs), 1)
    c["status_counts"] = dict((await s.execute(text("""select status, count(*)
        from training_feature_value where dataset_version = :v group by 1 order by 1"""),
        {"v": v})).all())
    c["reason_counts_invalid"] = dict((await s.execute(text("""select feature_id, count(*)
        from training_feature_value where dataset_version = :v and status = 'INVALID'
        group by 1 order by 2 desc"""), {"v": v})).all())
    return c


async def coverage_table(s, ds) -> list[dict]:
    rows = (await s.execute(text("""select feature_id,
          min(session_date) filter (where status = 'VALID'),
          max(session_date) filter (where status = 'VALID'),
          count(*), count(*) filter (where status = 'VALID'),
          count(*) filter (where status = 'MISSING_INPUT'),
          count(*) filter (where status = 'STALE_INPUT'),
          count(*) filter (where status = 'INVALID'),
          count(*) filter (where status = 'NOT_APPLICABLE'),
          count(*) filter (where status = 'NOT_AVAILABLE_HISTORICALLY'),
          count(*) filter (where input_max_knowable_at >= as_of),
          count(distinct session_date) filter (where status = 'VALID')
        from training_feature_value where dataset_version = :v group by 1"""),
        {"v": ds.version})).all()
    out = []
    for r in rows:
        spec = R.BY_ID[r[0]]
        fam = sorted({A.FAMILY.get(i, i) for i in spec.inputs})
        applicable = r[3] - r[8]
        nah = r[9]
        cls = ("UNAVAILABLE_HISTORICALLY" if r[4] == 0 else
               "PARTIAL_HISTORY" if nah > 0 or (applicable and r[4] / applicable < 0.5)
               else "BACKFILLED")
        out.append({"feature_id": r[0], "group": spec.group, "families": fam,
                    "earliest_valid": str(r[1]) if r[1] else None,
                    "latest_valid": str(r[2]) if r[2] else None, "rows": r[3],
                    "valid": r[4], "coverage_pct": round(100 * r[4] / applicable, 2)
                    if applicable else None,
                    "missing_input": r[5], "stale_input": r[6], "invalid": r[7],
                    "not_applicable": r[8], "not_available_historically": nah,
                    "sessions_with_valid": r[11],
                    "pit": "PASS" if r[10] == 0 else f"FAIL ({r[10]})", "class": cls})
    order = {f.id: i for i, f in enumerate(R.FEATURES)}
    return sorted(out, key=lambda x: order[x["feature_id"]])


async def family_windows(s, ds) -> list[dict]:
    """Per family: the first session with any VALID value, and the first session from
    which the family is VALID for >= 50% of its applicable rows (stable)."""
    fam_of = {f.id: "+".join(sorted({A.FAMILY.get(i, i) for i in f.inputs})) for f in R.FEATURES}
    rows = (await s.execute(text("""select session_date, feature_id,
          count(*) filter (where status <> 'NOT_APPLICABLE'),
          count(*) filter (where status = 'VALID')
        from training_feature_value where dataset_version = :v group by 1, 2"""),
        {"v": ds.version})).all()
    per: dict = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for d, f, n, ok in rows:
        per[f"{R.BY_ID[f].group}:{fam_of[f]}"][d][0] += n
        per[f"{R.BY_ID[f].group}:{fam_of[f]}"][d][1] += ok
    out = []
    for fam, days in sorted(per.items()):
        ds_ = sorted(days)
        first = next((d for d in ds_ if days[d][1] > 0), None)
        stable = next((d for i, d in enumerate(ds_)
                       if all(days[x][1] >= 0.5 * days[x][0] for x in ds_[i:] if days[x][0])),
                      None)
        out.append({"family": fam, "earliest_any_valid": str(first) if first else None,
                    "stable_from_50pct": str(stable) if stable else None,
                    "latest": str(ds_[-1]),
                    "usable_sessions": sum(1 for d in ds_ if days[d][1] > 0)})
    return out


async def label_checks(s) -> dict:
    r = await one(s, """select count(*), count(*) filter (where status = 'VALID'),
        count(distinct session_date), count(distinct instrument_key), min(session_date),
        max(session_date), count(*) - count(distinct (session_date, instrument_key, label_id))
        from training_label where label_version = :v""", v=L.VERSION)
    leak = await val(s, """select count(*) from training_label l join training_session_done d
        on d.session_date = l.session_date where l.label_start_at <= d.as_of""")
    pairs = await val(s, """select count(*) from training_label l join training_session_done d
        on d.session_date = l.session_date""")
    nontrade = await val(s, """select count(*) from training_label l where not exists (
        select 1 from trading_session t where t.session_date = l.session_date
          and t.is_trading_day)""")
    by = dict((await s.execute(text("""select label_id, round(avg(value)::numeric, 6)
        from training_label where status = 'VALID' group by 1 order by 1"""))).all())
    return {"version": L.VERSION, "rows": r[0], "valid": r[1], "sessions": r[2],
            "instruments": r[3], "first": str(r[4]), "last": str(r[5]), "duplicates": r[6],
            "leakage_label_start_le_as_of": leak, "label_snapshot_pairs_checked": pairs,
            "non_trading_dates": nontrade, "mean_by_label": {k: float(x) for k, x in by.items()},
            "definitions": L.__doc__}


async def replay_vs_production(s) -> dict:
    out = {}
    for d in (await s.execute(text("""select distinct f.session_date from feature_value f
        join training_session_done t on t.session_date = f.session_date
         and t.dataset_version = :v order by 1"""), {"v": P.DATASETS["strict"].version})
              ).scalars():
        r = await one(s, """select count(*),
              count(*) filter (where t.inputs_sha256 = f.inputs_sha256),
              count(*) filter (where t.reason is not distinct from f.reason),
              count(*) filter (where (t.status = 'VALID' and t.value = f.value::float8)
                               or (t.status <> 'VALID' and (f.value is null
                                   or t.status = 'NOT_AVAILABLE_HISTORICALLY'))),
              count(*) filter (where t.status = 'NOT_AVAILABLE_HISTORICALLY'
                               and f.value is not null)
            from training_feature_value t join feature_value f using (session_date, snapshot,
              instrument_key, feature_id)
            where t.dataset_version = :v and t.session_date = :d""",
                      v=P.DATASETS["strict"].version, d=d)
        diffs = (await s.execute(text("""select t.snapshot, t.feature_id, t.instrument_key,
              t.value, f.value::float8, t.status, t.reason, f.reason,
              t.inputs_sha256 = f.inputs_sha256
            from training_feature_value t join feature_value f using (session_date, snapshot,
              instrument_key, feature_id)
            where t.dataset_version = :v and t.session_date = :d
              and not ((t.status = 'VALID' and t.value = f.value::float8)
                       or (t.status <> 'VALID' and (f.value is null
                           or t.status = 'NOT_AVAILABLE_HISTORICALLY')))
            order by 2, 3 limit 40"""), {"v": P.DATASETS["strict"].version, "d": d})).all()
        prod_only = await val(s, """select count(*) from feature_value f where f.session_date = :d
            and not exists (select 1 from training_feature_value t where t.dataset_version = :v
              and t.session_date = f.session_date and t.snapshot = f.snapshot
              and t.instrument_key = f.instrument_key and t.feature_id = f.feature_id)""",
                              d=d, v=P.DATASETS["strict"].version)
        out[str(d)] = {"joined": r[0], "same_inputs_sha256": r[1], "same_reason": r[2],
                       "same_value": r[3], "production_value_nulled_as_not_available": r[4],
                       "production_rows_not_in_replay": prod_only,
                       "differences": [list(map(str, x)) for x in diffs]}
    return out


async def fresh_recompute(sm, ds, n_sessions: int, n_keys: int, rng: random.Random) -> dict:
    async with sm() as s:
        snaps = (await s.execute(text("""select session_date, snapshot from
            training_session_done where dataset_version = :v order by 1, 2"""),
            {"v": ds.version})).all()
    pick = rng.sample(snaps, min(n_sessions, len(snaps)))
    checked, mismatches, examples = 0, 0, []
    for d, k in sorted(pick):
        async with sm() as s:
            await E.consistent_read(s, read_only=True)
            if ds.search_path:
                await s.execute(text(f"set local search_path = {ds.search_path}"))
            snap = await SN.resolve(s, d, k)
            keys = list((await s.execute(text("""select distinct instrument_key
                from public.training_feature_value where dataset_version = :v
                  and session_date = :d and snapshot = :k and instrument_key like 'NSE_EQ|%%'"""),
                {"v": ds.version, "d": d, "k": k})).scalars())
            sample = sorted(rng.sample(keys, min(n_keys, len(keys))))
            res = await E.compute_snapshot(s, snap, sample, with_sector=False)
            stored = {(r[0], r[1]): (r[2], r[3], r[4]) for r in (await s.execute(text("""
                select instrument_key, feature_id, value, reason, inputs_sha256
                from public.training_feature_value where dataset_version = :v
                  and session_date = :d and snapshot = :k and instrument_key = any(:keys)"""),
                {"v": ds.version, "d": d, "k": k, "keys": [*sample, "MARKET"]})).all()}
            await s.rollback()
        for r in res.rows:
            if (r.instrument_key, r.feature_id) not in stored:
                continue
            v, why, sha = stored[(r.instrument_key, r.feature_id)]
            checked += 1
            same = why == r.reason and sha == r.inputs_sha256 and (
                v == r.value or v is None)          # NOT_AVAILABLE rows store null
            if not same:
                mismatches += 1
                if len(examples) < 10:
                    examples.append([str(d), k, r.instrument_key, r.feature_id, v, r.value])
    return {"sessions": [f"{d} {k}" for d, k in sorted(pick)], "keys_per_session": n_keys,
            "rows_compared": checked, "mismatches": mismatches, "examples": examples,
            "note": "sector_rs_20 excluded (peer set); every other feature recomputed"}


async def raw_sql_checks(s, ds, rng: random.Random) -> dict:
    """ret_1d, sma_20, avg_volume_20 and the ret_cc label from raw canon bars, for
    instruments with no corporate-action factor at all (no adjustment involved)."""
    snaps = (await s.execute(text("""select session_date, as_of, snapshot from
        training_session_done where dataset_version = :v and snapshot = 'PRE_SESSION'
        order by 1"""), {"v": ds.version})).all()
    snaps = [x for x in snaps if x[0] >= _dt.date(2025, 11, 15)] or snaps
    pick = sorted(rng.sample(snaps, min(10, len(snaps))))
    checked, bad, examples = 0, 0, []
    for d, _as_of, k in pick:
        rows = (await s.execute(text("""
            with t as (select instrument_key, feature_id, value from training_feature_value
                       where dataset_version = :v and session_date = :d and snapshot = :k
                         and status = 'VALID' and feature_id in ('ret_1d','sma_20','avg_volume_20')
                         and instrument_key like 'NSE_EQ|%%'
                         and instrument_key not in (select instrument_key from ca_factor
                                                    where instrument_key is not null)),
            keys as (select instrument_key from (select distinct instrument_key from t) x
                     order by md5(instrument_key) limit 10),
            b as (select instrument_key, market_date, close::float8 c, volume::float8 vol,
                    row_number() over (partition by instrument_key order by market_date desc) rn
                  from public.canon_market_bar where timeframe = '1d' and market_date < :d
                    and market_date >= cast(:d as date) - 450
                    and instrument_key in (select instrument_key from keys))
            select t.instrument_key, t.feature_id, t.value,
              case t.feature_id
                when 'ret_1d' then (select max(c) filter (where rn = 1)
                                     / max(c) filter (where rn = 2) - 1
                                   from b where b.instrument_key = t.instrument_key)
                when 'sma_20' then (select avg(c) from b where b.instrument_key = t.instrument_key
                                     and rn <= 20)
                else (select avg(vol) from b where b.instrument_key = t.instrument_key and rn <= 20)
              end
            from t where t.instrument_key in (select instrument_key from keys)"""),
            {"v": ds.version, "d": d, "k": k})).all()
        for key, fid, stored, raw in rows:
            checked += 1
            if raw is None or abs(stored - raw) > 1e-9 * max(1.0, abs(raw)):
                bad += 1
                if len(examples) < 10:
                    examples.append([str(d), key, fid, stored, raw])
    lab = (await s.execute(text("""
        with l as (select session_date, instrument_key, value from training_label
                   where label_version = :lv and label_id = 'ret_cc' and status = 'VALID'
                     and instrument_key like 'NSE_EQ|%%' and instrument_key not in
                     (select instrument_key from ca_factor where instrument_key is not null)
                   order by md5(instrument_key || session_date::text) limit 200)
        select l.session_date, l.instrument_key, l.value,
          (select b1.close::float8 / b0.close::float8 - 1
           from public.canon_market_bar b1 join public.canon_market_bar b0
             on b0.instrument_key = b1.instrument_key and b0.timeframe = '1d'
            and b0.market_date = (select max(session_date) from trading_session
                                  where is_trading_day and session_date < l.session_date)
           where b1.instrument_key = l.instrument_key and b1.timeframe = '1d'
             and b1.market_date = l.session_date)
        from l"""), {"lv": L.VERSION})).all()
    lbad = [x for x in lab if x[3] is None or abs(x[2] - x[3]) > 1e-9 * max(1.0, abs(x[3]))]
    return {"feature_rows_compared": checked, "feature_mismatches": bad,
            "feature_examples": examples, "sessions": [str(x[0]) for x in pick],
            "labels_compared": len(lab), "label_mismatches": len(lbad),
            "label_examples": [list(map(str, x)) for x in lbad[:10]],
            "tolerance": "relative 1e-9 (values are stored at 12 significant digits)"}


async def scenarios(s) -> dict:
    sv, av = P.DATASETS["strict"].version, P.DATASETS["asif"].version
    out = {}
    # late-arriving data: bars of a session that became knowable after a later snapshot
    late = (await s.execute(text("""select b.instrument_key, b.market_date, b.knowable_at
        from canon_market_bar b where b.timeframe = '1d' and b.instrument_key like 'NSE_EQ|%%'
          and b.market_date >= '2026-09-24' and b.knowable_at > ((select min(session_date)
            from trading_session t where t.is_trading_day and t.session_date > b.market_date)
            + time '08:59:59') at time zone 'Asia/Kolkata'
        order by 2, 1 limit 400"""))).all()
    seen = 0
    ok_stale = 0
    for key, md, kn in late:
        r = (await s.execute(text("""select status from training_feature_value
            where dataset_version = :v and instrument_key = :k and feature_id = 'ret_1d'
              and snapshot = 'PRE_SESSION' and session_date = (select min(session_date)
                from trading_session where is_trading_day and session_date > :md)
              and as_of < :kn"""), {"v": sv, "k": key, "md": md, "kn": kn})).scalar()
        if r is not None:
            seen += 1
            ok_stale += r in (A.STALE, A.MISSING_INPUT)
    out["late_arriving_bars"] = {"late_bars_found": len(late), "checked_in_strict": seen,
                                 "never_used_before_knowable": ok_stale,
                                 "pass": seen == ok_stale}
    # delayed fundamentals: first fundamentals knowable 2026-09-24 15:51 IST
    r = (await s.execute(text("""select session_date, snapshot, status, count(*)
        from training_feature_value where dataset_version = :v and feature_id = 'pe'
          and session_date in ('2026-09-24', '2026-09-25') group by 1, 2, 3 order by 1, 2, 3"""),
        {"v": sv})).all()
    out["delayed_fundamentals_strict"] = [list(map(str, x)) for x in r]
    out["delayed_fundamentals_pass"] = all(x[2] == A.NA_HIST for x in r
                                           if str(x[0]) == "2026-09-24")
    # delayed FII/DII: every value's inputs knowable before as_of (and the obs date)
    r = (await s.execute(text("""select dataset_version, count(*), count(*) filter (where
        status = 'VALID'), count(*) filter (where input_max_knowable_at >= as_of)
        from training_feature_value where feature_id = 'fii_net_cash_1d'
          and dataset_version in (:a, :b) group by 1"""), {"a": sv, "b": av})).all()
    out["fii_dii"] = [list(map(str, x)) for x in r]
    # missing news: never a zero before collection
    r = (await s.execute(text("""select dataset_version, count(*) filter (where value is not null
          and as_of < (select min(finished_at) from news_poll where mode = 'PRODUCTION')),
          count(*) filter (where as_of < (select min(finished_at) from news_poll
                                          where mode = 'PRODUCTION'))
        from training_feature_value where feature_id like 'mnews_%%'
          and dataset_version in (:a, :b) group by 1"""), {"a": sv, "b": av})).all()
    out["missing_news_never_zero"] = {x[0]: {"rows_before_collection": x[2],
                                             "non_null_before_collection": x[1]} for x in r}
    r = (await s.execute(text("""select dataset_version, count(*) filter (where value is not null
          and as_of < (select min(knowable_at) from canon_news)), count(*) filter (where
          as_of < (select min(knowable_at) from canon_news))
        from training_feature_value where feature_id in ('news_count_24h', 'news_count_7d')
          and dataset_version in (:a, :b) group by 1"""), {"a": sv, "b": av})).all()
    out["legacy_news_never_zero"] = {x[0]: {"rows_before_collection": x[2],
                                            "non_null_before_collection": x[1]} for x in r}
    # corporate actions knowable later: a CA whose knowable_at falls inside the AS_IF_LIVE
    # window must not change ca_days_to_any before it was knowable
    ca = (await s.execute(text("""select instrument_key, ex_date, knowable_at
        from canon_corporate_action where instrument_key is not null
          and knowable_at between '2025-10-15' and '2026-09-01' and ex_date > knowable_at::date
        order by md5(instrument_key) limit 50"""))).all()
    wrong = checked = 0
    for key, ex, kn in ca:
        r = (await s.execute(text("""select t.session_date, t.value from training_feature_value t
            where t.dataset_version = :v and t.instrument_key = :k
              and t.feature_id = 'ca_days_to_any' and t.as_of < :kn
              and t.session_date >= cast(:kn as date) - 10 and t.status = 'VALID'
              and not exists (select 1 from canon_corporate_action c   -- another, known CA
                              where c.instrument_key = :k and c.ex_date = :ex
                                and c.knowable_at < t.as_of)"""),
            {"v": av, "k": key, "kn": kn, "ex": ex})).all()
        checked += len(r)
        wrong += sum(1 for d, v in r if v == float((ex - d).days))
    out["corporate_action_knowable_later"] = {
        "cas": len(ca), "rows_before_knowable": checked,
        "rows_equal_to_the_not_yet_knowable_ex_date": wrong, "pass": wrong == 0}
    # STRICT: an action announced before a snapshot but first stored after it is invisible
    late_ca = (await s.execute(text("""select instrument_key, ex_date, knowable_at, fetched_at
        from canon_corporate_action where instrument_key is not null and ex_date is not null
          and fetched_at > knowable_at + interval '1 day' and fetched_at >= '2026-09-24'"""))).all()
    wrong = checked = 0
    for key, ex, kn, fetched in late_ca:
        r = (await s.execute(text("""select t.session_date, t.value from training_feature_value t
            where t.dataset_version = :v and t.instrument_key = :k and t.feature_id in
              ('ca_days_to_any', 'ca_days_since_any') and t.as_of >= :kn and t.as_of < :f
              and t.status = 'VALID' and not exists (select 1 from canon_corporate_action c
                where c.instrument_key = :k and c.ex_date = :ex
                  and greatest(c.knowable_at, c.fetched_at) < t.as_of)"""),
            {"v": sv, "k": key, "kn": kn, "f": fetched, "ex": ex})).all()
        checked += len(r)
        wrong += sum(1 for d, v in r if v == float(abs((ex - d).days)))
    out["strict_corporate_action_observed"] = {
        "actions_stored_after_announcement": len(late_ca),
        "rows_between_announcement_and_storage": checked,
        "rows_reflecting_the_unobserved_action": wrong, "pass": wrong == 0}
    # lifecycle: instruments removed from the master that appear in the datasets
    r = (await s.execute(text("""select t.dataset_version, count(distinct t.instrument_key)
        from training_feature_value t join canon_instrument ci using (instrument_key)
        where ci.lifecycle_status = 'REMOVED_FROM_MASTER' and t.dataset_version in (:a, :b)
        group by 1"""), {"a": sv, "b": av})).all()
    out["removed_from_master_present"] = {x[0]: x[1] for x in r}
    return out


async def survivorship(s) -> dict:
    av = P.DATASETS["asif"].version
    per = (await s.execute(text("""select session_date, instruments from training_session_done
        where dataset_version = :v order by 1"""), {"v": av})).all()
    r = await one(s, """with f as (select instrument_key, min(market_date) a, max(market_date) b
          from canon_market_bar where timeframe = '1d' and instrument_key like 'NSE_EQ|%%'
          group by 1)
        select count(*), count(*) filter (where a > '2025-09-24'), count(*) filter (
          where b < '2026-09-01'), count(*) filter (where a <= '2020-01-31')
        from f""")
    removed = (await s.execute(text("""select trading_symbol from canon_instrument
        where lifecycle_status = 'REMOVED_FROM_MASTER' order by 1"""))).scalars().all()
    return {"universe_per_session": {"first": [str(per[0][0]), per[0][1]] if per else None,
                                     "last": [str(per[-1][0]), per[-1][1]] if per else None,
                                     "min": min((x[1] for x in per), default=None),
                                     "max": max((x[1] for x in per), default=None)},
            "stocks_with_daily_bars": r[0], "first_bar_after_2025_09_24_new_listings": r[1],
            "last_bar_before_2026_09_01_vanished": r[2], "history_from_2020": r[3],
            "removed_from_master": removed,
            "delisted_never_in_master": "UNKNOWN: the instrument master (Upstox) lists only "
            "currently tradable instruments; companies delisted before 2026-09-23 were never "
            "downloaded, so their bars do not exist in Prajna (survivorship bias)"}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-count", type=int, default=801434)
    ap.add_argument("--baseline-md5", default="b45381f3c89664cdf3dbbfa95d70b1a5")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="../audit/evidence/stage4_training_dataset.json")
    a = ap.parse_args()
    rng = random.Random(a.seed)  # noqa: S311 - a reproducible sample, not security
    sm = get_sessionmaker()
    ev: dict = {"generated_at": now().astimezone(IST).isoformat(), "seed": a.seed}
    async with sm() as s:
        await s.execute(text("set transaction read only"))
        fp = await one(s, FP_SQL)
        ev["production_feature_value"] = {
            "count": fp[0], "md5": fp[1], "baseline_count": a.baseline_count,
            "baseline_md5": a.baseline_md5,
            "untouched_since_baseline": (fp[0], fp[1]) == (a.baseline_count, a.baseline_md5),
            "note": "rows added after the baseline by the live Stage 3 cron change this; "
                    "rows_before_baseline_identical checks the baseline rows themselves"}
        ev["production_feature_value"]["rows_before_baseline_identical"] = (await one(s, """
            select count(*), md5(string_agg(md5(concat_ws('|', instrument_key, session_date,
              snapshot, feature_id, value, reason, inputs_sha256)), '' order by id))
            from (select * from feature_value order by id limit :n) x""",
            n=a.baseline_count))[1] == a.baseline_md5
        ev["datasets"] = {}
        for name, ds in P.DATASETS.items():
            ev["datasets"][name] = {"version": ds.version, "policy": ds.policy,
                                    "snapshots": list(ds.snapshots),
                                    **await dataset_checks(s, ds),
                                    "family_windows": await family_windows(s, ds),
                                    "coverage": await coverage_table(s, ds)}
        ev["labels"] = await label_checks(s)
        ev["replay_vs_production"] = await replay_vs_production(s)
        ev["raw_sql"] = {n: await raw_sql_checks(s, ds, rng) for n, ds in P.DATASETS.items()}
        ev["scenarios"] = await scenarios(s)
        ev["survivorship"] = await survivorship(s)
        ev["storage"] = {t: (await one(s, "select pg_total_relation_size(cast(:t as regclass)),"
                                          " pg_size_pretty(pg_total_relation_size(cast(:t as "
                                          "regclass)))", t=t))[1]
                         for t in ("training_feature_value", "training_label",
                                   "training_session_done", "training_dataset_run")}
        await s.rollback()
    ev["fresh_recompute"] = {n: await fresh_recompute(sm, ds, 10, 10, rng)
                             for n, ds in P.DATASETS.items()}
    await asyncio.to_thread(pathlib.Path(a.out).write_text, json.dumps(ev, indent=1, default=str))
    summary = {n: {k: d[k] for k in ("rows", "duplicates", "pit_violations", "nan_inf_values",
                                     "orphan_instruments", "non_trading_dates",
                                     "registry_hash_mismatch", "duplicate_snapshots")}
               | {"missing_snapshots": len(d["completeness"]["missing"])}
               for n, d in ev["datasets"].items()}
    print(json.dumps({"datasets": summary, "labels": {k: ev["labels"][k] for k in (
        "rows", "valid", "duplicates", "leakage_label_start_le_as_of")},
        "fresh_recompute": {n: (x["rows_compared"], x["mismatches"])
                            for n, x in ev["fresh_recompute"].items()},
        "raw_sql": {n: (x["feature_rows_compared"], x["feature_mismatches"],
                        x["labels_compared"], x["label_mismatches"])
                    for n, x in ev["raw_sql"].items()},
        "production": ev["production_feature_value"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
