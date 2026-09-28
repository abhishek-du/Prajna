"""Multi-source news read API: read-only, point in time, and source facts kept
apart from derived fields and AI enrichment (test database only)."""

from __future__ import annotations

import urllib.parse as up

import httpx
import pytest

from app.readapi import main as M
from tests.news.test_news_pit import A1, B1, T, poll, rss, unlocked  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.integration]


def q(dt):
    return up.quote(dt.isoformat(), safe="")


@pytest.fixture
async def api(db_session, unlocked):  # noqa: F811
    async def bound():
        yield db_session
    M.api.dependency_overrides[M.session] = bound
    await poll(db_session, "MINT_MARKETS_RSS", rss(), T(9, 50))   # first polls: empty, so
    await poll(db_session, "ET_STOCKS_RSS", rss(), T(9, 50))      # later items are LIVE
    await poll(db_session, "ET_STOCKS_RSS", rss(A1), T(10, 7))
    await poll(db_session, "MINT_MARKETS_RSS", rss(B1), T(10, 12))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=M.api),
                                 base_url="http://t") as c:
        yield c
    M.api.dependency_overrides.clear()


async def test_articles_are_point_in_time_with_provenance_sections(api):
    early = (await api.get(f"/v1/news/articles?as_of={q(T(10, 3))}")).json()
    assert early["data"] == [] and early["meta"]["point_in_time"] is True
    got = (await api.get(f"/v1/news/articles?as_of={q(T(10, 30))}")).json()
    assert [a["source"] for a in got["data"]] == ["MINT_MARKETS_RSS", "ET_STOCKS_RSS"]
    et = got["data"][1]
    assert et["source_fact"]["published_at"].startswith("2026-09-28T04:30")    # 10:00 IST
    assert et["observation"]["first_seen_at"].startswith("2026-09-28T04:37")   # 10:07 IST
    assert et["observation"]["knowable_at"] == et["observation"]["first_seen_at"]
    assert et["observation"]["discovery_latency_s"] == 420.0
    assert et["observation"]["seconds_since_first_observation"] == 23 * 60
    assert "INDEX:SENSEX" in et["derived"]["entities"] and et["ai_enrichment"] is None
    assert any("never the publication time" in n for n in got["meta"]["notes"])


async def test_item_and_story_endpoints_respect_as_of(api):
    items = (await api.get(f"/v1/news/articles?as_of={q(T(10, 30))}")).json()["data"]
    mint = items[0]
    assert (await api.get(f"/v1/news/{mint['id']}?as_of={q(T(10, 10))}")).status_code == 404
    one = (await api.get(f"/v1/news/{mint['id']}?as_of={q(T(10, 30))}")).json()["data"]
    assert one["derived"]["story"]["method"] == "SAME_TITLE"
    sid = one["derived"]["story"]["story_id"]
    before = (await api.get(f"/v1/stories/{sid}?as_of={q(T(10, 10))}")).json()["data"]
    after = (await api.get(f"/v1/stories/{sid}?as_of={q(T(10, 30))}")).json()["data"]
    assert before["article_count"] == 1 and after["article_count"] == 2
    assert len(after["publishers"]) == 2


async def test_breaking_filters_and_stats(api):
    br = (await api.get(f"/v1/news/breaking?as_of={q(T(10, 30))}")).json()["data"]
    assert [b["source"] for b in br] == ["MINT_MARKETS_RSS"]
    assert "confirmed" in br[0]["derived"]["breaking_reason"]
    f = (await api.get(f"/v1/news/articles?as_of={q(T(10, 30))}&source=ET_STOCKS_RSS"
                       "&entity=INDEX:SENSEX")).json()["data"]
    assert len(f) == 1
    st = (await api.get(f"/v1/news/stats?as_of={q(T(10, 30))}")).json()["data"]
    assert st["items"] == 2 and st["stories"] == 1


async def test_sources_report_locks_and_are_read_only(api):
    src = {x["source"]: x for x in (await api.get("/v1/news/sources")).json()["data"]}
    assert src["MONEYCONTROL"]["status"] == "UNSUPPORTED"
    assert src["SEBI_RSS"]["db_write"] == "LOCKED" and not src["SEBI_RSS"]["write_flag_enabled"]
    for path in ("/v1/news/articles", "/v1/news/sources", "/v1/stories", "/v1/news/breaking"):
        assert (await api.post(path)).status_code == 405
        assert (await api.delete(path)).status_code == 405


async def test_existing_upstox_endpoint_is_unchanged(api):
    r = (await api.get("/v1/news")).json()
    assert r["data"] == [] and "vendor serves 7 days" in r["meta"]["notes"][0]
