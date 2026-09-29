"""SHADOW writes of the news pilot (test database only): the lock, knowable_at =
discovery, idempotency, edits as observations, versioned enrichments with their
own knowable_at, append-only storage, and the audit of refusals."""

from __future__ import annotations

import datetime as _dt
import os

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import clock
from app.core.config import get_settings
from app.features.locks import LockRefused
from app.news import collector as C
from app.news import locks as NL
from app.news import sources as S
from app.news.store import poll_shadow
from tests.news.test_pilot import BODY, T0, UNIVERSE

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
KEY = "NSE_ANNOUNCEMENTS"


def accept(tmp_path, statuses):
    import json
    p = tmp_path / "news.json"
    p.write_text(json.dumps({"generated_at": "t", "sources": {
        k: {"status": v} for k, v in statuses.items()}}))
    return p


@pytest.fixture
def unlocked(monkeypatch, tmp_path):
    """Every write condition satisfied for NSE only (tests break one at a time)."""
    st = get_settings()
    monkeypatch.setattr(st, "PRAJNA_NEWS_NSE_ENABLED", True)
    monkeypatch.setattr(st, "PRAJNA_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(C, "KILL_FILE", tmp_path / "news.kill")
    monkeypatch.setattr(NL, "KILL_FILE", tmp_path / "news.kill")
    monkeypatch.setattr(NL, "NEWS_REPORT", accept(tmp_path, {KEY: "PASS"}))
    monkeypatch.setattr(NL, "stage2_status", lambda *a, **k: (True, "PASS (test)"))
    src = S.SOURCES[KEY]
    fields = {f: getattr(src, f) for f in src.__slots__}
    monkeypatch.setitem(S.SOURCES, KEY, type(src)(**{**fields, "compliance": "APPROVED"}))

    async def uni():
        return UNIVERSE
    import app.news.store as ST
    monkeypatch.setattr(ST, "load_universe", uni)
    clock.freeze(T0)
    yield st
    clock.unfreeze()


def feed(body=BODY, status=200):
    return httpx.MockTransport(lambda req: httpx.Response(status, content=body if status == 200
                                                          else b""))


async def q(s, sql, **kw):
    return (await s.execute(text(sql), kw)).all()


async def test_locked_by_default_and_refusal_is_audited(db_session):
    with pytest.raises(LockRefused) as e:
        await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
    failing = e.value.report.summary()["failing"]
    # terms APPROVED 2026-09-29: still locked by the per-source flag and the acceptance
    # gate (which includes the human mapping review)
    assert {"source_flag", "source_acceptance"} <= set(failing)
    assert "compliance_approved" not in failing
    assert (await q(db_session, "select count(*) from news_item"))[0][0] == 0
    assert (await q(db_session, "select event from news_audit"))[0][0] == "REFUSED"


async def test_bad_token_and_kill_switch_refuse(db_session, unlocked, tmp_path):
    with pytest.raises(LockRefused) as e:
        await poll_shadow(db_session, KEY, token="wrong", transport=feed())
    assert e.value.report.summary()["failing"] == ["write_token"]
    NL.set_kill(True, "test")
    with pytest.raises(LockRefused) as e:
        await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
    assert e.value.report.summary()["failing"] == ["kill_switch_off"]


async def test_shadow_poll_writes_items_knowable_at_discovery(db_session, unlocked):
    r = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
    assert r["outcome"] == "OK" and r["inserted"] > 0 and r["backlog"] is True
    rows = await q(db_session, """select published_at, discovered_at, knowable_at, backlog
                                  from news_item""")
    assert all(k == d == T0 and b for _, d, k, b in rows)
    assert all(p is None or p != k for p, _, k, _ in rows)
    links = dict(await q(db_session, """select l.method, count(*) from news_entity_link l
                                        group by 1"""))
    assert links["EXACT_SYMBOL"] >= 2 and links["UNRESOLVED"] >= 1
    assert (await q(db_session, """select count(*) from news_entity_link
        where method = 'UNRESOLVED' and reason is null"""))[0][0] == 0
    # one event category per item, plus one market scope (scope-v1) per item
    cls = await q(db_session, """select count(*) filter (where method <> 'SCOPE_RULES'),
        count(*) filter (where method = 'SCOPE_RULES'), min(knowable_at)
        from news_classification""")
    assert cls[0][0] == cls[0][1] == r["inserted"] and cls[0][2] >= T0
    run = await q(db_session, """select status, source from ingest_run where
        stream = 'news.NSE_ANNOUNCEMENTS'""")
    assert run == [("COMPLETE", KEY)]


async def test_rerun_is_idempotent_and_an_edit_is_an_observation(db_session, unlocked):
    first = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
    clock.freeze(T0 + _dt.timedelta(minutes=5))
    again = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
    assert again["inserted"] == 0 and again["changed"] == 0 and again["backlog"] is False
    clock.freeze(T0 + _dt.timedelta(minutes=10))
    edited = BODY.replace(b"Jullundur Motor Agency (Delhi) Limited has informed",
                          b"Jullundur Motor Agency (Delhi) Limited has now informed")
    third = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed(edited))
    assert third["changed"] == 1 and third["inserted"] == 0
    n = (await q(db_session, "select count(*) from news_item"))[0][0]
    assert n == first["inserted"]
    o = await q(db_session, "select changed, observed_at from news_item_observation")
    assert o == [(["summary"], T0 + _dt.timedelta(minutes=10))]
    assert (await q(db_session, "select count(*) from news_poll"))[0][0] == 3


