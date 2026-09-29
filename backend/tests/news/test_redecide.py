"""dedup-v2 re-decision (append-only): only changed decisions get a new row,
knowable from now; the old row stays; a second run changes nothing."""

from __future__ import annotations

import datetime as _dt

import httpx
import pytest
from sqlalchemy import text

from app.core import clock
from app.news import redecide as RD
from app.news.store import poll_shadow
from tests.news.test_pilot import T0
from tests.news.test_store import KEY, TOKEN, unlocked  # noqa: F401 - fixture

T = _dt.datetime(2026, 9, 29, 12, 0, tzinfo=_dt.UTC)


def test_v2_rules():
    rows = [(1, "u1", "c1", T), (2, "u2", "c1", T), (3, "u1", "c3", T),
            (4, "u4", "c1", T + _dt.timedelta(hours=25))]
    assert RD.decide_v2(rows) == {
        1: ("NEW_ARTICLE", "FIRST_SEEN", None),
        2: ("STORY_RELATED", "STORY_SAME_TITLE", 1),        # separate filing, same text
        3: ("DUPLICATE_ARTICLE", "SAME_SOURCE_URL", 1),     # the same document link
        4: ("NEW_ARTICLE", "FIRST_SEEN", None)}             # outside the 24 h window


@pytest.mark.db
@pytest.mark.integration
async def test_append_only_and_idempotent(db_session, unlocked, monkeypatch):  # noqa: F811
    s = db_session
    empty = b'<rss version="2.0"><channel><title>NSE</title></channel></rss>'
    r = await poll_shadow(s, KEY, token=TOKEN, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=empty)))            # a real poll row + run
    pid = r["poll_id"]
    ids = []
    for n, url in ((1, "https://n/a.pdf"), (2, "https://n/b.pdf")):
        ids.append((await s.execute(text("""insert into news_item (source, source_article_id,
            url, canonical_url, title, title_norm_hash, summary, publisher, discovered_at,
            knowable_at, backlog, content_available, first_poll_id, content_sha256,
            payload_sha256, content_fetch_status) values (:k, :u, :u, :u, 'X Ltd', 'h',
            'same text', 'NSE', :t, :t, true, false, :p, 'c', 'p', 'NOT_AVAILABLE')
            returning id"""),
            {"k": KEY, "u": url, "t": T0, "p": pid})).scalar())
        await s.execute(text("""insert into news_decision (item_id, poll_id, decision, rule,
            rule_version, related_item_id, evidence, decided_at, knowable_at) values
            (:i, :p, :d, :r, 'dedup-v1', :rel, '{}', :t, :t)"""),
            {"i": ids[-1], "p": pid, "t": T0, "d": "NEW_ARTICLE" if n == 1
             else "DUPLICATE_ARTICLE", "r": "FIRST_SEEN" if n == 1 else "SAME_SOURCE_CONTENT",
             "rel": None if n == 1 else ids[0]})
    monkeypatch.setattr(RD, "STRICT", (KEY,))
    monkeypatch.setattr(unlocked, "PRAJNA_NEWS_MULTI_SOURCE_ENABLED", True)
    dry = await RD.redecide(s, token=TOKEN, commit=False)
    assert dry["changes"] == 1 and not dry["committed"]
    clock.freeze(T0 + _dt.timedelta(hours=1))
    got = await RD.redecide(s, token=TOKEN, commit=True)
    assert got == {"changes": 1, "committed": True, "by_change": {
        f"{KEY}: DUPLICATE_ARTICLE -> STORY_RELATED": 1}}
    rows = (await s.execute(text("""select decision, rule_version, knowable_at from
        news_decision where item_id = :i order by id"""), {"i": ids[1]})).all()
    assert [(r[0], r[1]) for r in rows] == [("DUPLICATE_ARTICLE", "dedup-v1"),
                                             ("STORY_RELATED", "dedup-v2")]   # old row kept
    assert rows[1][2] == T0 + _dt.timedelta(hours=1)          # knowable from the re-decision
    assert (await RD.redecide(s, token=TOKEN, commit=True))["changes"] == 0   # idempotent
