"""Maintenance: redact write tokens persisted in ingest_run.argv.

Until the runner redacted argv (authz.redact_argv), every run recorded
sys.argv verbatim, so `--token <secret>` sat in the ledger. This rewrites
those rows with the same redaction; nothing else on a run changes (its
fingerprint authz_token_sha256 still identifies the token).

Idempotent: a redacted argv redacts to itself, so a rerun writes 0 rows.
RUNNING rows are skipped (their process may still finalize them; a later
rerun catches them once finished). It runs through the run ledger (source
PRAJNA_MAINT), authorized like any write, dry-run unless --commit.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ARRAY, Text, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import redact_argv
from app.ingest.runner import IngestRunner

MAINT_SOURCE = "PRAJNA_MAINT"
STREAM = "maint.redact_argv"


async def redact_run_argv(s: AsyncSession, *, commit: bool, token: str | None,
                          operator: str = "cli") -> dict[str, Any]:
    runner = IngestRunner(s, source=MAINT_SOURCE, stream=STREAM,
                          vendor_endpoint="none: rewrites ingest_run.argv",
                          operator=operator)
    ctx = await runner.open(commit=commit, token=token)
    try:
        # the rows whose argv changes under redaction (scan is cheap: ~10^5 runs)
        rows = (await s.execute(text(
            "select run_id, status, argv from ingest_run where run_id <> :me"),
            {"me": ctx.run_id})).all()
        todo = [(r.run_id, redact_argv(r.argv)) for r in rows
                if r.status != "RUNNING" and redact_argv(r.argv) != r.argv]
        running = sum(1 for r in rows if r.status == "RUNNING"
                      and redact_argv(r.argv) != r.argv)
        if commit and todo:
            await s.execute(text("set local lock_timeout = '5s'"))
            stmt = text("update ingest_run set argv = :argv where run_id = :rid "
                        "and status <> 'RUNNING'").bindparams(bindparam("argv", type_=ARRAY(Text)))
            for i in range(0, len(todo), 1000):
                await s.execute(stmt, [{"rid": rid, "argv": a} for rid, a in todo[i:i + 1000]])
        outcome = {"runs_scanned": len(rows), "runs_redacted": len(todo) if commit else 0,
                   "runs_to_redact": len(todo), "running_skipped": running}
        await runner.finalize(rows_written=len(todo), outcome=outcome)
        return {"run_id": str(ctx.run_id), "committed": commit, **outcome}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
