"""Historical Stage 3 replay into training_feature_value (never feature_value).

For each trading session and snapshot of a dataset:
  1. the snapshot instant from the trading calendar (snapshots.resolve);
  2. ONE REPEATABLE READ transaction; for AS_IF_LIVE the search_path puts the
     train_asif shadow views first (SET LOCAL: this transaction only);
  3. the universe AS OF the snapshot: canonical NSE_EQ instruments (including
     ones since removed from the master) with a daily bar knowable before as_of
     in the 15 days before the session, plus the NSE indices - never today's
     active list as such;
  4. engine.compute_snapshot, unchanged - the production feature definitions;
  5. the missingness contract (availability.status);
  6. bounded inserts (<= PARAM_BUDGET binds per statement, on conflict do
     nothing), a read-back that must equal the computed rows, and the
     training_session_done marker, all in the same transaction.
A session with a done marker is skipped (resume); a rerun inserts nothing.
No lock, token, kill switch or stage3_event is involved: nothing production is
written, and PRAJNA_STAGE3_BACKFILL_ENABLED stays false.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import time
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.features import engine as E
from app.features import news_features as NF
from app.features import registry as R
from app.features import snapshots as SN
from app.training import availability as A
from app.training import policy as P

COLUMNS = ("dataset_version", "session_date", "snapshot", "as_of", "scope", "instrument_key",
           "feature_id", "feature_version", "value", "status", "reason", "inputs_sha256",
           "input_max_knowable_at", "run_id")
UNIVERSE_DAYS = 15


async def wait_outside(window: str) -> None:
    """Sleep while the IST clock is inside `window` ("HH:MM-HH:MM"): the replay never
    competes with the live Stage 3 snapshots (09:00:30 and 09:22 IST)."""
    import asyncio

    from app.core.clock import IST
    if not window:
        return
    a, b = (_dt.time.fromisoformat(x) for x in window.split("-"))
    while a <= now().astimezone(IST).time() < b:  # noqa: ASYNC110 - a clock window
        await asyncio.sleep(60)


class ReplayMismatch(RuntimeError):
    """Stored training rows differ from a recompute: never overwritten."""


async def universe(s: AsyncSession, snap: SN.Snapshot, limit: int | None = None
                   ) -> tuple[list[str], set[str]]:
    """(keys, stale): stale = no knowable bar for the previous session."""
    rows = (await s.execute(text("""
        select ci.instrument_key, max(b.market_date)
        from canon_instrument ci
        join canon_market_bar b on b.instrument_key = ci.instrument_key and b.timeframe = '1d'
          and b.market_date < :d and b.market_date >= :lo and b.knowable_at < :a
        where ci.included and ci.segment in ('NSE_EQ', 'NSE_INDEX')
        group by 1 order by 1"""),
        {"d": snap.session_date, "lo": snap.session_date - _dt.timedelta(days=UNIVERSE_DAYS),
         "a": snap.as_of})).all()
    keys = [k for k, _ in rows]
    if limit:
        idx = [k for k in keys if k.startswith("NSE_INDEX|")]
        eq = sorted((k for k in keys if k.startswith("NSE_EQ|")),
                    key=lambda k: hashlib.md5(k.encode()).hexdigest())[:limit]  # noqa: S324
        keys = sorted(idx + eq)
    stale = {k for k, d in rows if d != snap.previous_session and k in set(keys)}
    return keys, stale


def _families(feature_id: str) -> set[str]:
    return {A.FAMILY[i] for i in R.BY_ID[feature_id].inputs if i in A.FAMILY}


class BuildContractError(RuntimeError):
    """A build that would mix feature semantics inside one dataset version: refused."""


def code_version() -> dict[str, Any]:
    """The git commit the build runs from, and whether the working tree is dirty."""
    import pathlib
    import subprocess
    root = pathlib.Path(__file__).resolve().parents[3]
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S603,S607
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(root), "status", "--porcelain"],  # noqa: S603,S607
                                    capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        sha, dirty = "unknown", True
    return {"git_sha": sha, "dirty": dirty}


async def check_contract(s: AsyncSession, ds: P.Dataset) -> None:
    """Refuse a build that is not reproducible under one set of feature semantics:
    a frozen version, a registry other than the version's declared one, or a version
    whose existing (non-superseded) runs carry another registry hash."""
    if ds.version in P.FROZEN:
        raise BuildContractError(f"{ds.version} is frozen (built under earlier code); "
                                 "build a new dataset version instead")
    if R.VERSION != ds.registry_version:
        raise BuildContractError(f"{ds.version} must be built with {ds.registry_version}; "
                                 f"the active registry is {R.VERSION}")
    other = (await s.execute(text("""select distinct registry_sha256 from training_dataset_run
        where dataset_version = :v and status <> 'SUPERSEDED' and registry_sha256 <> :h"""),
        {"v": ds.version, "h": R.REGISTRY_SHA256})).scalars().all()
    if other:
        raise BuildContractError(f"{ds.version} already holds rows of registry "
                                 f"{other[0][:12]}...; refusing to add {R.REGISTRY_SHA256[:12]}...")


async def open_run(s: AsyncSession, ds: P.Dataset, start: _dt.date, end: _dt.date,
                   limit: int | None, operator: str, *,
                   code: dict[str, Any] | None = None) -> uuid.UUID:
    await check_contract(s, ds)
    params = await P.ensure_params(s) if ds.policy == P.ASIF else {}
    code = code or code_version()
    contract = {"policy": ds.policy, "search_path": ds.search_path,
                "snapshots": list(ds.snapshots), "registry_version": R.VERSION,
                "registry_sha256": R.REGISTRY_SHA256, "code_dirty": code["dirty"],
                "universe_days": UNIVERSE_DAYS}
    run_id = uuid.uuid4()
    await s.execute(text("""insert into training_dataset_run (run_id, dataset_version,
        knowability_policy, policy_params, registry_version, registry_sha256, feature_count,
        start_date, end_date, snapshots, instrument_limit, status, operator, started_at,
        code_git_sha, build_contract)
        values (:r, :v, :p, cast(:pp as jsonb), :rv, :rh, :fc, :a, :b, :sn, :lim, 'RUNNING',
                :op, :at, :git, cast(:bc as jsonb))"""),
        {"r": run_id, "v": ds.version, "p": ds.policy, "pp": json.dumps(params),
         "rv": R.VERSION, "rh": R.REGISTRY_SHA256, "fc": len(R.FEATURES), "a": start, "b": end,
         "sn": list(ds.snapshots), "lim": limit, "op": operator, "at": now(),
         "git": code["git_sha"], "bc": json.dumps(contract)})
    await s.commit()
    return run_id


async def finish_run(s: AsyncSession, run_id: uuid.UUID, status: str,
                     error: str | None = None) -> None:
    await s.rollback()
    await s.execute(text("""update training_dataset_run set status = :st, error = :e,
        completed_at = :at,
        sessions_done = (select count(*) from training_session_done where run_id = :r),
        row_count = (select coalesce(sum(rows), 0) from training_session_done where run_id = :r)
        where run_id = :r"""), {"st": status, "e": error, "at": now(), "r": run_id})
    await s.commit()


async def stale_runs(s: AsyncSession, older_than: _dt.timedelta) -> list[dict[str, Any]]:
    """Read-only: RUNNING runs started more than `older_than` ago (a killed worker leaves
    its run RUNNING; its done snapshots are kept and a rerun resumes after them)."""
    rows = (await s.execute(text("""select r.run_id, r.dataset_version, r.started_at,
          r.operator, (select count(*) from training_session_done d where d.run_id = r.run_id)
        from training_dataset_run r where r.status = 'RUNNING' and r.started_at < :t
        order by r.started_at"""), {"t": now() - older_than})).all()
    return [{"run_id": str(r[0]), "dataset_version": r[1], "started_at": r[2].isoformat(),
             "operator": r[3], "snapshots_done": r[4]} for r in rows]


async def reap_runs(s: AsyncSession, older_than: _dt.timedelta) -> list[dict[str, Any]]:
    """Mark stale RUNNING runs FAILED (their done snapshots stay valid: every snapshot is
    committed with its marker in one transaction, so nothing partial exists)."""
    stale = await stale_runs(s, older_than)
    for r in stale:
        await finish_run(s, uuid.UUID(r["run_id"]), "FAILED",
                         f"reaped: still RUNNING after {older_than} (worker gone); "
                         f"{r['snapshots_done']} done snapshots kept")
    return stale


async def completeness(s: AsyncSession, ds: P.Dataset, start: _dt.date, end: _dt.date
                       ) -> dict[str, Any]:
    """Read-only: calendar snapshots of [start, end] vs done markers of the version."""
    want = {(x.session_date, x.kind) for x in await snapshots(s, ds, start, end)}
    done = {(r[0], r[1]) for r in (await s.execute(text("""select session_date, snapshot
        from training_session_done where dataset_version = :v"""), {"v": ds.version})).all()}
    missing = sorted(want - done)
    return {"dataset_version": ds.version, "expected": len(want), "done": len(want & done),
            "missing": [f"{d} {k}" for d, k in missing[:50]], "complete": not missing}


def _rows_sha(rows: list[dict[str, Any]]) -> str:
    body = sorted((r["instrument_key"], r["feature_id"], r["value"], r["status"], r["reason"],
                   r["inputs_sha256"]) for r in rows)
    return hashlib.sha256(json.dumps(body, default=str).encode()).hexdigest()


async def replay_snapshot(s: AsyncSession, ds: P.Dataset, snap: SN.Snapshot, run_id: uuid.UUID,
                          *, limit: int | None = None, keys: list[str] | None = None
                          ) -> dict[str, Any]:
    """One snapshot, one transaction. Returns its stats ({'skipped': ...} if done)."""
    done = (await s.execute(text("""select rows from training_session_done
        where dataset_version = :v and session_date = :d and snapshot = :k"""),
        {"v": ds.version, "d": snap.session_date, "k": snap.kind})).scalar()
    if done is not None:
        await s.rollback()
        return {"session": str(snap.session_date), "snapshot": snap.kind, "skipped": "done",
                "rows": done}
    await s.rollback()
    t0 = time.monotonic()
    await E.consistent_read(s, read_only=False)
    if ds.search_path:
        await s.execute(text(f"set local search_path = {ds.search_path}"))
    u_keys, stale = await universe(s, snap, limit)
    keys = keys if keys is not None else u_keys
    res = await E.compute_snapshot(s, snap, keys)
    avail = await A.available(s, snap.as_of)
    news_state = await NF.coverage_state(s, snap.as_of)
    t_compute = time.monotonic() - t0
    values = []
    for r in res.rows:
        fam = _families(r.feature_id)
        st = A.status(r.reason, fam, avail, bar_stale=r.instrument_key in stale,
                      news_stale=news_state == "STALE")
        values.append({"dataset_version": ds.version, "session_date": snap.session_date,
                       "snapshot": snap.kind, "as_of": snap.as_of, "scope": r.scope,
                       "instrument_key": r.instrument_key, "feature_id": r.feature_id,
                       "feature_version": str(R.BY_ID[r.feature_id].version),
                       "value": r.value if st == A.VALID else None, "status": st,
                       "reason": r.reason, "inputs_sha256": r.inputs_sha256,
                       "input_max_knowable_at": r.input_max_knowable_at, "run_id": run_id})
    inserted = 0
    step = E.batch_rows(len(COLUMNS))
    cols = ", ".join(COLUMNS)
    for i in range(0, len(values), step):
        chunk = values[i:i + step]
        binds, params = [], {}
        for j, v in enumerate(chunk):
            binds.append("(" + ", ".join(f":{c}_{j}" for c in COLUMNS) + ")")
            params.update({f"{c}_{j}": v[c] for c in COLUMNS})
        inserted += (await s.execute(text(
            f"insert into public.training_feature_value ({cols}) values {', '.join(binds)} "  # noqa: S608
            "on conflict on constraint uq_training_feature_value do nothing"), params)).rowcount
    stored = {(r[0], r[1]): (r[2], r[3], r[4]) for r in (await s.execute(text("""
        select instrument_key, feature_id, value, status, inputs_sha256
        from public.training_feature_value
        where dataset_version = :v and session_date = :d and snapshot = :k"""),
        {"v": ds.version, "d": snap.session_date, "k": snap.kind})).all()}
    bad = [f"{v['instrument_key']}:{v['feature_id']}" for v in values
           if stored.get((v["instrument_key"], v["feature_id"])) != (
               v["value"], v["status"], v["inputs_sha256"])]
    if bad or len(stored) != len(values):
        raise ReplayMismatch(f"{len(bad)} stored rows differ, {len(stored)} stored vs "
                             f"{len(values)} computed (first: {bad[:3]}); nothing overwritten")
    stats = {"seconds_compute": round(t_compute, 1), "seconds_total": 0.0,
             "status": dict(Counter(v["status"] for v in values)),
             "refused_bars": dict(res.refused_bars), "available": avail,
             "news_coverage": news_state, "stale_instruments": len(stale)}
    stats["seconds_total"] = round(time.monotonic() - t0, 1)
    await s.execute(text("""insert into public.training_session_done (dataset_version,
        session_date, snapshot, run_id, as_of, rows, instruments, rows_sha256, stats, done_at)
        values (:v, :d, :k, :r, :a, :n, :i, :h, cast(:st as jsonb), :at)"""),
        {"v": ds.version, "d": snap.session_date, "k": snap.kind, "r": run_id, "a": snap.as_of,
         "n": len(values), "i": len(keys), "h": _rows_sha(values), "st": json.dumps(stats),
         "at": now()})
    if ds.search_path:          # this transaction only, also when joined to an outer one
        await s.execute(text("set local search_path to default"))
    await s.commit()
    return {"session": str(snap.session_date), "snapshot": snap.kind, "rows": len(values),
            "inserted": inserted, "instruments": len(keys), **stats}


async def snapshots(s: AsyncSession, ds: P.Dataset, start: _dt.date, end: _dt.date
                    ) -> list[SN.Snapshot]:
    out = []
    for d in await SN.sessions_between(s, start, end):
        for k in ds.snapshots:
            try:
                out.append(await SN.resolve(s, d, k))
            except SN.NoSnapshot:
                continue
    await s.rollback()
    return out
