"""News ingest end to end, offline, on the REAL 2026-09-24 response."""

from __future__ import annotations

import json
import os
import pathlib
import urllib.parse as up

import httpx
import pytest
from sqlalchemy import text

from app.core import clock
from app.core.clock import IST
from app.ingest.news import NewsIngestor, batches
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import RateLimiter, UpstoxRestClient

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_news"
MAN = json.loads((FIX / "manifest.json").read_text())[0]
REAL = json.loads((FIX / MAN["file"]).read_bytes())
KEYS = MAN["keys"]
import datetime as _dt  # noqa: E402

FETCHED = _dt.datetime.fromisoformat(MAN["fetched_at"])


class Vendor:
    """Serves the real articles for whichever of the 3 keys are requested,
    split into pages of `per_page` listings."""

    def __init__(self, per_page=100):
        self.data = json.loads(json.dumps(REAL["data"]))
        self.per_page = per_page
        self.calls: list[str] = []
        self.override: dict[int, httpx.Response] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req.url.raw_path.decode())
        q = dict(up.parse_qsl(req.url.query.decode()))
        page = int(q["page_number"])
        if page in self.override:
            return self.override.pop(page)
        keys = q["instrument_keys"].split(",")
        flat = [(k, a) for k in keys for a in self.data.get(k, [])]
        n = self.per_page
        chunk = flat[(page - 1) * n: page * n]
        data: dict = {}
        for k, a in chunk:
            data.setdefault(k, []).append(a)
        distinct = len({(a["heading"], a["published_time"]) for _, a in flat})
        pages = max(1, -(-len(flat) // n))
        return httpx.Response(200, content=json.dumps({"status": "success", "data": data,
            "metadata": {"page": {"page_number": page, "page_size": n,
                                  "total_records": distinct, "total_pages": pages}}}).encode())


class FakeClock:
    t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.t += d


@pytest.fixture
def at():
    clock.freeze(FETCHED)
    yield
    clock.unfreeze()


def _ing(s, v, tmp_path, commit=True):
    c = FakeClock()
    rest = UpstoxRestClient("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(v)),
                            limiter=RateLimiter(clock=c, sleep=c.sleep), sleep=c.sleep)
    return NewsIngestor(s, rest, PayloadStore(tmp_path), commit=commit,
                        token=TOKEN if commit else None)


async def _q(sess, sql, **kw):
    return (await sess.execute(text(sql), kw)).all()


def test_batches_are_30_and_sorted():
    b = batches([f"NSE_EQ|K{i:03}" for i in range(65)] + ["NSE_EQ|K000"])
    assert [len(x) for x in b] == [30, 30, 5] and b[0][0] == "NSE_EQ|K000"


async def test_commit_articles_links_and_provenance(db_session, tmp_path, at):
    rep = await _ing(db_session, Vendor(), tmp_path).run(KEYS)
    s = rep.summary()
    assert (s["complete"], s["inserted"], s["links_inserted"]) == (1, 11, 12), s
    bad = await _q(db_session, """
        select count(*) filter (where r.status <> 'COMPLETE' or r.mode <> 'COMMIT'),
               count(*) filter (where p.payload_sha256 is null),
               count(*) filter (where a.knowable_at > a.fetched_at),
               count(*) filter (where a.knowable_at <> a.published_at
                                or not a.knowable_at_verified),
               count(*) filter (where a.publisher is not null)
        from news_article a join ingest_run r using (run_id)
        left join raw_payload p on p.payload_sha256 = a.payload_sha256""")
    assert bad[0] == (0, 0, 0, 0, 0)
    shared = await _q(db_session, "select news_id from news_instrument group by 1 "
                                  "having count(*) = 2")
    assert len(shared) == 1
    lk = await _q(db_session, "select count(*) filter (where knowable_at <> fetched_at "
                              "or knowable_at_verified) from news_instrument")
    assert lk[0][0] == 0


async def test_rerun_is_idempotent(db_session, tmp_path, at):
    await _ing(db_session, Vendor(), tmp_path).run(KEYS)
    rep = await _ing(db_session, Vendor(), tmp_path).run(KEYS)
    s = rep.summary()
    assert (s["inserted"], s["already_present"], s["links_inserted"]) == (0, 11, 0)
    n = await _q(db_session, "select (select count(*) from news_article), "
                             "(select count(*) from news_instrument)")
    assert n[0] == (11, 12)


async def test_paging_collects_everything(db_session, tmp_path, at):
    v = Vendor(per_page=5)
    rep = await _ing(db_session, v, tmp_path).run(KEYS)
    assert rep.results[0].pages == 3 and len(v.calls) == 3
    assert rep.summary()["inserted"] == 11 and rep.summary()["links_inserted"] == 12


async def test_changed_article_is_kept_and_warned(db_session, tmp_path, at):
    await _ing(db_session, Vendor(), tmp_path).run(KEYS)
    v = Vendor()
    first = next(iter(v.data.values()))[0]
    first["summary"] = "edited by the vendor"
    rep = await _ing(db_session, v, tmp_path).run(KEYS)
    assert rep.results[0].status == "COMPLETE" and rep.summary()["inserted"] == 0
    w = await _q(db_session, "select a.severity, a.kind from ingest_anomaly a "
                             "where a.run_id = :r", r=rep.results[0].run_id)
    assert ("WARN", "DUPLICATE_KEY") in w
    body = await _q(db_session, "select count(*) from news_article where body = "
                                "'edited by the vendor'")
    assert body[0][0] == 0                      # never overwritten


async def test_dry_run_writes_nothing(db_session, tmp_path, at):
    rep = await _ing(db_session, Vendor(), tmp_path, commit=False).run(KEYS)
    assert rep.results[0].status == "COMPLETE"
    n = await _q(db_session, "select (select count(*) from news_article), "
                             "(select count(*) from news_instrument)")
    assert n[0] == (0, 0) and list(tmp_path.rglob("*.json.gz"))


async def test_rate_limit_aborts_and_rolls_back(db_session, tmp_path, at):
    v = Vendor(per_page=5)
    v.override[2] = httpx.Response(429, text="Too Many Requests")
    rep = await _ing(db_session, v, tmp_path).run(KEYS)
    assert rep.results[0].status == "ABORTED" and "RateLimited" in rep.stopped
    n = await _q(db_session, "select count(*) from news_article")
    assert n[0][0] == 0


async def test_schema_drift_fails_the_batch(db_session, tmp_path, at):
    v = Vendor()
    next(iter(v.data.values()))[0]["sentiment"] = "positive"
    rep = await _ing(db_session, v, tmp_path).run(KEYS)
    assert rep.results[0].status == "FAILED"
    assert (await _q(db_session, "select count(*) from news_article"))[0][0] == 0


def test_fetched_is_ist_evening():
    assert FETCHED.astimezone(IST).date() == _dt.date(2026, 9, 24)
