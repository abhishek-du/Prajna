"""The ingestion run lifecycle. Every source goes through it; none bypasses it.

    1 OPEN     insert ingest_run(status=RUNNING) — BEFORE the fetch
    2 FETCH    source.fetch() -> raw bytes
    3 ARCHIVE  payload_store.put() — bytes on disk before any parse
    4 PARSE    pure function: bytes -> typed rows
    5 CHECK    coverage / freshness / drift / provenance gates
    6 WRITE    ONE transaction: rows + run finalisation + watermark
    7 REPORT   structured summary

Step 6 is the part V1 got wrong and it matters more than it looks. Its run
ledger was updated separately from the data, so run c4332067 sat in RUNNING for
six days reporting rows_written = 0 while 269,642 of its rows were live in the
table — 44% of its entire provenance dataset, attributable to a run that
claimed to have written nothing. Here the ledger update and the data share a
transaction: they are both true or neither is.
"""

from __future__ import annotations

import datetime as _dt
import os
import pathlib
import socket
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import insert, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.provenance import RunMode, RunStatus, config_sha256
from app.core.authz import authorize_write, redact_argv
from app.core.clock import now
from app.core.logging import bind_run, clear_run, get_logger
from app.db.models import IngestAnomaly, IngestRun, IngestWatermark, RawPayload
from app.ingest.checks import CheckResult

log = get_logger("ingest.runner")


def git_sha() -> str:
    """Record exactly which code produced a row.

    V1 ran from a 396-path dirty working tree under watchmedo hot-reload, so the
    code that executed was not the code at HEAD and no row could say which it
    was. A dirty tree is marked here rather than hidden.
    """
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = subprocess.call(
            ["git", "diff", "--quiet", "HEAD"], stderr=subprocess.DEVNULL
        ) != 0
        return f"{sha[:39]}{'+' if dirty else ''}" if sha else "unknown"
    except Exception:
        return "unknown"


@dataclass(slots=True)
class RunContext:
    run_id: uuid.UUID
    source: str
    stream: str
    mode: RunMode
    started_at: _dt.datetime
    logical_date: _dt.date | None = None
    rows_written: int = 0
    checks: CheckResult = field(default_factory=CheckResult)

    @property
    def is_commit(self) -> bool:
        return self.mode is RunMode.COMMIT


def boot_id() -> str | None:
    try:
        return pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def runner_identity() -> dict[str, Any]:
    return {"pid": os.getpid(), "host": socket.gethostname(), "boot_id": boot_id()}


