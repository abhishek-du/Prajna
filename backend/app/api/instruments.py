"""Stock explorer and instrument search endpoints (/api/v1/instruments)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, InstrumentDetail, InstrumentItem, InstrumentListResponse, Meta
from app.core.clock import now

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=Envelope[InstrumentListResponse])
async def list_instruments(
    q: str | None = Query(None, description="search symbol, name or ISIN"),
    sector: str | None = Query(None, description="filter by sector"),
    security_class: str | None = Query(None, description="filter by class (STOCK, FUND_UNIT, etc.)"),
    segment: str | None = Query(None, description="filter by segment (NSE_EQ, NSE_INDEX)"),
    status: str | None = Query("ACTIVE", description="lifecycle status filter (default ACTIVE)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Envelope[InstrumentListResponse]:
    now_utc = now()

    conditions = ["i.valid_to = 'infinity'"]
    params: dict[str, Any] = {"lim": limit, "off": offset}

    if status:
        conditions.append("i.lifecycle_status = :status")
        params["status"] = status

    if segment:
        conditions.append("i.segment = :segment")
        params["segment"] = segment

    if security_class:
        conditions.append("isc.security_class = :sec_class")
        params["sec_class"] = security_class

    if sector:
        conditions.append("ci.sector = :sector")
        params["sector"] = sector

    if q:
        q_clean = f"%{q.strip().upper()}%"
        conditions.append(
            "(upper(i.trading_symbol) like :q or upper(coalesce(i.name, '')) like :q or upper(coalesce(i.isin, '')) like :q)"
        )
        params["q"] = q_clean

    where_clause = " and ".join(conditions)

    count_sql = f"""
        select count(*)
        from instrument i
        left join canon_instrument ci on ci.instrument_id = i.instrument_id
        left join instrument_security_class isc on isc.instrument_id = i.instrument_id
        where {where_clause}
    """
    total = (await db.execute(text(count_sql), params)).scalar() or 0

    list_sql = f"""
        select
            i.instrument_key,
            i.trading_symbol,
            i.name,
            i.isin,
            i.segment,
            i.exchange,
            i.instrument_type,
            i.lot_size,
            i.tick_size,
            isc.security_class,
            i.lifecycle_status,
            ci.sector,
            b.close as latest_close,
            b.session_date as latest_date
        from instrument i
        left join canon_instrument ci on ci.instrument_id = i.instrument_id
        left join instrument_security_class isc on isc.instrument_id = i.instrument_id
        left join lateral (
            select close, session_date
            from ohlcv_bar
            where instrument_id = i.instrument_id and timeframe = '1d'
            order by session_date desc limit 1
        ) b on true
        where {where_clause}
        order by i.trading_symbol asc
        limit :lim offset :off
    """
    rows = (await db.execute(text(list_sql), params)).all()

    items = [
        InstrumentItem(
            instrument_key=r[0],
            trading_symbol=r[1],
            name=r[2],
            isin=r[3],
            segment=r[4],
            exchange=r[5],
            instrument_type=r[6],
            lot_size=r[7],
            tick_size=float(r[8]) / 100.0 if r[8] is not None else None,
            security_class=r[9],
            lifecycle_status=r[10],
            sector=r[11],
            latest_close=float(r[12]) if r[12] is not None else None,
            latest_date=r[13],
        )
        for r in rows
    ]

    return Envelope(
        data=InstrumentListResponse(
            total=total,
            offset=offset,
            limit=limit,
            instruments=items,
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=[f"Matched {total} instruments"],
        ),
    )


@router.get("/{key:path}", response_model=Envelope[InstrumentDetail])
async def get_instrument_detail(
    key: str,
    db: AsyncSession = Depends(get_db),
) -> Envelope[InstrumentDetail]:
    now_utc = now()

    inst_sql = """
        select
            i.instrument_id,
            i.instrument_key,
            i.trading_symbol,
            i.name,
            i.isin,
            i.segment,
            i.exchange,
            i.instrument_type,
            i.lot_size,
            i.tick_size,
            isc.security_class,
            i.lifecycle_status,
            ci.sector,
            b.close as latest_close,
            b.session_date as latest_date
        from instrument i
        left join canon_instrument ci on ci.instrument_id = i.instrument_id
        left join instrument_security_class isc on isc.instrument_id = i.instrument_id
        left join lateral (
            select close, session_date
            from ohlcv_bar
            where instrument_id = i.instrument_id and timeframe = '1d'
            order by session_date desc limit 1
        ) b on true
        where i.instrument_key = :k and i.valid_to = 'infinity'
        limit 1
    """
    row = (await db.execute(text(inst_sql), {"k": key})).first()

    if not row:
        raise HTTPException(status_code=404, detail=f"Instrument {key} not found")

    inst_id = row[0]

    # Lifecycle periods
    periods = [
        dict(r)
        for r in (
            await db.execute(
                text(
                    """
            select status, valid_from, valid_to, reason, knowable_at
            from instrument_lifecycle_period
            where instrument_id = :id
            order by valid_from desc
        """
                ),
                {"id": inst_id},
            )
        )
        .mappings()
        .all()
    ]

    # Attribute versions
    attr_versions = [
        dict(r)
        for r in (
            await db.execute(
                text(
                    """
            select version, valid_from, valid_to, trading_symbol, lot_size, tick_size
            from instrument_attribute_version
            where instrument_id = :id
            order by version desc
        """
                ),
                {"id": inst_id},
            )
        )
        .mappings()
        .all()
    ]

    # Recent 1D bars
    recent_bars = [
        dict(r)
        for r in (
            await db.execute(
                text(
                    """
            select session_date, open, high, low, close, volume, knowable_at
            from ohlcv_bar
            where instrument_id = :id and timeframe = '1d'
            order by session_date desc limit 10
        """
                ),
                {"id": inst_id},
            )
        )
        .mappings()
        .all()
    ]

    # Corporate Actions
    ca_rows = [
        dict(r)
        for r in (
            await db.execute(
                text(
                    """
            select cf.action_type, cf.ex_date, ca.record_date, cf.factor_price, cf.status as factor_status, cf.vendor_applied
            from ca_factor cf
            left join corporate_action ca on ca.id = cf.ca_id
            where cf.instrument_key = :k
            order by cf.ex_date desc nulls last limit 10
        """
                ),
                {"k": key},
            )
        )
        .mappings()
        .all()
    ]

    # Fundamentals summary (Key ratios)
    ratios_row = (
        await db.execute(
            text(
                """
        select payload
        from fundamental_snapshot
        where instrument_key = :k and statement_type = 'key_ratios'
        order by knowable_at desc limit 1
    """
            ),
            {"k": key},
        )
    ).scalar()

    item = InstrumentItem(
        instrument_key=row[1],
        trading_symbol=row[2],
        name=row[3],
        isin=row[4],
        segment=row[5],
        exchange=row[6],
        instrument_type=row[7],
        lot_size=row[8],
        tick_size=float(row[9]) / 100.0 if row[9] is not None else None,
        security_class=row[10],
        lifecycle_status=row[11],
        sector=row[12],
        latest_close=float(row[13]) if row[13] is not None else None,
        latest_date=row[14],
    )

    detail = InstrumentDetail(
        instrument=item,
        lifecycle_periods=periods,
        attribute_versions=attr_versions,
        recent_bars=recent_bars,
        corporate_actions=ca_rows,
        fundamentals_summary={"ratios": ratios_row} if ratios_row else None,
    )

    return Envelope(
        data=detail,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=[f"Instrument details for {key}"],
        ),
    )
