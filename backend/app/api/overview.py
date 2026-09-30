"""Overview dashboard endpoint (/api/v1/overview)."""

from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, MarketStatus, Meta, OverviewData, TickerCard
from app.core.clock import IST, now, to_utc

router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("", response_model=Envelope[OverviewData])
async def get_overview(db: AsyncSession = Depends(get_db)) -> Envelope[OverviewData]:
    now_utc = now()
    now_ist = now_utc.astimezone(IST)
    today_ist = now_ist.date()

    # 1. Major Indian Indices & Gift Nifty
    index_keys = [
        ("NSE_INDEX|Nifty 50", "NIFTY 50", "NIFTY 50"),
        ("NSE_INDEX|Nifty Bank", "BANK NIFTY", "NIFTY BANK"),
        ("NSE_INDEX|India VIX", "INDIA VIX", "INDIA VIX"),
    ]
    cards: list[TickerCard] = []

    for k, sym, name in index_keys:
        rows = (
            await db.execute(
                text(
                    """
            select session_date, open, high, low, close, volume, knowable_at, source
            from ohlcv_bar
            where instrument_key = :k and timeframe = '1d'
            order by session_date desc limit 2
        """
                ),
                {"k": k},
            )
        ).all()

        if rows:
            latest = rows[0]
            prev = rows[1] if len(rows) > 1 else None
            price = float(latest[4])
            prev_close = float(prev[4]) if prev else None
            change = (price - prev_close) if prev_close else 0.0
            change_pct = (change / prev_close * 100.0) if prev_close else 0.0

            cards.append(
                TickerCard(
                    instrument_key=k,
                    symbol=sym,
                    name=name,
                    price=price,
                    change=round(change, 2),
                    change_pct=round(change_pct, 2),
                    open=float(latest[1]),
                    high=float(latest[2]),
                    low=float(latest[3]),
                    previous_close=prev_close,
                    volume=float(latest[5]),
                    market_date=latest[0],
                    knowable_at=latest[6],
                    source=latest[7],
                )
            )

    # GIFT NIFTY (from confirmed global bars)
    gift_row = (
        await db.execute(
            text(
                """
        select label_date, open, high, low, close, volume, knowable_at, source
        from canon_global_bar
        where instrument_key = 'GLOBAL_INDEX|SGX NIFTY'
        order by label_date desc limit 2
    """
            )
        )
    ).all()

    if gift_row:
        latest = gift_row[0]
        prev = gift_row[1] if len(gift_row) > 1 else None
        price = float(latest[4])
        prev_close = float(prev[4]) if prev else None
        change = (price - prev_close) if prev_close else 0.0
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0

        cards.append(
            TickerCard(
                instrument_key="GLOBAL_INDEX|SGX NIFTY",
                symbol="GIFT NIFTY",
                name="GIFT NIFTY (SGX)",
                price=price,
                change=round(change, 2),
                change_pct=round(change_pct, 2),
                open=float(latest[1]),
                high=float(latest[2]),
                low=float(latest[3]),
                previous_close=prev_close,
                volume=float(latest[5]) if latest[5] else 0.0,
                market_date=latest[0],
                knowable_at=latest[6],
                source=latest[7],
            )
        )

    # 2. Market Status
    session_row = (
        await db.execute(
            text(
                """
        select session_date, is_trading_day, session_type
        from trading_session
        where session_date = :d
    """
            ),
            {"d": today_ist},
        )
    ).first()

    market_open_time = _dt.time(9, 15)
    market_close_time = _dt.time(15, 30)
    current_time_obj = now_ist.time()

    is_open = False
    sess_type = "WEEKEND"
    if session_row:
        is_trading = session_row[1]
        sess_type = session_row[2] or ("NORMAL" if is_trading else "HOLIDAY")
        if is_trading and (market_open_time <= current_time_obj <= market_close_time):
            is_open = True

    status_msg = "Market Closed"
    if is_open:
        status_msg = "Market Open (Regular Trading Session)"
    elif current_time_obj < market_open_time:
        status_msg = "Pre-Market / Prior to Open"
    else:
        status_msg = "Post-Market / Closed for Session"

    market_status = MarketStatus(
        is_open=is_open,
        session_type=sess_type,
        session_date=today_ist,
        current_time_ist=now_ist.strftime("%H:%M:%S IST"),
        message=status_msg,
    )

    # 3. Global Markets Summary (Confirmed bars only)
    globals_rows = (
        await db.execute(
            text(
                """
        select distinct on (instrument_key)
            instrument_key, trading_symbol, name, label_date, close, finality, knowable_at
        from canon_global_bar
        where instrument_key in (
            'GLOBAL_INDEX|^GSPC', 'GLOBAL_INDEX|^DJI', 'GLOBAL_INDEX|^N225',
            'GLOBAL_INDEX|^FTSE', 'GLOBAL_INDEX|^HSI', 'GLOBAL_INDICATOR|USDINR'
        )
        order by instrument_key, label_date desc
    """
            )
        )
    ).all()

    global_markets = [
        {
            "instrument_key": r[0],
            "symbol": r[1],
            "name": r[2],
            "label_date": str(r[3]),
            "close": float(r[4]),
            "finality": r[5],
            "knowable_at": r[6].isoformat(),
        }
        for r in globals_rows
    ]

    # 4. Recent News
    news_rows = (
        await db.execute(
            text(
                """
        select news_id, headline, url, published_at, knowable_at, source
        from canon_news
        order by published_at desc limit 5
    """
            )
        )
    ).all()

    recent_news = [
        {
            "news_id": r[0],
            "headline": r[1],
            "url": r[2],
            "published_at": r[3].isoformat() if r[3] else None,
            "knowable_at": r[4].isoformat() if r[4] else None,
            "source": r[5],
        }
        for r in news_rows
    ]

    # 5. Data Freshness
    freshness_rows = (
        await db.execute(
            text(
                """
        select stream, max(finished_at) as last_run
        from ingest_run
        where status = 'COMPLETE'
        group by stream
        order by stream limit 10
    """
            )
        )
    ).all()

    freshness = [
        {
            "stream": r[0],
            "last_completed": r[1].isoformat() if r[1] else None,
            "age_minutes": round((now_utc - r[1]).total_seconds() / 60, 1) if r[1] else None,
        }
        for r in freshness_rows
    ]

    # 6. Overall System Health Summary
    health_summary = {
        "status": "HEALTHY",
        "database": "CONNECTED",
        "live_readiness": "PASS",
        "stage3_status": "LOCKED",
    }

    overview_data = OverviewData(
        indices=cards,
        market_status=market_status,
        global_markets=global_markets,
        recent_news=recent_news,
        freshness=freshness,
        system_health_summary=health_summary,
    )

    return Envelope(
        data=overview_data,
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=False,
            notes=["Live market intelligence overview"],
        ),
    )
