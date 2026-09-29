"""Database-mode news reports (read-only): daily reconciliation, latency and
monitoring states for the SHADOW / PRODUCTION collector.

Reconciliation (one IST day, one mode), per source:
  polls by outcome and the failures with their reasons; items fetched (sum of
  items seen per poll), stored, and each dedup decision; edits stored (with and
  without a material decision); stories founded / joined; market scopes;
  unresolved company links; lock refusals (news_audit).
Latency (seconds, LIVE items only - backlog excluded; never claimed "first"):
  detection   discovered_at - published_at    (the feed's lag + our polling)
  ingestion   processed_at - discovered_at    (parse, enrich and write)
  end_to_end  processed_at - published_at
  A negative detection latency is CLOCK_SKEW: counted, never averaged.
Invariants (each must be 0): duplicate (source, source_article_id); an item
knowable before it was discovered; a stored item without a dedup decision;
a decision knowable before it was made or before its article; an enrichment
(class, link, story, assessment) knowable before its article; anything
knowable in the future. Decisions are counted as the CURRENT decision per
article (an append-only re-decision supersedes; both rows stay).
Monitoring states per source (several can apply; the first listed is primary):
  SOURCE_DOWN       the latest poll was BLOCKED / AUTH_FAILED, or no successful
                    poll for 3x the expected interval while polls continue
  COLLECTOR_DOWN    no poll at all for 3x the expected interval
  RATE_LIMITED      the latest poll was rate limited
  FETCH_FAILURE     > 20% of the last 10 polls failed
  SOURCE_STALE      market hours, polls succeed, but no new item for longer than
                    the source's norm (4x its median gap between new items over
                    the trailing days, at least 2 h)
  UNUSUAL_VOLUME    today's stored items > 3x the trailing daily median (>= 3 days)
  UNUSUAL_DUP_RATE  duplicates > 30% of today's stored items (>= 10 items)
  HEALTHY           none of the above
There is no alert channel (none exists in Prajna): states go to the status file,
`ops status` and log markers.
"""

# ruff: noqa: S608 - the SQL is built only from constant fragments; every value is bound
from __future__ import annotations

import collections
import datetime as _dt
import json
import pathlib
import statistics
from itertools import pairwise
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST, now
from app.news.collector import BASE, interval_for
from app.news.report import market_hours, stats
from app.news.sources import SOURCES

STATUS_FILE = BASE / "var" / "status" / "news_health.json"
STATES = ("SOURCE_DOWN", "COLLECTOR_DOWN", "RATE_LIMITED", "FETCH_FAILURE", "SOURCE_STALE",
          "UNUSUAL_VOLUME", "UNUSUAL_DUP_RATE", "HEALTHY")
OK = ("OK", "NOT_MODIFIED")


def day_bounds(day: _dt.date) -> tuple[_dt.datetime, _dt.datetime]:
    start = _dt.datetime.combine(day, _dt.time(0), tzinfo=IST)
    return start, start + _dt.timedelta(days=1)


async def _rows(session: AsyncSession, sql: str, /, **kw) -> list[Any]:
    return (await session.execute(text(sql), kw)).all()


async def latency(s: AsyncSession, source: str, mode: str, start: _dt.datetime,
                  end: _dt.datetime) -> dict[str, Any]:
    rows = await _rows(s, """
        select i.discovered_at, i.published_at, i.processed_at, i.backlog
        from news_item i join news_poll p on p.id = i.first_poll_id and p.mode = :m
        where i.source = :s and i.discovered_at >= :a and i.discovered_at < :b""",
        s=source, m=mode, a=start, b=end)
    det: dict[str, list[float]] = {"all": [], "market_hours": [], "off_hours": []}
    ing, e2e, skew = [], [], 0
    for disc, pub, proc, backlog in rows:
        if proc:
            ing.append((proc - disc).total_seconds())
        if backlog or pub is None:
            continue
        x = (disc - pub).total_seconds()
        if x < 0:
            skew += 1
            continue
        det["all"].append(x)
        det["market_hours" if market_hours(disc) else "off_hours"].append(x)
        if proc:
            e2e.append((proc - pub).total_seconds())
    return {"detection_s": {k: stats(v) for k, v in det.items()}, "ingestion_s": stats(ing),
            "end_to_end_s": stats(e2e), "clock_skew_items": skew,
            "note": "measured, never claimed first; backlog and date-only items excluded"}


