"""Point-in-time visibility of multi-source news (test database only).

Adversarial timeline: an article PUBLISHED 10:00 is first SEEN by Prajna at 10:07.
  as_of 10:03 -> invisible (published earlier, but Prajna did not know it)
  as_of 10:08 -> visible
Edits, story membership and enrichments become visible only from their own
knowable_at; SHADOW rows are never visible; Upstox is projected from its first
fetch time, never its publication time."""

from __future__ import annotations

import datetime as _dt
import json
import os

import httpx
import pytest
from sqlalchemy import text

from app.canon import news_pit as NP
from app.core import clock
from app.core.clock import IST
from app.core.config import get_settings
from app.news import collector as C
from app.news import locks as NL
from app.news import sources as S
from app.news.store import poll_shadow
from tests.news.test_intelligence import UNI

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
T = lambda h, m: _dt.datetime(2026, 9, 28, h, m, tzinfo=IST)  # noqa: E731


def rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
                   f"<pubDate>{p}</pubDate></item>" for t, u, d, p in items)
    return f'<rss version="2.0"><channel>{body}</channel></rss>'.encode()


A1 = ("Sensex tumbles 1,124 points as crude surges", "https://et.example/a1", "first text",
      "Mon, 28 Sep 2026 10:00:00 +0530")
B1 = ("Sensex tumbles 1,124 points as crude surges", "https://mint.example/b1", "d",
      "Mon, 28 Sep 2026 10:05:00 +0530")


@pytest.fixture
def unlocked(monkeypatch, tmp_path):
    st = get_settings()
    for f in ("PRAJNA_NEWS_ET_ENABLED", "PRAJNA_NEWS_MINT_ENABLED",
              "PRAJNA_NEWS_MULTI_SOURCE_ENABLED"):
        monkeypatch.setattr(st, f, True)
    monkeypatch.setattr(st, "PRAJNA_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(C, "KILL_FILE", tmp_path / "news.kill")
    monkeypatch.setattr(NL, "KILL_FILE", tmp_path / "news.kill")
    rep = tmp_path / "news.json"
    rep.write_text(json.dumps({"generated_at": "t", "sources": {
        "ET_STOCKS_RSS": {"status": "PASS"}, "MINT_MARKETS_RSS": {"status": "PASS"}}}))
    monkeypatch.setattr(NL, "NEWS_REPORT", rep)
    monkeypatch.setattr(NL, "stage2_status", lambda *a, **k: (True, "PASS (test)"))
    for k in ("ET_STOCKS_RSS", "MINT_MARKETS_RSS"):
        src = S.SOURCES[k]
        fields = {f: getattr(src, f) for f in src.__slots__}
        monkeypatch.setitem(S.SOURCES, k, type(src)(**{**fields, "compliance": "APPROVED"}))

    async def uni():
        return UNI
    import app.news.store as ST
    monkeypatch.setattr(ST, "load_universe", uni)
    yield
    clock.unfreeze()


async def poll(s, key, body, at, mode="PRODUCTION"):
    clock.freeze(at)
    return await poll_shadow(s, key, token=TOKEN, mode=mode,
                             transport=httpx.MockTransport(lambda r: httpx.Response(200,
                                                                                    content=body)))


def ids(rows):
    return [r["source_article_id"] for r in rows]


async def test_published_1000_seen_1007(db_session, unlocked):
    await poll(db_session, "ET_STOCKS_RSS", rss(), T(9, 50))          # first poll: empty
    await poll(db_session, "ET_STOCKS_RSS", rss(A1), T(10, 7))
    assert await NP.items(db_session, T(10, 3)) == []                 # published, not known
    assert await NP.items(db_session, T(10, 7)) == []                 # strict <
    got = await NP.items(db_session, T(10, 8))
    assert ids(got) == ["https://et.example/a1"]
    r = got[0]
    assert r["knowable_at"] == T(10, 7) and r["published_at"] == T(10, 0)
    # keyword rules: "crude" (COMMODITIES) matches before "Sensex"; the scope is then the
    # index named in the headline
    assert r["backlog"] is False and r["market_scope"] == "INDEX"
    assert "INDEX:SENSEX" in r["entities"]


async def test_an_edit_is_visible_only_after_it_was_observed(db_session, unlocked):
    await poll(db_session, "ET_STOCKS_RSS", rss(A1), T(10, 7))
    edited = (A1[0], A1[1], "revised text", A1[3])
    await poll(db_session, "ET_STOCKS_RSS", rss(edited), T(10, 20))
    assert (await NP.items(db_session, T(10, 10)))[0]["summary"] == "first text"
    later = (await NP.items(db_session, T(10, 21)))[0]
    assert later["summary"] == "revised text" and later["edited"] is True


async def test_a_later_story_member_is_not_known_earlier(db_session, unlocked):
    await poll(db_session, "MINT_MARKETS_RSS", rss(), T(9, 50))   # so B1 is not backlog
    await poll(db_session, "ET_STOCKS_RSS", rss(A1), T(10, 7))
    await poll(db_session, "MINT_MARKETS_RSS", rss(B1), T(10, 12))
    early = await NP.stories(db_session, T(10, 10))
    assert len(early) == 1 and early[0]["article_count"] == 1
    late = await NP.stories(db_session, T(10, 13))
    assert len(late) == 1 and late[0]["article_count"] == 2
    assert late[0]["sources"] == ["ET_STOCKS_RSS", "MINT_MARKETS_RSS"]
    b = late[0]["members"][1]
    assert b["story_method"] == "SAME_TITLE" and b["story_evidence"]["with"].startswith("ET")
    # the later article is breaking by confirmation (a second publisher within 30 min);
    # a backlog item (first response of a source) could never be
    assert (await NP.items(db_session, T(10, 13), source="MINT_MARKETS_RSS"))[0]["is_breaking"]


async def test_shadow_rows_are_never_visible(db_session, unlocked):
    await poll(db_session, "ET_STOCKS_RSS", rss(A1), T(10, 7), mode="SHADOW")
    assert (await db_session.execute(text("select count(*) from news_item"))).scalar() == 1
    assert await NP.items(db_session, T(23, 0)) == []


async def test_filters_after_the_cut(db_session, unlocked):
    await poll(db_session, "ET_STOCKS_RSS", rss(A1), T(10, 7))
    assert await NP.items(db_session, T(11, 0), source="MINT_MARKETS_RSS") == []
    assert len(await NP.items(db_session, T(11, 0), entity="INDEX:SENSEX")) == 1
    assert await NP.items(db_session, T(11, 0), breaking=True) == []


async def test_upstox_projection_uses_first_fetch_not_publication(db_session):
    from tests.support import stage2_seed as SEED
    clock.freeze(SEED.NOW)
    try:
        await SEED.seed(db_session)
        # the seed article: published 09-22 10:00 IST, fetched 09-24 11:00 IST
        before = await NP.items(db_session, SEED.ist(2026, 9, 23, 12), include_upstox=True)
        assert before == []                                # published, not yet fetched
        after = await NP.items(db_session, SEED.ist(2026, 9, 24, 12), include_upstox=True)
        assert [r["source"] for r in after] == ["UPSTOX"]
        assert after[0]["knowable_at"] == SEED.ist(2026, 9, 24, 11)
    finally:
        clock.unfreeze()
