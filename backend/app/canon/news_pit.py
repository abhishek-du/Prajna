"""Point-in-time reads of the multi-source news layer (Stage 2 extension, additive).

Visibility at `as_of` (strict, like app.canon.pit):
  item          news_item.knowable_at (= Prajna's first observation) < as_of, and the
                item was written by a PRODUCTION poll - SHADOW rows are never visible
  title/summary the latest news_item_observation with observed_at < as_of, else the
                first observation (a later edit never leaks backwards)
  enrichments   each classification / entity link / mention / story membership /
                assessment / AI row only when ITS knowable_at < as_of: an article that
                joins a story later is not in that story for an earlier snapshot
  Upstox        optional projection of the Stage 1 Upstox news (include_upstox), with
                knowable_at = the article's FIRST FETCH (news_article.fetched_at),
                never its published_at; instrument links from news_instrument
                (knowable at their own fetch)
Nothing here writes. Filters are applied after the point-in-time cut.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import to_utc

_ITEMS = """
select i.id, i.source, i.source_article_id, i.url, i.canonical_url, i.publisher, i.author,
       coalesce(o.title, i.title) as title, coalesce(o.summary, i.summary) as summary,
       i.category_raw, i.symbol_raw, i.language, i.published_at, i.published_at_raw,
       coalesce(o.source_updated_at, i.source_updated_at) as source_updated_at,
       i.discovered_at, i.knowable_at, i.processed_at, i.backlog, i.source_priority,
       i.terms_status, i.content_fetch_status, (o.id is not null) as edited,
       c.category, c.confidence as category_confidence, c.method as category_method,
       a.market_scope, a.potential_impact, a.impact_direction, a.is_breaking, a.breaking_reason,
       a.rule_version as assessment_version, a.evidence as assessment_evidence,
       sm.story_id, sm.method as story_method, sm.score as story_score,
       sm.evidence as story_evidence, sm.knowable_at as story_knowable_at,
       array(select distinct l.instrument_key from news_entity_link l where l.item_id = i.id
             and l.instrument_key is not null and l.knowable_at < :as_of) as instruments,
       array(select distinct e.entity_type || ':' || e.entity_id from news_entity_mention e
             where e.item_id = i.id and e.knowable_at < :as_of) as entities,
       ai.output as ai_output, ai.model_id as ai_model_id, ai.prompt_version as ai_prompt_version,
       ai.generated_at as ai_generated_at
from news_item i
join news_poll p on p.id = i.first_poll_id and p.mode = 'PRODUCTION'
left join lateral (select * from news_item_observation x where x.item_id = i.id
                   and x.observed_at < :as_of order by x.observed_at desc, x.id desc limit 1) o
       on true
left join lateral (select * from news_classification x where x.item_id = i.id
                   and x.knowable_at < :as_of order by x.knowable_at desc, x.id desc limit 1) c
       on true
left join lateral (select * from news_assessment x where x.item_id = i.id and x.basis = 'RULES'
                   and x.knowable_at < :as_of order by x.knowable_at desc, x.id desc limit 1) a
       on true
left join lateral (select * from news_story_member x where x.item_id = i.id
                   and x.knowable_at < :as_of order by x.knowable_at desc, x.id desc limit 1) sm
       on true
left join lateral (select * from news_ai_enrichment x where x.item_id = i.id and x.status = 'OK'
                   and x.knowable_at < :as_of order by x.knowable_at desc, x.id desc limit 1) ai
       on true
where i.knowable_at < :as_of
"""

_UPSTOX = """
select -a.id as id, 'UPSTOX' as source, a.id::text as source_article_id, a.url,
       a.url as canonical_url, coalesce(a.publisher, 'Upstox') as publisher, null as author,
       a.headline as title, a.body as summary, null as category_raw, null as symbol_raw,
       'en' as language, a.published_at, null as published_at_raw, null as source_updated_at,
       a.fetched_at as discovered_at, a.fetched_at as knowable_at, a.fetched_at as processed_at,
       null::boolean as backlog, 2 as source_priority, 'APPROVED' as terms_status,
       'NOT_AVAILABLE' as content_fetch_status, false as edited,
       null as category, null as category_confidence, null as category_method,
       null as market_scope, null as potential_impact, null as impact_direction,
       null::boolean as is_breaking, null as breaking_reason, null as assessment_version,
       null::jsonb as assessment_evidence, null::bigint as story_id, null as story_method,
       null as story_score, null::jsonb as story_evidence, null as story_knowable_at,
       array(select distinct n.instrument_key from news_instrument n where n.news_id = a.id
             and n.knowable_at < :as_of) as instruments,
       array[]::text[] as entities, null::jsonb as ai_output, null as ai_model_id,
       null as ai_prompt_version, null as ai_generated_at