def feed_ttl(key: str) -> int | None:
    """The feed <ttl> the collector recorded (var/news/collect/<SRC>/state.json)."""
    try:
        return json.loads((BASE / "var" / "news" / "collect" / key / "state.json")
                          .read_text())["http"].get("ttl_s")
    except (OSError, ValueError, KeyError):
        return None


def monitor_states(src_key: str, polls: list[tuple], new_times: list[_dt.datetime],
                   trailing_counts: list[int], today_items: int, today_dups: int,
                   at: _dt.datetime, norm_gap_s: float | None,
                   feed_ttl_s: int | None = None) -> list[str]:
    """`polls`: (started_at, outcome) ascending; `new_times`: discovered_at of live
    items stored today, ascending; `feed_ttl_s`: the feed's own <ttl> (the collector
    never polls faster, so the expected interval is the longer of the two). Pure."""
    src = SOURCES[src_key]
    expected = max(interval_for(src, at), feed_ttl_s or 0, 60)
    out: list[str] = []
    if not polls or (at - polls[-1][0]).total_seconds() > 3 * expected:
        out.append("COLLECTOR_DOWN")
    else:
        last = polls[-1][1]
        ok = [t for t, o in polls if o in OK]
        if last in ("BLOCKED", "AUTH_FAILED") or not ok \
                or (at - ok[-1]).total_seconds() > 3 * expected:
            out.append("SOURCE_DOWN")
        if last == "RATE_LIMITED":
            out.append("RATE_LIMITED")
        recent = [o for _, o in polls[-10:]]
        if sum(1 for o in recent if o not in OK) / len(recent) > 0.2:
            out.append("FETCH_FAILURE")
        if market_hours(at) and not out and norm_gap_s:
            since = (at - new_times[-1]).total_seconds() if new_times else None
            limit = max(4 * norm_gap_s, 7200)
            if since is None or since > limit:
                out.append("SOURCE_STALE")
    if len(trailing_counts) >= 3 and today_items > 3 * max(statistics.median(trailing_counts), 1):
        out.append("UNUSUAL_VOLUME")
    if today_items >= 10 and today_dups / today_items > 0.3:
        out.append("UNUSUAL_DUP_RATE")
    order = {s: i for i, s in enumerate(STATES)}
    return sorted(out, key=order.__getitem__) or ["HEALTHY"]


