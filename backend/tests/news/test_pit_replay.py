"""Point-in-time replay of one PRODUCTION news day (test database): what the
Stage 2/3 reader (app.canon.news_pit) returns at 08:30, 08:55, 09:00, 09:15,
09:30, 10:00, 12:00 and 15:00 IST, for backlog, edited, duplicate, late,
future-dated and cross-poll items. knowable_at is Prajna's first observation,
never the publisher's time; an edit or a decision is visible only once made."""

from __future__ import annotations

import datetime as _dt
from xml.sax.saxutils import escape

import httpx
import pytest

from app.canon import news_pit as NP
from app.core import clock
from app.news.store import poll_shadow
from tests.news.test_store import KEY, TOKEN, unlocked  # noqa: F401 - fixture

pytestmark = [pytest.mark.db, pytest.mark.integration]
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
DAY = _dt.date(2026, 9, 28)


def at(hh, mm):
    return _dt.datetime.combine(DAY, _dt.time(hh, mm), tzinfo=IST)


def item(sym, title, desc, pub, q=""):
    return (f"<item><title>{escape(title)}</title><link>https://nsearchives.nseindia.com/"
            f"corporate/{sym}_28092026{pub.replace(':', '')}_x.pdf{escape(q)}</link>"
            f"<description>{escape(desc)}</description>"
            f"<pubDate>28-Sep-2026 {pub}</pubDate></item>")


def feed(*items):
    body = ("<rss version=\"2.0\"><channel><title>NSE</title><ttl>5</ttl>"
            + "".join(items) + "</channel></rss>").encode()
    return httpx.MockTransport(lambda r: httpx.Response(200, content=body))


A = ("JMA", "Jullundur Motor Agency (Delhi) Limited",
     "Jullundur Motor Agency (Delhi) Limited has informed |SUBJECT: Updates", "08:30:00")
A2 = (A[0], A[1], "Jullundur Motor Agency (Delhi) Limited has now informed |SUBJECT: Updates",
      A[3])
B = ("SHEETAL", "Sheetal Universal Limited", "Outcome of Board Meeting |SUBJECT: Outcome",
     "08:10:00")
C = ("PARAS", "Paras Def And Spce Tech L", "Order received |SUBJECT: Bagging of orders", "08:50:00")
D2 = ("PARAS2", C[1], C[2], "09:01:00")                  # a separate filing, identical text
D = (*C, "?utm_source=rss")                              # C's own link, tracking tag
E = ("AXISBANK", "Axis Bank Limited", "Credit rating |SUBJECT: Credit Rating", "10:30:00")
F = ("AMNPLST", "Amines & Plasticizers Limited", "Trading window |SUBJECT: Trading Window",
     "06:00:00")


@pytest.fixture
def production(unlocked, monkeypatch):  # noqa: F811
    monkeypatch.setattr(unlocked, "PRAJNA_NEWS_MULTI_SOURCE_ENABLED", True)
    return unlocked


async def test_a_news_day_replayed_at_eight_instants(db_session, production):
    async def poll(when, *items):
        clock.freeze(when)
        return await poll_shadow(db_session, KEY, token=TOKEN, mode="PRODUCTION",
                                 transport=feed(*(item(*x) for x in items)))

    await poll(at(8, 40), A, B)                      # the first poll: backlog
    r2 = await poll(at(8, 57), A2, B, C)             # A edited; C new
    await poll(at(9, 5), A2, B, C, D, D2)            # D repeats C's link; D2 same text
    await poll(at(9, 20), A2, B, C, D, D2, E)        # E published "10:30": a future time
    await poll(at(11, 0), A2, B, C, D, D2, E, F)     # F published 06:00, seen only at 11:00
    assert r2["changed"] == 1 and r2["decisions"] == {"STORY_UPDATE": 1, "NEW_ARTICLE": 1}

    async def view(hh, mm):
        rows = await NP.items(db_session, at(hh, mm), limit=100)
        for r in rows:                                          # nothing from the future
            assert r["knowable_at"] < at(hh, mm)
            for k in ("story_knowable_at",):
                assert r[k] is None or r[k] < at(hh, mm)
        return {r["source_article_id"]: r for r in rows}     # C and D share title+summary

    def titles(v):
        return sorted(r["title"] for r in v.values())

    assert await view(8, 30) == {}                              # before the first poll
    v = await view(8, 55)
    assert titles(v) == sorted([A[1], B[1]])
    assert any("has informed" in (r["summary"] or "") for r in v.values())  # the ORIGINAL
    assert all(r["backlog"] for r in v.values())
    v = await view(9, 0)
    assert titles(v) == sorted([A[1], B[1], C[1]])
    assert any("has now informed" in (r["summary"] or "") for r in v.values())  # edit 08:57
    assert [r["dedup_decision"] for r in v.values() if r["title"] == C[1]] == ["NEW_ARTICLE"]
    v = await view(9, 15)
    dups = [r for r in v.values() if r["dedup_decision"] == "DUPLICATE_ARTICLE"]
    assert len(dups) == 1 and dups[0]["duplicate_of"] is not None   # D marked, still stored
    related = [r for r in v.values() if r["dedup_decision"] == "STORY_RELATED"]
    assert len(related) == 1 and related[0]["source_article_id"].startswith(   # D2: C's story
        "https://nsearchives.nseindia.com/corporate/PARAS2")
    c_story = [r["story_id"] for r in v.values() if r["title"] == C[1]]
    assert len(set(c_story) - {None}) == 1 or related[0]["story_id"] in c_story
    assert len(v) == 5
    v = await view(9, 30)
    e = [r for r in v.values() if r["title"] == E[1]]
    # visible from its discovery (09:20) although its publisher time is 10:30
    assert len(e) == 1 and e[0]["published_at"] > at(9, 30) and e[0]["knowable_at"] == at(9, 20)
    assert F[1] not in titles(v)                               # published 06:00, not yet seen
    assert titles(await view(10, 0)) == titles(v)
    v = await view(12, 0)
    f = [r for r in v.values() if r["title"] == F[1]]
    assert len(f) == 1 and f[0]["knowable_at"] == at(11, 0)    # never back-dated to 06:00
    assert len(v) == 7 and titles(await view(15, 0)) == titles(v)

    # the Stage 3 news v2 candidate on the same day: duplicates never counted, and a
    # collector silent for more than 2 h makes every feature MISSING_INPUT, not 0
    from app.features import news_features as NF
    g = await NF.snapshot(db_session, at(12, 0), None)
    # C, D2, E, F are arrivals (D is a duplicate; A and B were the first poll's backlog)
    assert g["mnews_news_count_24h"] == (4.0, None)
    assert g["mnews_duplicate_count_24h"] == (1.0, None)
    assert await NF.coverage_state(db_session, at(12, 0)) == "NORMAL"
    assert await NF.coverage_state(db_session, at(15, 0)) == "STALE"      # last poll 11:00
    assert await NF.coverage_state(db_session, at(8, 30)) == "MISSING"    # before any poll
    g = await NF.snapshot(db_session, at(15, 0), None)
    assert set(g.values()) == {(None, "MISSING_INPUT")}


