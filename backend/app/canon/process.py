"""Stage 2 processing: Stage 1 tables -> canon_instrument + canon_coverage.

Incremental, idempotent, restartable, and read-only towards vendors.

    open run (source PRAJNA_CANON, stream canon.process)
    1  canon_instrument  every current instrument -> decision + enrichment;
                         written only where content_sha256 changed
    2  canon_coverage    per (included instrument, timeframe in scope):
                         recomputed only for pairs touched by Stage 1 runs
                         finished after the checkpoint (or everything when the
                         rules, the calendar or the approved depth changed);
                         a pair's ranges are rewritten only if they differ
    finalize             rows + checkpoint in ONE transaction; a crash rolls
                         both back, so a rerun resumes from the old checkpoint

The checkpoint lives in the outcome of the run that last finalized the stream
(ingest_watermark.last_run_id), like the Stage 1 candle checkpoints.
"""

from __future__ import annotations

import collections
import datetime as _dt
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import CANON_SOURCE
from app.canon import coverage as COV
from app.canon import universe as U
from app.canon.validate import CANON_TIMEFRAMES
from app.core.clock import IST, now
from app.db.models import CanonCoverage, CanonInstrument, IngestRun, IngestWatermark
from app.ingest.runner import IngestRunner

STREAM = "canon.process"
DEPTH_FIXED = {"1d": _dt.date(2020, 1, 1), "1h": _dt.date(2022, 1, 3),
               "15m": _dt.date(2022, 1, 3)}
ONE_MINUTE_DAYS = 183                    # D1: 1m for the last 6 months


def depth_start(tf: str, today: _dt.date) -> _dt.date:
    return DEPTH_FIXED.get(tf) or today - _dt.timedelta(days=ONE_MINUTE_DAYS)


@dataclass(slots=True)
class ProcessReport:
    committed: bool
    run_id: uuid.UUID | None = None
    status: str = "RUNNING"
    mode: str = ""                       # FULL / INCREMENTAL / NOOP
    reasons: list[str] = field(default_factory=list)
    instruments: dict[str, int] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    consumed_through: str | None = None
    seconds: float = 0.0
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


async def _prior(s: AsyncSession) -> dict[str, Any]:
    wm = await s.get(IngestWatermark, (CANON_SOURCE, STREAM))
    if wm is None or wm.last_run_id is None:
        return {}
    run = await s.get(IngestRun, wm.last_run_id)
    return ((run.request_params or {}).get("outcome") or {}) if run else {}


async def _calendar_sha(s: AsyncSession) -> str:
    rows = (await s.execute(text(
        "select session_date, is_trading_day, session_type from trading_session "
        "order by session_date"))).all()
    return hashlib.sha256(repr(rows).encode()).hexdigest()


# ── 1. canon_instrument ────────────────────────────────────────────────────
async def build_instruments(s: AsyncSession, run_id) -> tuple[list[dict], dict[int, str]]:
    rows = (await s.execute(text("""
        select i.instrument_id, i.instrument_key, i.segment, i.exchange, i.trading_symbol,
               i.name, i.isin, i.instrument_type,
               sec.sector, sec.knowable_at as sector_knowable_at, sec.id as sector_snapshot_id,
               uni.session_date as preopen_universe_session
        from instrument i
        left join lateral (
            select f.id, f.knowable_at, nullif(f.payload->>'sector', '') as sector
            from fundamental_snapshot f
            where f.instrument_key = i.instrument_key and f.statement_type = 'profile'
              and nullif(f.payload->>'sector', '') is not null
            order by f.knowable_at desc limit 1) sec on true
        left join lateral (
            select max(m.session_date) as session_date from instrument_universe_membership m
            where m.instrument_key = i.instrument_key and m.universe = 'preopen') uni on true
        where i.valid_to = 'infinity'
        order by i.instrument_id"""))).mappings().all()
    out = []
    for r in rows:
        d = U.decide(dict(r))
        row = {**dict(r), "included": d.included, "filter_reason": d.reason,
               "rules_sha256": U.RULES_SHA256}
        row["content_sha256"] = U.content_sha256(row)
        row["run_id"] = run_id
        out.append(row)
    current = dict((await s.execute(select(CanonInstrument.instrument_id,
                                           CanonInstrument.content_sha256))).all())
    return out, current


