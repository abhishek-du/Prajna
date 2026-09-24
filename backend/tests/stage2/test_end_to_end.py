"""End to end: the real Stage 1 candle ingest (real archived Upstox responses)
-> Stage 2 processing -> the point-in-time read API."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text

from app.canon import pit
from app.canon.process import process
from app.core import clock
from tests.integration.test_candle_ingest import (
    AFTER_CLOSE,
    SME,
    R,
    Vendor,
    _daily_jobs,
    _ingestor,
    _seed_instruments,
)

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
D = _dt.date


async def test_stage1_ingest_is_processed_and_served_point_in_time(db_session, tmp_path):
    s = db_session
    clock.freeze(AFTER_CLOSE)
    try:
        await _seed_instruments(s)
        from tests.integration.test_institutional_ingest import _seed_calendar
        await _seed_calendar(s, D(2026, 9, 1), D(2026, 9, 30))
        await s.execute(text("update instrument set isin = split_part(instrument_key, '|', 2),"
                             " instrument_type = 'EQ'"))
        rep1 = await _ingestor(s, Vendor(), tmp_path).run(_daily_jobs())
        assert rep1.results[0].inserted == 10
        p1 = await process(s, commit=True, token=TOKEN)
        assert p1.status == "COMPLETE" and p1.instruments["included"] == 2
        # Stage 3 view: before the fetch nothing, after it the 10 real bars
        assert await pit.bars(s, R, "1d", AFTER_CLOSE) == []
        got = await pit.bars(s, R, "1d", AFTER_CLOSE + _dt.timedelta(seconds=1))
        assert len(got) == 10 and got[-1]["market_date"] == D(2026, 9, 22)
        stored = (await s.execute(text(
            "select knowable_at, payload_sha256 from ohlcv_bar where instrument_key = :k "
            "order by session_date desc limit 1"), {"k": R})).one()
        assert (got[-1]["knowable_at"], got[-1]["payload_sha256"]) == tuple(stored)
        # a second Stage 1 run of the same data, then Stage 2 again: nothing changes
        await _ingestor(s, Vendor(), tmp_path).run(_daily_jobs())
        p2 = await process(s, commit=True, token=TOKEN)
        assert p2.status == "COMPLETE"
        assert all(v.get("pairs_changed", 0) == 0 for v in p2.coverage.values())
        assert p2.instruments["updated"] == 0 and p2.instruments["inserted"] == 0
        # the calendar covers September only: coverage names those sessions, and
        # the quality gate reports the rest of the depth instead of passing silently
        assert {r["state"] for r in await pit.current_coverage(s, SME, "1d")} <= {
            "DATA", "EMPTY", "PENDING_BACKFILL"}
        assert {r["state"] for r in await pit.coverage(s, SME, "1d", AFTER_CLOSE)} <= {
            "EMPTY", "PENDING_BACKFILL"}                  # the bars were not knowable yet
        from app.canon.quality import run_gates
        gates = {g["gate"]: g for g in (await run_gates(s))["gates"]}
        assert gates["calendar_gaps_in_depth"]["status"] == "FAIL"
    finally:
        clock.unfreeze()
