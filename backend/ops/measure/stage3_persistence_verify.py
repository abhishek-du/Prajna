"""Full-universe Stage 3 persistence verification. NO PRODUCTION WRITE.

    .venv/bin/python ops/measure/stage3_persistence_verify.py --session 2026-09-28

The real snapshots are COMPUTED from the production database READ ONLY (the
dry-run path: REPEATABLE READ, READ ONLY) and PERSISTED with the production code
(engine.persist, engine.consistent_read) into an ISOLATED SCHEMA of the TEST
database: `stage3_verify_<pid>` holds feature_value and ingest_run replicated
from prajna_test's public schema with the same constraint names, CHECKs,
indexes and append-only trigger. Connections put that schema first on their
search_path, so the unqualified SQL of persist() writes there. Real COMMITs are
made (unlike a rolled-back test), then the schema is dropped: public.feature_value
of the test database is untouched (checked before and after). The role cannot
CREATE DATABASE, hence a schema.

Steps (each recorded):
  A  PRE_SESSION: persist in one REPEATABLE READ transaction; a second connection
     sees 0 rows before COMMIT and all after (atomic visibility); every INSERT's
     bind-parameter count captured
  B  rerun of the same rows: 0 inserted, all present, count unchanged
  C  a second, independent compute from production persisted: 0 inserted
     (a real recompute agrees with every stored value)
  D  one value changed: DeterminismMismatch, rolled back, stored value unchanged
  E  PRE_OPEN with a failure injected after its first INSERT batch: rolled back,
     0 PRE_OPEN rows remain
  F  PRE_OPEN persisted and committed
Writes audit/evidence/stage3_persistence_full_universe.json (repository root).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import pathlib
import sys
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.clock import now
from app.core.config import BACKEND_ROOT, get_settings
from app.db.engine import get_sessionmaker
from app.features import engine as E
from app.features import snapshots as SN
from app.features.registry import REGISTRY_SHA256

OUT = BACKEND_ROOT.parent / "audit" / "evidence" / "stage3_persistence_full_universe.json"
S = f"stage3_verify_{os.getpid()}"
TABLES = ("ingest_run", "feature_value")          # FK order
UQ = "instrument_key, session_date, snapshot, feature_id"


class InjectedFailure(RuntimeError):
    pass


async def compute(session: _dt.date, kind: str) -> tuple[E.SnapshotResult, float]:
    t0 = time.monotonic()
    async with get_sessionmaker()() as s:
        await E.consistent_read(s, read_only=True)
        snap = await SN.resolve(s, session, kind)
        res = await E.compute_snapshot(s, snap, await E.universe(s))
        await s.rollback()
    return res, time.monotonic() - t0


async def replicate(c) -> list[str]:
    """public.<t> -> S.<t>: columns, defaults (own sequence), constraints (same names),
    indexes and triggers. Returns the DDL executed."""
    ddl = [f"create schema {S}", f"set search_path to {S}, public"]
    for t in TABLES:
        ddl.append(f"create table {S}.{t} (like public.{t} including defaults "
                   "including generated including identity)")
        for col, _ in (await c.execute(text(
                "select column_name, column_default from information_schema.columns where "
                "table_schema = 'public' and table_name = :t and column_default like "
                "'nextval(%'"), {"t": t})).all():
            ddl += [f"create sequence {S}.{t}_{col}_seq",
                    f"alter table {S}.{t} alter column {col} set default "
                    f"nextval('{S}.{t}_{col}_seq')"]
        cons = (await c.execute(text(
            "select conname, contype, pg_get_constraintdef(oid) from pg_constraint where "
            "conrelid = cast(:t as regclass) and contype in ('p', 'u', 'c', 'f') "
            "order by contype = 'f', conname"), {"t": f"public.{t}"})).all()
        # FK targets resolve through the search_path: ingest_run -> the copy,
        # instrument -> public.instrument
        ddl += [f"alter table {S}.{t} add constraint {n} {d}" for n, _, d in cons]
        names = {n for n, _, _ in cons}
        ddl += [d.replace(f" ON public.{t} ", f" ON {S}.{t} ") for n, d in (await c.execute(text(
            "select indexname, indexdef from pg_indexes where schemaname = 'public' and "
            "tablename = :t"), {"t": t})).all() if n not in names]
        ddl += [d.replace(f" ON public.{t} ", f" ON {S}.{t} ") for (d,) in (await c.execute(text(
            "select pg_get_triggerdef(oid) from pg_trigger where not tgisinternal and "
            "tgrelid = cast(:t as regclass)"), {"t": f"public.{t}"})).all()]
    for d in ddl:
        await c.execute(text(d))
    return ddl


async def count(eng, snapshot: str | None = None, schema: str = S) -> int:
    async with eng.connect() as c:                        # a separate connection
        return (await c.execute(text(
            f"select count(*) from {schema}.feature_value where "      # noqa: S608
            "cast(:k as text) is null or snapshot = :k"), {"k": snapshot})).scalar()


async def main(session: _dt.date) -> dict:
    st = get_settings()
    prod, test = make_url(st.PRAJNA_DATABASE_URL), make_url(st.PRAJNA_TEST_DATABASE_URL or "x://")
    if not test.database or test.database == prod.database or test.database == "prajna":
        raise SystemExit("REFUSED: PRAJNA_TEST_DATABASE_URL must name a separate test database")
    ev: dict = {"generated_at": now().isoformat(), "production_writes": 0,
                "compute_database": f"{prod.database} (READ ONLY, REPEATABLE READ)",
                "persist_database": f"{test.database}, isolated schema {S} (dropped afterwards)",
                "registry_sha256": REGISTRY_SHA256, "session": str(session),
                "asyncpg_max_bind_params": E.ASYNCPG_MAX_BIND_PARAMS,
                "param_budget": E.PARAM_BUDGET, "steps": {}}

    res_ps, t_ps = await compute(session, "PRE_SESSION")
    res_po, t_po = await compute(session, "PRE_OPEN")
    for k, r, t in (("PRE_SESSION", res_ps, t_ps), ("PRE_OPEN", res_po, t_po)):
        ev[f"compute_{k}"] = {"as_of": r.snapshot.as_of.isoformat(), "seconds": round(t, 1),
                              **r.stats()}

    admin = create_async_engine(st.PRAJNA_TEST_DATABASE_URL, poolclass=None)
    eng = create_async_engine(st.PRAJNA_TEST_DATABASE_URL, poolclass=None, connect_args={
        "server_settings": {"search_path": f"{S},public"}})
    stmts: list[dict] = []
    fail_after: dict = {"n": None}

    def before(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().lower().startswith("insert into feature_value"):
            stmts.append({"params": len(params), "rows": len(params) // 15})

    def after(conn, cursor, statement, params, context, executemany):
        if (fail_after["n"] is not None and statement.lstrip().lower()
                .startswith("insert into feature_value") and len(stmts) >= fail_after["n"]):
            raise InjectedFailure(f"injected after INSERT batch {len(stmts)}")

    event.listen(eng.sync_engine, "before_cursor_execute", before)
    event.listen(eng.sync_engine, "after_cursor_execute", after)
    try:
        ev["public_feature_value_before"] = await count(admin, schema="public")
        async with admin.begin() as c:
            ev["replicated_ddl"] = await replicate(c)
        rid = uuid.uuid4()
        async with eng.begin() as c:
            await c.execute(text("""insert into ingest_run (run_id, source, stream,
                vendor_endpoint, request_params, code_git_sha, config_sha256, argv, operator,
                mode, status, authz_token_sha256, started_at, rows_written) values (:r,
                'PRAJNA_STAGE3', 'features.verify', 'verification', '{}', 'verify', :c,
                ARRAY['verify'], 'verify', 'DRY_RUN', 'RUNNING', null, now(), 0)"""),
                {"r": rid, "c": "0" * 64})

        async def persist(res) -> dict:
            stmts.clear()
            out: dict = {"rows_offered": len(res.rows)}
            async with AsyncSession(eng) as s:
                out["isolation"] = await E.consistent_read(s, read_only=False)
                t0 = time.monotonic()
                try:
                    ins, present = await E.persist(s, res, rid)
                except BaseException as e:
                    await s.rollback()
                    out.update(outcome="ROLLED_BACK", error=f"{type(e).__name__}: {e}"[:300],
                               insert_statements_before_failure=len(stmts))
                    return out
                out["persist_s"] = round(time.monotonic() - t0, 1)
                out["visible_to_other_connection_before_commit"] = await count(
                    eng, res.snapshot.kind)
                t1 = time.monotonic()
                await s.commit()
                out.update(commit_s=round(time.monotonic() - t1, 2), outcome="COMMITTED",
                           inserted=ins, already_present=present,
                           insert_statements=len(stmts),
                           params_per_statement=sorted({x["params"] for x in stmts}),
                           max_params_in_one_statement=max((x["params"] for x in stmts),
                                                           default=0),
                           rows_per_batch_max=max((x["rows"] for x in stmts), default=0))
            out["committed_rows_for_snapshot"] = await count(eng, res.snapshot.kind)
            return out

        ev["steps"]["A_pre_session_first_persist"] = await persist(res_ps)
        ev["steps"]["B_rerun_same_rows"] = await persist(res_ps)
        res_ps2, t2 = await compute(session, "PRE_SESSION")
        ev["steps"]["C_independent_recompute_persisted"] = {
            "compute_s": round(t2, 1), **await persist(res_ps2)}
        # D: one value changed -> DeterminismMismatch, nothing overwritten
        i = next(i for i, r in enumerate(res_ps.rows) if r.value is not None)
        r0 = res_ps.rows[i]
        tampered = E.SnapshotResult(res_ps.snapshot)
        tampered.rows = [*res_ps.rows[:i], E.FeatureRow(r0.scope, r0.instrument_key,
                         r0.feature_id, r0.value * 2 + 1, None, r0.inputs_sha256,
                         r0.input_max_knowable_at), *res_ps.rows[i + 1:]]
        d = await persist(tampered)
        async with eng.connect() as c:
            stored = (await c.execute(text("""select value from feature_value where
                instrument_key = :k and feature_id = :f and snapshot = 'PRE_SESSION'"""),
                {"k": r0.instrument_key, "f": r0.feature_id})).scalar()
        d.update(row=f"{r0.instrument_key}:{r0.feature_id}", original=r0.value,
                 offered=r0.value * 2 + 1, stored_after=float(stored),
                 rows_after=await count(eng, "PRE_SESSION"))
        ev["steps"]["D_determinism_mismatch"] = d
        # E: failure after the first INSERT batch of PRE_OPEN
        fail_after["n"] = 1
        e_ = await persist(res_po)
        fail_after["n"] = None
        e_["pre_open_rows_after_rollback"] = await count(eng, "PRE_OPEN")
        ev["steps"]["E_failure_after_first_batch"] = e_
        ev["steps"]["F_pre_open_persist"] = await persist(res_po)
        async with eng.connect() as c:
            ev["final"] = {
                "rows_total": await count(eng),
                "duplicate_keys": (await c.execute(text(
                    f"select count(*) from (select 1 from feature_value group by {UQ} "  # noqa: S608
                    "having count(*) > 1) x"))).scalar(),
                "by_snapshot_values_and_reasons": {f"{k}/{w or 'VALUE'}": n for k, w, n in (
                    await c.execute(text("select snapshot, reason, count(*) from feature_value "
                                         "group by 1, 2 order by 1, 2"))).all()},
                "pit_violations": (await c.execute(text(
                    "select count(*) from feature_value where input_max_knowable_at >= as_of"
                ))).scalar(),
                "append_only_update_refused": None}
            try:
                async with eng.begin() as c2:
                    await c2.execute(text("update feature_value set value = value where "
                                          "id = (select min(id) from feature_value)"))
                ev["final"]["append_only_update_refused"] = False
            except Exception as ex:                       # the trigger refuses it
                ev["final"]["append_only_update_refused"] = type(ex).__name__
    finally:
        event.remove(eng.sync_engine, "before_cursor_execute", before)
        event.remove(eng.sync_engine, "after_cursor_execute", after)
        await eng.dispose()
        async with admin.begin() as c:
            await c.execute(text(f"drop schema if exists {S} cascade"))
            ev["schema_dropped"] = not (await c.execute(text(
                "select 1 from pg_namespace where nspname = :s"), {"s": S})).first()
        ev["public_feature_value_after"] = await count(admin, schema="public")
        await admin.dispose()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ev, indent=1, default=str))
    return ev


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    a = ap.parse_args()
    rep = asyncio.run(main(_dt.date.fromisoformat(a.session)))
    print(json.dumps({k: v for k, v in rep.items() if k != "replicated_ddl"}, indent=1,
                     default=str))
