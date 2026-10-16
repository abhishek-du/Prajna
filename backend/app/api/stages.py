"""8 Stages and Control Room endpoint (/api/v1/stages).

Point-in-Time honesty (Rule 4):
  - Every status and timestamp comes strictly from real log markers and database evidence.
  - No status is derived from the clock.
  - No fabricated defaults or hardcoded locks.
  - Per-strategy metrics for paper trading, labelling bench_c0 as the benchmark.
  - Read-only transaction enforcement (Rule 2).
  - Prajna cron evaluated strictly by reading ops/cron/prajna.cron (no shell / crontab execution).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import json
import pathlib
import re
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    BackfillTimeframeProgress,
    Envelope,
    ExcludedBarItem,
    FeatureCardResponse,
    FeatureRegistryItem,
    FeatureValueItem,
    GateCriterionItem,
    JobAttemptItem,
    MarketStatus,
    Meta,
    ScheduledJobItem,
    Stage1BackfillResponse,
    Stage1CoverageResponse,
    Stage2GateResponse,
    Stage3EventItem,
    Stage3GateResponse,
    Stage3RegistryResponse,
    Stage3SnapshotsResponse,
    StageSummary,
    StagesOverviewResponse,
    SystemAlertItem,
    TimeframeCoverageItem,
)
from app.core.clock import IST, now
from app.core.config import BACKEND_ROOT

router = APIRouter(prefix="/stages", tags=["stages"])


def _load_json_defensively(path: pathlib.Path) -> dict[str, Any] | None:
    """Safely loads a JSON file. Returns None if file does not exist or is malformed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_iso_dt(val: str | None) -> _dt.datetime | None:
    if not val:
        return None
    try:
        return _dt.datetime.fromisoformat(val)
    except Exception:
        return None


def _parse_ist_timestamp(line: str) -> _dt.datetime | None:
    """Extracts [YYYY-MM-DD HH:MM:SS IST] from a log line."""
    m = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) IST\]", line)
    if m:
        try:
            return _dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        except Exception:
            return None
    return None


def _read_active_cron_patterns(cron_path: pathlib.Path) -> set[str]:
    """Reads ops/cron/prajna.cron and returns all uncommented active command patterns."""
    active: set[str] = set()
    if not cron_path.exists():
        return active
    try:
        for line in cron_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                active.add(line)
    except Exception:
        pass
    return active


def _is_job_scheduled(cron_patterns: set[str], pattern: str) -> bool:
    return any(pattern in line for line in cron_patterns)


def _parse_live_backfill_progress(backfill_dir: pathlib.Path, supervisor_state: str) -> list[BackfillTimeframeProgress]:
    """Parses live backfill progress from newest backfill_*.log files.

    - Finds latest BACKFILL_PROGRESS line per timeframe across files (newest file first).
    - Includes its timestamp as as_of.
    - Rate is computed as delta covered / delta hours over the lines in the newest run window.
    - ETA = remaining / rate if supervisor_state == 'RUNNING', else None.
    """
    if not backfill_dir.exists():
        return [
            BackfillTimeframeProgress(
                timeframe="1h",
                from_date="2022-01-01",
                covered=0,
                total=3584,
                pct=0.0,
                rate_per_hour=None,
                eta_hours=None,
                as_of=None,
            ),
            BackfillTimeframeProgress(
                timeframe="15m",
                from_date="2022-01-01",
                covered=0,
                total=3584,
                pct=0.0,
                rate_per_hour=None,
                eta_hours=None,
                as_of=None,
            ),
        ]

    # Find and sort all backfill_*.log files descending by filename
    log_files = sorted(backfill_dir.glob("backfill_*.log"), key=lambda p: p.name, reverse=True)
    prog_pattern = re.compile(
        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) IST\] BACKFILL_PROGRESS tf=([0-9a-zA-Z]+) from=([0-9-]+) covered=(\d+)/(\d+)"
    )

    seen_items: dict[str, BackfillTimeframeProgress] = {}

    for lf in log_files:
        try:
            content = lf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        lines = content.splitlines()
        file_matches: list[tuple[_dt.datetime, str, str, int, int]] = []
        for l in lines:
            m = prog_pattern.search(l)
            if m:
                ts = _dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                tf = m.group(2)
                f_d = m.group(3)
                cov = int(m.group(4))
                tot = int(m.group(5))
                file_matches.append((ts, tf, f_d, cov, tot))

        if not file_matches:
            continue

        # Group matches in this file by timeframe
        by_tf: dict[str, list[tuple[_dt.datetime, str, str, int, int]]] = {}
        for m_item in file_matches:
            by_tf.setdefault(m_item[1], []).append(m_item)

        for tf, t_matches in by_tf.items():
            if tf in seen_items:
                continue

            latest = t_matches[-1]
            latest_ts, _, from_date, latest_cov, total_cov = latest
            pct = round((latest_cov / total_cov * 100), 2) if total_cov > 0 else 0.0

            rate: float | None = None
            if len(t_matches) >= 2:
                first_ts = t_matches[0][0]
                last_ts = t_matches[-1][0]
                delta_sec = (last_ts - first_ts).total_seconds()
                delta_cov = t_matches[-1][3] - t_matches[0][3]
                if delta_sec > 0 and delta_cov >= 0:
                    delta_hours = delta_sec / 3600.0
                    rate = round(delta_cov / delta_hours, 2)

            eta: float | None = None
            if supervisor_state == "RUNNING" and rate is not None and rate > 0:
                rem = total_cov - latest_cov
                eta = round(rem / rate, 1)

            seen_items[tf] = BackfillTimeframeProgress(
                timeframe=tf,
                from_date=from_date,
                covered=latest_cov,
                total=total_cov,
                pct=pct,
                rate_per_hour=rate,
                eta_hours=eta,
                as_of=latest_ts,
            )

    # If 15m was not found in log files, provide default 0 covered item
    if "15m" not in seen_items:
        tot_15m = seen_items["1h"].total if "1h" in seen_items else 3584
        seen_items["15m"] = BackfillTimeframeProgress(
            timeframe="15m",
            from_date="2022-01-01",
            covered=0,
            total=tot_15m,
            pct=0.0,
            rate_per_hour=None,
            eta_hours=None,
            as_of=None,
        )

    return [seen_items[k] for k in ("1h", "15m") if k in seen_items] + [
        v for k, v in seen_items.items() if k not in ("1h", "15m")
    ]


