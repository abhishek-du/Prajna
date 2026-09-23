"""WebSocket -> archive -> replay -> database, with nothing lost in between.

The recorder's lifecycle evidence (cap exclusions, disconnects) must surface
as ingest_anomaly rows, not only as events inside a file.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.core.clock import now_ist
from app.ingest.preopen import replay_archive
from app.sources.upstox_preopen_ws import (
    PreopenRecorder,
    RecorderConfig,
    open_capture_archive,
    plan_subscription,
)
from tests.integration.test_preopen_replay import _seed_session
from tests.support.fake_upstox_ws import FakeUpstoxFeed
from tests.support.upstox_frames import NIFTYBEES, RELIANCE

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def test_capture_then_replay(db_session, tmp_path):
    today = now_ist().date()
    await _seed_session(db_session, today)
    cfg = RecorderConfig(cap=1, stale_after=2.0, backoff_initial=0.01, backoff_max=0.05,
                         max_reconnects=3, open_timeout=2.0, proxy=None)
    plan = plan_subscription([NIFTYBEES, RELIANCE], cfg.cap)
    writer = open_capture_archive(tmp_path, session_date=today, plan=plan, config=cfg)

    async with FakeUpstoxFeed([("drop", 2), ("stream", 100)]) as feed:
        calls = 0

        async def auth():
            nonlocal calls
            calls += 1
            return feed.url(calls)

        summary = await PreopenRecorder(writer, auth, plan, cfg, max_frames=9).run()

    rep = await replay_archive(db_session, writer.path, commit=True,
                               token=os.environ["PRAJNA_WRITE_TOKEN"])
    assert rep.status == "COMPLETE", rep.anomalies
    keys = (await db_session.execute(text(
        "select distinct instrument_key from preopen_tick"))).scalars().all()
    assert keys == [RELIANCE]                        # the cap kept the first sorted key
    assert rep.ticks_inserted == summary.frames - summary.connections  # minus market_info

    kinds = {(a["kind"], a["subject"]) for a in rep.anomalies}
    assert ("COVERAGE_CAP", "recorder.coverage_cap") in kinds
    assert ("GAP", "recorder.disconnected") in kinds
    cap = next(a for a in rep.anomalies if a["kind"] == "COVERAGE_CAP")
    assert cap["detail"]["dropped_keys"] == [NIFTYBEES]

    stored = (await db_session.execute(text(
        "select kind from ingest_anomaly where run_id=:r"), {"r": rep.run_id})).scalars().all()
    assert "COVERAGE_CAP" in stored and "GAP" in stored
