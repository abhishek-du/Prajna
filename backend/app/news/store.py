"""SHADOW recorder: one poll -> the news_* tables (LOCKED; see app.news.locks).

One IngestRunner run per poll (ledger, token, reaper). The feed body is archived
(raw_payload) before anything is parsed. "Seen" comes from the database: an
item already stored for the source is not new, and a difference in title /
summary / times is stored as a news_item_observation (the item row is never
updated). Classification and entity links are inserted with the item, stamped
with their version and knowable_at = the moment they were computed.
Idempotent: a rerun of the same response inserts nothing new.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.core.config import get_settings
from app.db.models import (
    NewsClassification,
    NewsEntityLink,
    NewsItem,
    NewsItemObservation,
    NewsPoll,
)
from app.ingest.runner import IngestRunner
from app.news import enrich as EN
from app.news import http as H
from app.news import locks
from app.news.collector import Seen, _iso, load_universe, process
from app.news.model import canonical_url, title_hash
from app.news.sources import SOURCES
from app.storage.payload_store import PayloadStore


async def _seen(s: AsyncSession, source: str) -> dict[str, Seen]:
    """Latest known state of every stored item of the source (item + observations)."""
    rows = (await s.execute(text("""
        select i.source_article_id, i.discovered_at,
               coalesce(o.title, i.title), coalesce(o.summary, i.summary),
               coalesce(o.published_at, i.published_at),
               coalesce(o.source_updated_at, i.source_updated_at)
        from news_item i
        left join lateral (select * from news_item_observation x where x.item_id = i.id
                           order by x.observed_at desc, x.id desc limit 1) o on true
        where i.source = :s"""), {"s": source})).all()
    return {r[0]: Seen(_iso(r[1]), r[2], r[3], _iso(r[4]), _iso(r[5])) for r in rows}


async def _aliases(s: AsyncSession, source: str, at: _dt.datetime) -> EN.Aliases:
    """Filer names learned from EXACT_SYMBOL links knowable before `at`."""
    a = EN.Aliases()
    for title, sym in (await s.execute(text("""
            select i.title, l.matched_text from news_entity_link l
            join news_item i on i.id = l.item_id
            where i.source = :s and l.method = 'EXACT_SYMBOL' and l.knowable_at < :at"""),
            {"s": source, "at": at})).all():
        a.learn(title, sym)
    return a


async def poll_shadow(s: AsyncSession, source_key: str, *, token: str | None,
                      operator: str = "cli", transport=None,
                      http_state: H.SourceState | None = None,
                      mode: str = "SHADOW") -> dict[str, Any]:
    """One committed poll in SHADOW (invisible) or PRODUCTION (visible) mode."""
    await locks.require(s, source_key, mode=mode, token=token, operator=operator)
    src = SOURCES[source_key]
    runner = IngestRunner(s, source=src.key[:32], stream=f"news.{src.key}"[:64],
                          vendor_endpoint=src.url, request_params={"mode": mode},
                          operator=operator)
    ctx = await runner.open(commit=True, token=token)
    try:
        state = http_state or H.SourceState()
        f = await H.fetch(src.url, state, transport=transport)
        sha = None
        if f.body:
            stored = PayloadStore(get_settings().archive_dir).put(
                f.body, source=src.key[:32], content_type="application/xml", ext="xml",
                fetched_at=f.finished_at)
            await runner.record_payload(stored, http_status=f.http_status, vendor_endpoint=src.url)
            sha = stored.sha256
        seen = await _seen(s, src.key)
        first = not seen and not (await s.execute(text(
            "select 1 from news_poll where source = :s and outcome = 'OK' limit 1"),
            {"s": src.key})).first()
        o = process(src, f, seen, universe=await load_universe(),
                    aliases=await _aliases(s, src.key, f.finished_at), first_success=first)
        poll_id = (await s.execute(insert(NewsPoll).values(
            source=src.key, mode=mode, run_id=ctx.run_id, started_at=f.started_at,
            finished_at=f.finished_at, outcome=o.fetch.outcome, http_status=f.http_status,
            bytes=len(f.body), items_seen=o.seen, items_new=len(o.new),
            items_changed=len(o.changed), backlog=o.backlog, etag=f.etag,
            last_modified=f.last_modified, payload_sha256=sha, error=o.fetch.error,
        ).returning(NewsPoll.id))).scalar()
        inserted = 0
        for d in o.new:
            it, t = d.item, now()
            iid = (await s.execute(pg_insert(NewsItem).values(
                source=src.key, source_article_id=it.source_article_id, url=it.url,
                canonical_url=canonical_url(it.url), title=it.title,
                title_norm_hash=title_hash(it.title), summary=it.summary, body=None,
                publisher=it.publisher, author=it.author, category_raw=it.category_raw,
                symbol_raw=it.symbol_raw, attachment_url=it.attachment_url,
                language=it.language, region=it.region, published_at=it.published_at,
                published_at_raw=it.published_at_raw, source_updated_at=it.source_updated_at,
                discovered_at=d.discovered_at, knowable_at=d.discovered_at, backlog=d.backlog,
                content_available=False, first_poll_id=poll_id, payload_sha256=sha,
            ).on_conflict_do_nothing(constraint="uq_news_item_source_id")
                .returning(NewsItem.id))).scalar()
            if iid is None:
                continue
            inserted += 1
            c = d.classification
            await s.execute(insert(NewsClassification).values(
                item_id=iid, category=c.category, confidence=c.confidence, method=c.method,
                version=c.version, classified_at=t, knowable_at=t))
            for ln in d.links:
                await s.execute(insert(NewsEntityLink).values(
                    item_id=iid, instrument_key=ln.instrument_key, method=ln.method,
                    confidence=ln.confidence, matched_text=ln.matched_text, reason=ln.reason,
                    version=ln.version, mapped_at=t, knowable_at=t))
        if o.changed:
            ids = dict((await s.execute(select(NewsItem.source_article_id, NewsItem.id).where(
                NewsItem.source == src.key, NewsItem.source_article_id.in_(
                    [it.source_article_id for it, _ in o.changed])))).all())
            for it, ch in o.changed:
                await s.execute(insert(NewsItemObservation).values(
                    item_id=ids[it.source_article_id], poll_id=poll_id,
                    observed_at=f.finished_at, title=it.title, summary=it.summary,
                    published_at=it.published_at, source_updated_at=it.source_updated_at,
                    changed=ch))
        if f.outcome in ("BLOCKED", "AUTH_FAILED"):
            await locks.audit(s, "BLOCKED", src.key, operator,
                              {"http_status": f.http_status, "error": f.error})
        outcome = {"outcome": o.fetch.outcome, "http_status": f.http_status, "items_seen": o.seen,
                   "inserted": inserted, "changed": len(o.changed), "backlog": o.backlog,
                   "poll_id": poll_id}
        await runner.finalize(rows_written=inserted + len(o.changed) + 1, outcome=outcome)
        return {"run_id": str(ctx.run_id), **outcome}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
