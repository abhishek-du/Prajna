"""Admin and operations endpoints (/api/v1/ops)."""

from __future__ import annotations

import datetime as _dt
import pathlib

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    AnomalyItem,
    BackupItem,
    Envelope,
    IngestRunItem,
    Meta,
    RevisionItem,
    WarmupPlanResponse,
)
from app.core.clock import now
from app.core.config import BACKEND_ROOT
from app.ops.warmup import plan as plan_warmup

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/runs", response_model=Envelope[list[IngestRunItem]])
async def list_runs(
    status: str | None = Query(None, description="filter by status (COMPLETE, RUNNING, FAILED)"),
    stream: str | None = Query(None, description="filter by stream prefix"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Envelope[list[IngestRunItem]]:
    now_utc = now()

    conditions = ["1=1"]
    params: dict = {"lim": limit, "off": offset}

    if status:
        conditions.append("status = :status")
        params["status"] = status

    if stream:
        conditions.append("stream like :stream")
        params["stream"] = f"%{stream}%"

    where_clause = " and ".join(conditions)

    sql = f"""
        select
            run_id,
            source,
            stream,
            logical_date,
            status,
            rows_written,
            started_at,
            finished_at,
            error
        from ingest_run
        where {where_clause}
        order by started_at desc
        limit :lim offset :off
    """
    rows = (await db.execute(text(sql), params)).all()

    runs = [
        IngestRunItem(
            run_id=str(r[0]),
            source=r[1],
            stream=r[2],
            logical_date=r[3],
            status=r[4],
            rows_written=r[5],
            started_at=r[6],
            finished_at=r[7],
            duration_seconds=round((r[7] - r[6]).total_seconds(), 2) if r[7] else None,
            error=r[8],
        )
        for r in rows
    ]

    return Envelope(
        data=runs,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=[f"Returned {len(runs)} ingest runs"],
        ),
    )


@router.get("/anomalies", response_model=Envelope[list[AnomalyItem]])
async def list_anomalies(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Envelope[list[AnomalyItem]]:
    now_utc = now()

    sql = """
        select id, rule, severity, entity_key, details, run_id, created_at
        from ingest_anomaly
        order by created_at desc limit :lim
    """
    rows = (await db.execute(text(sql), {"lim": limit})).all()

    anomalies = [
        AnomalyItem(
            id=r[0],
            rule=r[1],
            severity=r[2],
            entity_key=r[3],
            details=r[4] if isinstance(r[4], dict) else {},
            run_id=str(r[5]) if r[5] else None,
            created_at=r[6],
        )
        for r in rows
    ]

    return Envelope(
        data=anomalies,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=[f"Returned {len(anomalies)} anomalies"],
        ),
    )


@router.get("/revisions", response_model=Envelope[list[RevisionItem]])
async def list_revisions(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Envelope[list[RevisionItem]]:
    now_utc = now()

    sql = """
        select id, instrument_key, timeframe, session_date, classification, reason, explained_by, created_at
        from ohlcv_observation
        order by created_at desc limit :lim
    """
    rows = (await db.execute(text(sql), {"lim": limit})).all()

    revisions = [
        RevisionItem(
            id=r[0],
            instrument_key=r[1],
            timeframe=r[2],
            session_date=r[3],
            classification=r[4],
            reason=r[5],
            explained_by=r[6] if isinstance(r[6], dict) else {},
            created_at=r[7],
        )
        for r in rows
    ]

    return Envelope(
        data=revisions,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=["Audit trail of later vendor observations"],
        ),
    )


@router.get("/backups", response_model=Envelope[list[BackupItem]])
async def list_backups() -> Envelope[list[BackupItem]]:
    now_utc = now()
    backups_dir = BACKEND_ROOT / "var/backups"

    items: list[BackupItem] = []
    if backups_dir.exists():
        dumps = sorted(backups_dir.glob("*.dump"), reverse=True)
        for d in dumps:
            stat = d.stat()
            size_mb = round(stat.st_size / (1024 * 1024), 2)
            sha_file = d.with_suffix(".dump.sha256")
            prefix = ""
            if sha_file.exists():
                try:
                    prefix = sha_file.read_text().strip()[:12]
                except Exception:
                    pass

            items.append(
                BackupItem(
                    filename=d.name,
                    size_bytes=stat.st_size,
                    size_human=f"{size_mb} MB",
                    sha256_prefix=prefix,
                    modified_at=_dt.datetime.fromtimestamp(stat.st_mtime, tz=_dt.timezone.utc),
                    verified=sha_file.exists(),
                )
            )

    return Envelope(
        data=items,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=[f"Found {len(items)} verified backups"],
        ),
    )


@router.get("/warmup", response_model=Envelope[WarmupPlanResponse])
async def calculate_warmup(
    sessions: int = Query(20, ge=1, le=100),
    timeframes: str = Query("1m,15m,1h", description="comma-separated timeframes"),
    fraction: float = Query(0.5, ge=0.1, le=0.9),
    db: AsyncSession = Depends(get_db),
) -> Envelope[WarmupPlanResponse]:
    now_utc = now()
    tf_list = [t.strip() for t in timeframes.split(",") if t.strip()]

    try:
        plan_result = await plan_warmup(db, sessions=sessions, timeframes=tf_list, fraction=fraction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    resp = WarmupPlanResponse(
        sessions=plan_result["sessions"],
        from_date=plan_result["from"],
        to_date=plan_result["to"],
        active_instruments=plan_result["active_instruments"],
        fraction=plan_result["fraction"],
        timeframes=plan_result["timeframes"],
        total_requests=plan_result["total_requests"],
        total_hours_at_fraction=plan_result["total_hours_at_fraction"],
        deferred_full_backfill_requests=plan_result["deferred_full_backfill_requests"],
    )

    return Envelope(
        data=resp,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=["Stage 3 warm-up calculation (read-only; 0 vendor calls; 0 writes)"],
        ),
    )
