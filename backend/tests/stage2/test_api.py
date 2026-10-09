"""The read API (/v1): point-in-time through HTTP, read-only, documented.

Runs against the Stage 2 seed world (tests/support/stage2_seed.py) with the
API's session dependency bound to the test database session."""

from __future__ import annotations

import datetime as _dt
import inspect
import os
import urllib.parse as up

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.canon import process as P
from app.core import clock
from app.readapi import main as M
from tests.support import stage2_seed as SEED
from tests.support.stage2_seed import NOW, R, ist

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
KEY = up.quote(R, safe="")


@pytest.fixture
async def client(db_session):
    clock.freeze(NOW)
    await SEED.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)

    async def bound():
        yield db_session
    M.api.dependency_overrides[M.session] = bound
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=M.api),
                                 base_url="http://test") as c:
        yield c
    M.api.dependency_overrides.clear()
    clock.unfreeze()


def q(dt: _dt.datetime) -> str:
    return up.quote(dt.isoformat(), safe="")


async def test_candles_are_point_in_time(client):
    before = (await client.get(f"/v1/instruments/{KEY}/candles?timeframe=1d"
                               f"&as_of={q(ist(2026, 9, 24, 7, 59))}")).json()
    assert before["data"]["candles"] == [] and before["meta"]["point_in_time"] is True
    after = (await client.get(f"/v1/instruments/{KEY}/candles?timeframe=1d"
                              f"&as_of={q(ist(2026, 9, 24, 8, 0, 1))}")).json()
    rows = after["data"]["candles"]
    assert rows and all(_dt.datetime.fromisoformat(r["knowable_at"]) < ist(2026, 9, 24, 8, 0, 1)
                        for r in rows)
    assert after["meta"]["knowledge_rule"] == "knowable_at < as_of"


async def test_sector_as_of_is_historical_while_instrument_sector_is_current(client):
    old = (await client.get(f"/v1/instruments/{KEY}/profile?as_of={q(ist(2026, 9, 15))}")).json()
    new = (await client.get(f"/v1/instruments/{KEY}/profile?as_of={q(NOW)}")).json()
    assert old["data"]["sector_as_of"] == "Old"
    assert new["data"]["sector_as_of"] == "Refineries"


async def test_a_corporate_action_is_invisible_before_it_was_knowable(client):
    now_ = (await client.get(f"/v1/instruments/{KEY}/corporate-actions?as_of={q(NOW)}")).json()
    # CA-OBSERVED: announced 09-24, stored 09-25 10:00 -> invisible until it was stored
    early = (await client.get(f"/v1/instruments/{KEY}/corporate-actions"
                              f"?as_of={q(ist(2026, 9, 25, 1))}")).json()
    later = (await client.get(f"/v1/instruments/{KEY}/corporate-actions"
                              f"?as_of={q(ist(2026, 9, 25, 10, 1))}")).json()
    assert now_["data"] == [] and early["data"] == [] and len(later["data"]) >= 1


async def test_news_needs_the_instrument_link_to_be_knowable(client):
    early = (await client.get(f"/v1/news?instrument_key={KEY}&as_of={q(ist(2026, 9, 24, 10, 59))}"))
    late = (await client.get(f"/v1/news?instrument_key={KEY}&as_of={q(ist(2026, 9, 24, 11, 1))}"))
    assert early.json()["data"] == []
    (item,) = late.json()["data"]
    assert item["published_at"] < item["received_at"]         # vendor time vs Prajna's fetch


async def test_errors_are_explicit(client):
    assert (await client.get(f"/v1/instruments/{KEY}/candles?timeframe=5m")).status_code == 422
    naive = await client.get(f"/v1/instruments/{KEY}/candles?timeframe=1d"
                             "&as_of=2026-09-24T10:00:00")
    assert naive.status_code == 422                           # no guessing a timezone
    assert (await client.get("/v1/instruments/NSE_EQ%7CNOPE/profile")).status_code == 404


