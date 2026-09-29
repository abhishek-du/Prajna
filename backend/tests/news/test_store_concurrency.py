"""Concurrent news writers (test database only, real commits on separate
connections): overlapping polls of one source never duplicate an item or an
edit, and a writer that dies mid-transaction leaves no news rows.

These tests commit, so each one removes exactly the rows it created (the news
tables are append-only: the cleanup disables the triggers inside its own
transaction, on the test database only)."""

from __future__ import annotations

import asyncio
import datetime as _dt

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.news import store as NS
from app.news.store import poll_shadow
from tests.conftest import TEST_DSN
from tests.news.test_pilot import BODY, T0
from tests.news.test_store import KEY, TOKEN, feed, unlocked  # noqa: F401 - fixture

pytestmark = [pytest.mark.db, pytest.mark.integration]

ITEM_TABLES = ("news_story_member", "news_assessment", "news_entity_mention",
               "news_entity_link", "news_classification", "news_item_observation",
               "news_content", "news_ai_enrichment")
EDITED = BODY.replace(b"Jullundur Motor Agency (Delhi) Limited has informed",
                      b"Jullundur Motor Agency (Delhi) Limited has now informed")


async def _cleanup(eng) -> None:
    async with eng.begin() as c:
        tables = (*ITEM_TABLES, "news_story", "news_item", "news_poll", "news_audit")
        for t in tables:
            await c.execute(text(f"alter table {t} disable trigger tr_{t}_append_only"))
        items = "select id from news_item where source = :s"
        for t in ITEM_TABLES:
            await c.execute(text(f"delete from {t} where item_id in ({items})"), {"s": KEY})
        await c.execute(text(f"delete from news_story where first_item_id in ({items})"),
                        {"s": KEY})
        await c.execute(text("delete from news_item where source = :s"), {"s": KEY})
        await c.execute(text("delete from news_poll where source = :s"), {"s": KEY})
        await c.execute(text("delete from news_audit where source = :s"), {"s": KEY})
        for t in tables:
            await c.execute(text(f"alter table {t} enable trigger tr_{t}_append_only"))
        runs = "select run_id from ingest_run where stream = :st"
        st = {"st": f"news.{KEY}"}
        await c.execute(text(f"delete from ingest_anomaly where run_id in ({runs})"), st)
        await c.execute(text(f"delete from raw_payload where first_seen_run in ({runs})"), st)
        await c.execute(text("delete from ingest_watermark where stream = :st"), st)
        await c.execute(text("delete from ingest_run where stream = :st"), st)


@pytest.fixture
async def eng():
    e = create_async_engine(TEST_DSN, poolclass=NullPool)
    async with e.connect() as c:
        n = (await c.execute(text("select count(*) from news_item where source = :s"),
                             {"s": KEY})).scalar()
    if n:
        await e.dispose()
        pytest.skip("committed news rows already exist in the test database")
    try:
        yield e
    finally:
        await _cleanup(e)
        await e.dispose()


async def _poll(e, body=BODY):
    async with AsyncSession(e, expire_on_commit=False) as s:
        return await poll_shadow(s, KEY, token=TOKEN, transport=feed(body))


async def _count(e, sql):
    async with e.connect() as c:
        return (await c.execute(text(sql), {"s": KEY})).scalar()


async def test_overlapping_polls_insert_each_item_once(eng, unlocked):  # noqa: F811
    res = await asyncio.gather(*(_poll(eng) for _ in range(3)))
    assert all(r["outcome"] == "OK" for r in res)
    items = await _count(eng, "select count(*) from news_item where source = :s")
    assert items > 0 and sum(r["inserted"] for r in res) == items
    assert sorted(r["inserted"] for r in res)[:2] == [0, 0]          # exactly one writer won
    assert await _count(eng, """select count(*) from news_story_member m
        join news_item i on i.id = m.item_id where i.source = :s""") == items
    assert await _count(eng, "select count(*) from news_poll where source = :s") == 3


async def test_overlapping_polls_record_an_edit_once(eng, unlocked):  # noqa: F811
    await _poll(eng)
    clock.freeze(T0 + _dt.timedelta(minutes=5))
    res = await asyncio.gather(*(_poll(eng, EDITED) for _ in range(3)))
    assert sorted(r["changed"] for r in res) == [0, 0, 1]
    assert await _count(eng, """select count(*) from news_item_observation o
        join news_item i on i.id = o.item_id where i.source = :s""") == 1


async def test_a_writer_dying_mid_transaction_leaves_no_news_rows(eng, unlocked,  # noqa: F811
                                                                   monkeypatch):
    calls = {"n": 0}
    real = NS._metadata_sha

    def dies_on_the_third_item(it):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("killed mid-transaction")
        return real(it)
    monkeypatch.setattr(NS, "_metadata_sha", dies_on_the_third_item)
    with pytest.raises(RuntimeError):
        await _poll(eng)
    assert await _count(eng, "select count(*) from news_item where source = :s") == 0
    assert await _count(eng, "select count(*) from news_poll where source = :s") == 0
    assert await _count(eng, """select status from ingest_run where stream = 'news.' || :s
        order by started_at desc limit 1""") == "FAILED"
    monkeypatch.setattr(NS, "_metadata_sha", real)                   # the retry is complete
    r = await _poll(eng)
    assert r["inserted"] == await _count(eng, "select count(*) from news_item where source = :s")