async def reconcile(s: AsyncSession, day: _dt.date, mode: str,
                    at: _dt.datetime | None = None) -> dict[str, Any]:
    """The day's reconciliation for every implemented source. Read-only."""
    at = at or min(now(), day_bounds(day)[1])
    start, end = day_bounds(day)
    out: dict[str, Any] = {"day": str(day), "mode": mode, "generated_at": now().isoformat(),
                           "as_of": at.isoformat(), "sources": {}}
    inv = {
        "duplicate_source_ids": (await _rows(s, """select count(*) from (select 1 from news_item
            group by source, source_article_id having count(*) > 1) x"""))[0][0],
        "knowable_before_discovery": (await _rows(
            s, "select count(*) from news_item where knowable_at < discovered_at"))[0][0],
        "items_without_decision": (await _rows(s, """select count(*) from news_item i
            where i.discovered_at >= :a and i.discovered_at < :b and not exists
            (select 1 from news_decision d where d.item_id = i.id
             and d.observation_id is null)""", a=start, b=end))[0][0],
        "decision_knowable_before_made": (await _rows(
            s, "select count(*) from news_decision where knowable_at < decided_at"))[0][0],
        "decision_knowable_before_item": (await _rows(s, """select count(*) from news_decision d
            join news_item i on i.id = d.item_id where d.knowable_at < i.knowable_at"""))[0][0],
        "enrichment_knowable_before_item": (await _rows(s, """select
            (select count(*) from news_classification c join news_item i on i.id = c.item_id
             where c.knowable_at < i.knowable_at)
          + (select count(*) from news_entity_link c join news_item i on i.id = c.item_id
             where c.knowable_at < i.knowable_at)
          + (select count(*) from news_story_member c join news_item i on i.id = c.item_id
             where c.knowable_at < i.knowable_at)
          + (select count(*) from news_assessment c join news_item i on i.id = c.item_id
             where c.knowable_at < i.knowable_at)"""))[0][0],
        # future data: nothing may be knowable after the moment it was written
        "knowable_in_the_future": (await _rows(s, """select
            (select count(*) from news_item where knowable_at > now())
          + (select count(*) from news_decision where knowable_at > now())"""))[0][0],
    }
    out["invariants"] = {**inv, "ok": all(v == 0 for v in inv.values())}
    states: dict[str, list[str]] = {}
    for key, src in SOURCES.items():
        if src.parse is None or src.status == "UNSUPPORTED":
            continue
        polls = await _rows(s, """select started_at, outcome, http_status, error, items_seen,
            items_new, items_changed from news_poll where source = :s and mode = :m
            and started_at >= :a and started_at < :b order by started_at""",
            s=key, m=mode, a=start, b=end)
        # a constant SQL fragment; every value is bound
        items = """from news_item i join news_poll p on p.id = i.first_poll_id and p.mode = :m
            where i.source = :s and i.discovered_at >= :a and i.discovered_at < :b"""
        kw = {"s": key, "m": mode, "a": start, "b": end}
        stored = (await _rows(s, f"select count(*), count(*) filter (where not i.backlog) {items}",
                              **kw))[0]
        # the CURRENT decision per article (a later re-decision supersedes, both stay stored)
        decisions = dict(await _rows(s, f"""select decision, count(*) from (
            select distinct on (d.item_id) d.decision from news_decision d
            where d.observation_id is null and d.item_id in (select i.id {items})
            order by d.item_id, d.knowable_at desc, d.id desc) x group by 1""", **kw))
        edits = (await _rows(s, """select count(*), count(d.id) from news_item_observation o
            join news_poll p on p.id = o.poll_id and p.mode = :m
            left join news_decision d on d.observation_id = o.id
            where p.source = :s and o.observed_at >= :a and o.observed_at < :b""", **kw))[0]
        edit_decisions = dict(await _rows(s, """select d.decision, count(*) from news_decision d
            join news_poll p on p.id = d.poll_id and p.mode = :m
            where d.observation_id is not null and p.source = :s
            and d.decided_at >= :a and d.decided_at < :b group by 1""", **kw))
        scopes = dict(await _rows(s, f"""select c.category, count(*) from news_classification c
            where c.method = 'SCOPE_RULES' and c.item_id in (select i.id {items})
            group by 1 order by 2 desc""", **kw))
        unresolved = (await _rows(s, f"""select count(distinct l.item_id) from news_entity_link l
            where l.method = 'UNRESOLVED' and l.item_id in (select i.id {items})""", **kw))[0][0]
        new_times = [r[0] for r in await _rows(
            s, f"select i.discovered_at {items} and not i.backlog order by 1", **kw)]
        # the source's norm: median gap between new items, market hours, trailing 5 days
        trail = await _rows(s, """select i.discovered_at from news_item i
            join news_poll p on p.id = i.first_poll_id and p.mode = :m
            where i.source = :s and not i.backlog and i.discovered_at >= :t and i.discovered_at < :a
            order by 1""", s=key, m=mode, a=start, t=start - _dt.timedelta(days=5))
        mh = [r[0] for r in trail if market_hours(r[0])]
        gaps = [(b - a).total_seconds() for a, b in pairwise(mh)
                if a.astimezone(IST).date() == b.astimezone(IST).date()]
        norm = statistics.median(gaps) if len(gaps) >= 5 else None
        per_day = collections.Counter(r[0].astimezone(IST).date() for r in trail)
        st = monitor_states(key, [(p[0], p[1]) for p in polls], new_times, list(per_day.values()),
                            stored[0], decisions.get("DUPLICATE_ARTICLE", 0), at, norm,
                            feed_ttl(key))
        states[key] = st
        refusals = (await _rows(s, """select count(*) from news_audit where source = :s
            and event = 'REFUSED' and at >= :a and at < :b""", s=key, a=start, b=end))[0][0]
        out["sources"][key] = {
            "state": st,
            "polls": len(polls),
            "outcomes": dict(collections.Counter(p[1] for p in polls)),
            "failures": [{"at": p[0].isoformat(), "outcome": p[1], "http_status": p[2],
                          "error": (p[3] or "")[:160]} for p in polls if p[1] not in OK][:50],
            "items_fetched": sum(p[4] or 0 for p in polls),
            "items_stored": stored[0], "live_items": stored[1], "backlog_items":
                stored[0] - stored[1],
            "decisions": decisions,
            "edits": {"stored": edits[0], "with_decision": edits[1], "decisions": edit_decisions,
                      "not_material": edits[0] - edits[1]},
            "scopes": scopes, "unresolved_company_links": unresolved,
            "refusals": refusals,
            "latency": await latency(s, key, mode, start, end),
            "norm_new_item_gap_s": norm,
        }
    out["upstox_articles"] = (await _rows(s, """select count(*) from news_article
        where fetched_at >= :a and fetched_at < :b""", a=start, b=end))[0][0]
    out["states"] = states
    return out


