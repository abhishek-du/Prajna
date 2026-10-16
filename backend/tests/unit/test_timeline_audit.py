"""Fixture tests for timeline audit, live backfill progress, and crontab verification."""

from __future__ import annotations

import datetime as _dt
import pathlib
import pytest

from app.api.stages import _parse_live_backfill_progress, evaluate_scheduled_job
from app.core.clock import IST


@pytest.fixture
def tmp_prajna_env(tmp_path: pathlib.Path) -> pathlib.Path:
    var_dir = tmp_path / "var"
    var_dir.mkdir(parents=True)
    (var_dir / "logs" / "daily").mkdir(parents=True)
    (var_dir / "logs" / "paper").mkdir(parents=True)
    (var_dir / "logs" / "backfill").mkdir(parents=True)
    (var_dir / "run").mkdir(parents=True)
    return var_dir


def test_multi_attempt_ca(tmp_prajna_env: pathlib.Path):
    """Case 1: CA refresh multi-attempt: 06:50 FAILED rc=1 (CA_REFRESH_ALERT), then 13:01 DONE rc=0. Selfheal is evaluated separately."""
    day_str = "2026-10-16"
    ca_log = tmp_prajna_env / "logs" / "daily" / f"ca_refresh_{day_str}.log"
    ca_log.write_text(
        "[2026-10-16 06:50:30 IST] CA_REFRESH mode=targeted targeted=12 inserted=0 failed=0 rc=1\n"
        "[2026-10-16 06:50:30 IST] CA_REFRESH_ALERT mode=targeted corporate-actions ingest rc=1 inserted=0 failed=0\n"
        "[2026-10-16 08:40:02 IST] CA_REFRESH mode=selfheal failing=0 healed=0 still_failing=0\n"
        "[2026-10-16 13:01:02 IST] CA_REFRESH mode=targeted targeted=12 inserted=0 failed=0 rc=0\n"
    )

    active_patterns = {"45 6 * * 1-5 ca_refresh.sh targeted", "40 8 * * 1-5 ca_refresh.sh selfheal"}
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    # 1. Evaluate ca_refresh (06:45) - must NOT include selfheal
    job = evaluate_scheduled_job(
        job_id="ca_refresh",
        name="Corporate Actions Targeted Refresh",
        stage="Stage 1",
        scheduled_time=_dt.time(6, 45),
        grace_minutes=15,
        cron_pattern="ca_refresh.sh targeted",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns=active_patterns,
    )

    assert len(job.attempts) == 2
    assert job.attempts[0].time_ist == "06:50"
    assert job.attempts[0].status == "FAILED"
    assert "CA_REFRESH_ALERT" in job.attempts[0].detail

    assert job.attempts[1].time_ist == "13:01"
    assert job.attempts[1].status == "DONE"
    assert "rc=0" in job.attempts[1].detail

    assert job.status == "DONE"
    assert job.last_run_at == _dt.datetime(2026, 10, 16, 13, 1, 2, tzinfo=IST)
    assert "06:50 FAILED" in job.detail
    assert "13:01 DONE" in job.detail

    # 2. Evaluate ca_selfheal (08:40) - separate job row
    job_sh = evaluate_scheduled_job(
        job_id="ca_selfheal",
        name="Corporate Actions Self-Heal",
        stage="Stage 1",
        scheduled_time=_dt.time(8, 40),
        grace_minutes=15,
        cron_pattern="ca_refresh.sh selfheal",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns=active_patterns,
    )

    assert len(job_sh.attempts) == 1
    assert job_sh.attempts[0].time_ist == "08:40"
    assert job_sh.attempts[0].status == "DONE"
    assert job_sh.status == "DONE"
    assert "mode=selfheal" in job_sh.detail


