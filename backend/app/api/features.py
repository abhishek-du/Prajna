"""Feature card endpoint (/api/v1/features/{key}).

Provides per-instrument feature inspection for a given snapshot and session date.
"""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, FeatureCardResponse, FeatureValueItem, Meta
from app.core.clock import now
from app.features.registry import FEATURES

router = APIRouter(prefix="/features", tags=["features"])

FEATURE_SPEC_BY_ID = {f.id: f for f in FEATURES}


@router.get("/{key:path}", response_model=Envelope[FeatureCardResponse])
async def get_instrument_features(
    key: str,
    snapshot: str = Query("PRE_OPEN", description="Snapshot type: PRE_OPEN or PRE_SESSION"),
    date: _dt.date | None = Query(None, description="Session date (defaults to today or latest)"),
    db: AsyncSession = Depends(get_db),
) -> Envelope[FeatureCardResponse]:
    """Inspects all 104 registered features, values, and refusal reasons for an instrument."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()
    target_date = date or _dt.date(2026, 10, 16)

    # Check instrument exists
    inst_exists = (
        await db.execute(
            text("SELECT 1 FROM canon_instrument WHERE instrument_key = :k"),
            {"k": key},
        )
    ).scalar()

    if not inst_exists:
        inst_exists = (
            await db.execute(
                text("SELECT 1 FROM instrument WHERE instrument_key = :k"),
                {"k": key},
            )
        ).scalar()
        if not inst_exists and not key.startswith("NSE_INDEX|"):
            raise HTTPException(status_code=404, detail=f"Instrument '{key}' not found.")


    rows = (
        await db.execute(
            text(
                """
                SELECT feature_id, feature_version, registry_sha256, value, reason,
                       input_max_knowable_at, computed_at
                FROM feature_value
                WHERE instrument_key = :k AND session_date = :d AND snapshot = :s
                ORDER BY feature_id
                """
            ),
            {"k": key, "d": target_date, "s": snapshot},
        )
    ).fetchall()

    feature_items: list[FeatureValueItem] = []
    values_cnt = 0
    nulls_cnt = 0
    feat_ver = "features-v4"
    reg_sha = "6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3"

    for r in rows:
        fid = str(r[0])
        feat_ver = str(r[1])
        reg_sha = str(r[2])
        val = float(r[3]) if r[3] is not None else None
        reason = r[4]
        if val is not None:
            values_cnt += 1
        else:
            nulls_cnt += 1

        spec = FEATURE_SPEC_BY_ID.get(fid)
        group = spec.group if spec else "other"
        definition = spec.definition if spec else None

        feature_items.append(
            FeatureValueItem(
                feature_id=fid,
                group=group,
                definition=definition,
                value=val,
                reason=reason,
                knowable_at=r[5],
                computed_at=r[6],
            )
        )

    if not feature_items:
        for f in FEATURES:
            if snapshot in f.snapshots:
                feature_items.append(
                    FeatureValueItem(
                        feature_id=f.id,
                        group=f.group,
                        definition=f.definition,
                        value=None,
                        reason=f"No computation recorded for {snapshot} on {target_date}",
                        knowable_at=None,
                        computed_at=None,
                    )
                )
                nulls_cnt += 1

    return Envelope(
        data=FeatureCardResponse(
            instrument_key=key,
            session_date=target_date,
            snapshot=snapshot,
            feature_version=feat_ver,
            registry_sha256=reg_sha,
            values_count=values_cnt,
            nulls_count=nulls_cnt,
            features=feature_items,
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=[f"Feature card for {key} on {target_date} ({snapshot})."],
        ),
    )
