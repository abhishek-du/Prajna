"""SHADOW recorder: one poll -> the news_* tables (LOCKED; see app.news.locks).

One IngestRunner run per poll (ledger, token, reaper). The feed body is archived
(raw_payload) before anything is parsed. "Seen" comes from the database: an
item already stored for the source is not new, and a difference in title /
summary / times is stored as a news_item_observation (the item row is never
updated). Classification and entity links are inserted with the item, stamped
with their version and knowable_at = the moment they were computed.
Idempotent: a rerun of the same response inserts nothing new.

Concurrency: the database part of a poll (after the HTTP fetch) runs under two
transaction-scoped advisory locks, always taken in the same order - the
source's own, then one shared story lock - so two writers of one source (an
overlapping cron run, a manual poll) never both treat an item or an edit as new,
and two sources never both found a story for the same event. The unique key
(source, source_article_id) with ON CONFLICT DO NOTHING stays as the last guard.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.core.config import get_settings
from app.db.models import (
    NewsAssessment,
    NewsClassification,
    NewsDecision,
    NewsEntityLink,
    NewsEntityMention,
    NewsItem,
    NewsItemObservation,
    NewsPoll,
    NewsStory,
    NewsStoryMember,
)
from app.ingest.runner import IngestRunner
from app.news import dedup as DD
from app.news import enrich as EN
from app.news import http as H
from app.news import locks
from app.news import stories as ST
from app.news.collector import Seen, _iso, load_universe, process
from app.news.model import canonical_url, title_hash
from app.news.sources import SOURCES
from app.storage.payload_store import PayloadStore

STORY_LOCK = "news:stories"


def lock_key(name: str) -> int:
    """A stable signed 64-bit key for pg_advisory_xact_lock."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)


async def serialise(s: AsyncSession, source: str) -> None:
    """Held until the poll's transaction ends (commit or rollback); source first."""
    for name in (f"news:source:{source}", STORY_LOCK):
        await s.execute(text("select pg_advisory_xact_lock(:k)"), {"k": lock_key(name)})


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


async def _priors(s: AsyncSession, source: str, at: _dt.datetime) -> list[DD.Prior]:
    """The source's articles stored within the dedup window before `at`."""
    rows = (await s.execute(text("""
        select id, canonical_url, title_norm_hash, content_sha256, discovered_at
        from news_item where source = :s and discovered_at >= :since
          and content_sha256 is not null"""), {"s": source, "since": at - DD.WINDOW})).all()
    return [DD.Prior(*r) for r in rows]


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


async def _stories(s: AsyncSession, at: _dt.datetime) -> ST.StoryIndex:
    """Story members KNOWABLE before `at` within the grouping window (point in time)."""
    ix = ST.StoryIndex()
    rows = (await s.execute(text("""
        select m.story_id, i.source, i.source_article_id, i.title, i.summary, i.canonical_url,
               i.title_norm_hash, coalesce(i.published_at, i.discovered_at) as t_ref, m.knowable_at,
               (select c.category from news_classification c where c.item_id = i.id
                  and c.method <> 'SCOPE_RULES' and c.knowable_at < :at
                  order by c.knowable_at desc, c.id desc limit 1) as cat,
               array(select l.instrument_key from news_entity_link l where l.item_id = i.id
                  and l.instrument_key is not null and l.knowable_at < :at) as cos,
               array(select e.entity_type || ':' || e.entity_id from news_entity_mention e
                  where e.item_id = i.id and e.knowable_at < :at) as ents
        from news_story_member m join news_item i on i.id = m.item_id
        where m.knowable_at < :at and m.rule_version in ('story-v1', :v)
          and coalesce(i.published_at, i.discovered_at) > :since"""),
        {"at": at, "v": ST.VERSION, "since": at - 2 * ST.WINDOW})).all()
    for r in rows:
        ix.add(ST.Member(f"{r.source}|{r.source_article_id}", f"db:{r.story_id}", r.source,
                         ST.words(r.title), r.canonical_url,
                         ST.identity_hash(r.title, r.summary, strict=SOURCES[r.source].enrich in (
                             "EXCHANGE", "REGULATOR") if r.source in SOURCES else False),
                         frozenset(r.cos), frozenset(r.ents), r.cat or "OTHER", r.t_ref,
                         r.knowable_at, SOURCES[r.source].enrich in ("EXCHANGE", "REGULATOR")
                         if r.source in SOURCES else False))
    return ix