class IngestRunner:
    def __init__(
        self,
        session: AsyncSession,
        *,
        source: str,
        stream: str,
        vendor_endpoint: str,
        request_params: dict[str, Any] | None = None,
        operator: str = "cli",
        logical_date: _dt.date | None = None,
    ):
        self.session = session
        self.source = source
        self.stream = stream
        self.vendor_endpoint = vendor_endpoint
        self.request_params = request_params or {}
        self.operator = operator
        self.logical_date = logical_date
        self.ctx: RunContext | None = None

    async def open(self, *, commit: bool, token: str | None) -> RunContext:
        """Step 1. Authorization is resolved HERE, at the write path.

        V1's gate guarded main() while the library functions beneath stayed
        callable, and a driver script imported those directly and wrote 269,642
        unauthorized rows. A gate at the entry point is not a gate.
        """
        mode = RunMode.COMMIT if commit else RunMode.DRY_RUN
        authz = authorize_write(token) if commit else None

        ctx = RunContext(
            run_id=uuid.uuid4(), source=self.source, stream=self.stream,
            mode=mode, started_at=now(), logical_date=self.logical_date,
        )
        await self.session.execute(
            insert(IngestRun).values(
                run_id=ctx.run_id, source=self.source, stream=self.stream,
                logical_date=self.logical_date, vendor_endpoint=self.vendor_endpoint,
                # `runner` identifies the process, so an orphaned RUNNING row (a
                # killed process, a reboot) can be recognised and reaped; it is
                # excluded from config_sha256, which hashes only what was asked
                request_params={**self.request_params, "runner": runner_identity()},
                code_git_sha=git_sha(), config_sha256=config_sha256(self.request_params),
                argv=redact_argv(sys.argv),
                operator=self.operator, mode=mode.value, status=RunStatus.RUNNING.value,
                authz_token_sha256=authz, started_at=ctx.started_at, rows_written=0,
            )
        )
        # The run row is committed immediately so a crash leaves evidence that
        # the attempt happened, rather than no trace at all.
        await self.session.commit()

        self.ctx = ctx
        bind_run(str(ctx.run_id), self.source)
        log.info("run.open", stream=self.stream, mode=mode.value,
                 logical_date=str(self.logical_date), authorized=bool(authz))
        return ctx

    async def record_payload(
        self, stored, *, http_status: int | None = None, storage_uri: str | None = None,
        vendor_endpoint: str | None = None,
    ) -> bool:
        """Step 3 bookkeeping. Idempotent on the content address.

        `storage_uri` overrides the file path for payloads that live inside a
        larger archive (a WebSocket frame is `<archive>#seq=<n>`). Returns
        True if this call recorded the payload, False if it was already known.
        `vendor_endpoint` overrides the run's endpoint for runs that fetch from
        several URLs (the calendar: one holidays call, one timings call per day).
        """
        assert self.ctx
        exists = await self.session.get(RawPayload, stored.sha256)
        if exists:
            return False
        await self.session.execute(
            insert(RawPayload).values(
                payload_sha256=stored.sha256, source=self.source,
                vendor_endpoint=vendor_endpoint or self.vendor_endpoint,
                request_params=self.request_params, http_status=http_status,
                byte_size=stored.byte_size,
                content_type=stored.content_type, storage_uri=storage_uri or str(stored.path),
                first_seen_run=self.ctx.run_id, fetched_at=stored.fetched_at,
                vendor_reported_at=stored.vendor_reported_at,
            )
        )
        return True

    async def _flush_anomalies(self) -> None:
        assert self.ctx
        if not self.ctx.checks.anomalies:
            return
        await self.session.execute(
            insert(IngestAnomaly),
            [
                {
                    "run_id": self.ctx.run_id, "severity": a.severity.value,
                    "kind": a.kind.value, "subject": a.subject, "detail": a.detail,
                    "created_at": now(),
                }
                for a in self.ctx.checks.anomalies
            ],
        )

    def _with_outcome(self, values: dict, outcome: dict | None) -> dict:
        """`outcome` is merged into request_params under "outcome" (JSONB ||),
        so what a run FOUND sits next to what it ASKED FOR; e.g. a candle
        window's coverage record, which is the only trace of an EMPTY window."""
        if outcome is not None:
            values["request_params"] = IngestRun.request_params.op("||")(
                type_coerce({"outcome": outcome}, JSONB))
        return values

    async def finalize(self, *, rows_written: int, outcome: dict | None = None) -> None:
        """Step 6. Ledger + watermark + anomalies, in the caller's transaction.

        The caller has already staged its data rows on this same session and has
        NOT committed. One commit covers everything.
        """
        assert self.ctx
        ctx = self.ctx
        ctx.rows_written = rows_written if ctx.is_commit else 0

        await self._flush_anomalies()
        await self.session.execute(
            update(IngestRun).where(IngestRun.run_id == ctx.run_id).values(
                **self._with_outcome({"status": RunStatus.COMPLETE.value, "finished_at": now(),
                                      "rows_written": ctx.rows_written}, outcome))
        )
        if ctx.is_commit:
            await self.session.merge(
                IngestWatermark(
                    source=self.source, stream=self.stream,
                    last_logical_date=ctx.logical_date, last_success_at=now(),
                    last_run_id=ctx.run_id, consecutive_failures=0,
                    rows_last_run=ctx.rows_written,
                )
            )
        await self.session.commit()
        log.info("run.complete", rows_written=ctx.rows_written,
                 anomalies=len(ctx.checks.anomalies))
        clear_run()

    async def fail(self, error: str, *, status: RunStatus = RunStatus.FAILED,
                   outcome: dict | None = None) -> None:
        """Abort. Data is rolled back; the run row and anomalies are kept."""
        assert self.ctx
        await self.session.rollback()
        await self._flush_anomalies()
        await self.session.execute(
            update(IngestRun).where(IngestRun.run_id == self.ctx.run_id).values(
                **self._with_outcome({"status": status.value, "finished_at": now(),
                                      "rows_written": 0, "error": error[:8000]}, outcome))
        )
        await self.session.commit()
        log.error("run.failed", error=error[:400])
        clear_run()