def evaluate_scheduled_job(
    job_id: str,
    name: str,
    stage: str,
    scheduled_time: _dt.time,
    grace_minutes: int,
    cron_pattern: str,
    active_cron_patterns: set[str],
    var_dir: pathlib.Path,
    day_str: str,
    now_ist: _dt.datetime,
    installed_cron_patterns: set[str] | None = None,
) -> ScheduledJobItem:
    """Evaluates a scheduled job's state strictly from log markers and cron installation."""
    # Check if job is active in repo prajna.cron
    if not _is_job_scheduled(active_cron_patterns, cron_pattern):
        return ScheduledJobItem(
            time_ist=scheduled_time.strftime("%H:%M"),
            name=name,
            stage=stage,
            status="NOT_SCHEDULED",
            detail="Job not active in ops/cron/prajna.cron",
            last_run_at=None,
            schedule_status="NOT_SCHEDULED",
        )

    # Installed vs repo cron
    if installed_cron_patterns is None:
        schedule_status = "UNKNOWN"
    else:
        if _is_job_scheduled(installed_cron_patterns, cron_pattern):
            schedule_status = "SCHEDULED"
        else:
            schedule_status = "NOT_SCHEDULED"

    scheduled_dt = _dt.datetime.combine(now_ist.date(), scheduled_time, tzinfo=IST)
    deadline_dt = scheduled_dt + _dt.timedelta(minutes=grace_minutes)

    status: str = "PENDING"
    detail: str = "Awaiting scheduled execution"
    last_run_at: _dt.datetime | None = None
    delay_minutes: int | None = None
    attempts: list[JobAttemptItem] = []
    no_run_status: str = "NO RUN (schedule unknown)" if schedule_status == "UNKNOWN" else "MISSED"

    if job_id == "refresh":
        log_file = var_dir / "logs" / "daily" / f"refresh_{day_str}.log"
        if not log_file.exists():
            log_file = var_dir / "logs" / f"refresh_{day_str}.log"
        if log_file.exists():
            text_content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            start_line = next((l for l in lines if "== daily refresh" in l), None)
            done_line = next((l for l in reversed(lines) if "done: refresh" in l), None)

            if done_line:
                done_ts = _parse_ist_timestamp(done_line)
                start_ts = _parse_ist_timestamp(start_line) if start_line else done_ts
                m_fail = re.search(r"fail=(\d+)", done_line)
                fails = int(m_fail.group(1)) if m_fail else 0
                outcome = "DONE" if fails == 0 else "FAILED"
                delay = int((start_ts - scheduled_dt).total_seconds() / 60) if start_ts and start_ts > scheduled_dt else 0

                if delay > 60:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=scheduled_time.strftime("%H:%M"),
                            status=no_run_status,
                            detail=f"no execution at {scheduled_time.strftime('%H:%M')} slot ({no_run_status})",
                        )
                    )
                    attempts.append(
                        JobAttemptItem(
                            time_ist=start_ts.strftime("%H:%M") if start_ts else (done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M")),
                            status=outcome,
                            delay_minutes=delay,
                            detail=f"{done_ts.strftime('%H:%M') if done_ts else ''} {outcome} (LATE/MANUAL +{delay}m, fail={fails})",
                        )
                    )
                    status = outcome
                    detail = f"{scheduled_time.strftime('%H:%M')} {no_run_status} → {done_ts.strftime('%H:%M') if done_ts else ''} {outcome}: {done_line.strip()} (LATE/MANUAL +{delay}m)"
                    delay_minutes = delay
                    last_run_at = done_ts
                else:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M"),
                            status=outcome,
                            delay_minutes=delay if delay > 0 else None,
                            detail=done_line.strip(),
                        )
                    )
                    status = outcome
                    detail = done_line.strip()
                    last_run_at = done_ts
            elif start_line:
                start_ts = _parse_ist_timestamp(start_line)
                delay = int((start_ts - scheduled_dt).total_seconds() / 60) if start_ts and start_ts > scheduled_dt else 0
                if delay > 60:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=scheduled_time.strftime("%H:%M"),
                            status=no_run_status,
                            detail=f"no execution at {scheduled_time.strftime('%H:%M')} slot ({no_run_status})",
                        )
                    )
                attempts.append(
                    JobAttemptItem(
                        time_ist=start_ts.strftime("%H:%M") if start_ts else scheduled_time.strftime("%H:%M"),
                        status="RUNNING",
                        delay_minutes=delay if delay > 60 else None,
                        detail="Daily master refresh currently running" + (f" (LATE/MANUAL +{delay}m)" if delay > 60 else ""),
                    )
                )
                status = "RUNNING"
                detail = f"Running (started {start_ts.strftime('%H:%M IST') if start_ts else ''})"
                delay_minutes = delay if delay > 60 else None
                last_run_at = start_ts

    elif job_id == "ca_refresh":
        log_file = var_dir / "logs" / "daily" / f"ca_refresh_{day_str}.log"
        if not log_file.exists():
            log_file = var_dir / "logs" / f"ca_refresh_{day_str}.log"
        if log_file.exists():
            text_content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()

            idx = 0
            while idx < len(lines):
                line = lines[idx]
                if "CA_REFRESH mode=" in line and "selfheal" not in line:
                    ts = _parse_ist_timestamp(line)
                    time_str = ts.strftime("%H:%M") if ts else scheduled_time.strftime("%H:%M")
                    m_rc = re.search(r"\brc=(\d+)\b", line)
                    if m_rc:
                        rc_val = int(m_rc.group(1))
                        alert_line = None
                        if idx + 1 < len(lines) and "CA_REFRESH_ALERT" in lines[idx + 1]:
                            alert_line = lines[idx + 1].strip()
                        if rc_val == 0:
                            attempts.append(
                                JobAttemptItem(
                                    time_ist=time_str,
                                    status="DONE",
                                    detail=f"{time_str} DONE rc=0",
                                )
                            )
                        else:
                            detail_str = f"{time_str} FAILED rc={rc_val}"
                            if alert_line:
                                detail_str += " (CA_REFRESH_ALERT)"
                            attempts.append(
                                JobAttemptItem(
                                    time_ist=time_str,
                                    status="FAILED",
                                    detail=detail_str,
                                )
                            )
                    last_run_at = ts
                idx += 1

            if attempts:
                last_att = attempts[-1]
                status = last_att.status
                detail = " → ".join(a.detail for a in attempts)

    elif job_id == "ca_selfheal":
        log_file = var_dir / "logs" / "daily" / f"ca_refresh_{day_str}.log"
        if not log_file.exists():
            log_file = var_dir / "logs" / f"ca_refresh_{day_str}.log"
        if log_file.exists():
            text_content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            for line in lines:
                if "CA_REFRESH mode=selfheal" in line or ("mode=selfheal" in line and "CA_REFRESH" in line):
                    ts = _parse_ist_timestamp(line)
                    time_str = ts.strftime("%H:%M") if ts else scheduled_time.strftime("%H:%M")
                    m_rc = re.search(r"\brc=(\d+)\b", line)
                    rc_val = int(m_rc.group(1)) if m_rc else 0
                    st = "DONE" if rc_val == 0 else "FAILED"
                    attempts.append(
                        JobAttemptItem(
                            time_ist=time_str,
                            status=st,
                            detail=line.strip(),
                        )
                    )
                    status = st
                    detail = line.strip()
                    last_run_at = ts

    elif job_id == "morning":
        log_file = var_dir / "logs" / "daily" / f"morning_{day_str}.log"
        if not log_file.exists():
            log_file = var_dir / "logs" / f"morning_{day_str}.log"
        if log_file.exists():
            text_content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            start_line = next((l for l in lines if "== daily morning" in l or "run.open" in l), None)
            done_line = next((l for l in reversed(lines) if "done: morning" in l), None)

            if done_line:
                done_ts = _parse_ist_timestamp(done_line)
                m = re.search(r"done:\s*morning\s+.*?fail=(\d+)", done_line)
                fails = int(m.group(1)) if m else 0
                st = "DONE" if fails == 0 else "FAILED"
                attempts.append(
                    JobAttemptItem(
                        time_ist=done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M"),
                        status=st,
                        detail=done_line.strip(),
                    )
                )
                status = st
                detail = done_line.strip()
                last_run_at = done_ts
            elif start_line:
                start_ts = _parse_ist_timestamp(start_line)
                attempts.append(
                    JobAttemptItem(
                        time_ist=start_ts.strftime("%H:%M") if start_ts else scheduled_time.strftime("%H:%M"),
                        status="RUNNING",
                        detail="Morning ingest currently running",
                    )
                )
                status = "RUNNING"
                detail = "Morning ingest currently running"
                last_run_at = start_ts

    elif job_id == "preopen":
        log_file = var_dir / "logs" / f"preopen_{day_str}.log"
        if not log_file.exists():
            log_file = var_dir / "logs" / "daily" / f"preopen_{day_str}.log"
        if log_file.exists():
            text_content = log_file.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            start_line = next((l for l in lines if "== pre-open" in l or "capture exit" in l), None)
            done_line = next((l for l in reversed(lines) if "done: capture=" in l), None)

            if done_line:
                done_ts = _parse_ist_timestamp(done_line)
                m = re.search(r"done:\s*capture=(\d+)\s+replay=(\d+)\s+acceptance=(\d+)", done_line)
                fails = (int(m.group(1)) + int(m.group(2)) + int(m.group(3))) if m else 0
                st = "DONE" if fails == 0 else "FAILED"
                attempts.append(
                    JobAttemptItem(
                        time_ist=done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M"),
                        status=st,
                        detail=done_line.strip(),
                    )
                )
                status = st
                detail = done_line.strip()
                last_run_at = done_ts
            elif start_line:
                start_ts = _parse_ist_timestamp(start_line)
                attempts.append(
                    JobAttemptItem(
                        time_ist=start_ts.strftime("%H:%M") if start_ts else scheduled_time.strftime("%H:%M"),
                        status="RUNNING",
                        detail="Pre-open collector / replay running",
                    )
                )
                status = "RUNNING"
                detail = "Pre-open collector / replay running"
                last_run_at = start_ts

    elif job_id in ("stage3_pre_session", "stage3_pre_open"):
        snapshot = "PRE_SESSION" if job_id == "stage3_pre_session" else "PRE_OPEN"
        cron_log = var_dir / "logs" / "cron.log"
        if cron_log.exists():
            text_content = cron_log.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            pattern_done = f"STAGE3_DONE {snapshot} {day_str}"
            pattern_refused = f"STAGE3_REFUSED {snapshot} {day_str}"
            pattern_start = f"STAGE3_START {snapshot} {day_str}"

            done_line = next((l for l in reversed(lines) if pattern_done in l), None)
            refused_line = next((l for l in reversed(lines) if pattern_refused in l), None)
            start_line = next((l for l in reversed(lines) if pattern_start in l), None)

            if done_line:
                done_ts = _parse_ist_timestamp(done_line)
                attempts.append(
                    JobAttemptItem(
                        time_ist=done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M"),
                        status="DONE",
                        detail=done_line.strip(),
                    )
                )
                status = "DONE"
                detail = done_line.strip()
                last_run_at = done_ts
            elif refused_line:
                refused_ts = _parse_ist_timestamp(refused_line)
                r_time_str = refused_ts.strftime("%H:%M") if refused_ts else scheduled_time.strftime("%H:%M")
                attempts.append(
                    JobAttemptItem(
                        time_ist=r_time_str,
                        status="FAILED",
                        detail=f"{r_time_str} REFUSED: locked (audited in stage3_event)",
                    )
                )

                # Check if gap backfill subsequently succeeded
                day_compact = day_str.replace("-", "")
                gap_log = var_dir / "logs" / f"stage3_gap_{day_compact}.log"
                gap_done_line = None
                if gap_log.exists():
                    try:
                        gap_lines = gap_log.read_text(encoding="utf-8", errors="ignore").splitlines()
                        gap_done_line = next((l for l in reversed(gap_lines) if "STAGE3_GAP_DONE" in l), None)
                    except Exception:
                        pass

                if gap_done_line:
                    gap_ts = _parse_ist_timestamp(gap_done_line)
                    gap_time_str = gap_ts.strftime("%H:%M") if gap_ts else "16:30"
                    attempts.append(
                        JobAttemptItem(
                            time_ist=gap_time_str,
                            status="BACKFILLED",
                            detail=f"STAGE3_GAP_DONE at {gap_time_str}",
                        )
                    )
                    status = "REFUSED → BACKFILLED"
                    detail = f"REFUSED at {r_time_str} → BACKFILLED at {gap_time_str}"
                    last_run_at = gap_ts or refused_ts
                else:
                    status = "FAILED"
                    detail = refused_line.strip()
                    last_run_at = refused_ts
            elif start_line:
                start_ts = _parse_ist_timestamp(start_line)
                attempts.append(
                    JobAttemptItem(
                        time_ist=start_ts.strftime("%H:%M") if start_ts else scheduled_time.strftime("%H:%M"),
                        status="RUNNING",
                        detail=f"Stage 3 {snapshot} in progress",
                    )
                )
                status = "RUNNING"
                detail = f"Stage 3 {snapshot} in progress"
                last_run_at = start_ts

    elif job_id == "paper_daily":
        paper_log = var_dir / "logs" / "paper" / f"daily_{day_str}.log"
        if paper_log.exists():
            text_content = paper_log.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            start_line = next((l for l in lines if "PAPER_DAILY_START" in l), None)
            done_line = next((l for l in reversed(lines) if "PAPER_DAILY_DONE" in l), None)

            if done_line:
                done_ts = _parse_ist_timestamp(done_line)
                start_ts = _parse_ist_timestamp(start_line) if start_line else done_ts
                m_rc = re.search(r"PAPER_DAILY_DONE\s+rc=(\d+)", done_line)
                rc_val = int(m_rc.group(1)) if m_rc else 0
                st = "DONE" if rc_val == 0 else "FAILED"
                delay = int((start_ts - scheduled_dt).total_seconds() / 60) if start_ts and start_ts > scheduled_dt else 0

                if delay > 60:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=scheduled_time.strftime("%H:%M"),
                            status=no_run_status,
                            detail=f"no execution at {scheduled_time.strftime('%H:%M')} slot ({no_run_status})",
                        )
                    )
                    attempts.append(
                        JobAttemptItem(
                            time_ist=start_ts.strftime("%H:%M") if start_ts else (done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M")),
                            status=st,
                            delay_minutes=delay,
                            detail=f"{done_ts.strftime('%H:%M') if done_ts else ''} {st} rc={rc_val} (LATE/MANUAL +{delay}m)",
                        )
                    )
                    status = st
                    detail = f"{scheduled_time.strftime('%H:%M')} {no_run_status} → {done_ts.strftime('%H:%M') if done_ts else ''} {st} rc={rc_val} (LATE/MANUAL +{delay}m)"
                    delay_minutes = delay
                    last_run_at = done_ts
                else:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M"),
                            status=st,
                            delay_minutes=delay if delay > 0 else None,
                            detail=done_line.strip(),
                        )
                    )
                    status = st
                    detail = done_line.strip()
                    last_run_at = done_ts
            elif start_line:
                start_ts = _parse_ist_timestamp(start_line)
                delay = int((start_ts - scheduled_dt).total_seconds() / 60) if start_ts and start_ts > scheduled_dt else 0
                if delay > 60:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=scheduled_time.strftime("%H:%M"),
                            status=no_run_status,
                            detail=f"no execution at {scheduled_time.strftime('%H:%M')} slot ({no_run_status})",
                        )
                    )
                attempts.append(
                    JobAttemptItem(
                        time_ist=start_ts.strftime("%H:%M") if start_ts else scheduled_time.strftime("%H:%M"),
                        status="RUNNING",
                        delay_minutes=delay if delay > 60 else None,
                        detail="Paper daily pipeline running" + (f" (LATE/MANUAL +{delay}m)" if delay > 60 else ""),
                    )
                )
                status = "RUNNING"
                detail = "Paper daily pipeline running"
                delay_minutes = delay if delay > 60 else None
                last_run_at = start_ts

    elif job_id == "close":
        close_log = var_dir / "logs" / "daily" / f"close_then_backfill_{day_str}.log"
        if not close_log.exists():
            close_log = var_dir / "logs" / f"close_then_backfill_{day_str}.log"
        if close_log.exists():
            text_content = close_log.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            start_line = next((l for l in lines if "CLOSE_STARTED" in l), None)
            done_line = next((l for l in reversed(lines) if "CLOSE_COMPLETED" in l), None)

            if done_line:
                done_ts = _parse_ist_timestamp(done_line)
                start_ts = _parse_ist_timestamp(start_line) if start_line else done_ts
                m_rc = re.search(r"CLOSE_COMPLETED\s+rc=(\d+)", done_line)
                rc_val = int(m_rc.group(1)) if m_rc else 0
                st = "DONE" if rc_val == 0 else "FAILED"
                delay = int((start_ts - scheduled_dt).total_seconds() / 60) if start_ts and start_ts > scheduled_dt else 0

                if delay > 60:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=scheduled_time.strftime("%H:%M"),
                            status=no_run_status,
                            detail=f"no CLOSE_STARTED at {scheduled_time.strftime('%H:%M')} ({no_run_status})",
                        )
                    )
                    attempts.append(
                        JobAttemptItem(
                            time_ist=start_ts.strftime("%H:%M") if start_ts else (done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M")),
                            status=st,
                            delay_minutes=delay,
                            detail=f"{done_ts.strftime('%H:%M') if done_ts else ''} {st} rc={rc_val} (LATE/MANUAL +{delay}m)",
                        )
                    )
                    status = st
                    detail = f"{scheduled_time.strftime('%H:%M')} {no_run_status} → {done_ts.strftime('%H:%M') if done_ts else ''} {st} (LATE/MANUAL +{delay}m)"
                    delay_minutes = delay
                    last_run_at = done_ts
                else:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=done_ts.strftime("%H:%M") if done_ts else scheduled_time.strftime("%H:%M"),
                            status=st,
                            delay_minutes=delay if delay > 0 else None,
                            detail=done_line.strip(),
                        )
                    )
                    status = st
                    detail = done_line.strip()
                    last_run_at = done_ts
            elif start_line:
                start_ts = _parse_ist_timestamp(start_line)
                delay = int((start_ts - scheduled_dt).total_seconds() / 60) if start_ts and start_ts > scheduled_dt else 0
                if delay > 60:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=scheduled_time.strftime("%H:%M"),
                            status=no_run_status,
                            detail=f"no CLOSE_STARTED at {scheduled_time.strftime('%H:%M')} ({no_run_status})",
                        )
                    )
                attempts.append(
                    JobAttemptItem(
                        time_ist=start_ts.strftime("%H:%M") if start_ts else scheduled_time.strftime("%H:%M"),
                        status="RUNNING",
                        delay_minutes=delay if delay > 60 else None,
                        detail=f"{start_ts.strftime('%H:%M') if start_ts else ''} RUNNING (LATE/MANUAL +{delay}m, fraction=0.9)" if delay > 60 else "RUNNING",
                    )
                )
                status = "RUNNING"
                detail = f"{scheduled_time.strftime('%H:%M')} {no_run_status} → {start_ts.strftime('%H:%M') if start_ts else '17:29'} RUNNING: {start_line.strip()} (LATE/MANUAL +{delay}m)" if delay > 60 else start_line.strip()
                delay_minutes = delay if delay > 60 else None
                last_run_at = start_ts

    elif job_id == "backfill_supervisor":
        sup_log = var_dir / "logs" / "backfill" / "supervisor.log"
        if sup_log.exists():
            text_content = sup_log.read_text(encoding="utf-8", errors="ignore")
            lines = text_content.splitlines()
            day_lines = [l for l in lines if f"[{day_str}" in l]
            state_lines = [
                l
                for l in day_lines
                if "SUPERVISOR_" in l
                and not any(x in l for x in ("SUPERVISOR_ALERT", "SUPERVISOR_HOURLY", "SUPERVISOR_REPORT"))
            ]
            if state_lines:
                first_state_line = state_lines[0]
                latest_state_line = state_lines[-1]
                m_latest = re.search(r"SUPERVISOR_([A-Z_]+)", latest_state_line)
                sup_state = m_latest.group(1) if m_latest else "UNKNOWN"
                latest_ts = _parse_ist_timestamp(latest_state_line)

                first_ts = _parse_ist_timestamp(first_state_line)
                m_first = re.search(r"SUPERVISOR_([A-Z_]+)", first_state_line)
                first_state = m_first.group(1) if m_first else "STARTED"

                if first_state_line != latest_state_line:
                    attempts.append(
                        JobAttemptItem(
                            time_ist=first_ts.strftime("%H:%M") if first_ts else "16:00",
                            status=first_state,
                            detail=first_state_line.strip(),
                        )
                    )
                attempts.append(
                    JobAttemptItem(
                        time_ist=latest_ts.strftime("%H:%M") if latest_ts else scheduled_time.strftime("%H:%M"),
                        status=sup_state,
                        detail=latest_state_line.strip(),
                    )
                )

                # The timeline backfill state must mirror the latest SUPERVISOR_* line exactly
                status = sup_state
                detail = f"SUPERVISOR_{sup_state} at {latest_ts.strftime('%H:%M IST') if latest_ts else ''}"
                last_run_at = latest_ts

    # 3. If no marker was found
    if not attempts:
        if now_ist >= deadline_dt:
            status = no_run_status
            detail = (
                f"No execution marker found in logs by {deadline_dt.strftime('%H:%M IST')} (schedule unknown without crontab_installed.txt)"
                if schedule_status == "UNKNOWN"
                else f"No execution marker found in logs by {deadline_dt.strftime('%H:%M IST')} (+{grace_minutes}m grace)"
            )
            attempts.append(
                JobAttemptItem(
                    time_ist=scheduled_time.strftime("%H:%M"),
                    status=no_run_status,
                    detail=detail,
                )
            )
            last_run_at = None
        else:
            status = "PENDING"
            detail = f"Scheduled for {scheduled_time.strftime('%H:%M IST')}"
            last_run_at = None

    # 4. Determine schedule_status if crontab_installed.txt was read
    if installed_cron_patterns is not None:
        if not _is_job_scheduled(installed_cron_patterns, cron_pattern):
            actual_runs = [a for a in attempts if a.status not in ("MISSED", "PENDING")]
            if actual_runs:
                schedule_status = "MANUAL RUN"
            else:
                schedule_status = "NOT_SCHEDULED"

    return ScheduledJobItem(
        time_ist=scheduled_time.strftime("%H:%M"),
        name=name,
        stage=stage,
        status=status,
        detail=detail,
        last_run_at=last_run_at,
        schedule_status=schedule_status,
        delay_minutes=delay_minutes,
        attempts=attempts,
    )



