"""Point-in-time results events for Stage 3 (features-v5; docs/STAGE3_FEATURES_V5.md).

The results calendar (INTIMATION), results dissemination (OUTCOME) and the street's
verdict (ESTIMATE_NEWS) are derived AT THE SNAPSHOT from the news rows visible then,
with the same pure parser as the results_event table (app.fundamentals.events). The
table is filled by a daily job hours later, so reading it would give a live snapshot
less than a later recompute of the same instant; parsing here gives both the same.

Visibility at `as_of` (strict, like app.canon.pit / news_pit):
  item     news_item.knowable_at < as_of, written by a PRODUCTION poll
  text     the latest news_item_observation with observed_at < as_of, else the first one
  link     news_entity_link rows with knowable_at < as_of; confidence >= 0.9 for an NSE
           announcement, >= 0.8 for a news headline (the news sources' links reach 0.85);
           the event belongs to the best one; a headline linked to several names is no
           ESTIMATE_NEWS
  knowable the later of the item and its link; event_at = the publisher's time (published
           later than knowable: knowable_at instead)
coverage_from(): the first PRODUCTION poll of the NSE announcements source that succeeded
before as_of; before it no absence of an event means anything.
Nothing here writes.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon.time import assert_all_knowable
from app.core.clock import to_utc
from app.fundamentals import store as FS

WINDOW = _dt.timedelta(days=150)       # covers meeting lead times and the 120-day lookbacks


@dataclass(frozen=True, slots=True)
class ResultsEvent:
    kind: str
    instrument_key: str
    meeting_date: _dt.date | None
    period_end: _dt.date | None
    verdict: str | None
    event_at: _dt.datetime
    knowable_at: _dt.datetime
    news_id: int


_SQL = """
with it as (
  select n.id, n.source, n.category_raw, n.published_at, n.knowable_at,
         coalesce(o.title, n.title) as title, coalesce(o.summary, n.summary) as summary
    from news_item n
    join news_poll p on p.id = n.first_poll_id and p.mode = 'PRODUCTION'
    left join lateral (select x.title, x.summary from news_item_observation x
                        where x.item_id = n.id and x.observed_at < :as_of
                        order by x.observed_at desc, x.id desc limit 1) o on true
   where n.knowable_at < :as_of and n.knowable_at >= :since
     and ((n.source = :ann and n.category_raw = any(cast(:cats as text[])))
       or (n.source <> :ann and coalesce(o.title, n.title) ~* :pre))),
links as (
  select l.item_id, l.instrument_key, l.knowable_at, l.confidence,
         count(*) over (partition by l.item_id) as n_links,
         row_number() over (partition by l.item_id
                            order by l.confidence desc, l.instrument_key) as rk
    from news_entity_link l
   where l.item_id in (select id from it) and l.knowable_at < :as_of
     and l.instrument_key is not null and l.confidence >= cast(:cn as numeric))
select it.*, k.instrument_key, k.n_links,
       greatest(it.knowable_at, k.knowable_at) as knowable_at
  from it join links k on k.item_id = it.id and k.rk = 1
 where it.source <> :ann or k.confidence >= cast(:c as numeric)
 order by it.id"""


async def events(s: AsyncSession, as_of: _dt.datetime) -> dict[str, list[ResultsEvent]]:
    """instrument_key -> its results events visible at as_of (oldest knowable first)."""
    rows = [dict(r) for r in (await s.execute(text(_SQL), {
        "as_of": to_utc(as_of), "since": to_utc(as_of - WINDOW), "ann": FS.ANNOUNCEMENT_SOURCE,
        "cats": list(FS.ANNOUNCEMENT_CATEGORIES), "pre": FS.NEWS_PREFILTER,
        "c": FS.LINK_MIN_CONFIDENCE, "cn": FS.NEWS_LINK_MIN_CONFIDENCE})).mappings().all()]
    assert_all_knowable(rows, as_of, "results events")
    out: dict[str, list[ResultsEvent]] = {}
    for r in rows:
        ev = FS.event_for(SimpleNamespace(**r))
        if ev is None:
            continue
        at = r["published_at"] if r["published_at"] and r["published_at"] <= r["knowable_at"] \
            else r["knowable_at"]
        out.setdefault(r["instrument_key"], []).append(ResultsEvent(
            ev.kind, r["instrument_key"], ev.meeting_date, ev.period_end, ev.verdict, at,
            r["knowable_at"], r["id"]))
    for v in out.values():
        v.sort(key=lambda e: (e.knowable_at, e.news_id))
    return out


async def coverage_from(s: AsyncSession, as_of: _dt.datetime) -> _dt.datetime | None:
    return (await s.execute(text("""select min(finished_at) from news_poll
        where source = :ann and mode = 'PRODUCTION' and outcome in ('OK', 'NOT_MODIFIED')
          and finished_at < :as_of"""),
        {"ann": FS.ANNOUNCEMENT_SOURCE, "as_of": to_utc(as_of)})).scalar()


def provenance(evs: list[ResultsEvent]) -> list[Any]:
    return [[e.news_id, e.kind, e.meeting_date, e.period_end, e.verdict,
             e.knowable_at.isoformat()] for e in evs]


_HEADLINES = """
with it as (
  select n.id, n.knowable_at, coalesce(o.title, n.title) as title
    from news_item n
    join news_poll p on p.id = n.first_poll_id and p.mode = 'PRODUCTION'
    left join lateral (select x.title from news_item_observation x
                        where x.item_id = n.id and x.observed_at < :as_of
                        order by x.observed_at desc, x.id desc limit 1) o on true
   where n.knowable_at < :as_of and n.knowable_at >= :since and not n.backlog
     and coalesce(o.title, n.title) ~* :pre
     and not exists (select 1 from news_decision d where d.item_id = n.id
                      and d.observation_id is null and d.knowable_at < :as_of
                      and d.decision = 'DUPLICATE_ARTICLE')),
links as (
  select l.item_id, min(l.instrument_key) as instrument_key, max(l.knowable_at) as knowable_at,
         count(distinct l.instrument_key) as n
    from news_entity_link l
   where l.item_id in (select id from it) and l.knowable_at < :as_of
     and l.instrument_key is not null and l.confidence >= cast(:c as numeric)
   group by l.item_id)
select it.id, it.title, k.instrument_key, greatest(it.knowable_at, k.knowable_at) as knowable_at
  from it join links k on k.item_id = it.id and k.n = 1
 order by it.id"""


async def linked_headlines(s: AsyncSession, as_of: _dt.datetime, window: _dt.timedelta,
                           pattern: str) -> dict[str, list[tuple[_dt.datetime, str, int]]]:
    """instrument_key -> [(knowable_at, title, news id)] of the de-duplicated, non-backlog
    PRODUCTION headlines matching `pattern` knowable in the window before as_of and linked
    (confidence >= 0.8, link knowable before as_of) to exactly ONE instrument."""
    rows = [dict(r) for r in (await s.execute(text(_HEADLINES), {
        "as_of": to_utc(as_of), "since": to_utc(as_of - window), "pre": pattern,
        "c": FS.NEWS_LINK_MIN_CONFIDENCE})).mappings().all()]
    assert_all_knowable(rows, as_of, "linked headlines")
    out: dict[str, list[tuple[_dt.datetime, str, int]]] = {}
    for r in rows:
        out.setdefault(r["instrument_key"], []).append((r["knowable_at"], r["title"], r["id"]))
    return out