def _metadata_sha(it) -> str:
    return hashlib.sha256(json.dumps(
        {k: str(getattr(it, k)) for k in it.__slots__}, sort_keys=True).encode()).hexdigest()


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
        # serialised from here (after the HTTP fetch): two writers that fetched the same
        # bytes would otherwise race on raw_payload's key as well as on the items
        await serialise(s, src.key)
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
        story_ix = await _stories(s, f.finished_at)
        priors = await _priors(s, src.key, f.finished_at)
        exchange = src.enrich in ("EXCHANGE", "REGULATOR")
        o = process(src, f, seen, universe=await load_universe(),
                    aliases=await _aliases(s, src.key, f.finished_at), first_success=first,
                    stories=story_ix)
        if f.outcome == "OK" and o.fetch.outcome == "OK":   # the feed <ttl> paces the next poll
            ttl = src.parse(f.body).ttl_minutes
            state.ttl_s = ttl * 60 if ttl else None
        poll_id = (await s.execute(insert(NewsPoll).values(
            source=src.key, mode=mode, run_id=ctx.run_id, started_at=f.started_at,
            finished_at=f.finished_at, outcome=o.fetch.outcome, http_status=f.http_status,
            bytes=len(f.body), items_seen=o.seen, items_new=len(o.new),
            items_changed=len(o.changed), backlog=o.backlog, etag=f.etag,
            last_modified=f.last_modified, payload_sha256=sha, error=o.fetch.error,
        ).returning(NewsPoll.id))).scalar()
        inserted = 0
        decisions: dict[str, int] = {}
        db_story: dict[str, int] = {}          # in-memory story id -> news_story.id
        for d in o.new:
            it, t = d.item, now()
            curl, thash = canonical_url(it.url), title_hash(it.title)
            csha = hashlib.sha256(f"{it.title}\x1f{it.summary or ''}".encode()).hexdigest()
            iid = (await s.execute(pg_insert(NewsItem).values(
                source=src.key, source_article_id=it.source_article_id, url=it.url,
                canonical_url=curl, title=it.title,
                title_norm_hash=thash, summary=it.summary, body=None,
                publisher=it.publisher, author=it.author, category_raw=it.category_raw,
                symbol_raw=it.symbol_raw, attachment_url=it.attachment_url,
                language=it.language, region=it.region, published_at=it.published_at,
                published_at_raw=it.published_at_raw, source_updated_at=it.source_updated_at,
                discovered_at=d.discovered_at, knowable_at=d.discovered_at, backlog=d.backlog,
                content_available=False, first_poll_id=poll_id, payload_sha256=sha,
                source_priority=src.priority, terms_status=src.compliance, robots_allowed=None,
                content_fetch_status="NOT_AVAILABLE", metadata_sha256=_metadata_sha(it),
                content_sha256=csha,
                processed_at=t,
            ).on_conflict_do_nothing(constraint="uq_news_item_source_id")
                .returning(NewsItem.id))).scalar()
            if iid is None:
                continue
            inserted += 1
            c = d.classification
            await s.execute(insert(NewsClassification).values(
                item_id=iid, category=c.category, confidence=c.confidence, method=c.method,
                version=c.version, classified_at=t, knowable_at=t))
            if d.scope is not None:               # scope-v1: a second, versioned classification
                sc = d.scope
                await s.execute(insert(NewsClassification).values(
                    item_id=iid, category=sc.primary, confidence=sc.confidence,
                    method=sc.method, version=sc.version, classified_at=t, knowable_at=t))
            for ln in d.links:
                await s.execute(insert(NewsEntityLink).values(
                    item_id=iid, instrument_key=ln.instrument_key, method=ln.method,
                    confidence=ln.confidence, matched_text=ln.matched_text, reason=ln.reason,
                    version=ln.version, mapped_at=t, knowable_at=t))
            for m in d.mentions:
                await s.execute(insert(NewsEntityMention).values(
                    item_id=iid, entity_type=m.entity_type, entity_id=m.entity_id,
                    method="PATTERN", confidence=m.confidence, evidence=m.evidence,
                    version=m.version, mapped_at=t, knowable_at=t))
            story_pk = None
            if d.story is not None and d.story_id is not None:
                sid = d.story_id
                if sid.startswith("db:"):
                    story_pk = int(sid[3:])
                elif sid in db_story:
                    story_pk = db_story[sid]
                else:
                    story_pk = (await s.execute(insert(NewsStory).values(
                        first_item_id=iid, rule_version=ST.VERSION, created_at=t, knowable_at=t
                    ).returning(NewsStory.id))).scalar()
                    db_story[sid] = story_pk
                await s.execute(insert(NewsStoryMember).values(
                    story_id=story_pk, item_id=iid, method=d.story.method,
                    score=d.story.score, evidence=d.story.evidence, rule_version=ST.VERSION,
                    joined_at=t, knowable_at=t))
            dec = DD.decide_new(
                canonical_url=curl, title_norm_hash=thash, content_sha256=csha, title=it.title,
                discovered_at=d.discovered_at, priors=priors, exchange=exchange,
                story_method=d.story.method if d.story is not None else None,
                story_evidence=d.story.evidence if d.story is not None else None)
            await s.execute(insert(NewsDecision).values(
                item_id=iid, poll_id=poll_id, decision=dec.decision, rule=dec.rule,
                rule_version=dec.version, related_item_id=dec.related_item_id,
                story_id=story_pk, evidence=dec.evidence, decided_at=t, knowable_at=t))
            decisions[dec.decision] = decisions.get(dec.decision, 0) + 1
            priors.append(DD.Prior(iid, curl, thash, csha, d.discovered_at))
            if d.assessment is not None:
                a = d.assessment
                await s.execute(insert(NewsAssessment).values(
                    item_id=iid, basis=a.basis, market_scope=a.market_scope,
                    potential_impact=a.potential_impact, impact_direction=a.impact_direction,
                    is_breaking=a.is_breaking, breaking_reason=a.breaking_reason,
                    evidence={**a.evidence, "event_group": a.event_group,
                              **({"scope": {"primary": d.scope.primary,
                                            "secondary": list(d.scope.secondary),
                                            "version": d.scope.version, **d.scope.evidence}}
                                 if d.scope is not None else {})},
                    rule_version=a.version, assessed_at=t, knowable_at=t))
        if o.changed:
            ids = dict((await s.execute(select(NewsItem.source_article_id, NewsItem.id).where(
                NewsItem.source == src.key, NewsItem.source_article_id.in_(
                    [it.source_article_id for it, _ in o.changed])))).all())
            for it, ch in o.changed:
                oid = (await s.execute(insert(NewsItemObservation).values(
                    item_id=ids[it.source_article_id], poll_id=poll_id,
                    observed_at=f.finished_at, title=it.title, summary=it.summary,
                    published_at=it.published_at, source_updated_at=it.source_updated_at,
                    changed=ch).returning(NewsItemObservation.id))).scalar()
                prev = seen.get(it.source_article_id)
                dec = DD.decide_edit(ch, old_title=prev.title if prev else None,
                                     new_title=it.title)
                if dec is not None:
                    t = now()
                    await s.execute(insert(NewsDecision).values(
                        item_id=ids[it.source_article_id], observation_id=oid, poll_id=poll_id,
                        decision=dec.decision, rule=dec.rule, rule_version=dec.version,
                        evidence=dec.evidence, decided_at=t, knowable_at=t))
                    decisions[dec.decision] = decisions.get(dec.decision, 0) + 1
        if f.outcome in ("BLOCKED", "AUTH_FAILED"):
            await locks.audit(s, "BLOCKED", src.key, operator,
                              {"http_status": f.http_status, "error": f.error})
        outcome = {"outcome": o.fetch.outcome, "http_status": f.http_status, "items_seen": o.seen,
                   "inserted": inserted, "changed": len(o.changed), "backlog": o.backlog,
                   "decisions": decisions, "poll_id": poll_id}
        await runner.finalize(rows_written=inserted + len(o.changed) + 1, outcome=outcome)
        return {"run_id": str(ctx.run_id), **outcome}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
