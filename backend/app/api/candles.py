"""Candle endpoints for historical and PIT adjusted bars (/api/v1/candles)."""

from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    Candle,
    CandleSeriesResponse,
    CorporateActionMarker,
    Envelope,
    ExcludedBarMarker,
    Meta,
)
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
    await db.execute(text("SET TRANSACTION READ ONLY"))
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

    # Fetch corporate actions for this instrument
    ca_rows = (
        await db.execute(
            text(
                """
                SELECT id, action_type, ex_date, record_date, announcement_date,
                       amount, ratio_from, ratio_to, source
                FROM canon_corporate_action
                WHERE instrument_key = :k
                ORDER BY ex_date DESC NULLS LAST
                LIMIT 50
                """
            ),
            {"k": key},
        )
    ).fetchall()

    corporate_action_markers = [
        CorporateActionMarker(
            id=r[0],
            action_type=str(r[1]),
            ex_date=r[2],
            record_date=r[3],
            announcement_date=r[4],
            amount=float(r[5]) if r[5] is not None else None,
            ratio_from=float(r[6]) if r[6] is not None else None,
            ratio_to=float(r[7]) if r[7] is not None else None,
            source=r[8],
        )
        for r in ca_rows
        if r[2] is not None
    ]

    # Fetch excluded bars for this instrument and timeframe
    ex_rows = (
        await db.execute(
            text(
                """
                SELECT instrument_key, timeframe, session_date, bar_start_utc,
                       open, high, low, close, volume, reason, knowable_at
                FROM canon_excluded_bar
                WHERE instrument_key = :k AND timeframe = :tf
                ORDER BY bar_start_utc DESC
                LIMIT 100
                """
            ),
            {"k": key, "tf": tf},
        )
    ).fetchall()

    excluded_bar_markers = [
        ExcludedBarMarker(
            instrument_key=r[0],
            timeframe=r[1],
            session_date=r[2],
            bar_start_utc=r[3],
            bar_start_ist=r[3].astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST") if r[3] else "",
            open=float(r[4]) if r[4] is not None else None,
            high=float(r[5]) if r[5] is not None else None,
            low=float(r[6]) if r[6] is not None else None,
            close=float(r[7]) if r[7] is not None else None,
            volume=float(r[8]) if r[8] is not None else None,
            reason=str(r[9]),
            knowable_at=r[10],
        )
        for r in ex_rows
    ]

    series_response = CandleSeriesResponse(
        instrument_key=key,
        timeframe=tf,
        adjusted=adjusted,
        candles=candles_out,
        corporate_actions=corporate_action_markers,
        excluded_bars=excluded_bar_markers,
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