async def test_search_ranks_the_exact_symbol_first(client):
    hits = (await client.get("/v1/search?q=RELIANCE")).json()["data"]
    assert hits[0]["instrument_key"] == R and hits[0]["match"] == "SYMBOL_EXACT"


async def test_quote_is_labelled_as_not_real_time(client):
    d = (await client.get(f"/v1/instruments/{KEY}/quote")).json()
    assert "no live tick store" in d["data"]["source"]


def test_every_route_is_a_read_and_every_contract_area_is_covered():
    routes = [r for r in M.api.routes if getattr(r, "path", "").startswith("/v1/")
              and hasattr(r, "methods")]
    assert all(r.methods <= {"GET", "HEAD"} for r in routes)          # no write endpoint
    paths = {r.path for r in routes}
    for area in ("/v1/instruments", "/v1/search", "/v1/instruments/{instrument_key}/profile",
                 "/v1/instruments/{instrument_key}/candles",
                 "/v1/instruments/{instrument_key}/quote",
                 "/v1/instruments/{instrument_key}/fundamentals",
                 "/v1/instruments/{instrument_key}/corporate-actions", "/v1/sectors",
                 "/v1/global", "/v1/news", "/v1/freshness",
                 "/v1/instruments/{instrument_key}/quality", "/v1/pipeline/status",
                 "/v1/acceptance"):
        assert area in paths, area


async def test_the_session_is_read_only(db_session):
    assert "set transaction read only" in inspect.getsource(M.session)
    await db_session.execute(text("set transaction read only"))
    with pytest.raises(DBAPIError, match="read-only transaction"):
        await db_session.execute(text("create temporary table api_probe (x int)"))


async def test_latest_withholds_the_change_across_a_split_or_bonus(client, db_session):
    first = (await client.get(f"/v1/latest?keys={KEY}")).json()["data"]
    (row,) = first
    assert row["market_date"] == "2026-09-22" and row["previous_market_date"] == "2026-09-18"
    assert row["comparable"] is True and row["change"] == 0.0
    ca = (await db_session.execute(text("select id, run_id from corporate_action where "
                                        "instrument_key = :k"), {"k": R})).first()
    await db_session.execute(text("""
        insert into ca_factor (ca_id, instrument_key, action_type, ex_date, status, method,
          factor_price, factor_volume, knowable_at, vendor_applied, reason, method_version,
          derived_at, run_id) values (:c, :k, 'BONUS', '2026-09-21', 'EXACT', 'BONUS_RATIO',
          2, 2, now(), 'UNKNOWN', 'test', 'cafactor-v1', now(), :r)"""),
        {"c": ca.id, "k": R, "r": ca.run_id})
    (row,) = (await client.get(f"/v1/latest?keys={KEY}")).json()["data"]
    assert row["comparable"] is False and row["change"] is None     # not a market move
    assert "ex-date" in row["comparable_reason"]


async def test_market_session_is_the_calendar_not_a_feed_status(client):
    d = (await client.get("/v1/market/session?date=2026-09-22")).json()
    assert d["data"]["is_trading_day"] is True and d["data"]["state"] == "CLOSED"
    assert "not a data-feed status" in d["meta"]["notes"][0]
    assert (await client.get("/v1/market/session?date=2031-01-01")).status_code == 404


async def test_instrument_list_reports_its_total_and_filters_by_sector(client):
    every = (await client.get("/v1/instruments?lifecycle_status=ANY")).json()
    assert every["meta"]["total"] == len(every["data"]) >= 1
    empty = (await client.get("/v1/instruments?lifecycle_status=")).json()
    assert empty["meta"]["total"] == every["meta"]["total"]           # empty = no filter
    ref = (await client.get("/v1/instruments?lifecycle_status=ANY&sector=Refineries")).json()
    assert [i["instrument_key"] for i in ref["data"]] == [R] and ref["meta"]["total"] == 1


async def test_acceptance_states_stage3_is_locked(client):
    d = (await client.get("/v1/acceptance")).json()
    assert d["data"]["stage3"]["status"] == "LOCKED"
