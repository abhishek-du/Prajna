"""Orphan-run reaper (hardening phase 4).

A process killed by SIGKILL, an OOM or a reboot leaves its ingest_run row in
RUNNING forever (its data transaction rolled back with the connection). Such
rows made an external audit report "stale runs". This marks them ABORTED,
with the reason, only when the owner is provably gone:

  runner identity recorded at open (request_params.runner: pid, host, boot_id)
    other host                 -> left alone (cannot check), reported
    boot_id differs            -> ORPHAN: the machine rebooted since
    pid gone / not a python    -> ORPHAN: the process died
    pid alive (python)         -> alive, left alone
  no identity (runs opened before phase 4)
    older than LEGACY_AGE      -> ORPHAN: no run lasts that long
    younger                    -> left alone

Dry-run by default; authorized and ledgered (PRAJNA_MAINT) like any write.
"""

from __future__ import annotations

import datetime as _dt
import os
import pathlib
import socket
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.ingest.runner import IngestRunner, boot_id

SOURCE, STREAM = "PRAJNA_MAINT", "maint.reap_runs"
LEGACY_AGE = _dt.timedelta(hours=48)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:                  # exists, owned by someone else
        return True
    try:
        cmd = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"python" in cmd                  # a reused pid of another program is not our run


def verdict(runner: dict | None, started_at: _dt.datetime, *, at: _dt.datetime,
            host: str, boot: str | None, alive=pid_alive) -> tuple[bool, str]:
    """Pure (alive is injectable). -> (orphan?, reason)."""
    if not runner:
        if at - started_at > LEGACY_AGE:
            return True, f"no runner identity and RUNNING for > {LEGACY_AGE}"
        return False, "no runner identity; too recent to judge"
    if runner.get("host") != host:
        return False, f"opened on another host ({runner.get('host')}); not checkable here"
    if boot and runner.get("boot_id") and runner["boot_id"] != boot:
        return True, "machine rebooted since the run opened (boot_id differs)"
    if not alive(int(runner.get("pid") or 0)):
        return True, f"process {runner.get('pid')} is gone"
    return False, f"process {runner.get('pid')} is alive"


async def reap_runs(s: AsyncSession, *, commit: bool, token: str | None,
                    operator: str = "cli") -> dict[str, Any]:
    runner = IngestRunner(s, source=SOURCE, stream=STREAM,
                          vendor_endpoint="none: ingest_run status maintenance",
                          request_params={"legacy_age_hours": LEGACY_AGE.total_seconds() / 3600},
                          operator=operator)
    ctx = await runner.open(commit=commit, token=token)
    try:
        rows = (await s.execute(text("""
            select run_id, stream, started_at, request_params->'runner' as runner
            from ingest_run where status = 'RUNNING' and run_id <> :me order by started_at"""),
            {"me": ctx.run_id})).all()
        at, host, boot = now(), socket.gethostname(), boot_id()
        orphans, alive = [], []
        for r in rows:
            dead, why = verdict(r.runner, r.started_at, at=at, host=host, boot=boot)
            (orphans if dead else alive).append({"run_id": str(r.run_id), "stream": r.stream,
                                                 "started_at": r.started_at.isoformat(),
                                                 "reason": why})
        if commit:
            for o in orphans:
                await s.execute(text("""
                    update ingest_run set status = 'ABORTED', finished_at = :t, rows_written = 0,
                           error = :e where run_id = cast(:r as uuid) and status = 'RUNNING'"""),
                    {"t": at, "e": f"reaped by maint.reap_runs: {o['reason']}"[:8000],
                     "r": o["run_id"]})
        outcome = {"running": len(rows), "orphans": orphans, "left_alone": alive}
        await runner.finalize(rows_written=len(orphans) if commit else 0, outcome=outcome)
        return {"run_id": str(ctx.run_id), "committed": commit, **outcome}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
