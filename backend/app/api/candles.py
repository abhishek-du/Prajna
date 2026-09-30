"""Candle endpoints for historical and PIT adjusted bars (/api/v1/candles)."""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Candle, CandleSeriesResponse, Envelope, Meta
from app.canon import pit
from app.canon.validate import CANON_TIMEFRAMES
from app.core.clock import IST, now, to_utc

router = APIRouter(prefix="/candles", tags=["candles"])


@router.get("/{key:path}", response_model=Envelope[CandleSeriesResponse])
async def get_candles(
    key: str,
    timeframe: str = Query("1d", description="1m, 15m, 1h, 1d"),
    start: _dt.date | None = Query(None, description="Start date YYYY-MM-DD"),
    end: _dt.date | None = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(500, ge=1, le=2000),
    adjusted: bool = Query(False, description="Point-in-time corporate action adjusted"),
    as_of: _dt.datetime | None = Query(None, description="Knowledge instant (default now)"),
    allow_reconstructed: bool = Query(False),
    allow_low_confidence: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Envelope[CandleSeriesResponse]:
    tf = timeframe.lower()
    if tf not in CANON_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Timeframe {timeframe!r} not supported. In scope: {', '.join(CANON_TIMEFRAMES)}",
        )

    now_utc = now()
    as_of_u = to_utc(as_of) if as_of else now_utc

    candles_out: list[Candle] = []
    refused: dict[str, int] | None = None

    if adjusted and tf == "1d":
        # Point-in-time adjusted bars through pit.bars_adjusted
        try:
            adj_res = await pit.bars_adjusted(
                db,
                key,
                tf,
                as_of_u,
                start=start,
                end=end,
                allow_reconstructed=allow_reconstructed,
                allow_low_confidence=allow_low_confidence,
            )
            raw_rows = adj_res["rows"]
            refused = adj_res["refused"]
            if limit and len(raw_rows) > limit:
                raw_rows = raw_rows[-limit:]

            for r in raw_rows:
                st = r["bar_start_utc"]
                st_ist = st.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                candles_out.append(
                    Candle(
                        timeframe=tf,
                        bar_start_utc=st,
                        bar_start_ist=st_ist,
                        market_date=r["market_date"],
                        open=float(r["open"]),
                        high=float(r["high"]),
                        low=float(r["low"]),
                        close=float(r["close"]),
                        volume=float(r["volume"]),
                        open_interest=float(r["open_interest"]) if r.get("open_interest") else None,
                        knowable_at=r["knowable_at"],
                        price_basis=r.get("price_basis"),
                        basis_as_of=r.get("basis_as_of"),
                        adjustment_status=r.get("adjustment_status"),
                        factor_applied=float(r["factor_applied"])
                        if r.get("factor_applied")
                        else None,
                        basis_confidence=r.get("basis_confidence"),
                    )
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Adjustment error: {e}") from e

    else:
        # Raw canonical bars
        sql = """
            select
                bar_start_utc,
                market_date,
                open,
                high,
                low,
                close,
                volume,
                open_interest,
                knowable_at,
                price_basis,
                basis_as_of
            from (
                select *
                from canon_market_bar
                where instrument_key = :k
                  and timeframe = :tf
                  and knowable_at < :as_of
                  and (cast(:st as date) is null or market_date >= :st)
                  and (cast(:en as date) is null or market_date <= :en)
                order by bar_start_utc desc
                limit :lim
            ) x
            order by bar_start_utc asc
        """
        rows = (
            await db.execute(
                text(sql),
                {
                    "k": key,
                    "tf": tf,
                    "as_of": as_of_u,
                    "st": start,
                    "en": end,
                    "lim": limit,
                },
            )
        ).all()

        for r in rows:
            st = r[0]
            st_ist = st.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")
            candles_out.append(
                Candle(
                    timeframe=tf,
                    bar_start_utc=st,
                    bar_start_ist=st_ist,
                    market_date=r[1],
                    open=float(r[2]),
                    high=float(r[3]),
                    low=float(r[4]),
                    close=float(r[5]),
                    volume=float(r[6]),
                    open_interest=float(r[7]) if r[7] is not None else None,
                    knowable_at=r[8],
                    price_basis=r[9],
                    basis_as_of=r[10],
                    adjustment_status="AS_STORED",
                    factor_applied=1.0,
                    basis_confidence="HIGH",
                )
            )

    series_response = CandleSeriesResponse(
        instrument_key=key,
        timeframe=tf,
        adjusted=adjusted,
        candles=candles_out,
        refused=refused,
        total_count=len(candles_out),
    )

    return Envelope(
        data=series_response,
        meta=Meta(
            as_of=as_of_u,
            generated_at=now_utc,
            point_in_time=True,
            notes=[f"Returned {len(candles_out)} candles for {key} {tf}"],
        ),
    )
