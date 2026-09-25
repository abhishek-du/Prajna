"""The first observation is immutable; later vendor observations are
classified (phase 6). Replays the real CHAVDA incident through the real
CandleIngestor: raw 1D stored on 2026-09-23, 1:1 bonus ex 2026-09-24, the
vendor's re-adjusted history fetched 2026-09-25."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts import candles as C
from app.core import clock
from app.core.clock import IST
from app.ingest.candles import CandleJob
from tests.integration.test_candle_ingest import _ingestor

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
EV = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "vendor_evidence"
KEY = "NSE_EQ|INE0PT101017"                                   # CHAVDA, series SM, tick 0.05
D = _dt.date


def _window_body(name: str, frm: D, to: D) -> bytes:
    b = json.loads((EV / f"{name}.json").read_text())
    b["data"]["candles"] = [c for c in b["data"]["candles"]
                            if frm <= D.fromisoformat(c[0][:10]) <= to]
    return json.dumps(b).encode()


class Served:
    def __init__(self):
        self.body = b""

    def __call__(self, req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=self.body)


async def _seed(s):
    rid, sha = uuid.uuid4(), uuid.uuid4().hex * 2
    now = _dt.datetime(2026, 9, 23, 12, 0, tzinfo=IST)
    await s.execute(text("""
        insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
          code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
          started_at, finished_at, rows_written) values (:r,'UPSTOX_ASSETS','seed','t','{}',
          't',:c,ARRAY['pytest'],'pytest','COMMIT','COMPLETE',:a,:n,:n,0)"""),
        {"r": rid, "c": "c" * 64, "a": "a" * 64, "n": now})
    await s.execute(text("""
        insert into raw_payload (payload_sha256, source, vendor_endpoint, request_params,
          byte_size, content_type, storage_uri, first_seen_run, fetched_at)
        values (:s,'UPSTOX_ASSETS','t','{}',1,'application/json','/dev/null',:r,:n)"""),
        {"s": sha, "r": rid, "n": now})
    await s.execute(text("""
        insert into instrument (instrument_key, segment, exchange, trading_symbol, isin,
          instrument_type, tick_size, valid_from, source, run_id, payload_sha256, fetched_at,
          knowable_at, knowable_at_basis) values (:k,'NSE_EQ','NSE','CHAVDA','INE0PT101017',
          'SM',5.0,'2026-09-23','UPSTOX_ASSETS',:r,:s,:n,:n,'test')"""),
        {"k": KEY, "r": rid, "s": sha, "n": now})
    return rid, sha


async def _bonus(s, rid, sha):
    """The vendor's corporate action, as the weekly sweep stores it."""
    await s.execute(text("""
        insert into corporate_action (isin, instrument_key, trading_symbol, action_type,
          ex_date, record_date, announcement_date, ratio_from, ratio_to, content_sha256,
          vendor_payload, source, run_id, payload_sha256, fetched_at, knowable_at,
          knowable_at_verified, knowable_at_basis)
        values ('INE0PT101017', :k, 'CHAVDA', 'BONUS', '2026-09-24', '2026-09-24',
          '2026-08-06', 1, 1, :c, cast(:p as jsonb), 'UPSTOX_REST_V2', :r, :h,
          '2026-09-24 09:24+00', '2026-08-06 18:29:59.999+00', false, 'KN-CA')"""),
        {"k": KEY, "c": "b" * 64, "r": rid, "h": sha,
         "p": json.dumps({"name": "Bonus", "ratio": "1:1"})})


async def _run(s, served, tmp_path, name, frm, to, at, resume=True):
    """resume=False re-fetches windows the checkpoint already covers (an explicit
    re-verification); resume=True is the scheduled behaviour."""
    clock.freeze(at)
    served.body = _window_body(name, frm, to)
    rep = await _ingestor(s, served, tmp_path).run([CandleJob(KEY, "1d", C.Window(frm, to))],
                                                   resume=resume)
    return rep.results[0]


