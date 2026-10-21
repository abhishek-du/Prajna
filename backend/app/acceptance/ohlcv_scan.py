"""Stage 1 gate: the ohlcv_bar checks in ONE pass, full or incremental (decision GATE-INCR,
user 2026-10-21). Read only, except `checkpoint()`.

The gate's heavy ohlcv_bar checks - provenance (B), point in time (C), the daily same-day
and intraday end-plus-margin look-ahead counts (X) and the per-instrument bar counts of
the candle-depth evidence (F-J) - each scanned the whole table (500 M rows, ~90 s each on
2026-10-21), so the Stage 3 PRE_SESSION run (whose lock evaluates the gate) finished at
09:20-09:28. Same checks, same numbers, computed as

    totals = the latest checkpoint (rows of every run finished up to its cut)
           + the rows of runs finished after the cut or still running (via ix_ohlcv_bar_run_id)

Sound because ohlcv_bar is append-only (trigger, migration 0025; no code updates or deletes
it), run_id / payload_sha256 are NOT NULL foreign keys (ON DELETE RESTRICT), and a finished
ingest_run row does not change. A weekly FULL checkpoint (Saturday) rescans everything and
must equal the incremental totals, else the job fails (an alert). Without a checkpoint the
gate scans the whole table as before.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import timing as T

COUNTS = ("rows", "bad_run", "no_payload", "no_basis", "pit", "la_daily", "la_intraday")
TFS = ("1d", "1m", "5m", "15m", "1h")

_AGG = """
select count(*) as rows,
  count(*) filter (where r.run_id is null or r.status <> 'COMPLETE' or r.mode <> 'COMMIT')
    as bad_run,
  count(*) filter (where p.payload_sha256 is null) as no_payload,
  count(*) filter (where b.knowable_at_basis is null or b.knowable_at_basis = '') as no_basis,
  count(*) filter (where b.knowable_at > b.fetched_at) as pit,
  count(*) filter (where b.timeframe = '1d' and i.segment not like 'GLOBAL%'
    and (b.fetched_at at time zone 'Asia/Kolkata')::date <= b.session_date) as la_daily,
  count(*) filter (where b.timeframe in ('1m','5m','15m','1h') and b.bar_start_utc + case
      b.timeframe when '1m' then interval '1 minute' when '5m' then interval '5 minutes'
      when '15m' then interval '15 minutes' else interval '1 hour' end
    + make_interval(secs => case when b.timeframe in ('1m','15m','1h') then
        case when b.fetched_at < cast(:eff as timestamptz) then cast(:prev as float8)
        else cast(:cur as float8) end else cast(:oos as float8) end)
    > b.fetched_at) as la_intraday
