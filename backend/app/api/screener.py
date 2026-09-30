"""Stock screener endpoint with multi-factor filtering (/api/v1/screener)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, Meta, ScreenerResponse, ScreenerRow
from app.core.clock import now

router = APIRouter(prefix="/screener", tags=["screener"])


@router.get("", response_model=Envelope[ScreenerResponse])
async def screen_stocks(
    sector: str | None = Query(None, description="Filter by sector"),
    min_price: float | None = Query(None, description="Minimum price"),
    max_price: float | None = Query(None, description="Maximum price"),
    min_pe: float | None = Query(None, description="Minimum P/E"),
    max_pe: float | None = Query(None, description="Maximum P/E"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Envelope[ScreenerResponse]:
    now_utc = now()

    # Query distinct sectors for screener filter dropdown
    sectors_sql = """
        select distinct sector
        from canon_instrument
        where sector is not null and sector != ''
        order by sector
    """
    sector_rows = (await db.execute(text(sectors_sql))).scalars().all()
    available_sectors = [s for s in sector_rows if s]

    # Query active stocks with latest 1D bar and key ratios
    conditions = [
        "i.valid_to = 'infinity'",
        "i.lifecycle_status = 'ACTIVE'",
        "i.segment = 'NSE_EQ'",
        "b.close is not null",
    ]
    params: dict[str, Any] = {"lim": limit, "off": offset}

    if sector:
        conditions.append("ci.sector = :sector")
        params["sector"] = sector

    if min_price is not None:
        conditions.append("b.close >= :min_price")
        params["min_price"] = min_price

    if max_price is not None:
        conditions.append("b.close <= :max_price")
        params["max_price"] = max_price

    where_clause = " and ".join(conditions)

    sql = f"""
        select
            i.instrument_key,
            i.trading_symbol,
            i.name,
            ci.sector,
            isc.security_class,
            b.close,
            b.volume,
            b.prev_close,
            fs.payload as ratios_payload
        from instrument i
        join canon_instrument ci on ci.instrument_id = i.instrument_id
        left join instrument_security_class isc on isc.instrument_id = i.instrument_id
        join lateral (
            select
                close,
                volume,
                lag(close) over (order by session_date asc) as prev_close
            from (
                select close, volume, session_date
                from ohlcv_bar
                where instrument_id = i.instrument_id and timeframe = '1d'
                order by session_date desc limit 2
            ) sub
            order by session_date desc limit 1
        ) b on true
        left join lateral (
            select payload
            from fundamental_snapshot
            where instrument_key = i.instrument_key and statement_type = 'key_ratios'
            order by knowable_at desc limit 1
        ) fs on true
        where {where_clause}
        order by b.volume desc nulls last, i.trading_symbol asc
        limit :lim offset :off
    """
    rows = (await db.execute(text(sql), params)).all()

    stocks: list[ScreenerRow] = []
    for r in rows:
        key = r[0]
        sym = r[1]
        name = r[2]
        sec = r[3]
        s_class = r[4]
        price = float(r[5]) if r[5] is not None else None
        vol = float(r[6]) if r[6] is not None else None
        prev_cl = float(r[7]) if r[7] is not None else None
        chg_pct = (
            round(((price - prev_cl) / prev_cl) * 100.0, 2)
            if (price and prev_cl)
            else 0.0
        )

        pe = None
        pb = None
        roe = None
        roce = None
        market_cap = None

        raw_ratios = r[8]
        if raw_ratios:
            r_list = raw_ratios if isinstance(raw_ratios, list) else json.loads(raw_ratios)
            for item in r_list:
                if not isinstance(item, dict):
                    continue
                r_name = item.get("name", "").strip().upper()
                c_val_str = item.get("company_value") or item.get("value")
                try:
                    c_val = float(c_val_str) if c_val_str is not None else None
                except (ValueError, TypeError):
                    c_val = None

                if "P/E" in r_name:
                    pe = c_val
                elif "P/B" in r_name:
                    pb = c_val
                elif "ROE" in r_name:
                    roe = c_val
                elif "ROCE" in r_name:
                    roce = c_val
                elif "MARKET CAP" in r_name:
                    market_cap = c_val

        # P/E filter in python if requested
        if min_pe is not None and (pe is None or pe < min_pe):
            continue
        if max_pe is not None and (pe is None or pe > max_pe):
            continue

        stocks.append(
            ScreenerRow(
                instrument_key=key,
                trading_symbol=sym,
                name=name,
                sector=sec,
                security_class=s_class,
                price=price,
                change_pct=chg_pct,
                volume=vol,
                market_cap=market_cap,
                pe=pe,
                pb=pb,
                roe=roe,
                roce=roce,
            )
        )

    return Envelope(
        data=ScreenerResponse(
            total=len(stocks),
            offset=offset,
            limit=limit,
            stocks=stocks,
            sectors=available_sectors,
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=["Screener with live fundamentals and market quotes"],
        ),
    )
