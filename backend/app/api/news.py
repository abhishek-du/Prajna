"""News intelligence endpoint with provenance timestamps (/api/v1/news)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import Envelope, Meta, NewsArticleItem, NewsResponse
from app.core.clock import now

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=Envelope[NewsResponse])
async def list_news(
    instrument_key: str | None = Query(None, description="filter by instrument key"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Envelope[NewsResponse]:
    now_utc = now()

    conditions = ["1=1"]
    params: dict = {"lim": limit}

    if instrument_key:
        conditions.append(
            """
            a.id in (
                select news_id from news_instrument ni
                where ni.instrument_key = :k
            )
        """
        )
        params["k"] = instrument_key

    where_clause = " and ".join(conditions)

    sql = f"""
        select
            a.id,
            a.headline,
            a.body,
            a.url,
            a.publisher,
            a.published_at,
            a.fetched_at as received_at,
            r.finished_at as processed_at,
            a.source
        from news_article a
        left join ingest_run r on r.run_id = a.run_id
        where {where_clause}
        order by a.published_at desc nulls last, a.fetched_at desc
        limit :lim
    """
    rows = (await db.execute(text(sql), params)).all()

    article_ids = [r[0] for r in rows]

    # Get affected instruments per article
    instruments_map: dict[int, list[str]] = {aid: [] for aid in article_ids}
    if article_ids:
        inst_sql = """
            select ni.news_id, coalesce(i.trading_symbol, ni.instrument_key)
            from news_instrument ni
            left join instrument i on i.instrument_key = ni.instrument_key and i.valid_to = 'infinity'
            where ni.news_id = any(:ids)
        """
        inst_rows = (await db.execute(text(inst_sql), {"ids": article_ids})).all()
        for nid, sym in inst_rows:
            instruments_map[nid].append(sym)

    articles: list[NewsArticleItem] = []
    for r in rows:
        aid = r[0]
        pub_at = r[5]
        rec_at = r[6]
        proc_at = r[7]
        latency = (rec_at - pub_at).total_seconds() if (pub_at and rec_at) else None

        aff_inst = instruments_map.get(aid, [])
        classification = "MARKET"
        if len(aff_inst) == 1:
            classification = "STOCK"
        elif len(aff_inst) > 1:
            classification = "SECTOR"

        articles.append(
            NewsArticleItem(
                news_id=aid,
                headline=r[1],
                body=r[2],
                url=r[3],
                publisher=r[4],
                published_at=pub_at,
                received_at=rec_at,
                processed_at=proc_at,
                latency_seconds=round(latency, 1) if latency is not None else None,
                source=r[8],
                affected_instruments=aff_inst,
                classification=classification,
                # Sentiment status remains NOT_AVAILABLE (no fake sentiment scores)
            )
        )

    return Envelope(
        data=NewsResponse(
            total=len(articles),
            articles=articles,
        ),
        meta=Meta(
            as_of=now_utc,
            generated_at=now_utc,
            point_in_time=True,
            notes=["Provenance-bearing news feed (receipt & processing timestamps tracked)"],
        ),
    )
