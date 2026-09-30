"""Technical data endpoint with Stage 3 lock compliance (/api/v1/technicals)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, Meta, TechnicalValues
from app.core.clock import now

router = APIRouter(prefix="/technicals", tags=["technicals"])


@router.get("/{key:path}", response_model=Envelope[TechnicalValues])
async def get_technicals(
    key: str,
    timeframe: str = Query("1d", description="1m, 15m, 1h, 1d"),
    db: AsyncSession = Depends(get_db),
) -> Envelope[TechnicalValues]:
    now_utc = now()

    # Fetch last 2 bars of the requested timeframe to compute real metrics
    sql = """
        select session_date, open, high, low, close, volume
        from ohlcv_bar
        where instrument_key = :k and timeframe = :tf
        order by session_date desc, bar_start_utc desc limit 2
    """
    rows = (await db.execute(text(sql), {"k": key, "tf": timeframe.lower()})).all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No bars found for instrument {key} on timeframe {timeframe}",
        )

    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None

    op = float(latest[1])
    hi = float(latest[2])
    lo = float(latest[3])
    cl = float(latest[4])
    vol = float(latest[5])

    day_range = round(hi - lo, 2)
    avg_price = round((hi + lo + cl) / 3.0, 2)

    change = None
    change_pct = None
    if prev:
        prev_close = float(prev[4])
        change = round(cl - prev_close, 2)
        change_pct = round((change / prev_close) * 100.0, 2) if prev_close else 0.0

    tech_data = TechnicalValues(
        instrument_key=key,
        timeframe=timeframe.lower(),
        market_date=latest[0],
        open=op,
        high=hi,
        low=lo,
        close=cl,
        volume=vol,
        day_range=day_range,
        change=change,
        change_pct=change_pct,
        average_price=avg_price,
        computed_at=now_utc,
        # Stage 3 indicators strictly marked as locked - no fake values
    )

    return Envelope(
        data=tech_data,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Stage 3 indicators are locked in production"],
        ),
    )
