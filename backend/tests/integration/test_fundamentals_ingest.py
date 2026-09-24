"""Fundamentals ingest end to end, offline, on REAL Upstox responses."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib

import httpx
import pytest
from sqlalchemy import text

from app.core import clock
from app.core.clock import IST
from app.ingest.fundamentals import FundamentalsIngestor
from app.parsers import upstox_fundamentals as P
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import RateLimiter, UpstoxRestClient
from tests.integration.test_candle_ingest import _seed_instruments as _seed_keys

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_fundamentals"
R = "INE002A01018"
AT = _dt.datetime(2026, 9, 24, 18, 0, tzinfo=IST)
BY_ENDPOINT = {
    "profile": "RELIANCE_profile", "key-ratios": "RELIANCE_key_ratios",
    "share-holdings": "RELIANCE_share_holdings", "competitors": "RELIANCE_competitors",
    "balance-sheet?type=consolidated&fs=true": "RELIANCE_balance_sheet_consolidated",
    "cash-flow?type=standalone&fs=true": "RELIANCE_cash_flow_standalone",
    "income-statement?type=consolidated&time_period=quarterly&fs=true":
        "RELIANCE_income_consolidated_quarterly",
    "income-statement?type=standalone&time_period=yearly&fs=true":
        "RELIANCE_income_standalone_yearly",
}
VARS = tuple(v for v in P.VARIANTS if v.endpoint in BY_ENDPOINT)


class Vendor:
    def __init__(self):
        self.bodies = {e: json.loads((FIX / f"{n}.json").read_bytes())
                       for e, n in BY_ENDPOINT.items()}
        self.override: dict[str, httpx.Response] = {}

    def __call__(self, req):
        raw = req.url.raw_path.decode()
        ep = raw.split("/", 4)[4]
        if ep in self.override:
            return self.override.pop(ep)
        return httpx.Response(200, content=json.dumps(self.bodies[ep]).encode())


class FakeClock:
    t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.t += d


@pytest.fixture
def at():
    clock.freeze(AT)
    yield
    clock.unfreeze()


def _ing(s, v, tmp_path, commit=True):
    c = FakeClock()
    rest = UpstoxRestClient("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(v)),
                            limiter=RateLimiter(clock=c, sleep=c.sleep), sleep=c.sleep)
    return FundamentalsIngestor(s, rest, PayloadStore(tmp_path), commit=commit,
                                token=TOKEN if commit else None, variants=VARS)


async def _seed_instruments(s):
    await _seed_keys(s)
    await s.execute(text("update instrument set isin = split_part(instrument_key, '|', 2)"))


async def _q(sess, sql, **kw):
    return (await sess.execute(text(sql), kw)).all()


async def test_commit_snapshots_with_provenance(db_session, tmp_path, at):
    await _seed_instruments(db_session)
    rep = await _ing(db_session, Vendor(), tmp_path).run([R])
    s = rep.summary()
    assert (s["complete"], s["requests"], s["inserted"]) == (1, 8, 8), s
    bad = await _q(db_session, """
        select count(*) filter (where r.status <> 'COMPLETE' or r.mode <> 'COMMIT'),
               count(*) filter (where p.payload_sha256 is null),
               count(*) filter (where f.knowable_at <> f.fetched_at or f.knowable_at_verified),
               count(*) filter (where f.reported_at is not null)
        from fundamental_snapshot f join ingest_run r using (run_id)
        left join raw_payload p on p.payload_sha256 = f.payload_sha256""")
    assert bad[0] == (0, 0, 0, 0)
    q = await _q(db_session, "select period_end, period_type from fundamental_snapshot "
                             "where statement_type='income:consolidated:quarterly'")
    assert q == [(_dt.date(2026, 6, 30), "Q")]


async def test_unchanged_payload_is_not_stored_again(db_session, tmp_path, at):
    await _seed_instruments(db_session)
    await _ing(db_session, Vendor(), tmp_path).run([R])
    clock.freeze(AT + _dt.timedelta(days=1))
    rep = await _ing(db_session, Vendor(), tmp_path).run([R])
    assert (rep.summary()["inserted"], rep.summary()["unchanged"]) == (0, 8)


async def test_changed_payload_is_a_new_snapshot(db_session, tmp_path, at):
    await _seed_instruments(db_session)
    await _ing(db_session, Vendor(), tmp_path).run([R])
    clock.freeze(AT + _dt.timedelta(days=1))
    v = Vendor()
    v.bodies["key-ratios"]["data"][0]["company_value"] = "20.00"
    rep = await _ing(db_session, v, tmp_path).run([R])
    assert rep.summary()["inserted"] == 1
    n = await _q(db_session, "select count(*), count(distinct knowable_at) from "
                             "fundamental_snapshot where statement_type='key_ratios'")
    assert n[0] == (2, 2)                          # both observations kept, in time order


async def test_vendor_4xx_is_coverage_not_failure(db_session, tmp_path, at):
    await _seed_instruments(db_session)
    v = Vendor()
    v.override["profile"] = httpx.Response(
        400, json={"status": "error", "errors": [{"errorCode": "UDAPI100060"}]})
    rep = await _ing(db_session, v, tmp_path).run([R])
    r = rep.results[0]
    assert r.status == "COMPLETE" and r.inserted == 7
    assert r.coverage["VENDOR_ERROR"] == 1 and r.coverage["code:UDAPI100060"] == 1
    w = await _q(db_session, "select severity, kind from ingest_anomaly where run_id=:r",
                 r=r.run_id)
    assert w == [("WARN", "VENDOR_ERROR")]


async def test_schema_drift_fails_the_batch(db_session, tmp_path, at):
    await _seed_instruments(db_session)
    v = Vendor()
    v.bodies["key-ratios"] = {"status": "success", "data": {"not": "a list"}}
    rep = await _ing(db_session, v, tmp_path).run([R])
    assert rep.results[0].status == "FAILED"
    assert (await _q(db_session, "select count(*) from fundamental_snapshot"))[0][0] == 0


async def test_rate_limit_aborts(db_session, tmp_path, at):
    await _seed_instruments(db_session)
    v = Vendor()
    v.override["key-ratios"] = httpx.Response(429, text="Too Many Requests")
    rep = await _ing(db_session, v, tmp_path).run([R])
    assert rep.results[0].status == "ABORTED"
    assert (await _q(db_session, "select count(*) from fundamental_snapshot"))[0][0] == 0


async def test_unknown_isin_fails(db_session, tmp_path, at):
    await _seed_instruments(db_session)
    rep = await _ing(db_session, Vendor(), tmp_path).run(["INE999Z99999"])
    assert rep.results[0].status == "FAILED"
