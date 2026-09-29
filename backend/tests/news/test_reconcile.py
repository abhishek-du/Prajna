"""Daily reconciliation and monitoring states (app.news.reconcile): pure state
rules, and a reconciliation of real SHADOW polls on the test database."""

from __future__ import annotations

import datetime as _dt

import httpx
import pytest
from sqlalchemy import text

from app.core import clock
from app.news import reconcile as NR
from app.news.store import poll_shadow
from tests.news.test_pilot import BODY, T0
from tests.news.test_store import KEY, TOKEN, unlocked  # noqa: F401 - fixture

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
AT = _dt.datetime(2026, 9, 29, 11, 0, tzinfo=IST)          # a Tuesday, market hours


def polls(*outcomes, every_s=300, end=AT):
    n = len(outcomes)
    return [(end - _dt.timedelta(seconds=every_s * (n - 1 - i)), o) for i, o in enumerate(outcomes)]


def st(p, new=(), trailing=(), items=0, dups=0, at=AT, norm=None):
    return NR.monitor_states(KEY, p, list(new), list(trailing), items, dups, at, norm)


class TestStates:
    def test_healthy(self):
        assert st(polls("OK", "NOT_MODIFIED", "OK")) == ["HEALTHY"]

    def test_no_poll_is_collector_down(self):
        assert st([]) == ["COLLECTOR_DOWN"]
        old = polls("OK", end=AT - _dt.timedelta(hours=1))           # 3 x 300 s passed
        assert st(old) == ["COLLECTOR_DOWN"]

    def test_blocked_or_only_failures_is_source_down(self):
        assert st(polls("OK", "BLOCKED"))[0] == "SOURCE_DOWN"
        assert "SOURCE_DOWN" in st(polls("ERROR", "ERROR", "ERROR"))

    def test_rate_limited_and_fetch_failure(self):
        assert "RATE_LIMITED" in st(polls("OK", "OK", "RATE_LIMITED"))
        assert "FETCH_FAILURE" in st(polls(*["OK"] * 7, "ERROR", "MALFORMED", "ERROR"))
        assert "FETCH_FAILURE" not in st(polls(*["OK"] * 9, "ERROR"))  # 10% is tolerated

    def test_stale_source_only_in_market_hours_and_against_its_norm(self):
        p = polls("OK", "OK", "OK")
        last_new = [AT - _dt.timedelta(hours=3)]
        assert st(p, new=last_new, norm=600) == ["SOURCE_STALE"]       # 4 x 10 min < 2 h floor
        assert st(p, new=last_new, norm=3 * 3600) == ["HEALTHY"]        # a slow source
        assert st(p, new=last_new, norm=None) == ["HEALTHY"]            # no norm yet: unknown
        night = AT.replace(hour=22)
        assert "SOURCE_STALE" not in st(polls("OK", end=night), new=last_new, at=night, norm=600)

    def test_unusual_volume_and_duplicate_rate(self):
        assert "UNUSUAL_VOLUME" in st(polls("OK"), trailing=[100, 120, 90], items=400)
        assert "UNUSUAL_VOLUME" not in st(polls("OK"), trailing=[100, 120], items=400)  # < 3 days
        assert "UNUSUAL_DUP_RATE" in st(polls("OK"), items=20, dups=7)
        assert "UNUSUAL_DUP_RATE" not in st(polls("OK"), items=5, dups=4)             # too few


@pytest.mark.db
@pytest.mark.integration
async def test_reconciles_a_shadow_day(db_session, unlocked):  # noqa: F811
    feed = httpx.MockTransport(lambda r: httpx.Response(200, content=BODY))
    first = await poll_shadow(db_session, KEY, token=TOKEN, transport=feed)
    clock.freeze(T0 + _dt.timedelta(minutes=5))
    await poll_shadow(db_session, KEY, token=TOKEN, transport=feed)
    rep = await NR.reconcile(db_session, T0.date(), "SHADOW", at=T0 + _dt.timedelta(minutes=6))
    assert rep["invariants"]["ok"], rep["invariants"]
    v = rep["sources"][KEY]
    assert v["polls"] == 2 and v["outcomes"] == {"OK": 2}
    assert v["items_stored"] == first["inserted"] == sum(v["decisions"].values())
    assert v["backlog_items"] == first["inserted"]                  # the first poll is backlog
    assert v["latency"]["detection_s"]["all"]["n"] == 0              # backlog is never latency
    assert sum(v["scopes"].values()) == v["items_stored"]
    assert v["state"] == ["HEALTHY"]
    # PRODUCTION on the same day is a different ledger: nothing there
    prod = await NR.reconcile(db_session, T0.date(), "PRODUCTION", at=T0 + _dt.timedelta(minutes=6))
    assert prod["sources"][KEY]["polls"] == 0
    assert prod["sources"][KEY]["state"] == ["COLLECTOR_DOWN"]
    md = NR.to_markdown(rep)
    assert "Invariants: OK" in md and KEY in md


def test_ops_status_reports_the_news_states(tmp_path):
    from app.ops.status import news_health
    assert news_health(tmp_path / "none.json", AT)["status"] == "NOT_RUN"
    rep = {"generated_at": (AT - _dt.timedelta(hours=2)).isoformat(), "day": "2026-09-29",
           "mode": "SHADOW", "states": {KEY: ["HEALTHY"], "ET_STOCKS_RSS": ["SOURCE_STALE"]},
           "invariants": {"ok": True}}
    NR.write_status(rep, tmp_path / "news_health.json")
    h = news_health(tmp_path / "news_health.json", AT)
    assert h["age_hours"] == 2.0 and h["invariants_ok"] is True
    assert h["not_healthy"] == {"ET_STOCKS_RSS": ["SOURCE_STALE"]}


@pytest.mark.db
@pytest.mark.integration
async def test_a_future_row_violates_the_invariants(db_session, unlocked):  # noqa: F811
    feed = httpx.MockTransport(lambda r: httpx.Response(200, content=BODY))
    await poll_shadow(db_session, KEY, token=TOKEN, transport=feed)
    await db_session.execute(text("alter table news_decision disable trigger "
                                  "tr_news_decision_append_only"))
    await db_session.execute(text("""update news_decision set knowable_at = now() +
        interval '1 day', decided_at = now() + interval '1 day'"""))    # test database only
    rep = await NR.reconcile(db_session, T0.date(), "SHADOW", at=T0 + _dt.timedelta(minutes=1))
    assert rep["invariants"]["knowable_in_the_future"] > 0 and rep["invariants"]["ok"] is False
