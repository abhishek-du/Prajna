"""The scheduled collector (`app.news.collect`) on the test database: polite,
deadline-bound, lock-refusal stops a source, an error fails one poll only, a
restart waits out the interval, and its state file feeds `news health`."""

from __future__ import annotations

import datetime as _dt
import json
import random

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import clock
from app.news import collect as NC
from app.news import store as NS
from tests.news.test_pilot import BODY, T0
from tests.news.test_store import KEY, TOKEN, unlocked  # noqa: F401 - fixture
from tests.news.test_store_concurrency import _count, eng  # noqa: F401 - fixture

pytestmark = [pytest.mark.db, pytest.mark.integration]


def replay(*responses):
    seq, seen = list(responses), []

    def handler(req):
        seen.append(req)
        return seq.pop(0) if seq else httpx.Response(304)
    t = httpx.MockTransport(handler)
    t.requests = seen
    return t


async def advancing_sleep(s):                     # time passes while asleep
    clock.freeze(clock.now() + _dt.timedelta(seconds=s))


def kw(eng, tmp_path, **extra):  # noqa: F811
    return {"mode": "SHADOW", "token": TOKEN, "sleep": advancing_sleep,
            "rng": random.Random(0), "sessionmaker": async_sessionmaker(
                eng, expire_on_commit=False), "root": tmp_path / "collect", **extra}


async def test_collects_politely_until_the_deadline(eng, unlocked, tmp_path):  # noqa: F811
    until = T0 + _dt.timedelta(minutes=16)
    out = await NC.collect(KEY, until=until, transport=replay(httpx.Response(200, content=BODY)),
                           **kw(eng, tmp_path))
    assert out[0]["outcome"] == "OK" and all(r["outcome"] == "NOT_MODIFIED" for r in out[1:])
    assert 2 <= len(out) <= 4                               # ~every 5 min (the feed ttl)
    assert clock.now() < until
    assert await _count(eng, "select count(*) from news_poll where source = :s") == len(out)
    assert await _count(eng, """select count(*) from news_poll where source = :s
        and started_at >= '2026-09-28T10:21:00+00'""") == 0      # none at/after the deadline
    st = json.loads((tmp_path / "collect" / KEY / "state.json").read_text())
    assert st["http"]["ttl_s"] == 300
    assert st["status"]["mode"] == "SHADOW" and st["status"]["polls"] == len(out)


async def test_a_lock_refusal_stops_the_source(eng, unlocked, tmp_path,  # noqa: F811
                                               monkeypatch):
    from app.news import locks as NL
    NL.KILL_FILE.write_text("{}")                           # the kill switch (tmp, fixture)
    t = replay(httpx.Response(200, content=BODY))
    out = await NC.collect(KEY, until=T0 + _dt.timedelta(hours=1), transport=t,
                           **kw(eng, tmp_path))
    assert out == [] and t.requests == []
    st = json.loads((tmp_path / "collect" / KEY / "state.json").read_text())
    assert st["status"]["last_outcome"] == "REFUSED"
    assert "kill_switch_off" in st["status"]["refused"]
    assert await _count(eng, "select count(*) from news_audit where source = :s") == 1


async def test_production_needs_the_multi_source_switch(eng, unlocked, tmp_path):  # noqa: F811
    out = await NC.collect(KEY, until=T0 + _dt.timedelta(hours=1),
                           transport=replay(httpx.Response(200, content=BODY)),
                           **kw(eng, tmp_path, mode="PRODUCTION"))
    assert out == []
    st = json.loads((tmp_path / "collect" / KEY / "state.json").read_text())
    assert "multi_source_enabled" in st["status"]["refused"]
    assert await _count(eng, "select count(*) from news_item where source = :s") == 0


async def test_an_error_fails_one_poll_and_collection_continues(eng, unlocked, tmp_path,  # noqa: F811
                                                                monkeypatch):
    real, calls = NS._metadata_sha, {"n": 0}

    def fails_once(it):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        return real(it)
    monkeypatch.setattr(NS, "_metadata_sha", fails_once)
    ok = httpx.Response(200, content=BODY)
    out = await NC.collect(KEY, until=T0 + _dt.timedelta(minutes=20),
                           transport=replay(ok, httpx.Response(200, content=BODY)),
                           **kw(eng, tmp_path))
    assert out and out[0]["inserted"] > 0                   # the retry stored everything
    assert await _count(eng, """select count(*) from ingest_run
        where stream = 'news.' || :s and status = 'FAILED'""") == 1


async def test_a_restart_waits_out_the_interval(eng, unlocked, tmp_path):  # noqa: F811
    await NC.collect(KEY, until=T0 + _dt.timedelta(seconds=30),
                     transport=replay(httpx.Response(200, content=BODY)), **kw(eng, tmp_path))
    clock.freeze(T0 + _dt.timedelta(seconds=40))
    t = replay(httpx.Response(304))
    out = await NC.collect(KEY, until=T0 + _dt.timedelta(minutes=2), transport=t,
                           **kw(eng, tmp_path))
    assert out == [] and t.requests == []                   # 5 min not yet elapsed


async def test_mode_must_be_shadow_or_production(tmp_path):
    with pytest.raises(ValueError):
        await NC.collect(KEY, mode="DRY_RUN", token=None, until=T0, root=tmp_path)
