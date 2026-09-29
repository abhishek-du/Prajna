"""Append-only re-decision of exchange / regulator articles under dedup-v2.

dedup-v1 marked a separate filing with identical boilerplate text (a different
document link) as DUPLICATE_ARTICLE. dedup-v2 decides it as STORY_RELATED (or
NEW_ARTICLE). The earlier decision is never updated or deleted: a NEW
news_decision row (rule_version dedup-v2) is appended with knowable_at = now,
so a snapshot before now still sees what was decided then (point in time), and
every later read sees the corrected decision (news_pit takes the latest knowable
decision). Idempotent: an article that already has a dedup-v2 decision is
skipped. Only articles whose decision would CHANGE get a row.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.db.models import NewsDecision
from app.ingest.runner import IngestRunner
from app.news import dedup as DD
from app.news import locks
from app.news.sources import SOURCES

STRICT = tuple(k for k, s in SOURCES.items() if s.enrich in ("EXCHANGE", "REGULATOR"))


def decide_v2(rows: list[tuple]) -> dict[int, tuple[str, str, int | None]]:
    """rows: (id, canonical_url, content_sha256, discovered_at) in insertion order.
    -> {id: (decision, rule, related_id)} under dedup-v2 for a strict source."""
    by_url: dict[str, tuple[int, _dt.datetime]] = {}
    by_content: dict[str, tuple[int, _dt.datetime]] = {}
    out = {}
    for iid, url, content, disc in rows:
        u = by_url.get(url) if url else None
        c = by_content.get(content)
        if u and disc - u[1] <= DD.WINDOW:
            out[iid] = ("DUPLICATE_ARTICLE", "SAME_SOURCE_URL", u[0])
        elif c and disc - c[1] <= DD.WINDOW:
            out[iid] = ("STORY_RELATED", "STORY_SAME_TITLE", c[0])
        else:
            out[iid] = ("NEW_ARTICLE", "FIRST_SEEN", None)
        if url:
            by_url.setdefault(url, (iid, disc))
        by_content.setdefault(content, (iid, disc))
    return out


async def redecide(s: AsyncSession, *, token: str | None, commit: bool,
                   operator: str = "cli") -> dict[str, Any]:
    for k in STRICT:
        if commit:
            await locks.require(s, k, mode="PRODUCTION", token=token, operator=operator)
    plan: list[dict] = []
    for k in STRICT:
        rows = (await s.execute(text("""
            select i.id, i.canonical_url, i.content_sha256, i.discovered_at
            from news_item i where i.source = :s order by i.discovered_at, i.id"""),
            {"s": k})).all()
        latest = dict((await s.execute(text("""
            select distinct on (d.item_id) d.item_id, d.decision
            from news_decision d join news_item i on i.id = d.item_id
            where i.source = :s and d.observation_id is null
            order by d.item_id, d.knowable_at desc, d.id desc"""), {"s": k})).all())
        done = {r[0] for r in (await s.execute(text("""
            select d.item_id from news_decision d join news_item i on i.id = d.item_id
            where i.source = :s and d.observation_id is null and d.rule_version = :v"""),
            {"s": k, "v": DD.VERSION})).all()}
        polls = dict((await s.execute(text(
            "select id, first_poll_id from news_item where source = :s"), {"s": k})).all())
        for iid, (dec, rule, rel) in decide_v2(rows).items():
            if iid in done or latest.get(iid) == dec:
                continue
            plan.append({"item_id": iid, "source": k, "from": latest.get(iid), "to": dec,
                         "rule": rule, "related": rel, "poll_id": polls[iid]})
    summary = {"changes": len(plan), "by_change": {}}
    for p in plan:
        key = f"{p['source']}: {p['from']} -> {p['to']}"
        summary["by_change"][key] = summary["by_change"].get(key, 0) + 1
    if not commit or not plan:
        return {**summary, "committed": False}
    runner = IngestRunner(s, source="news_redecide", stream="news.redecide.dedup-v2",
                          vendor_endpoint="internal", request_params={"version": DD.VERSION},
                          operator=operator)
    await runner.open(commit=True, token=token)
    try:
        t = now()
        for p in plan:
            await s.execute(insert(NewsDecision).values(
                item_id=p["item_id"], poll_id=p["poll_id"], decision=p["to"], rule=p["rule"],
                rule_version=DD.VERSION, related_item_id=p["related"]
                if p["to"] == "DUPLICATE_ARTICLE" else None,
                evidence={"re_decision": True, "supersedes": p["from"],
                          "reason": "dedup-v2: for exchange / regulator sources only the same "
                                    "document link is a duplicate",
                          **({"with": p["related"]} if p["related"] else {})},
                decided_at=t, knowable_at=t))
        await runner.finalize(rows_written=len(plan), outcome=summary)
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
    return {**summary, "committed": True}