from news_article a
where a.fetched_at < :as_of
"""


def _where(f: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses, params = [], {}
    simple = {"source": "source", "category": "category", "market_scope": "market_scope",
              "potential_impact": "potential_impact", "impact_direction": "impact_direction",
              "publisher": "publisher", "story_id": "story_id"}
    for k, col in simple.items():
        if f.get(k) is not None:
            clauses.append(f"{col} = :{k}")
            params[k] = f[k]
    if f.get("breaking") is not None:
        clauses.append("coalesce(is_breaking, false) = :breaking")
        params["breaking"] = f["breaking"]
    if f.get("instrument_key"):
        clauses.append(":instrument_key = any(instruments)")
        params["instrument_key"] = f["instrument_key"]
    if f.get("entity"):
        clauses.append(":entity = any(entities)")
        params["entity"] = f["entity"]
    if f.get("since") is not None:
        clauses.append("knowable_at >= :since")
        params["since"] = to_utc(f["since"])
    return (" where " + " and ".join(clauses)) if clauses else "", params


async def items(s: AsyncSession, as_of: _dt.datetime, *, include_upstox: bool = False,
                limit: int = 200, offset: int = 0, **filters: Any) -> list[dict[str, Any]]:
    """News visible at `as_of`, newest knowable first, with the enrichments knowable then."""
    base = _ITEMS + (f" union all {_UPSTOX}" if include_upstox else "")
    where, params = _where(filters)
    # constant SQL fragments and whitelisted column names only; every value is bound
    sql = (f"select * from ({base}) v{where} order by knowable_at desc, id desc "  # noqa: S608
           f"limit :limit offset :offset")
    rows = await s.execute(text(sql), {"as_of": to_utc(as_of), "limit": limit,
                                       "offset": offset, **params})
    return [dict(r) for r in rows.mappings()]


async def item(s: AsyncSession, as_of: _dt.datetime, item_id: int, *,
               include_upstox: bool = False) -> dict[str, Any] | None:
    base = _ITEMS + (f" union all {_UPSTOX}" if include_upstox else "")
    r = (await s.execute(text(f"select * from ({base}) v where id = :id"),  # noqa: S608
                         {"as_of": to_utc(as_of), "id": item_id})).mappings().first()
    return dict(r) if r else None


async def stories(s: AsyncSession, as_of: _dt.datetime, *, limit: int = 100,
                  story_id: int | None = None, instrument_key: str | None = None
                  ) -> list[dict[str, Any]]:
    """Stories with >= 1 member visible at as_of; members/publishers as known then."""
    rows = await items(s, as_of, limit=5000, story_id=story_id, instrument_key=instrument_key)
    by: dict[int, dict[str, Any]] = {}
    for r in rows:
        if r["story_id"] is None:
            continue
        st = by.setdefault(r["story_id"], {
            "story_id": r["story_id"], "members": [], "publishers": set(), "sources": set(),
            "instruments": set(), "entities": set(), "first_knowable_at": r["knowable_at"],
            "last_knowable_at": r["knowable_at"], "is_breaking": False})
        st["members"].append({k: r[k] for k in ("id", "source", "publisher", "title", "url",
                                                "published_at", "knowable_at", "story_method",
                                                "story_score", "story_evidence")})
        st["publishers"].add(r["publisher"])
        st["sources"].add(r["source"])
        st["instruments"].update(r["instruments"] or [])
        st["entities"].update(r["entities"] or [])
        st["first_knowable_at"] = min(st["first_knowable_at"], r["knowable_at"])
        st["last_knowable_at"] = max(st["last_knowable_at"], r["knowable_at"])
        st["is_breaking"] = st["is_breaking"] or bool(r["is_breaking"])
    out = []
    for st in sorted(by.values(), key=lambda x: x["last_knowable_at"], reverse=True)[:limit]:
        m = sorted(st["members"], key=lambda x: x["knowable_at"])
        out.append({**st, "members": m, "title": m[0]["title"], "article_count": len(m),
                    "publishers": sorted(st["publishers"]), "sources": sorted(st["sources"]),
                    "instruments": sorted(st["instruments"]), "entities": sorted(st["entities"])})
    return out