async def test_not_modified_and_blocked_polls_are_recorded(db_session, unlocked):
    r = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed(status=304))
    assert r["outcome"] == "NOT_MODIFIED" and r["inserted"] == 0
    r = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed(status=403))
    assert r["outcome"] == "BLOCKED"
    assert (await q(db_session, "select event from news_audit"))[-1][0] == "BLOCKED"


async def test_storage_is_append_only_and_knowable_checked(db_session, unlocked):
    await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
    for sql in ("update news_item set title = 'x'", "delete from news_entity_link",
                "update news_classification set category = 'OTHER'"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db_session.begin_nested():
                await db_session.execute(text(sql))
    with pytest.raises(DBAPIError, match="ck_news_item_knowable"):
        async with db_session.begin_nested():
            await db_session.execute(text("""
                insert into news_item (source, source_article_id, title, title_norm_hash,
                  publisher, discovered_at, knowable_at, backlog, content_available,
                  first_poll_id, payload_sha256)
                select source, 'probe', 't', title_norm_hash, publisher, discovered_at,
                  discovered_at - interval '1 second', false, false, first_poll_id,
                  payload_sha256 from news_item limit 1"""))


@pytest.mark.parametrize("breaker,name", [
    (lambda mp, st, tp: mp.setattr(st, "PRAJNA_NEWS_NSE_ENABLED", False), "source_flag"),
    (lambda mp, st, tp: mp.setattr(NL, "NEWS_REPORT", accept(tp, {KEY: "FAIL"})),
     "source_acceptance"),
    (lambda mp, st, tp: mp.setattr(NL, "NEWS_REPORT", tp / "missing.json"), "source_acceptance"),
    (lambda mp, st, tp: mp.setattr(NL, "stage2_status", lambda *a, **k: (False, "FAIL")),
     "stage2_pass")])
async def test_each_write_condition_alone_refuses(db_session, unlocked, monkeypatch, tmp_path,
                                                  breaker, name):
    breaker(monkeypatch, unlocked, tmp_path)
    with pytest.raises(LockRefused) as e:
        await poll_shadow(db_session, KEY, token=TOKEN, transport=feed())
    assert e.value.report.summary()["failing"] == [name]


def test_one_source_flag_never_enables_another(unlocked):
    """NSE is fully unlocked; ET's own flag is still false."""
    r = NL.check("ET_STOCKS_RSS", mode="SHADOW", token=TOKEN)
    assert "source_flag" in r.summary()["failing"]
    assert all(s.flag is None or getattr(unlocked, s.flag) is False
               for k, s in S.SOURCES.items() if k != KEY)


async def test_production_mode_also_needs_the_visibility_flag(db_session, unlocked):
    with pytest.raises(LockRefused) as e:
        await poll_shadow(db_session, KEY, token=TOKEN, transport=feed(), mode="PRODUCTION")
    assert e.value.report.summary()["failing"] == ["multi_source_enabled"]


def test_every_source_flag_defaults_false():
    from app.core.config import Settings
    news_flags = [n for n in Settings.model_fields
                  if n.startswith("PRAJNA_NEWS_") and n.endswith("_ENABLED")]
    assert len(news_flags) >= 11
    assert all(Settings.model_fields[n].default is False for n in news_flags)
    assert "PRAJNA_NEWS_CRAWLER_ENABLED" not in news_flags       # no global switch
