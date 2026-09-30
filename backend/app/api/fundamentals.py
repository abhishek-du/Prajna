"""Fundamentals data endpoint (/api/v1/fundamentals)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    CorporateActionItem,
    Envelope,
    FinancialStatement,
    FundamentalsResponse,
    KeyRatios,
    Meta,
)
from app.core.clock import now

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])


@router.get("/{key:path}", response_model=Envelope[FundamentalsResponse])
async def get_fundamentals(
    key: str,
    db: AsyncSession = Depends(get_db),
) -> Envelope[FundamentalsResponse]:
    now_utc = now()

    # Check instrument exists
    inst_exists = (
        await db.execute(
            text("select 1 from instrument where instrument_key = :k limit 1"),
            {"k": key},
        )
    ).scalar()
    if not inst_exists:
        raise HTTPException(status_code=404, detail=f"Instrument {key} not found")

    # 1. Profile information
    prof_row = (
        await db.execute(
            text(
                """
        select payload
        from fundamental_snapshot
        where instrument_key = :k and statement_type = 'profile'
        order by knowable_at desc limit 1
    """
            ),
            {"k": key},
        )
    ).scalar()

    company_name = None
    sector = None
    industry = None
    description = None

    if prof_row:
        p_dict = prof_row if isinstance(prof_row, dict) else json.loads(prof_row)
        company_name = p_dict.get("company_name") or p_dict.get("companyName")
        sector = p_dict.get("sector")
        industry = p_dict.get("industry")
        description = p_dict.get("description")

    # 2. Key Ratios
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

    key_ratios = KeyRatios()
    if ratios_row:
        raw_list = ratios_row if isinstance(ratios_row, list) else json.loads(ratios_row)
        key_ratios.raw_ratios = raw_list
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip().upper()
            c_val_str = item.get("company_value") or item.get("value")
            s_val_str = item.get("sector_value")
            try:
                c_val = float(c_val_str) if c_val_str is not None else None
            except (ValueError, TypeError):
                c_val = None

            try:
                s_val = float(s_val_str) if s_val_str is not None else None
            except (ValueError, TypeError):
                s_val = None

            if "P/E" in name:
                key_ratios.pe = c_val
                key_ratios.sector_pe = s_val
            elif "P/B" in name:
                key_ratios.pb = c_val
            elif "EPS" in name:
                key_ratios.eps = c_val
            elif "ROE" in name:
                key_ratios.roe = c_val
            elif "ROCE" in name:
                key_ratios.roce = c_val
            elif "MARKET CAP" in name:
                key_ratios.market_cap = c_val
            elif "DIVIDEND YIELD" in name:
                key_ratios.dividend_yield = c_val
            elif "DEBT TO EQUITY" in name:
                key_ratios.debt_to_equity = c_val
            elif "PRICE TO SALES" in name:
                key_ratios.price_to_sales = c_val

    # 3. Financial Statements
    stmt_rows = (
        await db.execute(
            text(
                """
        select statement_type, period_end, period_type, payload, reported_at, knowable_at
        from fundamental_snapshot
        where instrument_key = :k and statement_type not in ('profile', 'key_ratios', 'share_holdings')
        order by statement_type, period_end desc nulls last, knowable_at desc
    """
            ),
            {"k": key},
        )
    ).all()

    statements = [
        FinancialStatement(
            statement_type=r[0],
            period_end=r[1],
            period_type=r[2],
            payload=r[3],
            reported_at=r[4],
            knowable_at=r[5],
        )
        for r in stmt_rows
    ]

    # 4. Shareholdings
    holdings_row = (
        await db.execute(
            text(
                """
        select payload
        from fundamental_snapshot
        where instrument_key = :k and statement_type = 'share_holdings'
        order by knowable_at desc limit 1
    """
            ),
            {"k": key},
        )
    ).scalar()

    # 5. Corporate Actions
    ca_rows = (
        await db.execute(
            text(
                """
        select cf.ca_id, cf.action_type, cf.ex_date, ca.record_date, cf.factor_price, cf.status as factor_status, cf.vendor_applied, cf.knowable_at
        from ca_factor cf
        left join corporate_action ca on ca.id = cf.ca_id
        where cf.instrument_key = :k
        order by cf.ex_date desc nulls last
    """
            ),
            {"k": key},
        )
    ).all()

    corporate_actions = [
        CorporateActionItem(
            id=r[0],
            action_type=r[1],
            ex_date=r[2],
            record_date=r[3],
            amount=None,
            ratio_from=None,
            ratio_to=None,
            face_value_before=None,
            face_value_after=None,
            factor_price=float(r[4]) if r[4] is not None else None,
            factor_status=r[5],
            vendor_applied=r[6],
            knowable_at=r[7],
        )
        for r in ca_rows
    ]

    response_data = FundamentalsResponse(
        instrument_key=key,
        company_name=company_name,
        sector=sector,
        industry=industry,
        description=description,
        key_ratios=key_ratios,
        statements=statements,
        corporate_actions=corporate_actions,
        shareholdings=holdings_row,
    )

    return Envelope(
        data=response_data,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=[f"Fundamentals for {key}"],
        ),
    )
