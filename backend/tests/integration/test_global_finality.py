"""Global-market finality (phase 5): a first observation is stored but only
exposed once final; revisions and placeholders are never exposed; vendor
absence is recorded, not failed. Real N225 / USDINR / HSI evidence."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.contracts import candles as C
from app.core import clock
from app.core.clock import IST
from app.ingest.candles import CandleJob
from app.ingest.global_contract import measure
from tests.integration.test_candle_ingest import _ingestor

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
EV = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "vendor_evidence"
D = _dt.date
N225 = "GLOBAL_INDEX|^N225"


def _candles(name):
    return json.loads((EV / f"{name}.json").read_text())["data"]["candles"]


class TestMeasuredContract:
    def test_usdinr_labels_are_a_shifted_calendar(self):
        bars = sorted((D.fromisoformat(c[0][:10]), c[1], c[2], c[3], c[4], c[5])
                      for c in _candles("USDINR_global_live"))
        m = measure(bars * 1, revisions=0, through=D(2026, 9, 24))
        assert m["weekday_profile"]["7"] >= 1                 # a Sunday label (09-20)
        assert "shifted calendar" in m["label_semantics"]

    def test_placeholder_and_same_open_are_counted_not_guessed(self):
        bars = [(D(2026, 9, 21), 10, 11, 9, 10.5, 5), (D(2026, 9, 22), 10.5, 10.5, 10.5,
                10.5, 0),                                    # flat repeat: placeholder
                (D(2026, 9, 23), 10.5, 11, 10, 10.8, 7)]     # same open: flagged only
        m = measure(bars, revisions=0, through=D(2026, 9, 23))
        assert m["placeholder_flat_repeat"] == 1 and m["same_open_as_previous"] == 1


async def _seed_global(s, key=N225):
    rid, sha = uuid.uuid4(), uuid.uuid4().hex * 2
    t0 = _dt.datetime(2026, 9, 20, 12, 0, tzinfo=IST)
    await s.execute(text("""
        insert into ingest_run (run_id, source, stream, vendor_endpoint, request_params,
          code_git_sha, config_sha256, argv, operator, mode, status, authz_token_sha256,
          started_at, finished_at, rows_written) values (:r,'UPSTOX_ASSETS','seed','t','{}',
          't',:c,ARRAY['pytest'],'pytest','COMMIT','COMPLETE',:a,:n,:n,0)"""),
        {"r": rid, "c": "c" * 64, "a": "a" * 64, "n": t0})
    await s.execute(text("""
        insert into raw_payload (payload_sha256, source, vendor_endpoint, request_params,
          byte_size, content_type, storage_uri, first_seen_run, fetched_at)
        values (:s,'UPSTOX_ASSETS','t','{}',1,'application/json','/dev/null',:r,:n)"""),
        {"s": sha, "r": rid, "n": t0})
    await s.execute(text("""
        insert into instrument (instrument_key, segment, exchange, trading_symbol, name,
          valid_from, source, run_id, payload_sha256, fetched_at, knowable_at,
          knowable_at_basis) values (:k,'GLOBAL_INDEX','GLOBAL','^N225','Nikkei 225',
          '2026-09-20','UPSTOX_ASSETS',:r,:s,:n,:n,'test')"""), {"k": key, "r": rid, "s": sha,
                                                              "n": t0})


class Served:
    def __init__(self):
        self.body = b""

    def __call__(self, req):
        return httpx.Response(200, content=self.body)


async def _fetch(s, served, tmp_path, name, at, frm=D(2026, 9, 18), to=D(2026, 9, 25)):
    clock.freeze(at)
    served.body = (EV / f"{name}.json").read_bytes()
    rep = await _ingestor(s, served, tmp_path).run([CandleJob(N225, "1d", C.Window(frm, to))],
                                                   resume=False)
    return rep.results[0]


async def _finality(s, day):
    return (await s.execute(text("""select finality, confirmed_at from global_bar_finality
        where instrument_key = :k and session_date = :d"""), {"k": N225, "d": day})).one()


async def test_n225_revision_is_withheld_and_confirmation_needs_time(db_session, tmp_path):
    s, served = db_session, Served()
    try:
        await _seed_global(s)
        # 1. 2026-09-25 13:41 IST: the first observation (label 09-24 as served then)
        # replayed with the window it was fetched with (2026-09-17 .. 2026-09-24)
        r1 = await _fetch(s, served, tmp_path, "N225_global_archived_20260925_1341",
                          _dt.datetime(2026, 9, 25, 13, 41, tzinfo=IST), frm=D(2026, 9, 17),
                          to=D(2026, 9, 24))
        assert r1.status == "COMPLETE" and r1.inserted >= 1
        assert (await _finality(s, D(2026, 9, 24)))[0] == "UNCONFIRMED"
        # 2. 14:11 IST: the vendor now serves a different 09-24 (open changed)
        r2 = await _fetch(s, served, tmp_path, "N225_global_live",
                          _dt.datetime(2026, 9, 25, 14, 11, tzinfo=IST))
        assert r2.status == "COMPLETE"                       # was a DUPLICATE_KEY FAIL
        assert r2.observations.get("GLOBAL_REVISION") == 1
        assert (await _finality(s, D(2026, 9, 24)))[0] == "REVISED"
        exposed = (await s.execute(text("select count(*) from canon_global_bar where "
                                        "instrument_key=:k and label_date='2026-09-24'"),
                                   {"k": N225})).scalar()
        assert exposed == 0                                  # never exposed
        # 09-22 was re-observed unchanged only 30 min later: not yet final
        assert (await _finality(s, D(2026, 9, 22)))[0] == "UNCONFIRMED"
        # 3. 21:10 IST: unchanged again, >= 6 h after the first observation -> final
        r3 = await _fetch(s, served, tmp_path, "N225_global_live",
                          _dt.datetime(2026, 9, 25, 21, 10, tzinfo=IST))
        assert r3.observations.get("REOBSERVED", 0) >= 1
        fin, confirmed_at = await _finality(s, D(2026, 9, 22))
        assert fin == "CONFIRMED" and confirmed_at.astimezone(IST).hour == 21
        row = (await s.execute(text("select knowable_at, fetched_at, finality from "
                                    "canon_global_bar where instrument_key=:k and "
                                    "label_date='2026-09-22'"), {"k": N225})).one()
        assert row.finality == "CONFIRMED" and row.knowable_at == confirmed_at
        assert row.knowable_at <= row.fetched_at             # PIT contract kept
        # the 09-23 holiday placeholder (flat, = previous close, no volume)
        assert (await _finality(s, D(2026, 9, 23)))[0] == "PLACEHOLDER"
        # vendor-absent weekdays inside the fetched windows, never failures
        absent = {r[0] for r in (await s.execute(text(
            "select absent_date from canon_global_vendor_absent where instrument_key=:k"),
            {"k": N225})).all()}
        assert D(2026, 9, 18) in absent and D(2026, 9, 21) in absent
    finally:
        clock.unfreeze()


async def test_a_genuine_flat_looking_day_is_not_a_placeholder(db_session, tmp_path):
    s, served = db_session, Served()
    try:
        await _seed_global(s)
        body = {"status": "success", "data": {"candles": [
            ["2026-09-15T00:00:00+05:30", 100.0, 101.0, 99.0, 100.0, 0, 0],
            ["2026-09-14T00:00:00+05:30", 99.0, 100.5, 98.0, 99.5, 0, 0]]}}
        (tmp_path / "flat.json").write_text(json.dumps(body))
        clock.freeze(_dt.datetime(2026, 9, 25, 13, 0, tzinfo=IST))
        served.body = json.dumps(body).encode()
        await _ingestor(s, served, tmp_path).run(
            [CandleJob(N225, "1d", C.Window(D(2026, 9, 14), D(2026, 9, 15)))])
        # same open as nothing, a real range, just no volume: stays visible (by age)
        assert (await _finality(s, D(2026, 9, 15)))[0] == "CONFIRMED_BY_AGE"
    finally:
        clock.unfreeze()
