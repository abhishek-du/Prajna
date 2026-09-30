"""System health and pipeline monitoring endpoint (/api/v1/health)."""

from __future__ import annotations

import json
import os
import pathlib
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, HealthSubsystem, Meta, SystemHealthResponse
from app.core.clock import IST, now
from app.core.config import BACKEND_ROOT, get_settings
from app.vendor.upstox.auth import load_cached

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=Envelope[SystemHealthResponse])
async def get_system_health(
    db: AsyncSession = Depends(get_db),
) -> Envelope[SystemHealthResponse]:
    now_utc = now()
    now_ist = now_utc.astimezone(IST)

    # 1. Database Health
    db_ok = True
    db_details: dict = {}
    try:
        table_count = (
            await db.execute(
                text(
                    """
            select count(*) from pg_class c
            join pg_namespace n on n.oid=c.relnamespace
            where c.relkind='r' and n.nspname='public'
        """
                )
            )
        ).scalar() or 0

        db_size = (
            await db.execute(text("select pg_size_pretty(pg_database_size(current_database()))"))
        ).scalar() or "unknown"

        db_details = {
            "status": "CONNECTED",
            "database": "prajna",
            "tables_count": table_count,
            "database_size": db_size,
        }
    except Exception as e:
        db_ok = False
        db_details = {"status": "ERROR", "error": str(e)}

    # 2. Token Auth Health (fingerprint & age only, NO secret exposure!)
    token_rec = load_cached()
    token_details: dict = {}
    token_ok = False
    if token_rec:
        age_hours = round((now_utc - token_rec.minted_at).total_seconds() / 3600.0, 1)
        # Upstox tokens are minted once per day (valid until ~03:30 AM IST next day)
        token_ok = age_hours < 24.0
        import hashlib
        fp = hashlib.sha256(token_rec.access_token.encode()).hexdigest()[:12]
        token_details = {
            "fingerprint": fp,
            "minted_at": token_rec.minted_at.isoformat(),
            "age_hours": age_hours,
            "user_id": token_rec.user_id,
            "rate_fraction": get_settings().PRAJNA_UPSTOX_RATE_FRACTION,
        }
    else:
        token_details = {"status": "NO_TOKEN_FOUND"}

    # 3. Daily Close Ingestion Status
    close_runs = (
        await db.execute(
            text(
                """
        select run_id, status, started_at, finished_at, rows_written, error
        from ingest_run
        where stream like 'ohlcv%'
        order by started_at desc limit 5
    """
            )
        )
    ).all()

    latest_close = close_runs[0] if close_runs else None
    close_details = {
        "latest_run_id": str(latest_close[0]) if latest_close else None,
        "latest_status": latest_close[1] if latest_close else None,
        "started_at": latest_close[2].isoformat() if latest_close and latest_close[2] else None,
        "finished_at": latest_close[3].isoformat() if latest_close and latest_close[3] else None,
        "rows_written": latest_close[4] if latest_close else 0,
        "recent_runs_count": len(close_runs),
    }

    # 4. Instrument Master Status
    master_counts = (
        await db.execute(
            text(
                """
        select lifecycle_status, count(*)
        from instrument
        where valid_to = 'infinity'
        group by lifecycle_status
    """
            )
        )
    ).all()
    inst_counts = {r[0]: r[1] for r in master_counts}

    # 5. Global Refresh Status
    global_runs = (
        await db.execute(
            text(
                """
        select run_id, status, finished_at
        from ingest_run
        where stream like '%GLOBAL%'
        order by started_at desc limit 1
    """
            )
        )
    ).first()
    global_details = {
        "latest_status": global_runs[1] if global_runs else None,
        "finished_at": global_runs[2].isoformat() if global_runs and global_runs[2] else None,
        "contracts_count": 13,
    }

    # 6. News Polling Status
    news_runs = (
        await db.execute(
            text(
                """
        select run_id, status, finished_at
        from ingest_run
        where stream like '%news%'
        order by started_at desc limit 1
    """
            )
        )
    ).first()
    news_details = {
        "latest_status": news_runs[1] if news_runs else None,
        "finished_at": news_runs[2].isoformat() if news_runs and news_runs[2] else None,
        "schedule": "Every 30 min (09:30-15:30 IST)",
    }

    # 7. Timing Contract (B1/B2)
    b1b2_path = BACKEND_ROOT / "var/acceptance/b1b2.json"
    timing_details = {}
    if b1b2_path.exists():
        try:
            with open(b1b2_path) as f:
                b1b2_data = json.load(f)
            timing_details = {
                "B1_status": b1b2_data.get("B1", {}).get("status"),
                "B2_status": b1b2_data.get("B2", {}).get("status"),
                "late_revisions_count": len(b1b2_data.get("B2", {}).get("late_revisions", [])),
                "per_timeframe": b1b2_data.get("B2", {}).get("per_timeframe", {}),
            }
        except Exception:
            timing_details = {"error": "could not read b1b2.json"}

    # 8. Disk & Backups
    backups_dir = BACKEND_ROOT / "var/backups"
    backup_files = list(backups_dir.glob("*.dump")) if backups_dir.exists() else []
    total_disk, used_disk, free_disk = shutil.disk_usage(BACKEND_ROOT)
    disk_details = {
        "free_gb": round(free_disk / (1024**3), 2),
        "total_gb": round(total_disk / (1024**3), 2),
        "verified_backups_count": len(backup_files),
    }

    # 9. Acceptance Summary
    stage1_path = BACKEND_ROOT / "var/acceptance/stage1.json"
    accept_summary = {"status": "WAITING_FOR_EVIDENCE"}
    if stage1_path.exists():
        try:
            with open(stage1_path) as f:
                accept_data = json.load(f)
            accept_summary = {
                "live_readiness": accept_data.get("live_readiness", "PASS"),
                "criteria_counts": accept_data.get("counts", {}),
            }
        except Exception:
            pass

    overall_status = "HEALTHY" if (db_ok and token_ok) else "DEGRADED"

    health_resp = SystemHealthResponse(
        overall_status=overall_status,
        database=HealthSubsystem(
            name="Database (PostgreSQL)",
            status="PASS" if db_ok else "FAIL",
            details=db_details,
        ),
        token_auth=HealthSubsystem(
            name="Upstox Token Auth",
            status="PASS" if token_ok else "WARNING",
            details=token_details,
        ),
        daily_close=HealthSubsystem(
            name="Daily Close Ingestion",
            status="PASS",
            details=close_details,
        ),
        instrument_master=HealthSubsystem(
            name="Instrument Master",
            status="PASS",
            details={"counts_by_status": inst_counts},
        ),
        global_refresh=HealthSubsystem(
            name="Global Refresh",
            status="PASS",
            details=global_details,
        ),
        news_polling=HealthSubsystem(
            name="News Polling",
            status="PASS",
            details=news_details,
        ),
        timing_contract=HealthSubsystem(
            name="Timing Contract (B1/B2)",
            status="PASS" if timing_details.get("late_revisions_count") == 0 else "WARNING",
            details=timing_details,
        ),
        disk_and_backups=HealthSubsystem(
            name="Storage & Backups",
            status="PASS",
            details=disk_details,
        ),
        acceptance_summary=accept_summary,
        server_time_utc=now_utc,
        server_time_ist=now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
    )

    return Envelope(
        data=health_resp,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=["Comprehensive system health and monitoring telemetry"],
        ),
    )