def write_status(rep: dict[str, Any], path: pathlib.Path = STATUS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps({"generated_at": rep["generated_at"], "day": rep["day"],
                               "mode": rep["mode"], "states": rep["states"],
                               "invariants_ok": rep["invariants"]["ok"]}, indent=1))
    tmp.replace(path)


def to_markdown(rep: dict[str, Any]) -> str:
    L = [f"# News daily reconciliation: {rep['day']} ({rep['mode']})", "",
         f"Generated {rep['generated_at']} (as of {rep['as_of']}), read-only, from the "
         "database. Produced by `prajna news reconcile`.", "",
         "## Invariants (each must be 0)", "", "| Check | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in rep["invariants"].items() if k != "ok"]
    L += ["", f"**Invariants: {'OK' if rep['invariants']['ok'] else 'VIOLATED'}**", "",
          "## Per source", "",
          "| Source | State | Polls | Failed | Fetched | Stored (live) | New | Duplicate | "
          "Related | Correction | Edits (material) | Refusals | Detection p50 / p95 s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in rep["sources"].items():
        d, lat = v["decisions"], v["latency"]["detection_s"]["all"]
        failed = sum(n for o, n in v["outcomes"].items() if o not in OK)
        L.append(f"| {k} | {', '.join(v['state'])} | {v['polls']} | {failed} | "
                 f"{v['items_fetched']} | {v['items_stored']} ({v['live_items']}) | "
                 f"{d.get('NEW_ARTICLE', 0)} | {d.get('DUPLICATE_ARTICLE', 0)} | "
                 f"{d.get('STORY_RELATED', 0)} | {d.get('STORY_CORRECTION', 0)} | "
                 f"{v['edits']['stored']} ({v['edits']['with_decision']}) | {v['refusals']} | "
                 f"{lat['p50']} / {lat['p95']} |")
    L += ["", f"Upstox `/v2/news` articles fetched the same day (production path 1): "
          f"{rep['upstox_articles']}.", "", "## Failures (first 50 per source)", ""]
    for k, v in rep["sources"].items():
        for f in v["failures"]:
            L.append(f"- {k} {f['at']} {f['outcome']} {f['http_status']} {f['error']}")
    L += ["", "## Scopes", ""]
    for k, v in rep["sources"].items():
        if v["scopes"]:
            L.append(f"- {k}: " + ", ".join(f"{a} {b}" for a, b in v["scopes"].items()))
    return "\n".join(L) + "\n"
