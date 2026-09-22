"""The run lifecycle, end to end, including the atomicity property."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus
from app.core.errors import AuthorizationError
from app.ingest.runner import IngestRunner

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _runner(session, **kw):
    return IngestRunner(
        session, source="UPSTOX_ASSETS", stream="test_stream",
        vendor_endpoint="https://assets.upstox.com/test", operator="pytest", **kw
    )


class TestRunLifecycle:
    async def test_dry_run_needs_no_token_and_writes_nothing(self, db_session):
        r = _runner(db_session)
        ctx = await r.open(commit=False, token=None)
        assert ctx.is_commit is False
        await r.finalize(rows_written=500)     # claims rows...
        row = (await db_session.execute(text(
            "select mode, status, rows_written from ingest_run where run_id=:r"),
            {"r": ctx.run_id})).one()
        assert row.mode == "DRY_RUN" and row.status == "COMPLETE"
        assert row.rows_written == 0           # ...but a dry run records zero

    async def test_commit_without_token_is_refused_before_any_write(self, db_session):
        r = _runner(db_session)
        with pytest.raises(AuthorizationError):
            await r.open(commit=True, token=None)
        n = (await db_session.execute(text("select count(*) from ingest_run"))).scalar()
        assert n == 0     # the run row is never even opened

    async def test_commit_with_token_records_authorization(self, db_session, monkeypatch):
        import os
        r = _runner(db_session)
        ctx = await r.open(commit=True, token=os.environ["PRAJNA_WRITE_TOKEN"])
        await r.finalize(rows_written=7)
        row = (await db_session.execute(text(
            "select mode, status, rows_written, authz_token_sha256, finished_at "
            "from ingest_run where run_id=:r"), {"r": ctx.run_id})).one()
        assert row.mode == "COMMIT" and row.status == "COMPLETE"
        assert row.rows_written == 7
        assert row.authz_token_sha256 and len(row.authz_token_sha256) == 64
        assert row.finished_at is not None

    async def test_failure_records_the_run_and_the_anomalies(self, db_session):
        """A failed run leaves evidence. V1's expired tasks left nothing."""
        r = _runner(db_session)
        ctx = await r.open(commit=False, token=None)
        ctx.checks.add(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "test_stream",
                       unknown_fields=["surpriseField"])
        await r.fail("vendor returned an unrecognised field")

        run = (await db_session.execute(text(
            "select status, error, rows_written from ingest_run where run_id=:r"),
            {"r": ctx.run_id})).one()
        assert run.status == RunStatus.FAILED.value and run.rows_written == 0
        anom = (await db_session.execute(text(
            "select severity, kind, detail from ingest_anomaly where run_id=:r"),
            {"r": ctx.run_id})).one()
        assert anom.severity == "FAIL" and anom.kind == "SCHEMA_DRIFT"
        assert anom.detail["unknown_fields"] == ["surpriseField"]

    async def test_watermark_advances_only_on_commit(self, db_session):
        import os
        await _runner(db_session).open(commit=False, token=None)
        r2 = _runner(db_session)
        await r2.open(commit=True, token=os.environ["PRAJNA_WRITE_TOKEN"])
        await r2.finalize(rows_written=3)
        wm = (await db_session.execute(text(
            "select rows_last_run, consecutive_failures from ingest_watermark "
            "where source='UPSTOX_ASSETS' and stream='test_stream'"))).one()
        assert wm.rows_last_run == 3 and wm.consecutive_failures == 0

    async def test_git_sha_is_recorded(self, db_session):
        """Rows must say which code produced them. V1 ran a dirty tree under
        hot-reload, so the executing code was never identifiable."""
        r = _runner(db_session)
        ctx = await r.open(commit=False, token=None)
        sha = (await db_session.execute(text(
            "select code_git_sha from ingest_run where run_id=:r"),
            {"r": ctx.run_id})).scalar()
        assert sha and sha != ""
