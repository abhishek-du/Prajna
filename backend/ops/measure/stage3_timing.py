"""Stage 3 run timing, measured without a production write.

    .venv/bin/python ops/measure/stage3_timing.py --session 2026-09-28 --snapshot PRE_OPEN

  compute      the real full-universe snapshot, computed READ ONLY from the
               production database at REPEATABLE READ (exactly the dry-run path)
  persist      those same rows inserted by engine.persist() into the TEST
               database, in one REPEATABLE READ transaction that is ALWAYS rolled
               back: first the insert, then the idempotent rerun (every row
               already present + the determinism compare), as a retry would do
  lookup       the instrument_id lookup persist() makes, timed on production
               (read only): the test database has no instruments, so its
               lookup there is cheaper than the real one

Nothing is committed to either database. Refuses unless the test database is a
different database from production. Writes one JSON line to
var/measure/stage3_timing.jsonl.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import sys
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.clock import now
from app.core.config import get_settings
from app.db.engine import get_sessionmaker
from app.features import engine as E
from app.features import snapshots as SN

OUT = pathlib.Path(__file__).resolve().parents[2] / "var" / "measure" / "stage3_timing.jsonl"


async def main(session: _dt.date, kind: str) -> dict:
    st = get_settings()
    prod, test = make_url(st.PRAJNA_DATABASE_URL), make_url(st.PRAJNA_TEST_DATABASE_URL or "x://")
    if not test.database or test.database == prod.database:
        raise SystemExit("REFUSED: PRAJNA_TEST_DATABASE_URL must name a separate test database")

    t0 = time.monotonic()
    async with get_sessionmaker()() as s:
        await E.consistent_read(s, read_only=True)
        snap = await SN.resolve(s, session, kind)
        keys = await E.universe(s)
        res = await E.compute_snapshot(s, snap, keys)
        tl = time.monotonic()
        await s.execute(text("select instrument_key, instrument_id from instrument "
                             "where valid_to = 'infinity'"))
        lookup = time.monotonic() - tl
        await s.rollback()
    compute = time.monotonic() - t0

    eng = create_async_engine(st.PRAJNA_TEST_DATABASE_URL, poolclass=None)
    try:
        async with eng.connect() as conn:
            conn = await conn.execution_options(isolation_level="REPEATABLE READ")
            trans = await conn.begin()
            try:
                s = AsyncSession(bind=conn)
                rid = uuid.uuid4()
                await s.execute(text("""
                    insert into ingest_run (run_id, source, stream, vendor_endpoint,
                      request_params, code_git_sha, config_sha256, argv, operator, mode, status,
                      authz_token_sha256, started_at, rows_written) values (:r, 'PRAJNA_STAGE3',
                      'features.timing', 'measure', '{}', 'measure', :c, ARRAY['measure'],
                      'measure', 'DRY_RUN', 'RUNNING', null, now(), 0)"""),
                    {"r": rid, "c": "0" * 64})
                t1 = time.monotonic()
                inserted, _ = await E.persist(s, res, rid)
                first = time.monotonic() - t1
                t2 = time.monotonic()
                again = await E.persist(s, res, rid)
                rerun = time.monotonic() - t2
            finally:
                await trans.rollback()                    # never committed
    finally:
        await eng.dispose()

    out = {"measured_at": now().isoformat(), "session": str(session), "snapshot": kind,
           "as_of": snap.as_of.isoformat(), "instruments": len(keys),
           "stats": res.stats(),
           "compute_s": round(compute, 1), "persist_insert_s": round(first, 1),
           "persist_rerun_s": round(rerun, 1), "instrument_lookup_prod_s": round(lookup, 2),
           "inserted": inserted, "present_on_rerun": again[1],
           "total_s": round(compute + first, 1), "committed": False}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as f:
        f.write(json.dumps(out) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--snapshot", choices=("PRE_SESSION", "PRE_OPEN"), required=True)
    a = ap.parse_args()
    print(json.dumps(asyncio.run(main(_dt.date.fromisoformat(a.session), a.snapshot)),
                     indent=1))
