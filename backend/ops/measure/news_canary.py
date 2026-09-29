"""Stage 3 news v2 canary (READ-ONLY; persists nothing).

For a real snapshot of a trading session (default: today's PRE_SESSION, as_of from
the session calendar) it computes the news v2 feature rows with the v2 specs
enabled ONLY inside this process, and checks them against the production data:

  1 coverage state at as_of (NORMAL expected while the collector runs)
  2 point in time: no input row knowable at/after as_of
  3 market-wide counts recomputed INDEPENDENTLY with raw SQL on the news tables
    (not through news_pit): 1h / 4h / 24h / 3d counts, duplicates, corrections
  4 per-company counts for the most-covered companies, the same way
  5 determinism: a second computation gives identical values and provenance
  6 non-news features unchanged: compute_snapshot for sampled instruments with and
    without the news specs gives identical non-news rows

  .venv/bin/python ops/measure/news_canary.py [--session YYYY-MM-DD] [--kind PRE_SESSION]
      [--out ../audit/evidence/news_stage3_canary_<date>_<kind>.json]
Exit 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.core.clock import IST, now
from app.db.engine import get_sessionmaker
from app.features import engine as E
from app.features import registry as R
from app.features.snapshots import resolve


async def sql_counts(s, as_of: _dt.datetime, key: str | None) -> dict[str, int]:
    """Independent: raw SQL on news_item / news_decision / news_poll (PRODUCTION),
    current decision per article knowable before as_of."""
    link = ("and exists (select 1 from news_entity_link l where l.item_id = i.id "
            "and l.instrument_key = :k and l.knowable_at < :a)") if key else ""
    q = f"""
      with it as (
        select i.id, i.knowable_at,
          (select d.decision from news_decision d where d.item_id = i.id
             and d.observation_id is null and d.knowable_at < :a
           order by d.knowable_at desc, d.id desc limit 1) as dec
        from news_item i join news_poll p on p.id = i.first_poll_id and p.mode = 'PRODUCTION'
        where i.knowable_at < :a and :a - i.knowable_at <= interval '3 days'
          and not i.backlog {link})
      select
        count(*) filter (where dec <> 'DUPLICATE_ARTICLE' and age <= interval '1 hour'),
        count(*) filter (where dec <> 'DUPLICATE_ARTICLE' and age <= interval '4 hours'),
        count(*) filter (where dec <> 'DUPLICATE_ARTICLE' and age <= interval '24 hours'),
        count(*) filter (where dec <> 'DUPLICATE_ARTICLE'),
        count(*) filter (where dec = 'DUPLICATE_ARTICLE' and age <= interval '24 hours'),
        count(*) filter (where dec = 'STORY_CORRECTION' and age <= interval '24 hours')
      from (select *, :a - knowable_at as age from it) x"""  # noqa: S608 - constant fragments; values bound
    r = (await s.execute(text(q), {"a": as_of, "k": key})).one()
    return dict(zip(("1h", "4h", "24h", "3d", "dup24h", "corr24h"), r, strict=True))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    ap.add_argument("--kind", default="PRE_SESSION")
    ap.add_argument("--out", default=None)
    ap.add_argument("--sample", type=int, default=25)
    ap.add_argument("--as-of", default=None, help="REHEARSAL only: override the snapshot "
                    "instant (ISO with offset); the real canary uses the calendar as_of")
    a = ap.parse_args()
    day = _dt.date.fromisoformat(a.session) if a.session else now().astimezone(IST).date()
    ev: dict = {"session": str(day), "kind": a.kind, "generated_at": now().isoformat(),
                "active_registry": {"version": R.VERSION, "sha256": R.REGISTRY_SHA256,
                                    "features": len(R.FEATURES)},
                "checks": {}}
    sm = get_sessionmaker()
    async with sm() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        snap = await resolve(s, day, a.kind)
        if a.as_of:
            import dataclasses
            snap = dataclasses.replace(snap, as_of=_dt.datetime.fromisoformat(a.as_of))
            ev["rehearsal"] = True
        ev["as_of"] = snap.as_of.isoformat()
        keys = list((await s.execute(text("""select instrument_key from canon_instrument
            where included and lifecycle_status = 'ACTIVE' and segment = 'NSE_EQ'
            order by 1"""))).scalars())
        base = E.FEATURES
        E.FEATURES = R.FEATURES_V1 + R.NEWS_V2_FEATURES          # this process only
        try:
            rows = await E.news_rows(s, snap, keys)
            again = await E.news_rows(s, snap, keys)
        finally:
            E.FEATURES = base
        from app.features import news_features as NF
        state = await NF.coverage_state(s, snap.as_of)
        ctx = {r.feature_id: r for r in rows if r.scope == "CONTEXT"}
        co = {(r.instrument_key, r.feature_id): r for r in rows if r.scope == "INSTRUMENT"}
        c = ev["checks"]
        c["coverage_state"] = {"value": state, "pass": state == "NORMAL"}
        late = [r for r in rows
                if r.input_max_knowable_at and r.input_max_knowable_at >= snap.as_of]
        c["point_in_time"] = {"rows": len(rows), "inputs_knowable_at_or_after_as_of": len(late),
                              "pass": not late}
        sq = await sql_counts(s, snap.as_of, None)
        mw = {"1h": "mnews_news_count_1h", "4h": "mnews_news_count_4h",
              "24h": "mnews_news_count_24h", "3d": "mnews_news_count_3d",
              "dup24h": "mnews_duplicate_count_24h", "corr24h": "mnews_correction_count_24h"}
        cmp = {k: {"feature": ctx[f].value, "sql": sq[k]} for k, f in mw.items()}
        c["market_wide_vs_independent_sql"] = {
            "values": cmp, "pass": all(v["feature"] == v["sql"] for v in cmp.values())}
        top = [k for (k,) in (await s.execute(text("""
            select l.instrument_key from news_entity_link l join news_item i on i.id = l.item_id
            join news_poll p on p.id = i.first_poll_id and p.mode = 'PRODUCTION'
            where l.instrument_key is not null and i.knowable_at < :a and not i.backlog
              and i.knowable_at >= :a - interval '24 hours'
            group by 1 order by count(*) desc, 1 limit :n"""),
            {"a": snap.as_of, "n": a.sample})).all()]
        comp = {}
        for k in top:
            sk = await sql_counts(s, snap.as_of, k)
            comp[k] = {f"{w}_{src}": (co[(k, f"mnews_company_count_{w}")].value
                                      if src == "feature" else sk[w])
                       for w in ("1h", "24h", "3d") for src in ("feature", "sql")}
        c["companies_vs_independent_sql"] = {
            "companies": comp, "pass": all(v[f"{w}_feature"] == v[f"{w}_sql"]
                                           for v in comp.values() for w in ("1h", "24h", "3d"))}
        zero = [k for k in keys if k not in top and (k, "mnews_company_count_3d") in co
                and co[(k, "mnews_company_count_3d")].value == 0.0]
        c["no_news_is_a_real_zero_with_coverage"] = {
            "instruments_with_zero": len(zero), "time_since_missing": sum(
                1 for k in zero if co[(k, "mnews_company_time_since_last_s")].reason
                == "MISSING_INPUT"), "pass": all(
                co[(k, "mnews_company_time_since_last_s")].reason == "MISSING_INPUT"
                for k in zero)}
        sig = [(r.instrument_key, r.feature_id, r.value, r.reason, r.inputs_sha256) for r in rows]
        sig2 = [(r.instrument_key, r.feature_id, r.value, r.reason, r.inputs_sha256)
                for r in again]
        c["deterministic"] = {"pass": sig == sig2}
        sample = keys[:: max(1, len(keys) // 10)][:10]
        without = await E.compute_snapshot(s, snap, sample, with_context=True, with_sector=False)
        E.FEATURES = R.FEATURES_V1 + R.NEWS_V2_FEATURES
        try:
            with_news = await E.compute_snapshot(s, snap, sample, with_context=True,
                                                 with_sector=False)
        finally:
            E.FEATURES = base
        a1 = sorted((r.instrument_key, r.feature_id, r.value, r.reason) for r in without.rows)
        a2 = sorted((r.instrument_key, r.feature_id, r.value, r.reason) for r in with_news.rows
                    if not r.feature_id.startswith("mnews_"))
        c["non_news_features_unchanged"] = {"instruments": len(sample), "rows": len(a1),
                                            "pass": a1 == a2}
        ev["market_wide_features"] = {f: [r.value, r.reason] for f, r in sorted(ctx.items())}
        await s.rollback()
    ev["pass"] = all(v["pass"] for v in ev["checks"].values())
    out = a.out or f"../audit/evidence/news_stage3_canary_{day}_{a.kind}.json"
    await asyncio.to_thread(pathlib.Path(out).write_text, json.dumps(ev, indent=1, default=str))
    print(json.dumps({k: v["pass"] for k, v in ev["checks"].items()} | {"PASS": ev["pass"]},
                     indent=1))
    return 0 if ev["pass"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