def test_missed_then_rerun_close(tmp_prajna_env: pathlib.Path):
    """Case 2: Missed-then-rerun Close: slot 16:05 missed, started at 17:29 (>60 min late -> LATE/MANUAL +84m delay)."""
    day_str = "2026-10-16"
    close_log = tmp_prajna_env / "logs" / "daily" / f"close_then_backfill_{day_str}.log"
    close_log.write_text("[2026-10-16 17:29:24 IST] CLOSE_STARTED day=2026-10-16 fraction=0.9\n")

    active_patterns = {"5 16 * * 1-5 close_then_backfill.sh"}
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    # With installed cron: slot is MISSED
    job = evaluate_scheduled_job(
        job_id="close",
        name="Daily Close Ingest",
        stage="Stage 1–2",
        scheduled_time=_dt.time(16, 5),
        grace_minutes=25,
        cron_pattern="close_then_backfill.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns=active_patterns,
    )

    assert len(job.attempts) == 2
    assert job.attempts[0].status == "MISSED"
    assert job.attempts[0].time_ist == "16:05"

    assert job.attempts[1].status == "RUNNING"
    assert job.attempts[1].time_ist == "17:29"
    assert job.attempts[1].delay_minutes == 84

    assert job.status == "RUNNING"
    assert job.delay_minutes == 84
    assert job.last_run_at == _dt.datetime(2026, 10, 16, 17, 29, 24, tzinfo=IST)
    assert "16:05 MISSED" in job.detail
    assert "17:29 RUNNING" in job.detail
    assert "+84m" in job.detail

    # Without installed cron (schedule unknown): slot is "NO RUN (schedule unknown)"
    job_unk = evaluate_scheduled_job(
        job_id="close",
        name="Daily Close Ingest",
        stage="Stage 1–2",
        scheduled_time=_dt.time(16, 5),
        grace_minutes=25,
        cron_pattern="close_then_backfill.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns=None,
    )

    assert len(job_unk.attempts) == 2
    assert job_unk.attempts[0].status == "NO RUN (schedule unknown)"
    assert "NO RUN (schedule unknown)" in job_unk.detail


def test_refused_then_backfilled_stage3(tmp_prajna_env: pathlib.Path):
    """Case 3: Refused-then-backfilled Stage 3: REFUSED at 09:02, backfilled at 16:30 via STAGE3_GAP_DONE."""
    day_str = "2026-10-16"
    cron_log = tmp_prajna_env / "logs" / "cron.log"
    cron_log.write_text(
        "[2026-10-16 09:00:31 IST] STAGE3_START PRE_SESSION 2026-10-16\n"
        "[2026-10-16 09:02:52 IST] STAGE3_REFUSED PRE_SESSION 2026-10-16: locked (audited in stage3_event); nothing written\n"
    )

    # Gap log with STAGE3_GAP_DONE
    gap_log = tmp_prajna_env / "logs" / "stage3_gap_20261016.log"
    gap_log.write_text(
        "[2026-10-16 15:35:14 IST] sessions: 2026-10-16\n"
        "[2026-10-16 16:29:32 IST]    2026-10-16..2026-10-16 done\n"
        "[2026-10-16 16:30:10 IST] STAGE3_GAP_DONE evidence in var/logs/stage3_gap/20261016T1535\n"
    )

    active_patterns = {"0 9 * * 1-5 stage3_snapshot.sh PRE_SESSION"}
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    job = evaluate_scheduled_job(
        job_id="stage3_pre_session",
        name="Stage 3 PRE_SESSION Snapshot",
        stage="Stage 3",
        scheduled_time=_dt.time(9, 0),
        grace_minutes=15,
        cron_pattern="stage3_snapshot.sh PRE_SESSION",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
    )

    assert len(job.attempts) == 2
    assert job.attempts[0].status == "FAILED"
    assert job.attempts[0].time_ist == "09:02"

    assert job.attempts[1].status == "BACKFILLED"
    assert job.attempts[1].time_ist == "16:30"

    assert job.status == "REFUSED → BACKFILLED"
    assert job.last_run_at == _dt.datetime(2026, 10, 16, 16, 30, 10, tzinfo=IST)
    assert "REFUSED at 09:02 → BACKFILLED at 16:30" in job.detail


