"""M4.3 candle ingest end to end, offline. The transport serves the REAL
2026-09-23 Upstox responses (tests/fixtures/upstox_candles), sliced to the
requested window. The clock is frozen at each fixture's recorded fetch time."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import urllib.parse as up
import uuid
from typing import ClassVar

import httpx
import pytest
from sqlalchemy import text

from app.contracts import candles as C
from app.core import clock
from app.core.clock import IST, UTC, now
from app.ingest import candles as IC
from app.ingest.candles import CandleIngestor, CandleJob, plan_jobs
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import RateLimiter, UpstoxRestClient

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "upstox_candles"
MAN = {m["file"][:-5]: m for m in json.loads((FIX / "manifest.json").read_text())}
R, SME, NB = "NSE_EQ|INE002A01018", "NSE_EQ|INE00C501018", "NSE_EQ|INF204KB14I2"
D = _dt.date
AFTER_CLOSE = _dt.datetime(2026, 9, 23, 17, 0, tzinfo=IST)


def _body(name):
    return json.loads((FIX / f"{name}.json").read_bytes())


def _slice(name, frm: D, to: D) -> bytes:
    """The real candles of `name` that fall in [frm, to], as Upstox would serve them."""
    b = _body(name)
    tf = MAN[name]["timeframe"]
    keep = []
    for c in b["data"]["candles"]:
        day = (C.daily_session_date(c[0]) if tf == "1d"
               else C.intraday_bar_start(c[0])[1])
        if frm <= day <= to:
            keep.append(c)
    b["data"]["candles"] = keep
    return json.dumps(b).encode()


class Vendor:
    """Routes /v3/historical-candle requests to real fixtures."""

    HIST = re.compile(r"/v3/historical-candle/(?P<key>[^/]+)/(?P<unit>\w+)/(?P<step>\d+)/"
                      r"(?P<to>[\d-]+)/(?P<frm>[\d-]+)$")
    INTRA = re.compile(r"/v3/historical-candle/intraday/(?P<key>[^/]+)/(?P<unit>\w+)/"
                       r"(?P<step>\d+)$")
    SOURCES: ClassVar[dict] = {(R, "days", "1"): "hist_1d_2026-09-08_22",
               (SME, "days", "1"): "hist_1d_sme_listing_label",
               (SME, "minutes", "1"): "hist_1m_sme_sparse",
               (R, "minutes", "5"): "hist_5m_2026-09-22"}
    INTRADAY: ClassVar[dict] = {(R, "minutes", "1"): "intraday_1m_1500",
                                (R, "minutes", "5"): "intraday_5m_1500",
                (R, "hours", "1"): "intraday_1h_1500"}

    def __init__(self):
        self.calls: list[str] = []
        self.override: dict[str, httpx.Response | list] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        self.calls.append(path)
        o = self.override.get(path)
        if isinstance(o, list) and not o:
            o = None                                  # one-shot responses used up
        if isinstance(o, list):
            r = o.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        if o is not None:
            return o
        if m := self.INTRA.search(path):
            name = self.INTRADAY[(up.unquote(m["key"]), m["unit"], m["step"])]
            return httpx.Response(200, content=(FIX / f"{name}.json").read_bytes())
        m = self.HIST.search(path)
        name = self.SOURCES.get((up.unquote(m["key"]), m["unit"], m["step"]))
        if name is None:
            return httpx.Response(200, content=b'{"status":"success","data":{"candles":[]}}')
        return httpx.Response(200, content=_slice(name, D.fromisoformat(m["frm"]),
                                                  D.fromisoformat(m["to"])))


async def _seed_instruments(s, keys=(R, SME)):
    rid, sha = uuid.uuid4(), uuid.uuid4().hex * 2
    await s.execute(text("""
        insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
          code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
          started_at, finished_at, rows_written) values (:r,'UPSTOX_ASSETS',
          'instrument.current','t','{}','t',:c,ARRAY['pytest'],'pytest','COMMIT','COMPLETE',:a,
          :n,:n,0)"""),
        {"r": rid, "c": "c" * 64, "a": "a" * 64, "n": now()})
    await s.execute(text("""
        insert into raw_payload (payload_sha256, source, vendor_endpoint, request_params,
          byte_size, content_type, storage_uri, first_seen_run, fetched_at)
        values (:s,'UPSTOX_ASSETS','t','{}',1,'application/gzip','/dev/null',:r,:n)"""),
        {"s": sha, "r": rid, "n": now()})
    for k in keys:
        await s.execute(text("""
            insert into instrument (instrument_key, segment, exchange, trading_symbol,
              valid_from, source, run_id, payload_sha256, fetched_at, knowable_at,
              knowable_at_basis) values (:k,'NSE_EQ','NSE',:t,'2026-09-23','UPSTOX_ASSETS',:r,
              :s,:n,:n,'test')"""), {"k": k, "t": k[-6:], "r": rid, "s": sha, "n": now()})


@pytest.fixture
def frozen():
    def at(t: _dt.datetime):
        clock.freeze(t)
    yield at
    clock.unfreeze()


def _ingestor(s, vendor, tmp_path, *, commit=True):
    c = FakeClock()
    rest = UpstoxRestClient("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(vendor)),
                            limiter=RateLimiter(clock=c, sleep=c.sleep), sleep=c.sleep)
    return CandleIngestor(s, rest, PayloadStore(tmp_path), commit=commit,
                          token=TOKEN if commit else None)


class FakeClock:
    t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.t += d


async def _q(s, sql, **kw):
    return (await s.execute(text(sql), kw)).all()


def _daily_jobs(key=R, frm=D(2026, 9, 8), to=D(2026, 9, 23)):
    return plan_jobs([key], ["1d"], frm, to)[0]


# ── happy path ─────────────────────────────────────────────────────────────
class TestIngest:
    async def test_daily_window_persists_complete_bars_with_provenance(self, db_session,
                                                                     tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        rep = await _ingestor(db_session, Vendor(), tmp_path).run(_daily_jobs())
        (res,) = rep.results
        assert res.status == "COMPLETE" and res.inserted == 10, res
        rows = await _q(db_session, """
            select b.session_date, b.bar_start_utc, b.close, b.vendor_ts_raw, b.knowable_at,
                   b.fetched_at, b.knowable_at_verified, b.payload_sha256, i.instrument_key,
                   p.storage_uri, p.http_status
            from ohlcv_bar b join instrument i on i.instrument_id = b.instrument_id
            join raw_payload p on p.payload_sha256 = b.payload_sha256 order by b.session_date""")
        assert rows[0].session_date == D(2026, 9, 8) and len(rows) == 10
        last = rows[-1]
        assert last.session_date == D(2026, 9, 22) and str(last.close) == "1240.4000"
        assert last.bar_start_utc == C.daily_bar_start(D(2026, 9, 22))
        assert last.vendor_ts_raw == "2026-09-22T00:00:00+05:30"
        assert last.knowable_at == last.fetched_at == AFTER_CLOSE and not last.knowable_at_verified
        assert last.instrument_key == R and last.http_status == 200
        assert PayloadStore.read(last.storage_uri, last.payload_sha256)
        # checkpoint: the day BEFORE the fetch, not the window end (09-23 bar not yet published)
        wm = await _q(db_session, "select last_logical_date from ingest_watermark "
                      "where stream=:st", st=f"ohlcv.1d.{R}")
        assert wm[0].last_logical_date == D(2026, 9, 22)
        run = await _q(db_session, "select request_params from ingest_run where run_id=:r",
                       r=res.run_id)
        assert run[0].request_params["outcome"]["outcome"] == "DATA"
        assert run[0].request_params["outcome"]["complete"] == 10

    async def test_rerun_is_idempotent(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        ing = _ingestor(db_session, Vendor(), tmp_path)
        await ing.run(_daily_jobs())
        again = await ing.run(_daily_jobs())
        (res,) = again.results
        assert res.status == "COMPLETE" and (res.inserted, res.already_present) == (0, 10)
        assert (await _q(db_session, "select count(*) n from ohlcv_bar"))[0].n == 10

    async def test_multi_window_history_with_labels_that_carry_a_time(self, db_session,
                                                                     tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        jobs = plan_jobs([SME], ["1d"], D(2016, 9, 24), D(2026, 9, 23))[0]
        assert len(jobs) == 2
        rep = await _ingestor(db_session, Vendor(), tmp_path).run(jobs)
        assert [r.status for r in rep.results] == ["COMPLETE", "COMPLETE"]
        assert rep.inserted == 594
        timed = await _q(db_session, "select count(*) n from ohlcv_bar where vendor_ts_raw "
                         "not like '%T00:00:00+05:30'")
        assert timed[0].n == 44

    async def test_sparse_intraday_month(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        jobs = plan_jobs([SME], ["1m"], D(2026, 8, 1), D(2026, 8, 31))[0]
        rep = await _ingestor(db_session, Vendor(), tmp_path).run(jobs)
        (res,) = rep.results
        assert res.inserted == 1719 and res.coverage["grid_unchecked"] == 1719

    async def test_intraday_persists_complete_bars_and_never_moves_the_checkpoint(
            self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(_dt.datetime.fromisoformat(MAN["intraday_1m_1500"]["fetched_at"]))
        rep = await _ingestor(db_session, Vendor(), tmp_path).run([CandleJob(R, "1m", None)])
        (res,) = rep.results
        assert res.status == "COMPLETE" and res.inserted == 343      # the SETTLING bar is not
        assert res.coverage["settling"] == 1 and res.complete_through is None
        wm = await _q(db_session, "select last_logical_date from ingest_watermark where "
                      "stream=:st", st=f"ohlcv.1m.{R}")
        assert wm[0].last_logical_date is None

    async def test_forming_1h_bar_is_not_persisted(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(_dt.datetime.fromisoformat(MAN["intraday_1h_1500"]["fetched_at"]))
        rep = await _ingestor(db_session, Vendor(), tmp_path).run([CandleJob(R, "1h", None)])
        assert rep.results[0].inserted == 5
        latest = await _q(db_session, "select max(bar_start_utc) m from ohlcv_bar")
        assert latest[0].m.astimezone(IST).time() == _dt.time(13, 15)

    async def test_grid_is_checked_where_the_calendar_knows_the_session(
            self, db_session, tmp_path, frozen):
        from tests.integration.test_preopen_replay import _seed_session
        await _seed_instruments(db_session)
        await _seed_session(db_session, D(2026, 9, 23))
        frozen(_dt.datetime.fromisoformat(MAN["intraday_5m_1500"]["fetched_at"]))
        rep = await _ingestor(db_session, Vendor(), tmp_path).run([CandleJob(R, "5m", None)])
        assert rep.results[0].coverage["grid_unchecked"] == 0

    async def test_empty_window_is_recorded_and_checkpointed(self, db_session, tmp_path,
                                                           frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        rep = await _ingestor(db_session, Vendor(), tmp_path).run(
            plan_jobs([R], ["1m"], D(2026, 8, 1), D(2026, 8, 31))[0])
        (res,) = rep.results
        assert res.status == "COMPLETE" and res.coverage["outcome"] == "EMPTY"
        assert res.complete_through == "2026-08-31"

    async def test_dry_run_writes_nothing_but_archives(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        rep = await _ingestor(db_session, Vendor(), tmp_path, commit=False).run(_daily_jobs())
        assert rep.results[0].status == "COMPLETE" and rep.inserted == 0
        for t in ("ohlcv_bar", "ingest_watermark"):
            assert (await _q(db_session, f"select count(*) n from {t}"))[0].n == 0
        assert (await _q(db_session, "select count(*) n from raw_payload where source="
                         "'UPSTOX_REST_V3'"))[0].n == 0
        assert list(tmp_path.rglob("*.json.gz"))


# ── failure and recovery ───────────────────────────────────────────────────
class TestFailClosed:
    async def test_conflicting_bar_fails_and_changes_nothing(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        ing = _ingestor(db_session, v, tmp_path)
        await ing.run(_daily_jobs())
        b = json.loads(_slice("hist_1d_2026-09-08_22", D(2026, 9, 8), D(2026, 9, 23)))
        b["data"]["candles"][0][4] = 1241.0                  # the 09-22 close, revised (in range)
        v.override[CandleJob(R, "1d", _daily_jobs()[0].window).path()] = httpx.Response(
            200, content=json.dumps(b).encode())
        rep = await ing.run(_daily_jobs())
        (res,) = rep.results
        assert res.status == "FAILED" and "different bar" in json.dumps(
            await _anoms(db_session, res.run_id))
        closes = await _q(db_session, "select close from ohlcv_bar where session_date="
                          "'2026-09-22'")
        assert str(closes[0].close) == "1240.4000"

    async def test_vendor_error_fails_the_window_and_stops_only_that_stream(
            self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        jobs = plan_jobs([SME], ["1d"], D(2016, 9, 24), D(2026, 9, 23))[0] + _daily_jobs()
        v.override[jobs[0].path()] = httpx.Response(
            400, content=(FIX / "err_400_udapi1148.json").read_bytes())
        rep = await _ingestor(db_session, v, tmp_path).run(jobs)
        by = {(r.job.instrument_key, r.job.window.from_date): r.status for r in rep.results}
        assert by[(SME, D(2016, 9, 24))] == "FAILED"
        assert by[(SME, D(2020, 1, 1))] == "NOT_ATTEMPTED"    # its stream stopped
        assert by[(R, D(2026, 9, 8))] == "COMPLETE"            # other streams carried on
        failed = next(r for r in rep.results if r.status == "FAILED")
        a = await _anoms(db_session, failed.run_id)
        assert any(x["kind"] == "VENDOR_ERROR" and x["detail"].get("codes") == "UDAPI1148"
                   for x in a)
        assert list(tmp_path.rglob("*.json.gz"))             # the error body is archived

    async def test_rate_limit_stops_everything_and_resume_finishes(self, db_session,
                                                                 tmp_path, frozen):
        """Streams run in key order: RELIANCE (INE002...) before the SME (INE00C...)."""
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        jobs = _daily_jobs() + plan_jobs([SME], ["1d"], D(2016, 9, 24), D(2026, 9, 23))[0]
        v.override[jobs[0].path()] = [httpx.Response(429, text="Too Many Requests")]
        ing = _ingestor(db_session, v, tmp_path)

        first = await ing.run(jobs)
        assert first.stopped and "RateLimited" in first.stopped
        assert [r.status for r in first.results] == ["ABORTED", "NOT_ATTEMPTED", "NOT_ATTEMPTED"]
        assert (await _q(db_session, "select count(*) n from ohlcv_bar"))[0].n == 0

        second = await ing.run(jobs)                      # the 429 was one-shot
        assert [r.status for r in second.results] == ["COMPLETE", "COMPLETE", "COMPLETE"]
        assert (await _q(db_session, "select count(*) n from ohlcv_bar"))[0].n == 10 + 594

        third = await ing.run(jobs)                       # completed windows are skipped
        assert [r.status for r in third.results] == ["COMPLETE", "SKIPPED", "COMPLETE"]
        assert third.inserted == 0

    async def test_transient_5xx_is_retried(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        path = _daily_jobs()[0].path()
        good = httpx.Response(200, content=_slice("hist_1d_2026-09-08_22", D(2026, 9, 8),
                                                  D(2026, 9, 23)))
        v.override[path] = [httpx.Response(503), good]
        rep = await _ingestor(db_session, v, tmp_path).run(_daily_jobs())
        assert rep.results[0].inserted == 10 and v.calls.count(path) == 2

    async def test_instrument_missing_from_the_table_fails(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session, keys=(SME,))
        frozen(AFTER_CLOSE)
        v = Vendor()
        rep = await _ingestor(db_session, v, tmp_path).run(_daily_jobs())
        assert rep.results[0].status == "FAILED" and v.calls == []

    async def test_malformed_body_fails_but_is_archived(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        v.override[_daily_jobs()[0].path()] = httpx.Response(200, content=b"<html>oops</html>")
        rep = await _ingestor(db_session, v, tmp_path).run(_daily_jobs())
        assert rep.results[0].status == "FAILED"
        (f,) = list(tmp_path.rglob("*.json.gz"))
        import gzip
        assert gzip.decompress(f.read_bytes()) == b"<html>oops</html>"

    async def test_interrupted_insert_rolls_back_and_resume_completes(
            self, db_session, tmp_path, frozen, monkeypatch):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        real = IC.pg_insert

        def boom(model):
            raise ConnectionResetError("database went away")
        monkeypatch.setattr(IC, "pg_insert", boom)
        with pytest.raises(ConnectionResetError):
            await _ingestor(db_session, Vendor(), tmp_path).run(_daily_jobs())
        assert (await _q(db_session, "select count(*) n from ohlcv_bar"))[0].n == 0
        st = await _q(db_session, "select status from ingest_run where stream=:st",
                      st=f"ohlcv.1d.{R}")
        assert [x.status for x in st] == ["FAILED"]
        monkeypatch.setattr(IC, "pg_insert", real)
        rep = await _ingestor(db_session, Vendor(), tmp_path).run(_daily_jobs())
        assert rep.results[0].inserted == 10

    async def test_every_persisted_bar_has_full_provenance(self, db_session, tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        await _ingestor(db_session, Vendor(), tmp_path).run(
            plan_jobs([SME], ["1d"], D(2016, 9, 24), D(2026, 9, 23))[0])
        bad = await _q(db_session, """
            select count(*) n from ohlcv_bar b left join raw_payload p using (payload_sha256)
            left join ingest_run r on r.run_id = b.run_id
            where p.payload_sha256 is null or r.status <> 'COMPLETE' or b.knowable_at > b.fetched_at
               or b.knowable_at_basis = '' or b.source <> 'UPSTOX_REST_V3'""")
        assert bad[0].n == 0


class TestCheckpointCoverage:
    """A checkpoint is a contiguous [covered_from, through]; it is never trusted
    for a start it does not cover, and never advanced across a hole."""

    async def _cp(self, s, key=SME, tf="1d"):
        return await CandleIngestor(s, None, None, commit=False, token=None).checkpoint(
            C.watermark_stream(tf, key))

    async def test_earlier_start_is_not_skipped_by_a_later_checkpoint(self, db_session,
                                                                     tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        late = plan_jobs([SME], ["1d"], D(2026, 9, 24 - 23), D(2026, 9, 23))[0]
        await _ingestor(db_session, v, tmp_path).run(late)
        assert (await self._cp(db_session)).covered_from == D(2026, 9, 1)
        # a backfill from 2016 must fetch everything, not trust the 09-01 checkpoint
        early = plan_jobs([SME], ["1d"], D(2016, 9, 24), D(2026, 9, 23))[0]
        rep = await _ingestor(db_session, v, tmp_path).run(early)
        assert [r.status for r in rep.results] == ["COMPLETE", "COMPLETE"]
        cp = await self._cp(db_session)
        assert (cp.covered_from, cp.through) == (D(2016, 9, 24), D(2026, 9, 22))
        # now it covers the start: a rerun skips what is covered
        again = await _ingestor(db_session, v, tmp_path).run(early)
        assert [r.status for r in again.results] == ["SKIPPED", "COMPLETE"]

    async def test_window_after_a_hole_never_moves_the_checkpoint(self, db_session, tmp_path,
                                                                 frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        await _ingestor(db_session, v, tmp_path).run(
            plan_jobs([R], ["5m"], D(2026, 7, 1), D(2026, 7, 31))[0])
        assert (await self._cp(db_session, R, "5m")).through == D(2026, 7, 31)
        # September only: August is a hole; its bars are stored, the checkpoint stays
        rep = await _ingestor(db_session, v, tmp_path).run(
            plan_jobs([R], ["5m"], D(2026, 9, 1), D(2026, 9, 23))[0])
        (res,) = rep.results
        assert res.status == "COMPLETE" and res.inserted > 0
        assert "not contiguous" in res.coverage["checkpoint"]["change"]
        cp = await self._cp(db_session, R, "5m")
        assert (cp.covered_from, cp.through) == (D(2026, 7, 1), D(2026, 7, 31))
        # so a later July->September run still fetches August
        rep = await _ingestor(db_session, v, tmp_path).run(
            plan_jobs([R], ["5m"], D(2026, 7, 1), D(2026, 9, 23))[0])
        assert [r.status for r in rep.results] == ["SKIPPED", "COMPLETE", "COMPLETE"]
        cp = await self._cp(db_session, R, "5m")
        assert (cp.covered_from, cp.through) == (D(2026, 7, 1), D(2026, 9, 22))

    async def test_legacy_checkpoint_without_covered_from_is_not_trusted(self, db_session,
                                                                        tmp_path, frozen):
        await _seed_instruments(db_session)
        frozen(AFTER_CLOSE)
        v = Vendor()
        await _ingestor(db_session, v, tmp_path).run(_daily_jobs())
        await db_session.execute(text(
            "update ingest_run set request_params = request_params #- '{outcome,checkpoint}' "
            "where stream = :s"), {"s": f"ohlcv.1d.{R}"})
        cp = await self._cp(db_session, R)
        assert cp.through == D(2026, 9, 22) and cp.covered_from is None
        v.calls.clear()
        rep = await _ingestor(db_session, v, tmp_path).run(_daily_jobs())
        assert rep.results[0].status == "COMPLETE" and len(v.calls) == 1
        assert (await self._cp(db_session, R)).covered_from == D(2026, 9, 8)


def test_checkpoint_advance_rules():
    w = C.Window
    cp = IC.Checkpoint()
    cp, why = cp.advance(w(D(2026, 7, 1), D(2026, 7, 31)), D(2026, 7, 31))
    assert (cp.covered_from, cp.through, why) == (D(2026, 7, 1), D(2026, 7, 31), "started")
    cp2, why = cp.advance(w(D(2026, 8, 1), D(2026, 8, 31)), D(2026, 8, 20))
    assert (cp2.through, why) == (D(2026, 8, 20), "advanced")
    cp3, why = cp2.advance(w(D(2026, 9, 1), D(2026, 9, 30)), D(2026, 9, 22))
    assert cp3 == cp2 and "not contiguous" in why          # 08-21..08-31 still pending
    cp4, why = cp.advance(w(D(2026, 8, 1), D(2026, 8, 31)), D(2026, 7, 31))
    assert cp4 == cp and why == "nothing complete in the window"
    assert IC.Checkpoint(D(2026, 7, 1), D(2026, 9, 1)).covers_start(D(2026, 7, 1))
    assert not IC.Checkpoint(D(2026, 7, 2), D(2026, 9, 1)).covers_start(D(2026, 7, 1))
    assert not IC.Checkpoint(None, D(2026, 9, 1)).covers_start(D(2020, 1, 1))


async def _anoms(s, run_id):
    return [{"kind": r.kind, "detail": r.detail} for r in await _q(
        s, "select kind, detail from ingest_anomaly where run_id=:r", r=run_id)]


def test_plan_jobs_reports_what_the_vendor_cannot_serve():
    jobs, unavailable = plan_jobs([R, R], ["1m"], D(2021, 12, 1), D(2022, 2, 28))
    assert [(j.window.from_date, j.window.to_date) for j in jobs] == [
        (D(2022, 1, 1), D(2022, 1, 31)), (D(2022, 2, 1), D(2022, 2, 28))]
    (u,) = unavailable
    assert u.outcome is C.WindowOutcome.BEFORE_AVAILABILITY and u.window.to_date == D(2021, 12, 31)


def test_now_is_frozen_for_fetched_at():
    clock.freeze(AFTER_CLOSE)
    try:
        assert now() == AFTER_CLOSE.astimezone(UTC)
    finally:
        clock.unfreeze()