# ── 2. canon_coverage ──────────────────────────────────────────────────────
async def _stage1_inputs(s: AsyncSession, tf: str, keys: set[str] | None):
    """Bars per (key, session), quarantined per (key, session), windows per key,
    checkpoint per key, for one timeframe (optionally only some keys)."""
    kf = "" if keys is None else " and b.instrument_key = any(:keys)"
    bars: dict = collections.defaultdict(dict)
    for k, d, n in (await s.execute(text(
            f"select b.instrument_key, b.session_date, count(*) from ohlcv_bar b "  # noqa: S608
            f"where b.timeframe = :tf{kf} group by 1, 2"),
            {"tf": tf, "keys": list(keys or [])})).all():
        bars[k][d] = n
    qf = "" if keys is None else " and a.detail->>'instrument_key' = any(:keys)"
    quar: dict = collections.defaultdict(lambda: collections.defaultdict(int))
    for k, d, n in (await s.execute(text(f"""
            select a.detail->>'instrument_key', (a.detail->>'session_date')::date, count(*)
            from ingest_anomaly a join ingest_run r using (run_id)
            where a.kind = 'QUARANTINED' and r.mode = 'COMMIT' and r.status = 'COMPLETE'
              and a.detail->>'timeframe' = :tf{qf} group by 1, 2"""),       # noqa: S608
            {"tf": tf, "keys": list(keys or [])})).all():
        quar[k][d] += n
    sf = "" if keys is None else " and split_part(stream, '.', 3) = any(:keys)"
    wins: dict = collections.defaultdict(list)
    for stream, status, started, rp in (await s.execute(text(f"""
            select stream, status, started_at, request_params from ingest_run
            where stream like :p and mode = 'COMMIT' and status in ('COMPLETE', 'FAILED',
                                                       'ABORTED')
              and not request_params ? 'superseded'{sf}"""),                # noqa: S608
            {"p": f"ohlcv.{tf}.%", "keys": list(keys or [])})).all():
        key = stream.split(".", 2)[2]
        w = rp.get("window")
        if w:
            f, t = _dt.date.fromisoformat(w[0]), _dt.date.fromisoformat(w[1])
        else:                                           # intraday run: its own IST day
            f = t = started.astimezone(IST).date()
        wins[key].append(COV.Window(f, t, status, started))
    cf = "" if keys is None else " and split_part(w.stream, '.', 3) = any(:keys)"
    cps = {}
    for stream, through, cfrom in (await s.execute(text(f"""
            select w.stream, w.last_logical_date,
                   (r.request_params->'outcome'->'checkpoint'->>'covered_from')::date
            from ingest_watermark w left join ingest_run r on r.run_id = w.last_run_id
            where w.source = 'UPSTOX_REST_V3' and w.stream like :p{cf}"""),  # noqa: S608
            {"p": f"ohlcv.{tf}.%", "keys": list(keys or [])})).all():
        if through and cfrom:
            cps[stream.split(".", 2)[2]] = (cfrom, through)
    return bars, quar, wins, cps


async def build_coverage(s: AsyncSession, tf: str, sessions: list[_dt.date],
                         instruments: dict[str, int], keys: set[str] | None,
                         run_id, write: bool) -> dict[str, int]:
    bars, quar, wins, cps = await _stage1_inputs(s, tf, keys)
    targets = instruments if keys is None else {k: v for k, v in instruments.items()
                                                if k in keys}
    existing: dict = collections.defaultdict(list)
    q = select(CanonCoverage).where(CanonCoverage.timeframe == tf)
    if keys is not None:
        q = q.where(CanonCoverage.instrument_id.in_(list(targets.values())))
    for r in (await s.execute(q)).scalars():
        existing[r.instrument_id].append((r.from_date, r.to_date, r.state, r.sessions, r.bars,
                                          r.quarantined))
    stats = collections.Counter()
    new_rows: list[dict] = []
    replace: list[int] = []
    for key, iid in sorted(targets.items()):
        rs = COV.ranges(sessions, bars=bars.get(key, {}), quarantined=quar.get(key, {}),
                        windows=wins.get(key, []), checkpoint=cps.get(key))
        got = [(r.from_date, r.to_date, r.state, r.sessions, r.bars, r.quarantined) for r in rs]
        for r in rs:
            stats[f"sessions_{r.state}"] += r.sessions
        if sorted(existing.get(iid, [])) == got:
            stats["pairs_unchanged"] += 1
            continue
        stats["pairs_changed"] += 1
        stats["ranges_deleted"] += len(existing.get(iid, []))
        stats["ranges_inserted"] += len(got)
        replace.append(iid)
        new_rows += [{"instrument_id": iid, "timeframe": tf, "from_date": r.from_date,
                      "to_date": r.to_date, "state": r.state, "sessions": r.sessions,
                      "bars": r.bars, "quarantined": r.quarantined, "run_id": run_id}
                     for r in rs]
    if write and replace:
        for i in range(0, len(replace), 1000):
            await s.execute(delete(CanonCoverage).where(
                CanonCoverage.timeframe == tf,
                CanonCoverage.instrument_id.in_(replace[i:i + 1000])))
        for i in range(0, len(new_rows), 2000):
            await s.execute(insert(CanonCoverage), new_rows[i:i + 2000])
    stats["pairs"] = len(targets)
    return dict(stats)


