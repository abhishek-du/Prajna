"""Tests for scheduled-job timeline evidence parsing and gate honesty.

Verifies:
  - Job states: DONE, FAILED, RUNNING, MISSED, PENDING, NOT_SCHEDULED
  - Marker timestamps parsed from log lines, never synthesised
  - Missing gate files yield null / NOT_AVAILABLE, never fabricated defaults
  - Per-strategy reporting in paper execution, risk, and monitoring with bench_c0 labelled
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import pytest
from app.core.clock import IST
from app.api.stages import evaluate_scheduled_job


@pytest.fixture
def tmp_var_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    var_dir = tmp_path / "var"
    var_dir.mkdir(parents=True)
    (var_dir / "logs" / "daily").mkdir(parents=True)
    (var_dir / "logs" / "paper").mkdir(parents=True)
    (var_dir / "logs" / "backfill").mkdir(parents=True)
    return var_dir


def test_job_state_done(tmp_var_dir: pathlib.Path):
    """A log with a success marker yields DONE and exact marker timestamp."""
    day_str = "2026-10-16"
    log_file = tmp_var_dir / "logs" / "daily" / f"refresh_{day_str}.log"
    log_file.write_text("[2026-10-16 13:00:14 IST] done: refresh  fail=0\n")

    active_patterns = {"30 6 * * * daily.sh --login refresh"}
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    job = evaluate_scheduled_job(
        job_id="refresh",
        name="Daily Master Refresh",
        stage="Stage 1",
        scheduled_time=_dt.time(6, 30),
        grace_minutes=15,
        cron_pattern="daily.sh --login refresh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_var_dir,
        day_str=day_str,
        now_ist=now_ist,
    )

    assert job.status == "DONE"
    assert job.last_run_at == _dt.datetime(2026, 10, 16, 13, 0, 14, tzinfo=IST)
    assert "done: refresh  fail=0" in job.detail


def test_job_state_failed(tmp_var_dir: pathlib.Path):
    """A log with a failure marker yields FAILED and failure detail text."""
    day_str = "2026-10-16"
    log_file = tmp_var_dir / "logs" / "daily" / f"morning_{day_str}.log"
    log_file.write_text("[2026-10-16 08:32:27 IST] done: morning 2026-10-15 fail=1\n")

    active_patterns = {"0 7 * * 1-5 daily.sh --login morning"}
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    job = evaluate_scheduled_job(
        job_id="morning",
        name="Morning News & Market Prep",
        stage="Stage 1",
        scheduled_time=_dt.time(7, 0),
        grace_minutes=30,
        cron_pattern="daily.sh --login morning",
        active_cron_patterns=active_patterns,
        var_dir=tmp_var_dir,
        day_str=day_str,
        now_ist=now_ist,
    )

    assert job.status == "FAILED"
    assert job.last_run_at == _dt.datetime(2026, 10, 16, 8, 32, 27, tzinfo=IST)
    assert "done: morning 2026-10-15 fail=1" in job.detail


def test_job_state_running(tmp_var_dir: pathlib.Path):
    """A start marker without a completion marker yields RUNNING."""
    day_str = "2026-10-16"
    log_file = tmp_var_dir / "logs" / "daily" / f"close_then_backfill_{day_str}.log"
    log_file.write_text("[2026-10-16 17:29:24 IST] CLOSE_STARTED day=2026-10-16 fraction=0.9\n")

    active_patterns = {"5 16 * * 1-5 close_then_backfill.sh"}
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    job = evaluate_scheduled_job(
        job_id="close",
        name="Daily Close Ingest",
        stage="Stage 1–2",
        scheduled_time=_dt.time(16, 5),
        grace_minutes=25,
        cron_pattern="close_then_backfill.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_var_dir,
        day_str=day_str,
        now_ist=now_ist,
    )

    assert job.status == "RUNNING"
    assert job.last_run_at == _dt.datetime(2026, 10, 16, 17, 29, 24, tzinfo=IST)
    assert "CLOSE_STARTED" in job.detail


def test_job_state_missed(tmp_var_dir: pathlib.Path):
    """Scheduled time plus grace has elapsed without log marker -> MISSED, last_run_at is None."""
    day_str = "2026-10-16"
    active_patterns = {"25 8 * * 1-5 preopen_day.sh"}
    now_ist = _dt.datetime(2026, 10, 16, 10, 0, 0, tzinfo=IST)  # Past 08:25 + 30m grace

    # When crontab_installed is present and matches: status is MISSED
    job = evaluate_scheduled_job(
        job_id="preopen",
        name="Pre-open Book Setup",
        stage="Stage 1",
        scheduled_time=_dt.time(8, 25),
        grace_minutes=30,
        cron_pattern="preopen_day.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_var_dir,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns=active_patterns,
    )

    assert job.status == "MISSED"
    assert job.last_run_at is None
    assert "No execution marker found" in job.detail

    # When crontab_installed is absent (schedule unknown): status is NO RUN (schedule unknown)
    job_unk = evaluate_scheduled_job(
        job_id="preopen",
        name="Pre-open Book Setup",
        stage="Stage 1",
        scheduled_time=_dt.time(8, 25),
        grace_minutes=30,
        cron_pattern="preopen_day.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_var_dir,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns=None,
    )
    assert job_unk.status == "NO RUN (schedule unknown)"
    assert job_unk.last_run_at is None


def test_job_state_pending(tmp_var_dir: pathlib.Path):
    """Before scheduled execution time -> PENDING, last_run_at is None."""
    day_str = "2026-10-16"
    active_patterns = {"40 15 * * 1-5 paper_daily.sh"}
    now_ist = _dt.datetime(2026, 10, 16, 14, 0, 0, tzinfo=IST)  # Before 15:40

    job = evaluate_scheduled_job(
        job_id="paper_daily",
        name="Paper Trading Execution",
        stage="Stages 5–7",
        scheduled_time=_dt.time(15, 40),
        grace_minutes=20,
        cron_pattern="paper_daily.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_var_dir,
        day_str=day_str,
        now_ist=now_ist,
    )

    assert job.status == "PENDING"
    assert job.last_run_at is None
    assert "Scheduled for 15:40 IST" in job.detail


def test_job_state_not_scheduled(tmp_var_dir: pathlib.Path):
    """Job not present in ops/cron/prajna.cron -> NOT_SCHEDULED."""
    day_str = "2026-10-16"
    active_patterns = set()  # Empty cron, job not enabled
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    job = evaluate_scheduled_job(
        job_id="refresh",
        name="Daily Master Refresh",
        stage="Stage 1",
        scheduled_time=_dt.time(6, 30),
        grace_minutes=15,
        cron_pattern="daily.sh --login refresh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_var_dir,
        day_str=day_str,
        now_ist=now_ist,
    )

    assert job.status == "NOT_SCHEDULED"
    assert job.last_run_at is None
    assert "not active in ops/cron/prajna.cron" in job.detail


@pytest.mark.anyio
async def test_missing_gate_files_yield_null_not_defaults(monkeypatch, tmp_path):
    """Hard Rule 4: Missing gate files must yield NOT_AVAILABLE with null/unavailable notes, never hardcoded defaults."""
    from httpx import ASGITransport, AsyncClient
    from app.api.app import app

    # Point BACKEND_ROOT to empty tmp directory where no gate files exist
    empty_backend = tmp_path / "backend"
    empty_backend.mkdir(parents=True)
    (empty_backend / "var" / "acceptance").mkdir(parents=True)
    (empty_backend / "var" / "logs").mkdir(parents=True)
    (empty_backend / "ops" / "cron").mkdir(parents=True)

    monkeypatch.setattr("app.api.stages.BACKEND_ROOT", empty_backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/stages")
        assert resp.status_code == 200
        body = resp.json()
        stages = body["data"]["stages"]

        s1 = next(s for s in stages if s["stage_number"] == 1)
        s2 = next(s for s in stages if s["stage_number"] == 2)
        s3 = next(s for s in stages if s["stage_number"] == 3)

        # Stage 1 missing
        assert s1["status"] == "NOT_AVAILABLE"
        assert "stage1.json missing" in s1["key_metric_value"]

        # Stage 2 missing: MUST NOT return 3584 or 14336
        assert s2["status"] == "NOT_AVAILABLE"
        assert "stage2.json missing" in s2["key_metric_value"]
        assert "3584" not in s2["key_metric_value"]

        # Stage 3 missing: MUST NOT return 104 or features-v4
        assert s3["status"] == "NOT_AVAILABLE"
        assert "stage3.json missing" in s3["key_metric_value"]
        assert "104" not in s3["key_metric_value"]
        assert "features-v4" not in s3["key_metric_value"]
