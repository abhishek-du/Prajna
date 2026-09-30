"""Global markets endpoint with finality contract enforcement (/api/v1/global-markets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, GlobalMarketItem, GlobalMarketsResponse, Meta
from app.core.clock import now

router = APIRouter(prefix="/global-markets", tags=["global-markets"])


@router.get("", response_model=Envelope[GlobalMarketsResponse])
async def list_global_markets(
    db: AsyncSession = Depends(get_db),
) -> Envelope[GlobalMarketsResponse]:
    now_utc = now()

    # Query confirmed global bars joined with contract metadata
    sql = """
        select distinct on (b.instrument_key)
            b.instrument_key,
            b.trading_symbol,
            b.name,
            b.segment,
            b.label_date,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
            b.finality,
            b.knowable_at,
            b.confirmed_at,
            c.weekend_label_share,
            c.label_semantics,
            coalesce(c.confirm_hours, 6) as confirm_hours
        from canon_global_bar b
        left join global_instrument_contract c on c.instrument_key = b.instrument_key
        order by b.instrument_key, b.label_date desc
    """
    rows = (await db.execute(text(sql))).all()

    items = [
        GlobalMarketItem(
            instrument_key=r[0],
            trading_symbol=r[1],
            name=r[2],
            segment=r[3],
            label_date=r[4],
            open=float(r[5]),
            high=float(r[6]),
            low=float(r[7]),
            close=float(r[8]),
            volume=float(r[9]) if r[9] is not None else None,
            finality=r[10],
            knowable_at=r[11],
            confirmed_at=r[12],
            weekend_label_share=float(r[13]) if r[13] is not None else None,
            semantics=r[14],
            confirm_hours=r[15],
        )
        for r in rows
    ]

    # Withheld counts from global_bar_finality view (transparency stats)
    withheld_sql = """
        select finality, count(*)
        from global_bar_finality
        group by finality
    """
    withheld_rows = (await db.execute(text(withheld_sql))).all()
    withheld_counts = {r[0]: r[1] for r in withheld_rows}

    response_data = GlobalMarketsResponse(
        markets=items,
        withheld_counts=withheld_counts,
        contract_notes=[
            "Strict global finality enforced (P5 contract).",
            "REVISED bars, flat PLACEHOLDERS, and UNCONFIRMED bars are never exposed as final.",
            "Bars become CONFIRMED only upon unchanged re-observation >= 6 hours after first fetch.",
        ],
    )

    return Envelope(
        data=response_data,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Global market finality contract v1"],
        ),
    )