from ohlcv_bar b
left join ingest_run r on r.run_id = b.run_id
left join raw_payload p on p.payload_sha256 = b.payload_sha256
join instrument i on i.instrument_id = b.instrument_id
"""
_BARS = """select b.timeframe, b.instrument_key, count(*) from ohlcv_bar b
  left join ingest_run r on r.run_id = b.run_id"""


def _where(after: _dt.datetime | None, upto: _dt.datetime | None) -> tuple[str, dict]:
    """Rows of runs finished in (after, upto]; upto None also includes running runs."""
    c, p = [], {}
    if after is not None:
        c.append("(r.finished_at > :after or r.finished_at is null)")
        p["after"] = after
    if upto is not None:
        c.append("r.finished_at <= :upto")
        p["upto"] = upto
    if after is not None:          # select the few new runs first, then their bars by index
        c.append("b.run_id in (select run_id from ingest_run where finished_at > :after "
                 "or finished_at is null)")
    return (" where " + " and ".join(c)) if c else "", p


async def scan(s: AsyncSession, *, after: _dt.datetime | None = None,
               upto: _dt.datetime | None = None) -> dict[str, Any]:
    w, p = _where(after, upto)
    r = (await s.execute(text(_AGG + w), {
        "eff": T.MARGIN_EFFECTIVE_FROM, "prev": T.PREVIOUS_MARGIN_S,
        "cur": T.COMPLETION_MARGIN_S["1m"], "oos": T.OUT_OF_SCOPE_MARGIN_S["5m"], **p})).one()
    bars: dict[str, dict[str, int]] = {tf: {} for tf in TFS}
    for tf, k, n in (await s.execute(text(_BARS + w + " group by 1, 2"), p)).all():
        bars.setdefault(tf, {})[k] = int(n)
    return {"counts": {c: int(getattr(r, c)) for c in COUNTS}, "bars": bars}


def add(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    bars = {tf: dict(a["bars"].get(tf, {})) for tf in set(a["bars"]) | set(b["bars"])}
    for tf, m in b["bars"].items():
        for k, n in m.items():
            bars[tf][k] = bars[tf].get(k, 0) + n
    return {"counts": {c: a["counts"][c] + b["counts"][c] for c in COUNTS}, "bars": bars}


async def latest(s: AsyncSession, scope: str = "ohlcv_bar") -> dict[str, Any] | None:
    r = (await s.execute(text("""select id, method, through_finished_at, counts, bars,
        created_at from gate_scan_checkpoint where scope = :sc
        order by id desc limit 1"""), {"sc": scope})).first()
    if r is None:
        return None
    return {"id": r.id, "method": r.method, "through": r.through_finished_at,
            "counts": r.counts, "bars": r.bars, "created_at": r.created_at}


async def totals(s: AsyncSession) -> dict[str, Any]:
    """What the gate uses: checkpoint + live delta, or a full live scan without one."""
    cp = await latest(s)
    if cp is None:
        out = await scan(s)
        out["method"] = "FULL_LIVE (no checkpoint)"
        return out
    out = add(cp, await scan(s, after=cp["through"]))
    out["method"] = (f"CHECKPOINT {cp['method']} #{cp['id']} through "
                     f"{cp['through'].isoformat()} + live delta")
    return out


async def checkpoint(s: AsyncSession, *, full: bool, commit: bool = False,
                     token: str | None = None) -> dict[str, Any]:
    """A new checkpoint at the cut = the latest finished run. FULL rescans everything and
    must equal the previous checkpoint + the increment (else `consistent` False)."""
    from app.core.authz import authorize_write
    from app.core.clock import now
    from app.training.replay import code_version

    fp = authorize_write(token) if commit else None
    conn = await s.connection()
    if not conn.in_nested_transaction():        # one snapshot for the cut and both scans
        await s.execute(text("set transaction isolation level repeatable read"))
    cut = (await s.execute(text("""select max(finished_at) from ingest_run
        where finished_at is not null"""))).scalar()
    prev = await latest(s)
    out: dict[str, Any] = {"cut": cut.isoformat() if cut else None, "full": full,
                           "previous": prev["id"] if prev else None}
    inc = None
    if prev is not None:
        inc = add(prev, await scan(s, after=prev["through"], upto=cut))
    if full or prev is None:
        cur = await scan(s, upto=cut)
        out["consistent"] = None if inc is None else (cur == {k: inc[k] for k in cur})
    else:
        cur = {k: inc[k] for k in ("counts", "bars")}
        out["consistent"] = None
    out["counts"] = cur["counts"]
    # the raw archive (criterion T): FULL rehashes every payload, INCREMENTAL those fetched
    # after the previous archive checkpoint; mismatches accumulate
    from app.acceptance.stage1 import verify_archive
    aprev = await latest(s, "raw_archive")
    afull = full or aprev is None
    arch = await verify_archive(s, since=None if afull else aprev["through"])
    acut = cut                       # the same run cut as the ohlcv_bar counts
    amis = arch["mismatched"] + (0 if afull else int(aprev["counts"].get("mismatched", 0)))
    out["archive"] = {**arch, "mismatched_total": amis, "full": afull}
    if commit:
        if acut is not None:
            await s.execute(text("""insert into gate_scan_checkpoint (scope, method,
                through_finished_at, counts, bars, consistent, previous_id, created_at,
                code_git_sha, authz_token_sha256) values ('raw_archive', :m, :t,
                cast(:c as jsonb), '{}'::jsonb, null, :pid, :at, :g, :fp)"""),
                {"m": "FULL" if afull else "INCREMENTAL", "t": acut,
                 "c": json.dumps({"mismatched": amis, "missing": arch["missing"],
                                  "hashed": arch["file_payloads_verified"]
                                  + arch["frame_payloads_verified"]}),
                 "pid": aprev["id"] if aprev else None, "at": now(),
                 "g": code_version()["git_sha"], "fp": fp})
        await s.execute(text("""insert into gate_scan_checkpoint (scope, method,
            through_finished_at, counts, bars, consistent, previous_id, created_at,
            code_git_sha, authz_token_sha256) values ('ohlcv_bar', :m, :t, cast(:c as jsonb),
            cast(:b as jsonb), :ok, :pid, :at, :g, :fp)"""),
            {"m": "FULL" if (full or prev is None) else "INCREMENTAL", "t": cut,
             "c": json.dumps(cur["counts"]), "b": json.dumps(cur["bars"]),
             "ok": out["consistent"], "pid": prev["id"] if prev else None, "at": now(),
             "g": code_version()["git_sha"], "fp": fp})
        await s.commit()
    else:
        await s.rollback()
    return out