async def test_shadow_rows_are_never_visible(db_session, unlocked):  # noqa: F811
    clock.freeze(at(8, 40))
    await poll_shadow(db_session, KEY, token=TOKEN, transport=feed(item(*A), item(*B)))
    assert await NP.items(db_session, at(15, 0)) == []


async def test_stage3_news_rows_activation_rehearsal(db_session, production, monkeypatch):
    """The engine's news step on the replayed day, with the v2 specs switched on for this
    test only: market-wide rows under MARKET, per-company rows for the linked company,
    real zeros for an unlinked one, STALE -> MISSING_INPUT, and nothing while inactive."""
    from app.features import engine as E
    from app.features import registry as R
    from app.features.snapshots import Snapshot

    async def poll(when, *items):
        clock.freeze(when)
        return await poll_shadow(db_session, KEY, token=TOKEN, mode="PRODUCTION",
                                 transport=feed(*(item(*x) for x in items)))
    await poll(at(8, 40), A, B)
    await poll(at(8, 57), A2, B, C)
    await poll(at(9, 5), A2, B, C, D, D2)

    def snap(hh, mm):
        return Snapshot(DAY, "PRE_SESSION", at(hh, mm), DAY - _dt.timedelta(days=3))

    jma, other = "NSE_EQ|INE045601023", "NSE_EQ|INE238A01034"   # PARAS (C, D2) / not linked
    assert await E.news_rows(db_session, snap(9, 10), [jma, other]) == []  # v1: inactive
    monkeypatch.setattr(E, "FEATURES", R.FEATURES_V1 + R.NEWS_V2_FEATURES)
    rows = await E.news_rows(db_session, snap(9, 10), [jma, other])
    ctx = {r.feature_id: r for r in rows if r.scope == "CONTEXT"}
    co = {(r.instrument_key, r.feature_id): r for r in rows if r.scope == "INSTRUMENT"}
    assert len(ctx) == 32 and {r.instrument_key for r in ctx.values()} == {"MARKET"}
    assert ctx["mnews_news_count_24h"].value == 2.0     # C, D2 (D duplicate; A, B backlog)
    assert ctx["mnews_duplicate_count_24h"].value == 1.0
    assert all(r.input_max_knowable_at < at(9, 10) for r in rows if r.input_max_knowable_at)
    assert co[(jma, "mnews_company_count_24h")].value == 2.0                   # C and D2
    assert co[(other, "mnews_company_count_24h")].value == 0.0                 # a real zero
    assert co[(other, "mnews_company_time_since_last_s")].reason == "MISSING_INPUT"
    # deterministic: the same snapshot again gives the same values and provenance
    again = await E.news_rows(db_session, snap(9, 10), [jma, other])
    assert [(r.feature_id, r.value, r.reason, r.inputs_sha256) for r in again] == \
        [(r.feature_id, r.value, r.reason, r.inputs_sha256) for r in rows]
    stale = await E.news_rows(db_session, snap(12, 0), [jma])                  # last poll 09:05
    assert {r.reason for r in stale} == {"MISSING_INPUT"}
