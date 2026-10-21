"""Stage 3 features-v5 canary (READ-ONLY; persists nothing; docs/STAGE3_FEATURES_V5.md).

For a real snapshot (default: the latest PRE_SESSION) it computes the v5 feature list in
THIS process only (engine.FEATURES swapped, the active registry untouched) for the whole
Stage 3 universe and checks:

  1 point in time        no row's input knowable at/after as_of (the engine also raises)
  2 v4 unchanged         every v4 row identical with and without v5, except the four
                         ca_days_to_* rows, which v5 drops (registered UNSUPPORTED)
  3 determinism          a second v5 computation of a sample gives identical rows
  4 independent recount  the results calendar recounted with raw SQL on the news tables
                         (not through results_pit or the parser's pre-filter): the
                         instruments with a results intimation knowable before as_of
  5 own vs vendor P/E    pe_ttm / vendor pe within [0.67, 1.5] for >= 85 % of the
                         instruments that have both (the vendor ratio is a ~monthly
                         snapshot; a split, a demerger or a stale vendor value explain the
                         rest, listed)
  6 coverage             values and null reasons per v5 feature (reported)
  7 time                 the extra seconds of the v5 computation (reported; the PRE_OPEN
                         run must finish before 09:30)

  .venv/bin/python ops/measure/features_v5_canary.py [--session YYYY-MM-DD]
      [--kind PRE_SESSION|PRE_OPEN] [--limit N] [--out ../audit/evidence/...json]
Exit 0 only if checks 1-5 pass.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.canon import results_pit as RP
from app.core.clock import IST, now
from app.db.engine import get_sessionmaker
from app.features import engine as E
from app.features import registry as R
from app.features.snapshots import resolve

PE_BAND, PE_SHARE = (0.67, 1.5), 0.85
SAMPLE = 60


async def intimation_keys(s, as_of: _dt.datetime) -> set[str]:
    """Independent: raw SQL, no parser pre-filter - PRODUCTION NSE intimations about
    financial results knowable before as_of (item and link), best link per item."""
    rows = (await s.execute(text("""
        select distinct on (n.id) l.instrument_key
          from news_item n
          join news_poll p on p.id = n.first_poll_id and p.mode = 'PRODUCTION'
          join news_entity_link l on l.item_id = n.id and l.knowable_at < :a
                                 and l.confidence >= 0.9 and l.instrument_key like 'NSE_EQ|%'
         where n.source = 'NSE_ANNOUNCEMENTS' and n.category_raw = 'Board Meeting Intimation'
           and n.knowable_at < :a and n.knowable_at >= :since
           and n.summary ilike '%financial result%' and n.summary ilike '%to be held on%'
         order by n.id, l.confidence desc, l.instrument_key"""),
        {"a": as_of, "since": as_of - _dt.timedelta(days=150)})).scalars().all()
    return set(rows)


def by_key(rows) -> dict:
    return {(r.instrument_key, r.feature_id): asdict(r) for r in rows}


async def canary(session: _dt.date | None, kind: str, limit: int | None) -> dict:
    async with get_sessionmaker()() as s:
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        if session is None:
            session = (await s.execute(text("""select max(session_date) from trading_session
                where is_trading_day and session_date <= :d"""),
                {"d": now().astimezone(IST).date()})).scalar()
        snap = await resolve(s, session, kind)
        keys = await E.universe(s)
        keys = keys[:limit] if limit else keys
        base = E.FEATURES
        E.FEATURES = R.FEATURES_V4                          # the v4 baseline, explicitly
        t0 = time.monotonic()
        v4 = await E.compute_snapshot(s, snap, keys)
        t4 = time.monotonic() - t0
        E.FEATURES = R.features_v5(R.FEATURES_V4)            # this process only
        try:
            t0 = time.monotonic()
            v5 = await E.compute_snapshot(s, snap, keys)
            t5 = time.monotonic() - t0
            sample = keys[::max(1, len(keys) // SAMPLE)][:SAMPLE]
            again = await E.compute_snapshot(s, snap, sample, with_context=False)
            first = await E.compute_snapshot(s, snap, sample, with_context=False)
        finally:
            E.FEATURES = base
        recount = await intimation_keys(s, snap.as_of)
        intimations = await RP.events(s, snap.as_of)
        await s.rollback()

    a, b = by_key(v5.rows), by_key(v4.rows)
    checks: dict[str, dict] = {}
    late = [k for k, r in a.items() if r["input_max_knowable_at"] is not None
            and r["input_max_knowable_at"] >= snap.as_of]
    checks["pit"] = {"pass": not late, "late": [list(k) for k in late[:10]]}
    dropped = {f for _, f in set(b) - set(a)}
    changed = [k for k in a if k in b and a[k] != b[k]]
    checks["v4_unchanged"] = {"pass": dropped == set(R.CA_TO_FEATURES) and not changed
                              and not {f for _, f in set(a) - set(b)} - R.V5_IDS,
                              "dropped": sorted(dropped),
                              "changed": [list(k) for k in changed[:10]]}
    checks["determinism"] = {"pass": by_key(again.rows) == by_key(first.rows),
                             "instruments": len(sample)}
    known = {k for k, f in a if f == "results_days_to_next"}      # the computed universe
    reader = {k for k, v in intimations.items() if any(e.kind == "INTIMATION" for e in v)}
    reader, want = reader & known, recount & known
    checks["recount"] = {"pass": want == reader, "independent": len(want),
                         "reader": len(reader), "only_independent": sorted(want - reader)[:10],
                         "only_reader": sorted(reader - want)[:10]}
    ratio, far = [], []
    for k in {k for k, _ in a}:
        pe, own = a.get((k, "pe"), {}).get("value"), a.get((k, "pe_ttm"), {}).get("value")
        if pe and own and pe > 0:
            q = own / pe
            ratio.append(q)
            if not PE_BAND[0] <= q <= PE_BAND[1]:
                far.append([k, round(pe, 2), round(own, 2)])
    share = sum(PE_BAND[0] <= q <= PE_BAND[1] for q in ratio) / len(ratio) if ratio else None
    checks["pe_vs_vendor"] = {"pass": share is not None and share >= PE_SHARE,
                              "both": len(ratio), "share_in_band": share,
                              "median_ratio": statistics.median(ratio) if ratio else None,
                              "outside": sorted(far)[:25]}
    cov: dict[str, dict[str, int]] = {}
    for (_, f), r in a.items():
        if f in R.V5_IDS:
            cov.setdefault(f, Counter())[r["reason"] or "VALUE"] += 1
    return {"session": str(session), "kind": kind, "as_of": snap.as_of.isoformat(),
            "generated_at": now().isoformat(), "instruments": len(keys),
            "active_registry": {"version": R.VERSION, "sha256": R.REGISTRY_SHA256},
            "v5_features": len(R.FEATURES_V5_NEW), "checks": checks,
            "coverage": {f: dict(c) for f, c in sorted(cov.items())},
            "seconds": {"v4": round(t4, 1), "v5": round(t5, 1)},
            "pass": all(c["pass"] for c in checks.values())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", type=_dt.date.fromisoformat)
    ap.add_argument("--kind", default="PRE_SESSION", choices=("PRE_SESSION", "PRE_OPEN"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out")
    a = ap.parse_args()
    rep = asyncio.run(canary(a.session, a.kind, a.limit))
    out = a.out or (f"../audit/evidence/features_v5_canary_{rep['session']}_{rep['kind']}.json")
    pathlib.Path(out).write_text(json.dumps(rep, indent=1, default=str) + "\n")
    print(json.dumps({k: rep[k] for k in ("session", "kind", "instruments", "pass", "seconds")}
                     | {"checks": {k: v["pass"] for k, v in rep["checks"].items()}}))
    print(f"written {out}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