def test_live_backfill_progress_two_files(tmp_prajna_env: pathlib.Path):
    """Case 4: Live backfill progress parsed across two log files: newest file first, honest rate delta, and null ETA when WAITING_CLOSE."""
    backfill_dir = tmp_prajna_env / "logs" / "backfill"

    # Older file from previous overnight run
    older_file = backfill_dir / "backfill_2026-10-15_2345.log"
    older_file.write_text(
        "[2026-10-15 23:45:04 IST] BACKFILL_PROGRESS tf=1h from=2022-01-01 covered=0/3581\n"
        "[2026-10-16 06:50:02 IST] BACKFILL_PROGRESS tf=1h from=2022-01-01 covered=1295/3581\n"
    )

    # Newest file from today's afternoon run
    newest_file = backfill_dir / "backfill_2026-10-16_1600.log"
    newest_file.write_text(
        "[2026-10-16 16:00:07 IST] BACKFILL_PROGRESS tf=1h from=2022-01-01 covered=1295/3584\n"
        "[2026-10-16 16:30:08 IST] BACKFILL_PROGRESS tf=1h from=2022-01-01 covered=1320/3584\n"
        "[2026-10-16 17:00:09 IST] BACKFILL_PROGRESS tf=1h from=2022-01-01 covered=1410/3584\n"
        "[2026-10-16 17:27:08 IST] BACKFILL_PROGRESS tf=1h from=2022-01-01 covered=1500/3584\n"
    )

    # When supervisor is WAITING_CLOSE: ETA must be None
    prog_waiting = _parse_live_backfill_progress(backfill_dir, supervisor_state="WAITING_CLOSE")
    p_1h = next(p for p in prog_waiting if p.timeframe == "1h")

    assert p_1h.covered == 1500
    assert p_1h.total == 3584
    assert p_1h.pct == 41.85
    assert p_1h.as_of == _dt.datetime(2026, 10, 16, 17, 27, 8, tzinfo=IST)
    # Rate = 205 covered over 1.45028 hours = 141.35
    assert p_1h.rate_per_hour == 141.35
    assert p_1h.eta_hours is None

    # When supervisor is RUNNING: ETA = (3584 - 1500) / 141.35 = 14.7 hours
    prog_running = _parse_live_backfill_progress(backfill_dir, supervisor_state="RUNNING")
    p_1h_running = next(p for p in prog_running if p.timeframe == "1h")
    assert p_1h_running.eta_hours == 14.7


def test_missing_crontab_installed_yields_unknown(tmp_prajna_env: pathlib.Path):
    """Case 5: If crontab_installed.txt is absent -> schedule status UNKNOWN (never NOT_SCHEDULED or DONE). When present without matching line -> MANUAL RUN if ran."""
    day_str = "2026-10-16"
    active_patterns = {"40 15 * * 1-5 paper_daily.sh"}
    now_ist = _dt.datetime(2026, 10, 16, 18, 0, 0, tzinfo=IST)

    paper_log = tmp_prajna_env / "logs" / "paper" / f"daily_{day_str}.log"
    paper_log.write_text(
        "[2026-10-16 17:22:16 IST] PAPER_DAILY_START strategies=bench_c0\n"
        "[2026-10-16 17:22:25 IST] PAPER_DAILY_DONE rc=0\n"
    )

    # 1. crontab_installed.txt is missing -> schedule status UNKNOWN
    job_unknown = evaluate_scheduled_job(
        job_id="paper_daily",
        name="Paper Trading Execution",
        stage="Stages 5–7",
        scheduled_time=_dt.time(15, 40),
        grace_minutes=20,
        cron_pattern="paper_daily.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns=None,  # File is absent
    )
    assert job_unknown.schedule_status == "UNKNOWN"

    # 2. crontab_installed.txt is present and matches -> SCHEDULED
    job_scheduled = evaluate_scheduled_job(
        job_id="paper_daily",
        name="Paper Trading Execution",
        stage="Stages 5–7",
        scheduled_time=_dt.time(15, 40),
        grace_minutes=20,
        cron_pattern="paper_daily.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns={"40 15 * * 1-5 paper_daily.sh"},
    )
    assert job_scheduled.schedule_status == "SCHEDULED"

    # 3. crontab_installed.txt is present and missing matching line, but job ran -> MANUAL RUN
    job_manual = evaluate_scheduled_job(
        job_id="paper_daily",
        name="Paper Trading Execution",
        stage="Stages 5–7",
        scheduled_time=_dt.time(15, 40),
        grace_minutes=20,
        cron_pattern="paper_daily.sh",
        active_cron_patterns=active_patterns,
        var_dir=tmp_prajna_env,
        day_str=day_str,
        now_ist=now_ist,
        installed_cron_patterns={"0 7 * * 1-5 daily.sh morning"},  # Not containing paper_daily.sh
    )
    assert job_manual.schedule_status == "MANUAL RUN"
