"""Stock explorer and instrument search endpoints (/api/v1/instruments)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    Envelope,
    InstrumentDetail,
    InstrumentItem,
    InstrumentListResponse,
    Meta,
    PreopenHistoryItem,
    StockLifecycleItem,
    StockPaperTradeItem,
)
from app.core.clock import IST, now

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


@router.get("/{key:path}/preopen", response_model=Envelope[list[PreopenHistoryItem]])
async def get_instrument_preopen(
    key: str,
    limit: int = Query(60, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> Envelope[list[PreopenHistoryItem]]:
    """Returns pre-open session history (IEP, order imbalance, gap %) per session."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()

    # Query latest preopen tick per session_date
    sql = """
        SELECT DISTINCT ON (market_date)
            market_date, event_ts, iep, ieq, tbq, tsq, rp, ltp, cas_eligible, knowable_at
        FROM canon_preopen
        WHERE instrument_key = :k
        ORDER BY market_date DESC, event_ts DESC
        LIMIT :lim
    """
    rows = (await db.execute(text(sql), {"k": key, "lim": limit})).fetchall()

    items: list[PreopenHistoryItem] = []
    for r in rows:
        m_date = r[0]
        ev_ts = r[1]
        ev_ts_ist = ev_ts.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST") if ev_ts else ""
        iep_val = float(r[2]) if r[2] is not None and float(r[2]) > 0 else None
        ieq_val = int(r[3]) if r[3] is not None else None
        tbq_val = float(r[4]) if r[4] is not None else None
        tsq_val = float(r[5]) if r[5] is not None else None
        rp_val = float(r[6]) if r[6] is not None and float(r[6]) > 0 else None
        ltp_val = float(r[7]) if r[7] is not None and float(r[7]) > 0 else None

        imbalance_qty = None
        imbalance_side = None
        if tbq_val is not None and tsq_val is not None:
            imbalance_qty = int(abs(tbq_val - tsq_val))
            if tbq_val > tsq_val:
                imbalance_side = "BUY"
            elif tsq_val > tbq_val:
                imbalance_side = "SELL"
            else:
                imbalance_side = "BALANCED"

        gap_pct = None
        ref_price = iep_val or ltp_val
        if ref_price and rp_val and rp_val > 0:
            gap_pct = round(((ref_price - rp_val) / rp_val) * 100.0, 2)

        items.append(
            PreopenHistoryItem(
                market_date=m_date,
                event_ts=ev_ts,
                event_ts_ist=ev_ts_ist,
                iep=iep_val,
                ieq=ieq_val,
                tbq=tbq_val,
                tsq=tsq_val,
                imbalance_qty=imbalance_qty,
                imbalance_side=imbalance_side,
                rp=rp_val,
                ltp=ltp_val,
                gap_pct=gap_pct,
                cas_eligible=r[8],
                knowable_at=r[9],
            )
        )

    return Envelope(
        data=items,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=[f"Returned {len(items)} pre-open session records for {key}"],
        ),
    )


@router.get("/{key:path}/paper-trades", response_model=Envelope[list[StockPaperTradeItem]])
async def get_instrument_paper_trades(
    key: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> Envelope[list[StockPaperTradeItem]]:
    """Returns simulated paper trading fills for this instrument. PAPER ONLY — simulated fills, not a profitability claim."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()

    sql = """
        SELECT f.id, f.run_id, r.strategy, r.session_date, f.status, f.reason,
               f.qty, f.buy_px, f.sell_px, f.buy_value_inr, f.sell_value_inr,
               f.pnl_inr, f.charges, f.mode
        FROM paper_fill f
        JOIN paper_run r ON f.run_id = r.run_id
        WHERE f.instrument_key = :k
        ORDER BY r.session_date DESC
        LIMIT :lim
    """
    rows = (await db.execute(text(sql), {"k": key, "lim": limit})).fetchall()

    items: list[StockPaperTradeItem] = []
    for r in rows:
        items.append(
            StockPaperTradeItem(
                id=r[0],
                run_id=str(r[1]),
                strategy=r[2],
                session_date=r[3],
                status=r[4],
                reason=r[5],
                qty=r[6] or 0,
                buy_px=float(r[7]) if r[7] is not None else None,
                sell_px=float(r[8]) if r[8] is not None else None,
                buy_value_inr=float(r[9]) if r[9] is not None else None,
                sell_value_inr=float(r[10]) if r[10] is not None else None,
                pnl_inr=float(r[11]) if r[11] is not None else None,
                charges=r[12] if isinstance(r[12], dict) else None,
                mode=r[13] or "PAPER",
            )
        )

    return Envelope(
        data=items,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=[
                "PAPER ONLY — simulated fills, not a profitability claim",
                f"Returned {len(items)} simulated paper records for {key}",
            ],
        ),
    )


@router.get("/{key:path}/lifecycle", response_model=Envelope[StockLifecycleItem])
async def get_instrument_lifecycle(
    key: str,
    db: AsyncSession = Depends(get_db),
) -> Envelope[StockLifecycleItem]:
    """Returns lifecycle and ISIN history for an instrument."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    now_utc = now()

    inst_sql = """
        SELECT
            i.instrument_id, i.instrument_key, i.trading_symbol, i.name, i.isin,
            i.segment, i.exchange, i.instrument_type, i.lifecycle_status,
            i.first_seen, i.last_seen, ci.included, ci.filter_reason, ci.sector
        FROM instrument i
        LEFT JOIN canon_instrument ci ON ci.instrument_id = i.instrument_id
        WHERE i.instrument_key = :k
        ORDER BY i.valid_to DESC
        LIMIT 1
    """
    row = (await db.execute(text(inst_sql), {"k": key})).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Instrument {key} not found")

    inst_id = row[0]

    # Lifecycle periods
    period_rows = (
        await db.execute(
            text(
                """
                SELECT status, valid_from, valid_to, reason, knowable_at
                FROM instrument_lifecycle_period
                WHERE instrument_id = :id
                ORDER BY valid_from DESC
                """
            ),
            {"id": inst_id},
        )
    ).mappings().all()
    periods = [dict(p) for p in period_rows]

    # Attribute versions
    attr_rows = (
        await db.execute(
            text(
                """
                SELECT id, valid_from, valid_to, trading_symbol, isin, lot_size, tick_size
                FROM instrument_attribute_version
                WHERE instrument_id = :id
                ORDER BY valid_from DESC
                """
            ),
            {"id": inst_id},
        )
    ).mappings().all()
    attrs = [dict(a) for a in attr_rows]

    item = StockLifecycleItem(
        instrument_id=row[0],
        instrument_key=row[1],
        trading_symbol=row[2],
        name=row[3],
        isin=row[4],
        segment=row[5],
        exchange=row[6],
        instrument_type=row[7],
        lifecycle_status=row[8],
        first_seen=row[9],
        last_seen=row[10],
        included=row[11],
        filter_reason=row[12],
        sector=row[13],
        lifecycle_periods=periods,
        attribute_versions=attrs,
    )

    return Envelope(
        data=item,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=[f"Lifecycle and ISIN history for {key}"],
        ),
    )


@router.get("/{key:path}", response_model=Envelope[InstrumentDetail])
async def get_instrument_detail(
    key: str,
    db: AsyncSession = Depends(get_db),
) -> Envelope[InstrumentDetail]:
    await db.execute(text("SET TRANSACTION READ ONLY"))
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
            select id, valid_from, valid_to, trading_symbol, isin, lot_size, tick_size
            from instrument_attribute_version
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
