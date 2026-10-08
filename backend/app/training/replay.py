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


async def open_run(s: AsyncSession, ds: P.Dataset, start: _dt.date, end: _dt.date,
                   limit: int | None, operator: str) -> uuid.UUID:
    params = await P.ensure_params(s) if ds.policy == P.ASIF else {}
    run_id = uuid.uuid4()
    await s.execute(text("""insert into training_dataset_run (run_id, dataset_version,
        knowability_policy, policy_params, registry_version, registry_sha256, feature_count,
        start_date, end_date, snapshots, instrument_limit, status, operator, started_at)
        values (:r, :v, :p, cast(:pp as jsonb), :rv, :rh, :fc, :a, :b, :sn, :lim, 'RUNNING',
                :op, :at)"""),
        {"r": run_id, "v": ds.version, "p": ds.policy, "pp": json.dumps(params),
         "rv": R.VERSION, "rh": R.REGISTRY_SHA256, "fc": len(R.FEATURES), "a": start, "b": end,
         "sn": list(ds.snapshots), "lim": limit, "op": operator, "at": now()})
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
