"""FII/DII ingest end to end, offline. The fake vendor serves the REAL
2026-09-23 records (tests/fixtures/upstox_institutional) with the measured
`from` semantics: the 30 latest records dated on or before `from`."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import urllib.parse as up
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core import clock
from app.core.clock import IST, now
from app.ingest.institutional import InstitutionalIngestor, watermark_stream
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import RateLimiter, UpstoxRestClient

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_institutional"
D = _dt.date
EVENING = _dt.datetime(2026, 9, 23, 19, 15, tzinfo=IST)
CASH = "NSE_EQ|CASH"


def _ms(day: D) -> int:
    return int(_dt.datetime.combine(day, _dt.time(0), IST).timestamp() * 1000)


def _day(rec) -> D:
    return _dt.datetime.fromtimestamp(rec["time_stamp"] / 1000, IST).date()


def _real(side: str, dtype: str) -> dict[D, dict]:
    """Every real record of (side, dtype) across the fixtures, by date."""
    out: dict[D, dict] = {}
    for f in FIX.glob(f"{side.lower()}_*.json"):
        for rec in json.loads(f.read_bytes())["data"].get(dtype, []):
            out[_day(rec)] = rec
    return out


class Vendor:
    def __init__(self):
        self.records = {("FII", CASH): _real("FII", CASH), ("DII", CASH): _real("DII", CASH)}
        self.calls: list[str] = []
        self.override: dict[str, list[httpx.Response]] = {}
        self.window = 30                                  # records per request (measured)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        self.calls.append(path)
        if self.override.get(path):
            return self.override[path].pop(0)
        side = req.url.path.rsplit("/", 1)[-1].upper()
        q = dict(up.parse_qsl(req.url.query.decode()))
        end = D.fromisoformat(q["from"]) if "from" in q else D.max
        body = {}
        for t in q["data_type"].split(","):
            recs = self.records.get((side, t), {})
            days = sorted(d for d in recs if d <= end)[-self.window:]
            body[t] = [recs[d] for d in reversed(days)]           # newest first
        return httpx.Response(200, content=json.dumps(
            {"status": "success", "data": body}).encode())


class FakeClock:
    t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.t += d


@pytest.fixture
def at():
    def _at(t):
        clock.freeze(t)
    yield _at
    clock.unfreeze()


def _ing(s, vendor, tmp_path, *, commit=True):
    c = FakeClock()
    rest = UpstoxRestClient("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(vendor)),
                            limiter=RateLimiter(clock=c, sleep=c.sleep), sleep=c.sleep)
    return InstitutionalIngestor(s, rest, PayloadStore(tmp_path), commit=commit,
                                 token=TOKEN if commit else None)


async def _q(sess, sql, **kw):
    return (await sess.execute(text(sql), kw)).all()


async def _rows(s, code_prefix="FII|NSE_EQ|CASH"):
    return (await _q(s, "select count(*) from macro_observation where series_code like :p",
                     p=code_prefix + "%"))[0][0]


async def _mark(s, side="FII", dtype=CASH):
    r = await _q(s, "select last_logical_date from ingest_watermark where stream=:s",
                 s=watermark_stream(side, dtype))
    return r[0][0] if r else None


START = D(2026, 8, 11)          # the fixtures hold every trading day from here to 09-22


class TestWalk:
    async def test_commit_walks_to_yesterday_with_full_provenance(self, db_session, tmp_path, at):
        at(EVENING)
        v = Vendor()
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        assert rep.count("COMPLETE") == 2 and not rep.stopped, rep.summary()
        # 08-11 + 28 = 09-08, then 09-08 + 28 is capped at today
        assert [c.rsplit("from=", 1)[-1] for c in v.calls] == ["2026-09-08", "2026-09-23"]
        assert await _mark(db_session) == D(2026, 9, 22)
        stored = {d for (d,) in await _q(db_session,
                                         "select distinct observation_date from macro_observation")}
        assert {d for d in v.records[("FII", CASH)] if START <= d <= D(2026, 9, 22)} <= stored
        assert await _rows(db_session) == 2 * len(stored)          # buy + sell per date
        bad = await _q(db_session, """
            select count(*) filter (where r.run_id is null or r.status <> 'COMPLETE'
                                    or r.mode <> 'COMMIT'),
                   count(*) filter (where p.payload_sha256 is null),
                   count(*) filter (where m.knowable_at <> m.fetched_at or m.knowable_at_verified),
                   count(*) filter (where m.fetched_at <> p.fetched_at),
                   count(*) filter (where m.source <> 'UPSTOX_REST_V2'
                                    or m.observation_ts is not null)
            from macro_observation m left join ingest_run r using (run_id)
            left join raw_payload p on p.payload_sha256 = m.payload_sha256""")
        assert bad[0] == (0, 0, 0, 0, 0)

    async def test_rerun_is_idempotent_and_resumes_from_the_checkpoint(self, db_session,
                                                                         tmp_path, at):
        at(EVENING)
        v = Vendor()
        await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        before = await _rows(db_session)
        v.calls.clear()
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        assert len(v.calls) == 1                  # from the 09-22 checkpoint straight to today
        assert rep.summary()["inserted"] == 0 and rep.summary()["already_present"] > 0
        assert await _rows(db_session) == before

    async def test_earlier_start_is_not_skipped_by_a_later_checkpoint(self, db_session,
                                                                       tmp_path, at):
        at(EVENING)
        v = Vendor()
        await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        v.calls.clear()
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=D(2026, 4, 1))
        assert v.calls[0].endswith("from=2026-04-29")          # walked from 04-01, not 09-22
        assert not rep.count("FAILED")
        got = await _q(db_session, "select min(observation_date) from macro_observation")
        assert got[0][0] == D(2026, 4, 1)
        # the fixtures hold nothing between 04-01 and 05-04: the walk stalls
        # there and says so, instead of jumping the hole
        assert rep.results[-1].status == "STALLED"
        assert "no date after 2026-04-01" in rep.results[-1].error

    async def test_same_day_figure_is_never_persisted(self, db_session, tmp_path, at):
        at(EVENING)
        v = Vendor()
        today = dict(v.records[("FII", CASH)][D(2026, 9, 22)], time_stamp=_ms(D(2026, 9, 23)))
        v.records[("FII", CASH)][D(2026, 9, 23)] = today
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        assert rep.results[-1].outcome["same_day_excluded"] == 2
        assert not await _q(db_session, "select 1 from macro_observation "
                                        "where observation_date = '2026-09-23'")
        assert await _mark(db_session) == D(2026, 9, 22)
        # the next day it is fetched again and persisted, knowable from then
        at(_dt.datetime(2026, 9, 24, 8, 0, tzinfo=IST))
        await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        ka = await _q(db_session, "select min(knowable_at) from macro_observation "
                                  "where observation_date = '2026-09-23'")
        assert ka[0][0] == _dt.datetime(2026, 9, 24, 8, 0, tzinfo=IST)
        assert await _mark(db_session) == D(2026, 9, 23)

    async def test_dry_run_writes_no_rows_and_no_checkpoint(self, db_session, tmp_path, at):
        at(EVENING)
        rep = await _ing(db_session, Vendor(), tmp_path, commit=False).run(
            [("FII", CASH), ("DII", CASH)], start=START)
        assert rep.count("COMPLETE") == 4
        assert await _rows(db_session, "") == 0
        assert await _mark(db_session) is None
        assert any(tmp_path.rglob("*.json.gz"))                    # archived all the same

    async def test_start_before_the_vendor_data_is_clamped(self, db_session, tmp_path, at):
        at(EVENING)
        v = Vendor()
        rep = await _ing(db_session, v, tmp_path, commit=False).run(
            [("FII", CASH)], start=D(2025, 1, 1), max_requests=1)
        assert v.calls[0].endswith("from=2026-04-29")              # 04-01 + 28
        assert rep.stopped == "max_requests=1 reached"


class TestFailures:
    async def test_revision_fails_and_keeps_the_stored_value(self, db_session, tmp_path, at):
        at(EVENING)
        v = Vendor()
        await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        v.records[("FII", CASH)][D(2026, 9, 22)] = dict(
            v.records[("FII", CASH)][D(2026, 9, 22)], buy_amount=1.0)
        at(_dt.datetime(2026, 9, 24, 8, 0, tzinfo=IST))
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        assert rep.count("FAILED") == 1 and rep.summary()["inserted"] == 0
        stored = await _q(db_session, "select value from macro_observation where series_code"
                                      "='FII|NSE_EQ|CASH|1D|buy_amt' "
                                      "and observation_date='2026-09-22'")
        assert [str(x[0]) for x in stored] == ["9845.810000"]
        an = await _q(db_session, "select kind, severity from ingest_anomaly a join ingest_run r"
                                  " using (run_id) where r.stream=:s",
                      s=watermark_stream("FII", CASH))
        assert ("DUPLICATE_KEY", "FAIL") in an
        assert await _mark(db_session) == D(2026, 9, 22)

    async def test_window_that_skips_days_is_a_gap(self, db_session, tmp_path, at):
        at(EVENING)
        v = Vendor()
        await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        # a later window that no longer reaches back to the checkpoint: the
        # vendor returns fewer records than it should
        at(_dt.datetime(2026, 10, 30, 8, 0, tzinfo=IST))
        recs = v.records[("FII", CASH)]
        base = recs[D(2026, 9, 22)]
        for i in range(1, 38):
            d = D(2026, 9, 22) + _dt.timedelta(days=i)
            if d.weekday() < 5:
                recs[d] = dict(base, time_stamp=_ms(d))
        v.window = 5
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=START)
        assert rep.count("FAILED") == 1
        assert "GAP" in rep.results[0].error
        assert await _mark(db_session) == D(2026, 9, 22)
        assert not await _q(db_session, "select 1 from macro_observation "
                                        "where observation_date > '2026-09-22'")

    async def test_missing_trading_day_in_the_calendar_is_a_gap(self, db_session, tmp_path, at):
        at(EVENING)
        await _seed_calendar(db_session, D(2026, 9, 14), D(2026, 9, 22))
        v = Vendor()
        del v.records[("FII", CASH)][D(2026, 9, 17)]
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH)], start=D(2026, 9, 14))
        assert rep.count("FAILED") == 1 and "GAP" in rep.results[0].error
        assert await _rows(db_session) == 0

    async def test_rate_limit_aborts_and_later_series_are_not_attempted(self, db_session,
                                                                         tmp_path, at):
        at(EVENING)
        v = Vendor()
        v.override["/v2/market/fii?data_type=NSE_EQ|CASH&interval=1D&from=2026-09-08"] = [
            httpx.Response(429, text="Too Many Requests")]
        rep = await _ing(db_session, v, tmp_path).run([("FII", CASH), ("DII", CASH)],
                                                      start=START)
        assert [r.status for r in rep.results] == ["ABORTED", "NOT_ATTEMPTED"]
        assert "RateLimited" in rep.stopped
        assert await _rows(db_session, "") == 0

    async def test_vendor_error_body_is_archived_and_fails(self, db_session, tmp_path, at):
        at(EVENING)
        v = Vendor()
        v.override["/v2/market/dii?data_type=NSE_EQ|CASH&interval=1D&from=2026-09-08"] = [
            httpx.Response(400, json={"status": "error", "errors": [{"errorCode": "UDAPI1"}]})]
        rep = await _ing(db_session, v, tmp_path).run([("DII", CASH)], start=START)
        assert rep.count("FAILED") == 1
        # the error body is archived before anything else (the raw_payload row
        # is rolled back with the failed run, as on the candle path)
        sha = rep.results[0].outcome["payload_sha256"]
        assert list(tmp_path.rglob(f"{sha}.json.gz"))
        err = await _q(db_session, "select request_params->'outcome'->>'payload_sha256' "
                                   "from ingest_run where run_id=:r", r=rep.results[0].run_id)
        assert err[0][0] == sha

    async def test_commit_without_a_token_is_refused(self, db_session, tmp_path, at):
        at(EVENING)
        ing = _ing(db_session, Vendor(), tmp_path)
        ing.token = None
        with pytest.raises(Exception):
            await ing.run([("FII", CASH)], start=START)
        assert await _rows(db_session, "") == 0


async def _seed_calendar(s, lo: D, hi: D):
    rid, sha = uuid.uuid4(), uuid.uuid4().hex * 2
    await s.execute(text("""
        insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
          code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
          started_at, finished_at, rows_written) values (:r,'UPSTOX_REST_V2','calendar','t','{}',
          't',:c,ARRAY['pytest'],'pytest','COMMIT','COMPLETE',:a,:n,:n,0)"""),
        {"r": rid, "c": "c" * 64, "a": "a" * 64, "n": now()})
    await s.execute(text("""
        insert into raw_payload (payload_sha256, source, vendor_endpoint, request_params,
          byte_size, content_type, storage_uri, first_seen_run, fetched_at)
        values (:s,'UPSTOX_REST_V2','t','{}',1,'application/json','/dev/null',:r,:n)"""),
        {"s": sha, "r": rid, "n": now()})
    d = lo
    while d <= hi:
        trading = d.weekday() < 5
        await s.execute(text("""
            insert into trading_session (session_date, is_trading_day, session_type, open_ist,
              close_ist, source, run_id, payload_sha256, fetched_at, knowable_at,
              knowable_at_basis) values (:d, :t, :ty, :o, :c, 'UPSTOX_REST_V2', :r, :s, :n, :n,
              'test')"""),
            {"d": d, "t": trading, "ty": "NORMAL" if trading else "WEEKEND",
             "o": _dt.time(9, 15) if trading else None, "c": _dt.time(15, 30) if trading else None,
             "r": rid, "s": sha, "n": now()})
        d += _dt.timedelta(days=1)
