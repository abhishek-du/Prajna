"""Corporate-action ingest end to end, offline, on REAL Upstox responses."""

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
from app.ingest.corporate_actions import CorporateActionIngestor
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import RateLimiter, UpstoxRestClient

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_corporate_actions"
BY_ISIN = {m["isin"]: m["file"] for m in json.loads((FIX / "manifest.json").read_text())
           if m["isin"]}
ISINS = [*sorted(BY_ISIN), "INE000A00000"]          # the last one has no events
AT = _dt.datetime(2026, 9, 24, 18, 0, tzinfo=IST)


class Vendor:
    def __init__(self):
        self.bodies = {i: json.loads((FIX / f).read_bytes()) for i, f in BY_ISIN.items()}
        self.override: dict[str, httpx.Response] = {}
        self.calls: list[str] = []

    def __call__(self, req):
        isin = req.url.path.split("/")[-2]
        self.calls.append(isin)
        if isin in self.override:
            return self.override.pop(isin)
        body = self.bodies.get(isin, {"status": "success", "data": []})
        return httpx.Response(200, content=json.dumps(body).encode())


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


def _ing(s, v, tmp_path, commit=True, batch=50):
    c = FakeClock()
    rest = UpstoxRestClient("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(v)),
                            limiter=RateLimiter(clock=c, sleep=c.sleep), sleep=c.sleep)
    return CorporateActionIngestor(s, rest, PayloadStore(tmp_path), commit=commit,
                                   token=TOKEN if commit else None, batch=batch)


async def _q(sess, sql, **kw):
    return (await sess.execute(text(sql), kw)).all()


async def test_commit_events_with_full_provenance(db_session, tmp_path, at):
    rep = await _ing(db_session, Vendor(), tmp_path).run(ISINS)
    s = rep.summary()
    assert (s["complete"], s["inserted"]) == (1, 12), s        # 2+3+1+1+5 events
    bad = await _q(db_session, """
        select count(*) filter (where r.status <> 'COMPLETE' or r.mode <> 'COMMIT'),
               count(*) filter (where p.payload_sha256 is null),
               count(*) filter (where c.knowable_at <> c.fetched_at or c.knowable_at_verified),
               count(*) filter (where c.announced_at is not null),
               count(*) filter (where c.announcement_date is null or c.content_sha256 is null)
        from corporate_action c join ingest_run r using (run_id)
        left join raw_payload p on p.payload_sha256 = c.payload_sha256""")
    assert bad[0] == (0, 0, 0, 0, 0)
    types = dict(await _q(db_session, "select action_type, count(*) from corporate_action "
                                      "group by 1"))
    assert types == {"DIVIDEND": 9, "SPLIT": 1, "BONUS": 1, "RIGHTS": 1}
    same = await _q(db_session, "select count(*) from corporate_action "
                                "where isin='INE572G01025' and ex_date='2026-09-21'")
    assert same[0][0] == 2                           # two real dividends, one ex-date


async def test_rerun_is_idempotent(db_session, tmp_path, at):
    await _ing(db_session, Vendor(), tmp_path).run(ISINS)
    rep = await _ing(db_session, Vendor(), tmp_path).run(ISINS)
    assert (rep.summary()["inserted"], rep.summary()["already_present"]) == (0, 12)


async def test_changed_event_is_added_and_flagged(db_session, tmp_path, at):
    await _ing(db_session, Vendor(), tmp_path).run(ISINS)
    v = Vendor()
    v.bodies["INE002A01018"]["data"][0]["amount"] = 6.5          # a vendor edit
    rep = await _ing(db_session, v, tmp_path).run(ISINS)
    assert rep.summary()["inserted"] == 1
    w = await _q(db_session, "select severity, kind from ingest_anomaly where run_id=:r",
                 r=rep.results[0].run_id)
    assert ("WARN", "DUPLICATE_KEY") in w
    n = await _q(db_session, "select count(*) from corporate_action where isin='INE002A01018'")
    assert n[0][0] == 2                              # nothing overwritten


async def test_vendor_error_fails_the_batch_and_is_archived(db_session, tmp_path, at):
    v = Vendor()
    v.override["INE467B01029"] = httpx.Response(
        400, json={"status": "error", "errors": [{"errorCode": "UDAPI100011"}]})
    rep = await _ing(db_session, v, tmp_path).run(ISINS)
    assert rep.results[0].status == "FAILED"
    assert (await _q(db_session, "select count(*) from corporate_action"))[0][0] == 0
    assert len(list(tmp_path.rglob("*.json.gz"))) >= 1


async def test_rate_limit_aborts_and_later_batches_wait(db_session, tmp_path, at):
    v = Vendor()
    v.override[ISINS[0]] = httpx.Response(429, text="Too Many Requests")
    rep = await _ing(db_session, v, tmp_path, batch=2).run(ISINS)
    assert [r.status for r in rep.results] == ["ABORTED", "NOT_ATTEMPTED", "NOT_ATTEMPTED"]
    assert (await _q(db_session, "select count(*) from corporate_action"))[0][0] == 0


async def test_dry_run_writes_nothing(db_session, tmp_path, at):
    rep = await _ing(db_session, Vendor(), tmp_path, commit=False).run(ISINS)
    assert rep.results[0].status == "COMPLETE" and rep.summary()["inserted"] == 0
    assert (await _q(db_session, "select count(*) from corporate_action"))[0][0] == 0