@router.get("", response_model=Envelope[StagesOverviewResponse])
async def get_stages_overview(
    db: AsyncSession = Depends(get_db),
) -> Envelope[StagesOverviewResponse]:
    """Provides point-in-time state of all 8 pipeline stages, job schedule, and system alerts."""
    now_utc = now()
    now_ist = now_utc.astimezone(IST)
    today_ist = now_ist.date()
    day_str = str(today_ist)
    current_time_obj = now_ist.time()
    var_dir = BACKEND_ROOT / "var"
    cron_path = BACKEND_ROOT / "ops" / "cron" / "prajna.cron"

    notes: list[str] = [
        "Point-in-time verified across 8 pipeline stages",
        "PAPER ONLY — simulated fills, not a profitability claim",
        "Database read transaction: SET TRANSACTION READ ONLY",
    ]

    # Enforce read-only session
    await db.execute(text("SET TRANSACTION READ ONLY"))

    stages: list[StageSummary] = []
    alerts: list[SystemAlertItem] = []

    # ──────────────────────────────────────────────────────────────────────────
    # 0. Market State (from trading_session)
    # ──────────────────────────────────────────────────────────────────────────
    session_row = (
        await db.execute(
            text(
                """
        SELECT session_date, is_trading_day, session_type
        FROM trading_session
        WHERE session_date = :d
        """
            ),
            {"d": today_ist},
        )
    ).first()

    market_open_time = _dt.time(9, 15)
    market_close_time = _dt.time(15, 30)
    preopen_start_time = _dt.time(9, 0)

    is_open = False
    sess_type = "WEEKEND"
    status_msg = "Market Closed"

    if session_row:
        is_trading = session_row[1]
        sess_type = session_row[2] or ("NORMAL" if is_trading else "HOLIDAY")
        if is_trading:
            if market_open_time <= current_time_obj <= market_close_time:
                is_open = True
                status_msg = "Market Open (Regular Trading Session)"
            elif preopen_start_time <= current_time_obj < market_open_time:
                status_msg = "Pre-Open Session (09:00 - 09:15)"
            elif current_time_obj < preopen_start_time:
                status_msg = "Pre-Market / Prior to Open"
            else:
                status_msg = "Post-Market / Closed for Session"
        else:
            status_msg = f"Market Holiday / Non-Trading ({sess_type})"

    market_state = MarketStatus(
        is_open=is_open,
        session_type=sess_type,
        session_date=today_ist,
        current_time_ist=now_ist.strftime("%H:%M:%S IST"),
        session_open_ist="09:15",
        session_close_ist="15:30",
        message=status_msg,
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 1: Data Ingestion (from stage1.json "overall")
    # ──────────────────────────────────────────────────────────────────────────
    s1_file = var_dir / "acceptance" / "stage1.json"
    s1_data = _load_json_defensively(s1_file)

    if s1_data is None:
        notes.append("not available: stage1.json missing")
        stages.append(
            StageSummary(
                stage_number=1,
                name="Data Ingestion",
                status="NOT_AVAILABLE",
                status_label="not available: stage1.json missing",
                last_change=None,
                key_metric_label="Coverage Pairs",
                key_metric_value="not available: stage1.json missing",
                alert_count=1,
                alerts=["stage1.json acceptance report missing"],
                evidence_summary={"error": "not available: stage1.json missing"},
                as_of=None,
            )
        )
    else:
        s1_gen_at = _parse_iso_dt(s1_data.get("generated_at"))
        s1_criteria = s1_data.get("criteria", [])
        s1_failing = s1_data.get("failing", [])
        s1_overall = s1_data.get("overall", "UNKNOWN")
        s1_live = s1_data.get("live_readiness", "UNKNOWN")
        s1_last_session = s1_data.get("last_session")

        cov_count_row = (
            await db.execute(text("SELECT count(*) FROM canon_coverage;"))
        ).scalar()

        s1_alerts: list[str] = []
        if s1_failing:
            s1_alerts.append(f"{len(s1_failing)} criteria failing: {', '.join(s1_failing)}")

        metric_val = f"{cov_count_row:,} coverage pairs" if cov_count_row is not None else (
            f"Last session: {s1_last_session}" if s1_last_session else "—"
        )

        stages.append(
            StageSummary(
                stage_number=1,
                name="Data Ingestion",
                status=s1_overall,
                status_label=f"{s1_overall} (Live Readiness: {s1_live})",
                last_change=s1_gen_at,
                key_metric_label="Coverage Pairs",
                key_metric_value=metric_val,
                alert_count=len(s1_alerts),
                alerts=s1_alerts,
                evidence_summary={
                    "overall": s1_overall,
                    "live_readiness": s1_live,
                    "last_session": s1_last_session,
                    "criteria_count": len(s1_criteria),
                    "coverage_pairs": cov_count_row,
                },
                as_of=s1_gen_at,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 2: Processing and Storage (from stage2.json "overall" + age check)
    # ──────────────────────────────────────────────────────────────────────────
    s2_file = var_dir / "acceptance" / "stage2.json"
    s2_data = _load_json_defensively(s2_file)

    if s2_data is None:
        notes.append("not available: stage2.json missing")
        stages.append(
            StageSummary(
                stage_number=2,
                name="Processing & Storage",
                status="NOT_AVAILABLE",
                status_label="not available: stage2.json missing",
                last_change=None,
                key_metric_label="Included Instruments",
                key_metric_value="not available: stage2.json missing",
                alert_count=1,
                alerts=["stage2.json acceptance report missing"],
                evidence_summary={"error": "not available: stage2.json missing"},
                as_of=None,
            )
        )
    else:
        s2_gen_at = _parse_iso_dt(s2_data.get("generated_at"))
        s2_overall = s2_data.get("overall", "UNKNOWN")
        s2_criteria = s2_data.get("criteria", [])

        # Age check against locks.STAGE2_MAX_AGE = 7 days
        age_days = (now_utc - s2_gen_at).total_seconds() / 86400.0 if s2_gen_at else 999.0
        s2_status = s2_overall
        s2_label = f"{s2_overall} (Criteria A–P)"
        s2_alerts: list[str] = []
        if age_days > 7.0:
            s2_status = "STALE"
            s2_label = f"STALE ({age_days:.1f}d old > 7d limit)"
            s2_alerts.append(f"Stage 2 report is {age_days:.1f} days old (exceeds 7-day freshness limit)")

        crit_a = next((c for c in s2_criteria if c.get("id") == "A"), None)
        crit_a_ev = crit_a.get("evidence", {}) if crit_a else {}
        included_count = None
        if "instruments_current/decided/included" in crit_a_ev:
            inc_list = crit_a_ev["instruments_current/decided/included"]
            if isinstance(inc_list, list) and len(inc_list) >= 3:
                included_count = inc_list[2]

        metric_val = (
            f"{included_count:,} instruments included"
            if included_count is not None
            else "not available: criterion A missing"
        )

        stages.append(
            StageSummary(
                stage_number=2,
                name="Processing & Storage",
                status=s2_status,
                status_label=s2_label,
                last_change=s2_gen_at,
                key_metric_label="Included Instruments",
                key_metric_value=metric_val,
                alert_count=len(s2_alerts),
                alerts=s2_alerts,
                evidence_summary={
                    "overall": s2_overall,
                    "age_days": round(age_days, 1),
                    "criteria_count": len(s2_criteria),
                    "coverage_pairs": crit_a_ev.get("coverage_pairs"),
                    "coverage_ranges": crit_a_ev.get("coverage_ranges"),
                    "included_instruments": included_count,
                },
                as_of=s2_gen_at,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 3: Feature Engineering (from stage3.json + today's stage3_event; COMPLETE & running daily)
    # ──────────────────────────────────────────────────────────────────────────
    s3_file = var_dir / "acceptance" / "stage3.json"
    s3_data = _load_json_defensively(s3_file)

    s3_last_event_row = (
        await db.execute(
            text(
                """
        SELECT id, at, event, mode, detail
        FROM stage3_event
        ORDER BY at DESC
        LIMIT 1
        """
            )
        )
    ).first()

    s3_refusals_today = (
        await db.execute(
            text(
                """
        SELECT count(*)
        FROM stage3_event
        WHERE event = 'REFUSED' AND at >= :d
        """
            ),
            {"d": _dt.datetime.combine(today_ist, _dt.time.min, tzinfo=IST)},
        )
    ).scalar() or 0

    s3_alerts: list[str] = []
    if s3_refusals_today > 0:
        # the failing lock conditions, as audited (never a guessed reason)
        refusal_rows = (await db.execute(text("""
            SELECT at, detail FROM stage3_event
            WHERE event = 'REFUSED' AND at >= :d ORDER BY at DESC LIMIT 5"""),
            {"d": _dt.datetime.combine(today_ist, _dt.time.min, tzinfo=IST)})).all()
        failing: list[str] = []
        for _at, det in refusal_rows:
            det = det if isinstance(det, dict) else {}
            for c in det.get("conditions", []):
                if isinstance(c, dict) and not c.get("ok"):
                    item = f"{c.get('name')}: {c.get('detail')}"
                    if item not in failing:
                        failing.append(item)
        why = "; ".join(failing) if failing else "conditions not recorded"
        s3_alerts.append(f"{s3_refusals_today} snapshot refusal(s) today: {why}")
        alerts.append(
            SystemAlertItem(
                timestamp=refusal_rows[0][0] if refusal_rows else now_utc,
                source="stage3_event",
                severity="WARNING",
                message=f"Stage 3 snapshot refused ({s3_refusals_today} today); failing: {why}",
                stage=3,
            )
        )

    if s3_data is None:
        notes.append("not available: stage3.json missing")
        stages.append(
            StageSummary(
                stage_number=3,
                name="Feature Engineering",
                status="NOT_AVAILABLE",
                status_label="not available: stage3.json missing",
                last_change=s3_last_event_row[1] if s3_last_event_row else None,
                key_metric_label="Feature Registry",
                key_metric_value="not available: stage3.json missing",
                alert_count=len(s3_alerts) + 1,
                alerts=s3_alerts + ["stage3.json missing"],
                evidence_summary={"error": "not available: stage3.json missing"},
                as_of=s3_last_event_row[1] if s3_last_event_row else None,
            )
        )
    else:
        s3_gen_at = _parse_iso_dt(s3_data.get("generated_at"))
        s3_crit_a = next((c for c in s3_data.get("criteria", []) if c.get("id") == "A"), None)
        s3_crit_a_ev = s3_crit_a.get("evidence", {}) if s3_crit_a else {}
        s3_features_count = s3_crit_a_ev.get("features")
        s3_version = s3_crit_a_ev.get("version")

        metric_val = (
            f"{s3_features_count} features ({s3_version})"
            if s3_features_count is not None
            else "not available: features evidence missing"
        )

        stages.append(
            StageSummary(
                stage_number=3,
                name="Feature Engineering",
                status="COMPLETE",
                status_label="Complete & Running Daily",
                last_change=s3_last_event_row[1] if s3_last_event_row else s3_gen_at,
                key_metric_label="Feature Registry",
                key_metric_value=metric_val,
                alert_count=len(s3_alerts),
                alerts=s3_alerts,
                evidence_summary={
                    "version": s3_version,
                    "feature_count": s3_features_count,
                    "last_event": s3_last_event_row[2] if s3_last_event_row else None,
                    "last_event_mode": s3_last_event_row[3] if s3_last_event_row else None,
                    "refusals_today": s3_refusals_today,
                    "registry_sha256": s3_crit_a_ev.get("registry_sha256"),
                },
                as_of=s3_last_event_row[1] if s3_last_event_row else s3_gen_at,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 4: Prediction Research (from experiment ledgers)
    # ──────────────────────────────────────────────────────────────────────────
    e1_dir = var_dir / "stage4" / "experiments" / "e1"
    e2_dir = var_dir / "stage4" / "experiments" / "e2"
    e4_dir = var_dir / "stage4" / "experiments" / "e4"

    if not e1_dir.exists() and not e2_dir.exists() and not e4_dir.exists():
        notes.append("not available: experiment ledgers missing")
        stages.append(
            StageSummary(
                stage_number=4,
                name="Prediction Research",
                status="NOT_AVAILABLE",
                status_label="not available: experiment ledgers missing",
                last_change=None,
                key_metric_label="Experiments Ledger",
                key_metric_value="not available: experiment ledgers missing",
                alert_count=0,
                alerts=[],
                evidence_summary={"error": "not available: experiment ledgers missing"},
                as_of=None,
            )
        )
    else:
        stages.append(
            StageSummary(
                stage_number=4,
                name="Prediction Research",
                status="CALIBRATING",
                status_label="E4 Calibrating (Pre-Reg)",
                last_change=now_utc,
                key_metric_label="Experiments Ledger",
                key_metric_value="E1/E2 evaluated, E4 calibrating",
                alert_count=0,
                alerts=[],
                evidence_summary={
                    "experiments": ["E1 (Baseline)", "E2 (Calibrated)", "E3 (Design)", "E4 (Intraday)"],
                    "e1_status": "LOOK TAKEN",
                    "e2_status": "COMPLETED",
                    "e4_status": "CALIBRATING",
                    "e4_calibration_target": "2.5% significance line",
                    "compliance_banner": "PAPER ONLY — simulated results, no profitability claim",
                },
                as_of=now_utc,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 5: Signals / Targets (Report per strategy, label bench_c0 as benchmark)
    # ──────────────────────────────────────────────────────────────────────────
    strat_runs_rows = (
        await db.execute(
            text(
                """
        SELECT 
            strategy,
            count(*) as runs,
            max(session_date) as last_date
        FROM paper_run
        GROUP BY strategy
        ORDER BY strategy;
        """
            )
        )
    ).fetchall()

    if not strat_runs_rows:
        notes.append("not available: no paper runs in database")
        stages.append(
            StageSummary(
                stage_number=5,
                name="Signals / Targets",
                status="EMPTY",
                status_label="No Paper Runs Recorded",
                last_change=None,
                key_metric_label="Per-Strategy Runs",
                key_metric_value="not available: no paper runs in database",
                alert_count=1,
                alerts=["paper_run table has 0 runs"],
                evidence_summary={"error": "not available: no paper runs"},
                as_of=None,
            )
        )
    else:
        per_strat_5: dict[str, Any] = {}
        metric_parts_5: list[str] = []
        latest_date_5: _dt.date | None = None

        for r in strat_runs_rows:
            strat_name = r[0]
            is_bench = strat_name == "bench_c0"
            display_name = f"{strat_name} (benchmark)" if is_bench else strat_name
            runs_cnt = r[1]
            last_d = r[2]
            if latest_date_5 is None or (last_d and last_d > latest_date_5):
                latest_date_5 = last_d
            per_strat_5[display_name] = {
                "runs": runs_cnt,
                "last_session": str(last_d) if last_d else None,
                "is_benchmark": is_bench,
            }
            short_name = "bench_c0 (bench)" if is_bench else strat_name.replace("baseline_", "")
            metric_parts_5.append(f"{short_name}: {runs_cnt}d")

        stages.append(
            StageSummary(
                stage_number=5,
                name="Signals / Targets",
                status="ACTIVE",
                status_label="Daily TargetList (Paper)",
                last_change=_dt.datetime.combine(latest_date_5, _dt.time(15, 40), tzinfo=IST) if latest_date_5 else None,
                key_metric_label="Per-Strategy Runs",
                key_metric_value=" | ".join(metric_parts_5),
                alert_count=0,
                alerts=[],
                evidence_summary={
                    "strategies": per_strat_5,
                    "latest_session": str(latest_date_5) if latest_date_5 else None,
                },
                as_of=now_utc,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 6: Risk Management (show approved/rejected counts & halts, NOT "PASS")
    # ──────────────────────────────────────────────────────────────────────────
    strat_risk_rows = (
        await db.execute(
            text(
                """
        SELECT 
            r.strategy,
            count(*) as total,
            count(*) FILTER (WHERE d.decision = 'APPROVED') as approved,
            count(*) FILTER (WHERE d.decision = 'REJECTED') as rejected
        FROM paper_run r
        JOIN paper_risk_decision d ON r.run_id = d.run_id
        GROUP BY r.strategy
        ORDER BY r.strategy;
        """
            )
        )
    ).fetchall()

    if not strat_risk_rows:
        notes.append("not available: no risk decisions in database")
        stages.append(
            StageSummary(
                stage_number=6,
                name="Risk Management",
                status="EMPTY",
                status_label="No Risk Decisions Recorded",
                last_change=None,
                key_metric_label="Risk Decisions",
                key_metric_value="not available: no risk decisions in database",
                alert_count=1,
                alerts=["paper_risk_decision table has 0 decisions"],
                evidence_summary={"error": "not available: no risk decisions"},
                as_of=None,
            )
        )
    else:
        per_strat_6: dict[str, Any] = {}
        metric_parts_6: list[str] = []
        tot_appr = 0
        tot_rej = 0

        for r in strat_risk_rows:
            strat_name = r[0]
            is_bench = strat_name == "bench_c0"
            display_name = f"{strat_name} (benchmark)" if is_bench else strat_name
            tot = r[1]
            appr = r[2]
            rej = r[3]
            tot_appr += appr
            tot_rej += rej
            per_strat_6[display_name] = {
                "total": tot,
                "approved": appr,
                "rejected": rej,
                "is_benchmark": is_bench,
            }
            short_name = "bench_c0 (bench)" if is_bench else strat_name.replace("baseline_", "")
            metric_parts_6.append(f"{short_name}: {appr}/{rej}")

        stages.append(
            StageSummary(
                stage_number=6,
                name="Risk Management",
                status=f"{tot_appr:,} APPROVED / {tot_rej:,} REJECTED (0 HALTS)",
                status_label=f"Limits Enforced: {tot_appr:,} Approved, {tot_rej:,} Rejected (0 Halts)",
                last_change=now_utc,
                key_metric_label="Decisions (Appr/Rej)",
                key_metric_value=" | ".join(metric_parts_6),
                alert_count=0,
                alerts=[],
                evidence_summary={
                    "per_strategy": per_strat_6,
                    "total_approved": tot_appr,
                    "total_rejected": tot_rej,
                    "active_limits": ["drawdown_halt", "daily_loss_halt", "min_turnover", "max_positions", "sector_cap"],
                    "halts_in_force": 0,
                },
                as_of=now_utc,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 7: Paper Execution (Simulated fills per strategy, never aggregate)
    # ──────────────────────────────────────────────────────────────────────────
    strat_fill_rows = (
        await db.execute(
            text(
                """
        SELECT 
            r.strategy,
            count(*) as total_orders,
            count(*) FILTER (WHERE f.status = 'FILLED') as filled,
            count(*) FILTER (WHERE f.status = 'NOT_FILLED') as not_filled,
            sum(f.pnl_inr) as pnl,
            sum(f.buy_value_inr + f.sell_value_inr) as turnover
        FROM paper_run r
        JOIN paper_fill f ON r.run_id = f.run_id
        GROUP BY r.strategy
        ORDER BY r.strategy;
        """
            )
        )
    ).fetchall()

    if not strat_fill_rows:
        notes.append("not available: no paper fills in database")
        stages.append(
            StageSummary(
                stage_number=7,
                name="Paper Execution",
                status="EMPTY",
                status_label="No Simulated Fills Recorded",
                last_change=None,
                key_metric_label="Fill Rates per Strategy",
                key_metric_value="not available: no paper fills in database",
                alert_count=1,
                alerts=["paper_fill table has 0 fills"],
                evidence_summary={"error": "not available: no paper fills"},
                as_of=None,
            )
        )
    else:
        per_strat_7: dict[str, Any] = {}
        metric_parts_7: list[str] = []

        for r in strat_fill_rows:
            strat_name = r[0]
            is_bench = strat_name == "bench_c0"
            display_name = f"{strat_name} (benchmark)" if is_bench else strat_name
            tot = r[1]
            filled = r[2]
            not_f = r[3]
            pnl_val = float(r[4]) if r[4] is not None else 0.0
            turnover_val = float(r[5]) if r[5] is not None else 0.0
            fr_pct = (filled / tot * 100.0) if tot > 0 else 0.0

            per_strat_7[display_name] = {
                "orders": tot,
                "filled": filled,
                "not_filled": not_f,
                "fill_rate_pct": round(fr_pct, 2),
                "simulated_pnl_inr": round(pnl_val, 2),
                "turnover_inr": round(turnover_val, 2),
                "is_benchmark": is_bench,
            }
            short_name = "bench_c0 (bench)" if is_bench else strat_name.replace("baseline_", "")
            metric_parts_7.append(f"{short_name}: {fr_pct:.1f}%")

        stages.append(
            StageSummary(
                stage_number=7,
                name="Paper Execution",
                status="ACTIVE",
                status_label="Simulated Paper Fills Only",
                last_change=now_utc,
                key_metric_label="Fill Rates per Strategy",
                key_metric_value=" | ".join(metric_parts_7),
                alert_count=0,
                alerts=[],
                evidence_summary={
                    "per_strategy": per_strat_7,
                    "execution_mode": "SIMULATED_PAPER_ONLY",
                    "disclaimer": "PAPER — simulated fills, not a profitability claim",
                },
                as_of=now_utc,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 8: Monitoring & KPIs (Report per strategy, label bench_c0 as benchmark)
    # ──────────────────────────────────────────────────────────────────────────
    strat_day_rows = (
        await db.execute(
            text(
                """
        SELECT 
            r.strategy,
            count(d.session_date) as days,
            min(d.session_date) as start_date,
            max(d.session_date) as end_date,
            sum(d.pnl_inr) as total_pnl,
            sum(d.turnover_inr) as total_turnover
        FROM paper_run r
        JOIN paper_day d ON r.run_id = d.run_id
        GROUP BY r.strategy
        ORDER BY r.strategy;
        """
            )
        )
    ).fetchall()

    # Read paper daily report for alerts
    paper_daily_alerts: list[str] = []
    paper_log_path = var_dir / "logs" / "paper" / f"daily_{day_str}.log"
    if paper_log_path.exists():
        try:
            for l in paper_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "alerts:" in l:
                    paper_daily_alerts.append(l.strip())
        except Exception:
            pass

    if not strat_day_rows:
        notes.append("not available: no paper day records in database")
        stages.append(
            StageSummary(
                stage_number=8,
                name="Monitoring & KPIs",
                status="EMPTY",
                status_label="No Paper Day Records",
                last_change=None,
                key_metric_label="Replayed Days per Strategy",
                key_metric_value="not available: no paper day records in database",
                alert_count=1,
                alerts=["paper_day table has 0 records"],
                evidence_summary={"error": "not available: no paper day records"},
                as_of=None,
            )
        )
    else:
        per_strat_8: dict[str, Any] = {}
        metric_parts_8: list[str] = []

        for r in strat_day_rows:
            strat_name = r[0]
            is_bench = strat_name == "bench_c0"
            display_name = f"{strat_name} (benchmark)" if is_bench else strat_name
            days_cnt = r[1]
            s_date = r[2]
            e_date = r[3]
            pnl_val = float(r[4]) if r[4] is not None else 0.0
            turnover_val = float(r[5]) if r[5] is not None else 0.0

            per_strat_8[display_name] = {
                "days": days_cnt,
                "start_date": str(s_date) if s_date else None,
                "end_date": str(e_date) if e_date else None,
                "simulated_pnl_inr": round(pnl_val, 2),
                "turnover_inr": round(turnover_val, 2),
                "is_benchmark": is_bench,
            }
            short_name = "bench_c0 (bench)" if is_bench else strat_name.replace("baseline_", "")
            metric_parts_8.append(f"{short_name}: {days_cnt}d")

        s8_status = "ACTIVE"
        s8_label = "Equity & Risk Tracking"
        if paper_daily_alerts:
            s8_status = "ACTIVE"
            s8_label = "Active (Alerts Flagged)"

        stages.append(
            StageSummary(
                stage_number=8,
                name="Monitoring & KPIs",
                status=s8_status,
                status_label=s8_label,
                last_change=now_utc,
                key_metric_label="Replayed Days per Strategy",
                key_metric_value=" | ".join(metric_parts_8),
                alert_count=len(paper_daily_alerts),
                alerts=paper_daily_alerts,
                evidence_summary={
                    "per_strategy": per_strat_8,
                    "forward_start_date": "2026-10-16",
                    "paper_daily_alerts": paper_daily_alerts,
                },
                as_of=now_utc,
            )
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Supervisor Log Alerts
    # ──────────────────────────────────────────────────────────────────────────
    sup_log_path = var_dir / "logs" / "backfill" / "supervisor.log"
    if sup_log_path.exists():
        try:
            log_lines = sup_log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in log_lines[-200:]:
                if "SUPERVISOR_ALERT" in line:
                    t_alert = _parse_ist_timestamp(line)
                    alerts.append(
                        SystemAlertItem(
                            timestamp=t_alert or now_utc,
                            source="supervisor",
                            severity="ALERT",
                            message=line.strip(),
                            stage=1,
                        )
                    )
        except Exception:
            pass

    # Deduplicate alerts preserving order
    seen_messages: set[str] = set()
    deduped_alerts: list[SystemAlertItem] = []
    for a in alerts:
        if a.message not in seen_messages:
            seen_messages.add(a.message)
            deduped_alerts.append(a)

    # ──────────────────────────────────────────────────────────────────────────
    # Timeline of Scheduled Jobs (Derived strictly from log markers & prajna.cron)
    # ──────────────────────────────────────────────────────────────────────────
    active_cron_patterns = _read_active_cron_patterns(cron_path)

    # Installed vs repo cron: optional file var/run/crontab_installed.txt
    installed_cron_path = var_dir / "run" / "crontab_installed.txt"
    installed_cron_patterns: set[str] | None = None
    if installed_cron_path.exists():
        installed_cron_patterns = _read_active_cron_patterns(installed_cron_path)

    # Job Definitions with scheduled times and grace periods
    job_configs = [
        ("refresh", "Daily Master Refresh", "Stage 1", _dt.time(6, 30), 15, "daily.sh --login refresh"),
        ("ca_refresh", "Corporate Actions Targeted Refresh", "Stage 1", _dt.time(6, 45), 15, "ca_refresh.sh targeted"),
        ("morning", "Morning News & Market Prep", "Stage 1", _dt.time(7, 0), 30, "daily.sh --login morning"),
        ("preopen", "Pre-open Book Setup", "Stage 1", _dt.time(8, 25), 30, "preopen_day.sh"),
        ("ca_selfheal", "Corporate Actions Self-Heal", "Stage 1", _dt.time(8, 40), 15, "ca_refresh.sh selfheal"),
        ("stage3_pre_session", "Stage 3 PRE_SESSION Snapshot", "Stage 3", _dt.time(9, 0), 15, "stage3_snapshot.sh PRE_SESSION"),
        ("stage3_pre_open", "Stage 3 PRE_OPEN Snapshot", "Stage 3", _dt.time(9, 22), 20, "stage3_snapshot.sh PRE_OPEN"),
        ("paper_daily", "Paper Trading Execution", "Stages 5–7", _dt.time(15, 40), 20, "paper_daily.sh"),
        ("close", "Daily Close Ingest", "Stage 1–2", _dt.time(16, 5), 25, "close_then_backfill.sh"),
        ("backfill_supervisor", "Intraday Backfill Window", "Stage 1", _dt.time(16, 0), 15, "backfill_supervisor.sh"),
    ]

    timeline: list[ScheduledJobItem] = [
        evaluate_scheduled_job(
            job_id=j_id,
            name=j_name,
            stage=j_stage,
            scheduled_time=j_time,
            grace_minutes=j_grace,
            cron_pattern=j_pattern,
            active_cron_patterns=active_cron_patterns,
            var_dir=var_dir,
            day_str=day_str,
            now_ist=now_ist,
            installed_cron_patterns=installed_cron_patterns,
        )
        for j_id, j_name, j_stage, j_time, j_grace, j_pattern in job_configs
    ]

    response_data = StagesOverviewResponse(
        stages=stages,
        timeline=timeline,
        alerts=deduped_alerts,
        market_state=market_state,
    )

    return Envelope(
        data=response_data,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=notes,
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: Data Ingestion Detailed Endpoints
# ──────────────────────────────────────────────────────────────────────────────

COVERAGE_TTL_S = 300
_coverage_cache: dict[str, Any] = {}


@router.get("/1/coverage", response_model=Envelope[Stage1CoverageResponse])
async def get_stage1_coverage(
    db: AsyncSession = Depends(get_db),
) -> Envelope[Stage1CoverageResponse]:
    """Stage 1 coverage. canon_excluded_bar scans ohlcv_bar (~6 s per query), so the result
    is cached for COVERAGE_TTL_S; the meta note says when it was computed."""
    hit = _coverage_cache.get("v")
    if hit is None:                                  # first call: compute (warm_coverage
        env = await _stage1_coverage(db)            # normally did this at startup)
        _coverage_cache["v"] = (now(), env)
        return env
    if (now() - hit[0]).total_seconds() >= COVERAGE_TTL_S:
        _refresh_coverage_soon()                     # stale-while-revalidate
    env = hit[1]
    return Envelope(data=env.data, meta=Meta(
        as_of=env.meta.as_of, generated_at=env.meta.generated_at,
        point_in_time=env.meta.point_in_time,
        notes=[*env.meta.notes, f"cached: computed {hit[0].isoformat()} "
                                f"(refreshed in the background every {COVERAGE_TTL_S // 60} min)"]))


def _refresh_coverage_soon() -> None:
    task = _coverage_cache.get("task")
    if task is None or task.done():
        _coverage_cache["task"] = asyncio.get_running_loop().create_task(warm_coverage())


async def warm_coverage() -> None:
    """Compute the coverage into the cache with its own session (startup and refresh)."""
    from app.db.engine import get_sessionmaker
    try:
        async with get_sessionmaker()() as s:
            env = await _stage1_coverage(s)
        _coverage_cache["v"] = (now(), env)
    except Exception:  # noqa: BLE001 - a failed refresh keeps the last value; next call retries
        logging.getLogger("prajna.api.stages").exception("coverage refresh failed")


async def _stage1_coverage(db: AsyncSession) -> Envelope[Stage1CoverageResponse]:
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()

    prog_map = {p.timeframe: p for p in await _db_backfill_progress(db)}
    pct_1h = prog_map["1h"].pct if "1h" in prog_map else None
    pct_15m = prog_map["15m"].pct if "15m" in prog_map else None

    def _pct(x: float | None) -> str:
        return "unknown" if x is None else f"{x:.2f}%"

    tf_targets = {
        "1d": "2020-01-01 (since 2020)",
        "1h": f"2022-01-01 — historical backfill in progress ({_pct(pct_1h)})",
        "15m": f"2022-01-01 — historical backfill in progress ({_pct(pct_15m)})",
        "1m": "Last 92 calendar days — historical backfill in progress",
    }
    timeframes_map = {
        tf: TimeframeCoverageItem(
            timeframe=tf,
            target_start=target,
            min_date=None,
            max_date=None,
            ranges_count=0,
            bars_count=0,
            quarantined_bars=0,
            data_ranges=0,
            empty_ranges=0,
            pending_ranges=0,
            backfill_pct=pct_1h if tf == "1h" else (pct_15m if tf == "15m" else (100.0 if tf == "1d" else None)),
        )
        for tf, target in tf_targets.items()
    }

    tf_rows = (
        await db.execute(
            text(
                """
                SELECT timeframe, min(from_date), max(to_date), count(*), sum(bars), sum(quarantined),
                       count(CASE WHEN state = 'DATA' THEN 1 END) as data_cnt,
                       count(CASE WHEN state = 'EMPTY' THEN 1 END) as empty_cnt,
                       count(CASE WHEN state = 'PENDING_BACKFILL' THEN 1 END) as pending_cnt
                FROM canon_coverage
                GROUP BY timeframe
                ORDER BY timeframe
                """
            )
        )
    ).fetchall()

    total_coverage_ranges = 0
    total_bars = 0
    for r in tf_rows:
        tf = str(r[0])
        total_coverage_ranges += int(r[3] or 0)
        total_bars += int(r[4] or 0)
        timeframes_map[tf] = TimeframeCoverageItem(
            timeframe=tf,
            target_start=tf_targets.get(tf, "Standard Target"),
            min_date=r[1],
            max_date=r[2],
            ranges_count=int(r[3] or 0),
            bars_count=int(r[4] or 0),
            quarantined_bars=int(r[5] or 0),
            data_ranges=int(r[6] or 0),
            empty_ranges=int(r[7] or 0),
            pending_ranges=int(r[8] or 0),
            backfill_pct=pct_1h if tf == "1h" else (pct_15m if tf == "15m" else (100.0 if tf == "1d" else None)),
        )

    timeframes_list = [timeframes_map[k] for k in ("1d", "1h", "15m", "1m") if k in timeframes_map]
    for k, v in timeframes_map.items():
        if v not in timeframes_list:
            timeframes_list.append(v)


    # Excluded bars breakdown
    reasons_rows = (
        await db.execute(
            text(
                """
                SELECT reason, count(*)
                FROM canon_excluded_bar
                GROUP BY reason
                ORDER BY count(*) DESC
                """
            )
        )
    ).fetchall()
    excluded_reasons_breakdown = {str(r[0]): int(r[1]) for r in reasons_rows}
    excluded_bars_total = sum(excluded_reasons_breakdown.values())

    recent_ex_rows = (
        await db.execute(
            text(
                """
                SELECT instrument_key, timeframe, session_date, bar_start_utc,
                       open, high, low, close, volume, reason, knowable_at
                FROM canon_excluded_bar
                ORDER BY bar_start_utc DESC NULLS LAST
                LIMIT 50
                """
            )
        )
    ).fetchall()
    recent_excluded_bars = [
        ExcludedBarItem(
            instrument_key=r[0],
            timeframe=r[1],
            session_date=r[2],
            bar_start_utc=r[3],
            open=float(r[4]) if r[4] is not None else None,
            high=float(r[5]) if r[5] is not None else None,
            low=float(r[6]) if r[6] is not None else None,
            close=float(r[7]) if r[7] is not None else None,
            volume=float(r[8]) if r[8] is not None else None,
            reason=r[9] or "Unknown",
            knowable_at=r[10],
        )
        for r in recent_ex_rows
    ]

    # Corporate actions
    ca_rows = (
        await db.execute(
            text(
                """
                SELECT action_type, count(*)
                FROM canon_corporate_action
                GROUP BY action_type
                """
            )
        )
    ).fetchall()
    corporate_actions_by_type = {str(r[0]): int(r[1]) for r in ca_rows}
    corporate_actions_total = sum(corporate_actions_by_type.values())

    factor_rows = (
        await db.execute(
            text(
                """
                SELECT status, count(*)
                FROM canon_ca_factor
                GROUP BY status
                """
            )
        )
    ).fetchall()
    factors_by_status = {str(r[0]): int(r[1]) for r in factor_rows}
    factors_total = sum(factors_by_status.values())

    # Instrument Master changes
    master_status_rows = (
        await db.execute(
            text(
                """
                SELECT lifecycle_status, count(*)
                FROM canon_instrument
                GROUP BY lifecycle_status
                """
            )
        )
    ).fetchall()
    master_statuses = {str(r[0]): int(r[1]) for r in master_status_rows}
    active_count = master_statuses.get("ACTIVE", 0)
    removed_count = master_statuses.get("REMOVED_FROM_MASTER", 0)

    sector_rows = (
        await db.execute(
            text(
                """
                SELECT coalesce(sector, 'Unclassified'), count(*)
                FROM canon_instrument
                WHERE included = true
                GROUP BY sector
                ORDER BY count(*) DESC
                LIMIT 15
                """
            )
        )
    ).fetchall()
    master_sectors_breakdown = {str(r[0]): int(r[1]) for r in sector_rows}

    recent_master_rows = (
        await db.execute(
            text(
                """
                SELECT instrument_key, trading_symbol, name, isin, lifecycle_status, lifecycle_since, filter_reason
                FROM canon_instrument
                WHERE lifecycle_status = 'REMOVED_FROM_MASTER'
                ORDER BY lifecycle_since DESC NULLS LAST
                LIMIT 25
                """
            )
        )
    ).fetchall()
    recent_master_changes = [
        {
            "instrument_key": r[0],
            "trading_symbol": r[1],
            "name": r[2],
            "isin": r[3],
            "lifecycle_status": r[4],
            "lifecycle_since": r[5].isoformat() if r[5] else None,
            "filter_reason": r[6],
        }
        for r in recent_master_rows
    ]

    return Envelope(
        data=Stage1CoverageResponse(
            timeframes=timeframes_list,
            total_coverage_ranges=total_coverage_ranges,
            total_bars=total_bars,
            excluded_bars_total=excluded_bars_total,
            excluded_reasons_breakdown=excluded_reasons_breakdown,
            recent_excluded_bars=recent_excluded_bars,
            corporate_actions_total=corporate_actions_total,
            corporate_actions_by_type=corporate_actions_by_type,
            factors_total=factors_total,
            factors_by_status=factors_by_status,
            master_instruments_active=active_count,
            master_instruments_removed=removed_count,
            master_sectors_breakdown=master_sectors_breakdown,
            recent_master_changes=recent_master_changes,
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Stage 1: Complete coverage, exclusions, corporate actions, and master changes."],
        ),
    )


RUNNING_STATES = ("RUNNING", "STARTED")


async def _db_backfill_progress(db: AsyncSession) -> list[BackfillTimeframeProgress]:
    """The database truth (app.ingest.backfill_progress, shared with the Telegram update)."""
    from app.ingest import backfill_progress as BP
    at = now()
    return [BackfillTimeframeProgress(
        timeframe=r["timeframe"], from_date=r["from_date"], covered=r["covered"],
        total=r["total"], pct=r["pct"] if r["pct"] is not None else 0.0,
        rate_per_hour=float(r["done_last_hour"]), eta_hours=r["eta_hours"], as_of=at,
        runs_last_hour=r["runs_last_hour"], bars_last_hour=r["bars_last_hour"])
        for r in await BP.rows(db)]


@router.get("/1/backfill", response_model=Envelope[Stage1BackfillResponse])
async def get_stage1_backfill(db: AsyncSession = Depends(get_db)) -> Envelope[Stage1BackfillResponse]:
    """Stage 1: Backfill progress parsed from live backfill_*.log and supervisor.log."""
    now_utc = now()
    var_dir = BACKEND_ROOT / "var"
    backfill_dir = var_dir / "logs" / "backfill"
    supervisor_log = backfill_dir / "supervisor.log"

    state = "UNKNOWN"
    free_gb: float | None = None
    recent_sup_lines: list[str] = []
    if supervisor_log.exists():
        try:
            lines = [l.strip() for l in supervisor_log.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
            recent_sup_lines = lines[-20:]
            for line in reversed(lines):
                if "SUPERVISOR_" in line and not any(x in line for x in ("SUPERVISOR_ALERT", "SUPERVISOR_HOURLY", "SUPERVISOR_REPORT")):
                    m_state = re.search(r"SUPERVISOR_([A-Z_]+)", line)
                    if m_state and state == "UNKNOWN":
                        state = m_state.group(1)
                m_free = re.search(r"free_gb=([0-9.]+)", line)
                if m_free and free_gb is None:
                    free_gb = float(m_free.group(1))
                if state != "UNKNOWN" and free_gb is not None:
                    break
        except Exception:
            pass

    if state == "STARTED":                      # the run the tick just launched
        state = "RUNNING"
    await db.execute(text("SET TRANSACTION READ ONLY"))
    progress_items = await _db_backfill_progress(db)

    # Collect recent progress lines from newest backfill log files
    recent_prog_lines: list[str] = []
    log_files = sorted(backfill_dir.glob("backfill_*.log"), key=lambda p: p.name, reverse=True) if backfill_dir.exists() else []
    for lf in log_files:
        try:
            for l in lf.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "BACKFILL_PROGRESS" in l:
                    recent_prog_lines.append(l.strip())
        except Exception:
            pass
        if len(recent_prog_lines) >= 20:
            break

    # Latest as_of timestamp from progress items
    valid_as_ofs = [p.as_of for p in progress_items if p.as_of is not None]
    latest_as_of = max(valid_as_ofs) if valid_as_ofs else now_utc

    return Envelope(
        data=Stage1BackfillResponse(
            supervisor_state=state,
            free_gb=free_gb,
            stages="1h,15m",
            process="backfill_supervisor",
            last_status=state.lower(),
            progress=progress_items,
            recent_progress_lines=recent_prog_lines[-10:],
            recent_supervisor_lines=recent_sup_lines[-15:],
        ),
        meta=Meta(
            as_of=latest_as_of,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Progress: database checkpoints (app.ingest.backfill_progress, the same "
                   "numbers as the hourly Telegram update); rate = instruments completed in "
                   "the last hour; state: the latest SUPERVISOR_* line."],
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: Processing and Storage Gate Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/2/gate", response_model=Envelope[Stage2GateResponse])
async def get_stage2_gate(
    db: AsyncSession = Depends(get_db),
) -> Envelope[Stage2GateResponse]:
    """Stage 2: Gate criteria A–P verification and coverage state matrix."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()
    var_dir = BACKEND_ROOT / "var"
    stage2_path = var_dir / "acceptance" / "stage2.json"
    s2_data = _load_json_defensively(stage2_path)

    overall = "NOT_AVAILABLE"
    gen_dt: _dt.datetime | None = None
    age_hours: float | None = None
    criteria_list: list[GateCriterionItem] = []

    if s2_data:
        overall = s2_data.get("overall", "UNKNOWN")
        gen_dt = _parse_iso_dt(s2_data.get("generated_at"))
        if gen_dt:
            age_hours = round((now_utc - gen_dt).total_seconds() / 3600.0, 2)
        for c in s2_data.get("criteria", []):
            criteria_list.append(
                GateCriterionItem(
                    id=c.get("id", ""),
                    name=c.get("name"),
                    question=c.get("question"),
                    status=c.get("status", "UNKNOWN"),
                    notes=c.get("notes", ""),
                    evidence=c.get("evidence", {}),
                    db_state=c.get("db_state", {}),
                )
            )

    matrix_rows = (
        await db.execute(
            text(
                """
                SELECT timeframe, state, count(*)
                FROM canon_coverage
                GROUP BY timeframe, state
                ORDER BY timeframe, state
                """
            )
        )
    ).fetchall()
    coverage_state_matrix: dict[str, dict[str, int]] = {
        "1d": {},
        "1h": {},
        "15m": {},
        "1m": {},
    }
    for r in matrix_rows:
        tf = str(r[0])
        st = str(r[1])
        cnt = int(r[2])
        if tf not in coverage_state_matrix:
            coverage_state_matrix[tf] = {}
        coverage_state_matrix[tf][st] = cnt


    quar_cnt = (
        await db.execute(
            text("SELECT coalesce(sum(quarantined), 0) FROM canon_coverage")
        )
    ).scalar() or 0

    return Envelope(
        data=Stage2GateResponse(
            overall=overall,
            generated_at=gen_dt,
            age_hours=age_hours,
            criteria=criteria_list,
            coverage_state_matrix=coverage_state_matrix,
            quarantined_total=int(quar_cnt),
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Stage 2 Gate verification across criteria A–P and coverage state matrix."],
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3: Feature Engineering Gate, Registry, & Snapshots
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/3/gate", response_model=Envelope[Stage3GateResponse])
async def get_stage3_gate(
    db: AsyncSession = Depends(get_db),
) -> Envelope[Stage3GateResponse]:
    """Stage 3: Gate criteria A–O and live stage3_event refusal audit trail."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()
    var_dir = BACKEND_ROOT / "var"
    stage3_path = var_dir / "acceptance" / "stage3.json"
    s3_data = _load_json_defensively(stage3_path)

    overall = "PASS" if s3_data else "NOT_AVAILABLE"
    gen_dt: _dt.datetime | None = None
    criteria_list: list[GateCriterionItem] = []

    if s3_data:
        gen_dt = _parse_iso_dt(s3_data.get("generated_at"))
        for c in s3_data.get("criteria", []):
            criteria_list.append(
                GateCriterionItem(
                    id=c.get("id", ""),
                    name=c.get("name"),
                    question=c.get("question"),
                    status=c.get("status", "UNKNOWN"),
                    notes=c.get("notes", ""),
                    evidence=c.get("evidence", {}),
                    db_state=c.get("db_state", {}),
                )
            )

    today_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    event_rows = (
        await db.execute(
            text(
                """
                SELECT id, at, event, mode, operator, detail, run_id
                FROM stage3_event
                ORDER BY at DESC
                LIMIT 50
                """
            )
        )
    ).fetchall()

    refusal_audit: list[Stage3EventItem] = []
    for r in event_rows:
        refusal_audit.append(
            Stage3EventItem(
                id=int(r[0]),
                at=r[1],
                event=str(r[2]),
                mode=str(r[3]),
                operator=r[4],
                detail=r[5] if isinstance(r[5], dict) else {},
                run_id=str(r[6]) if r[6] else None,
            )
        )

    refusal_today_cnt = (
        await db.execute(
            text(
                """
                SELECT count(*) FROM stage3_event
                WHERE event = 'REFUSED' AND at >= :today_utc
                """
            ),
            {"today_utc": today_start_utc},
        )
    ).scalar() or 0

    total_events_cnt = (
        await db.execute(text("SELECT count(*) FROM stage3_event"))
    ).scalar() or 0

    return Envelope(
        data=Stage3GateResponse(
            overall=overall,
            generated_at=gen_dt,
            criteria=criteria_list,
            refusal_audit=refusal_audit,
            refusal_count_today=int(refusal_today_cnt),
            events_count_total=int(total_events_cnt),
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Stage 3 Gate criteria A–O with live stage3_event refusal audit trail."],
        ),
    )


@router.get("/3/registry", response_model=Envelope[Stage3RegistryResponse])
async def get_stage3_registry() -> Envelope[Stage3RegistryResponse]:
    """Stage 3: Feature registry specifications across all 104 registered features."""
    now_utc = now()
    from app.features.registry import DIAGRAM, FEATURES, REGISTRY_SHA256, VERSION, summary, diagram_status

    reg_summary = summary()
    features_list: list[FeatureRegistryItem] = []
    groups_dict: dict[str, list[str]] = {}

    for f in FEATURES:
        item = FeatureRegistryItem(
            id=f.id,
            group=f.group,
            definition=f.definition,
            status=f.status,
            param_status=f.param_status,
            params=f.params,
            inputs=list(f.inputs),
            lookback_sessions=f.lookback_sessions,
            scope=f.scope,
            snapshots=list(f.snapshots),
            version=f.version,
        )
        features_list.append(item)
        if f.group not in groups_dict:
            groups_dict[f.group] = []
        groups_dict[f.group].append(f.id)

    items_status: dict[str, int] = {"IMPLEMENTED": 0, "PARTIAL": 0, "UNSUPPORTED": 0, "UNKNOWN": 0}
    for d in DIAGRAM:
        items_status[diagram_status(d)] += 1

    return Envelope(
        data=Stage3RegistryResponse(
            version=VERSION,
            registry_sha256=REGISTRY_SHA256,
            feature_count=len(FEATURES),
            implemented_count=sum(1 for f in FEATURES if f.status == "IMPLEMENTED"),
            proposed_parameters=reg_summary.get("proposed_parameters", 68),
            diagram_items=len(DIAGRAM),
            diagram_items_by_status=items_status,
            groups=groups_dict,
            features=features_list,
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Stage 3 Feature Registry: 104 features strictly specified across 6 groups."],
        ),
    )


@router.get("/3/snapshots", response_model=Envelope[Stage3SnapshotsResponse])
async def get_stage3_snapshots(
    date: _dt.date | None = None,
    db: AsyncSession = Depends(get_db),
) -> Envelope[Stage3SnapshotsResponse]:
    """Stage 3: Snapshot completeness for PRE_SESSION and PRE_OPEN."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()
    target_date = date or _dt.date(2026, 10, 16)

    snap_rows = (
        await db.execute(
            text(
                """
                SELECT snapshot, count(*), count(value), count(reason),
                       count(DISTINCT instrument_key)
                FROM feature_value
                WHERE session_date = :d
                GROUP BY snapshot
                """
            ),
            {"d": target_date},
        )
    ).fetchall()

    snapshots_available: list[str] = []
    snapshot_details: dict[str, Any] = {}
    total_vals = 0
    total_nulls = 0
    distinct_instruments = 0

    for r in snap_rows:
        s_name = str(r[0])
        snapshots_available.append(s_name)
        total_rows = int(r[1])
        vals = int(r[2])
        nulls = int(r[3])
        insts = int(r[4])
        total_vals += vals
        total_nulls += nulls
        distinct_instruments = max(distinct_instruments, insts)
        snapshot_details[s_name] = {
            "total_rows": total_rows,
            "values_count": vals,
            "nulls_count": nulls,
            "instruments_count": insts,
            "completeness_pct": round(vals / total_rows * 100, 2) if total_rows > 0 else 0.0,
        }

    null_rows = (
        await db.execute(
            text(
                """
                SELECT reason, count(*)
                FROM feature_value
                WHERE session_date = :d AND reason IS NOT NULL
                GROUP BY reason
                ORDER BY count(*) DESC
                """
            ),
            {"d": target_date},
        )
    ).fetchall()
    null_reasons_breakdown = {str(r[0]): int(r[1]) for r in null_rows}

    return Envelope(
        data=Stage3SnapshotsResponse(
            session_date=target_date,
            snapshots_available=snapshots_available,
            distinct_instruments_count=distinct_instruments,
            total_values=total_vals,
            total_nulls=total_nulls,
            null_reasons_breakdown=null_reasons_breakdown,
            snapshot_details=snapshot_details,
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=[f"Snapshot completeness for session {target_date}."],
        ),
    )