# ── the run ────────────────────────────────────────────────────────────────
async def process(s: AsyncSession, *, commit: bool, token: str | None, full: bool = False,
                  operator: str = "cli") -> ProcessReport:
    t0 = time.monotonic()
    rep = ProcessReport(committed=commit)
    today = now().astimezone(IST).date()
    prior = await _prior(s)
    runner = IngestRunner(s, source=CANON_SOURCE, stream=STREAM,
                          vendor_endpoint="derived: Stage 1 tables (no vendor call)",
                          request_params={"full": full, "prior": prior.get("consumed_through")},
                          operator=operator)
    ctx = await runner.open(commit=commit, token=token)
    rep.run_id = ctx.run_id
    try:
        consumed = (await s.execute(text(
            "select max(finished_at) from ingest_run where stream like 'ohlcv.%' "
            "and mode = 'COMMIT' and status in ('COMPLETE','FAILED','ABORTED')"))).scalar()
        cal_sha = await _calendar_sha(s)
        depth = {tf: str(depth_start(tf, today)) for tf in CANON_TIMEFRAMES}
        # 1 instruments
        rows, current = await build_instruments(s, ctx.run_id)
        fresh = [r for r in rows if r["instrument_id"] not in current]
        changed = [r for r in rows if r["instrument_id"] in current
                   and current[r["instrument_id"]] != r["content_sha256"]]
        rep.instruments = {"current": len(rows), "included": sum(r["included"] for r in rows),
                           "inserted": len(fresh), "updated": len(changed),
                           "unchanged": len(rows) - len(fresh) - len(changed)}
        if commit:
            if fresh:
                await s.execute(insert(CanonInstrument), fresh)
            for r in changed:
                await s.execute(update(CanonInstrument).where(
                    CanonInstrument.instrument_id == r["instrument_id"]).values(**r))
        # 2 coverage: full or incremental, per timeframe
        included = {r["instrument_key"]: r["instrument_id"] for r in rows if r["included"]}
        reasons = []
        if full:
            reasons.append("requested --full")
        if not prior:
            reasons.append("no checkpoint")
        if prior and prior.get("rules_sha256") != U.RULES_SHA256:
            reasons.append("universe rules changed")
        if prior and prior.get("calendar_sha256") != cal_sha:
            reasons.append("calendar changed")
        if changed or fresh:
            reasons.append("instrument decisions changed")
        full_all = bool(reasons)
        touched: dict[str, set[str]] = collections.defaultdict(set)
        if not full_all and prior.get("consumed_through"):
            for stream, in (await s.execute(text(
                    "select distinct stream from ingest_run where stream like 'ohlcv.%' "
                    "and mode = 'COMMIT' and finished_at > :c"),
                    {"c": _dt.datetime.fromisoformat(prior["consumed_through"])})).all():
                _, tf, key = stream.split(".", 2)
                touched[tf].add(key)
        last = (await s.execute(text(
            "select max(session_date) from trading_session where is_trading_day "
            "and session_date < :t"), {"t": today})).scalar()
        cov = {}
        for tf in CANON_TIMEFRAMES:
            tf_full = full_all or (prior.get("depth") or {}).get(tf) != depth[tf]
            keys = None if tf_full else (touched.get(tf, set()) & set(included))
            if keys is not None and not keys:
                cov[tf] = {"mode": "NOOP"}
                continue
            sessions = list((await s.execute(text(
                "select session_date from trading_session where is_trading_day "
                "and session_date between :a and :b order by 1"),
                {"a": depth_start(tf, today), "b": last})).scalars())
            st = await build_coverage(s, tf, sessions, included, keys, ctx.run_id, commit)
            st["mode"] = "FULL" if keys is None else "INCREMENTAL"
            cov[tf] = st
        rep.coverage = cov
        rep.reasons = reasons
        modes = {v["mode"] for v in cov.values()}
        rep.mode = "FULL" if "FULL" in modes else ("INCREMENTAL" if "INCREMENTAL" in modes
                                                    else "NOOP")
        rep.consumed_through = consumed.isoformat() if consumed else None
        rep.seconds = round(time.monotonic() - t0, 2)
        ctx.logical_date = last
        written = rep.instruments["inserted"] + rep.instruments["updated"] + sum(
            v.get("ranges_inserted", 0) for v in cov.values())
        await runner.finalize(rows_written=written if commit else 0, outcome={
            "consumed_through": rep.consumed_through, "rules_sha256": U.RULES_SHA256,
            "calendar_sha256": cal_sha, "depth": depth, "mode": rep.mode,
            "reasons": reasons, "instruments": rep.instruments, "coverage": cov,
            "seconds": rep.seconds})
        rep.status = "COMPLETE"
        return rep
    except BaseException as e:
        rep.status, rep.error = "FAILED", f"{type(e).__name__}: {e}"[:500]
        await runner.fail(rep.error)
        raise