async def test_chavda_bonus_is_classified_not_failed(db_session, tmp_path):
    s, served = db_session, Served()
    try:
        rid, sha = await _seed(s)
        # 1. 2026-09-23 evening: the raw history (before the bonus went ex)
        r1 = await _run(s, served, tmp_path, "chavda_1d_archived_20260923", D(2023, 9, 25),
                        D(2026, 9, 22), _dt.datetime(2026, 9, 23, 19, 55, tzinfo=IST))
        assert r1.status == "COMPLETE" and r1.inserted == 740
        await _bonus(s, rid, sha)
        # 2. 2026-09-25 morning: the daily window, now vendor-adjusted
        r2 = await _run(s, served, tmp_path, "chavda_1d_live", D(2026, 9, 17), D(2026, 9, 24),
                        _dt.datetime(2026, 9, 25, 8, 0, tzinfo=IST))
        assert r2.status == "COMPLETE", r2.error                  # was FAILED before phase 6
        assert r2.observations == {"CA_ADJUSTMENT": 4} and r2.inserted == 2
        # the first observation is untouched
        close = (await s.execute(text("select close from ohlcv_bar where instrument_key=:k "
                                      "and session_date='2026-09-17'"), {"k": KEY})).scalar()
        assert float(close) == 120.5
        obs = (await s.execute(text("select classification, close, explained_by from "
                                    "ohlcv_observation where instrument_key=:k and "
                                    "session_date='2026-09-17'"), {"k": KEY})).one()
        assert obs.classification == "CA_ADJUSTMENT" and float(obs.close) == 60.25
        assert obs.explained_by["factor"] == "2"
        # 3. a full re-fetch of the adjusted history: 740 explained, 0 failures
        r3 = await _run(s, served, tmp_path, "chavda_1d_live", D(2023, 9, 25), D(2026, 9, 24),
                        _dt.datetime(2026, 9, 25, 9, 0, tzinfo=IST), resume=False)
        assert r3.status == "COMPLETE" and r3.observations == {"CA_ADJUSTMENT": 740}
        bases = dict((await s.execute(text("""select b.price_basis, count(*) from
            ohlcv_payload_basis b join raw_payload p using (payload_sha256)
            where p.first_seen_run = any(:r) group by 1"""),
            {"r": [r1.run_id, r2.run_id, r3.run_id]})).all())
        assert bases == {"VENDOR_ADJUSTED": 3}
    finally:
        clock.unfreeze()


async def test_unexplained_revision_fails_closed_and_keeps_the_payload(db_session, tmp_path):
    s, served = db_session, Served()
    try:
        await _seed(s)
        await _run(s, served, tmp_path, "chavda_1d_archived_20260923", D(2026, 9, 1),
                   D(2026, 9, 22), _dt.datetime(2026, 9, 23, 19, 55, tzinfo=IST))
        b = json.loads(_window_body("chavda_1d_archived_20260923", D(2026, 9, 1),
                                    D(2026, 9, 22)))
        b["data"]["candles"][0][4] = 141.0     # inside [low, high]: sane, but no rule explains it
        clock.freeze(_dt.datetime(2026, 9, 24, 8, 0, tzinfo=IST))
        served.body = json.dumps(b).encode()
        rep = await _ingestor(s, served, tmp_path).run(
            [CandleJob(KEY, "1d", C.Window(D(2026, 9, 1), D(2026, 9, 22)))], resume=False)
        res = rep.results[0]
        assert res.status == "FAILED"
        kinds = (await s.execute(text("select kind, detail->>'classification' from "
                                      "ingest_anomaly where run_id=:r"),
                                 {"r": res.run_id})).all()
        assert ("DUPLICATE_KEY", "UNEXPLAINED") in kinds
        kept = (await s.execute(text("select count(*) from raw_payload where first_seen_run=:r"),
                                {"r": res.run_id})).scalar()
        assert kept == 1                         # the failed run's archive stays indexed
        assert (await s.execute(text("select count(*) from ohlcv_observation"))).scalar() == 0
    finally:
        clock.unfreeze()


async def test_observations_are_append_only(db_session, tmp_path):
    s, served = db_session, Served()
    try:
        rid, sha = await _seed(s)
        await _run(s, served, tmp_path, "chavda_1d_archived_20260923", D(2026, 9, 17),
                   D(2026, 9, 22), _dt.datetime(2026, 9, 23, 19, 55, tzinfo=IST))
        await _bonus(s, rid, sha)
        await _run(s, served, tmp_path, "chavda_1d_live", D(2026, 9, 17), D(2026, 9, 22),
                   _dt.datetime(2026, 9, 25, 8, 0, tzinfo=IST), resume=False)
        assert (await s.execute(text("select count(*) from ohlcv_observation"))).scalar() == 4
        for sql in ("update ohlcv_observation set close = 1", "delete from ohlcv_observation"):
            with pytest.raises(DBAPIError, match="append-only"):
                async with s.begin_nested():
                    await s.execute(text(sql))
    finally:
        clock.unfreeze()
