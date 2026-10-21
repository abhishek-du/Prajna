"""Stage 1 gate, incremental ohlcv_bar checks (GATE-INCR; app/acceptance/ohlcv_scan.py):
checkpoint + increment == a full scan, a violation in a later run is counted, a FULL
checkpoint verifies the increments, and ohlcv_bar is append-only."""

from __future__ import annotations

import datetime as _dt
import os

import pytest
from sqlalchemy import text

from app.acceptance import ohlcv_scan as OS
from app.core import clock
from tests.support import stage3_seed as W
from tests.support.stage2_seed import _payload, _run

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]


async def _later_run(s, ids, *, basis="t", finished=None, n=3):
    rid = await _run(s, "ohlcv.1d.late", finished=finished or W.NOW + _dt.timedelta(hours=2))
    sha = await _payload(s, rid)
    for j in range(n):
        d = _dt.date(2026, 9, 30)
        await s.execute(text("""insert into ohlcv_bar (instrument_id, timeframe, session_date,
            bar_start_utc, source, instrument_key, open, high, low, close, volume, vendor_ts_raw,
            run_id, payload_sha256, fetched_at, knowable_at, knowable_at_verified,
            knowable_at_basis) values (:i, '1d', :d, :b, :src, :k, 10, 11, 9, 10, 5, 'x', :r,
            :h, :f, :f, false, :basis)"""),
            {"i": ids[W.STOCKS[j]], "d": d, "b": W.ist(2026, 9, 30) + _dt.timedelta(minutes=j),
             "src": f"TEST{j}", "k": W.STOCKS[j], "r": rid, "h": sha,
             "f": W.ist(2026, 10, 1, 16), "basis": basis})
    return rid


async def test_checkpoint_plus_increment_equals_a_full_scan(db_session):
    s = db_session
    clock.freeze(W.NOW)
    try:
        ids = await W.seed(s)
        full0 = await OS.scan(s)
        cp = await OS.checkpoint(s, full=True, commit=True, token=TOKEN)
        assert cp["consistent"] is None and cp["counts"] == full0["counts"]
        got = await OS.totals(s)
        assert got["method"].startswith("CHECKPOINT FULL")
        assert {k: got[k] for k in ("counts", "bars")} == full0
        await _later_run(s, ids, basis="")                    # 3 bars without a basis
        full1 = await OS.scan(s)
        got = await OS.totals(s)
        assert {k: got[k] for k in ("counts", "bars")} == full1
        assert got["counts"]["no_basis"] == full0["counts"]["no_basis"] + 3
        assert got["counts"]["rows"] == full0["counts"]["rows"] + 3
        inc = await OS.checkpoint(s, full=False, commit=True, token=TOKEN)
        assert inc["counts"] == full1["counts"]
        chk = await OS.checkpoint(s, full=True, commit=True, token=TOKEN)
        assert chk["consistent"] is True
    finally:
        clock.unfreeze()


async def test_a_running_run_is_counted_live_but_not_checkpointed(db_session):
    s = db_session
    clock.freeze(W.NOW)
    try:
        ids = await W.seed(s)
        await OS.checkpoint(s, full=True, commit=True, token=TOKEN)
        rid = await _later_run(s, ids)
        await s.execute(text("update ingest_run set finished_at = null, status = 'RUNNING' "
                             "where run_id = :r"), {"r": rid})
        got = await OS.totals(s)
        assert {k: got[k] for k in ("counts", "bars")} == await OS.scan(s)
        assert got["counts"]["bad_run"] >= 3                  # rows of a run not COMPLETE
    finally:
        clock.unfreeze()


async def test_ohlcv_bar_is_append_only(db_session):
    s = db_session
    clock.freeze(W.NOW)
    try:
        await W.seed(s)
        with pytest.raises(Exception, match="append-only"):
            await s.execute(text("update ohlcv_bar set close = close + 1"))
    finally:
        clock.unfreeze()


async def test_archive_checkpoint_keeps_the_full_result(db_session):
    """The raw archive (T): a checkpoint's mismatches stay counted, a payload of a later run
    is hashed again, and a missing file is found without a rehash."""
    from app.acceptance import stage1 as S1
    s = db_session
    clock.freeze(W.NOW)
    try:
        ids = await W.seed(s)
        full = await S1.verify_archive(s)
        cp = await OS.checkpoint(s, full=True, commit=True, token=TOKEN)
        assert cp["archive"]["mismatched_total"] == full["mismatched"]
        a = await OS.latest(s, "raw_archive")
        inc = await S1.verify_archive(s, since=a["through"])
        assert inc["file_payloads_verified"] + inc["mismatched"] == 0        # nothing new
        assert inc["missing"] == full["missing"]
        await _later_run(s, ids)                    # a new payload (seeded at /dev/null)
        inc = await S1.verify_archive(s, since=a["through"])
        assert inc["file_payloads_verified"] + inc["mismatched"] == 1
        assert inc["mismatched"] + a["counts"]["mismatched"] == (await S1.verify_archive(s))[
            "mismatched"]
    finally:
        clock.unfreeze()
