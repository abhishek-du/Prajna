"""The acceptance harness. It must never certify B7/B8 from synthetic data."""

from __future__ import annotations

import json
import os

import pytest

from app.acceptance.preopen_day import PRODUCTION_FEED_HOST, evaluate
from app.contracts.universe import plan_shards
from app.core.clock import now_ist
from app.ingest.preopen import replay_session
from app.sources.upstox_preopen_session import PreopenCaptureSession
from app.sources.upstox_preopen_ws import RecorderConfig
from app.storage.frame_archive import FrameArchiveWriter
from app.vendor.upstox.proto import PROTO_SHA256
from tests.integration.test_preopen_replay import _seed_session
from tests.support.fake_upstox_ws import FakeUpstoxFeed
from tests.support.upstox_frames import (
    NIFTYBEES,
    RELIANCE,
    SESSION,
    frame,
    ist,
    market_ff,
    status_frame,
)

pytestmark = [pytest.mark.db, pytest.mark.integration]
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]


def _by_id(rep):
    return {c.id: c for c in rep.checks}


async def test_a_fake_capture_never_resolves_b7_b8(db_session, tmp_path):
    today = now_ist().date()
    await _seed_session(db_session, today)
    plan = plan_shards([RELIANCE, NIFTYBEES], per_connection=1, max_connections=2)
    cfg = RecorderConfig(cap=1, stale_after=2.0, backoff_initial=0.01, max_reconnects=2,
                         open_timeout=2.0, proxy=None, heartbeat_every=0.05, ping_interval=0.05)
    async with FakeUpstoxFeed([("stream", 10**6)], interval=0.02) as feed:
        n = {"i": 0}

        async def auth():
            n["i"] += 1
            return feed.url(n["i"])
        s = PreopenCaptureSession(tmp_path, session_date=today, plan=plan, authorize=auth,
                                  config=cfg, max_frames_per_connection=20)
        await s.run()
    assert (await replay_session(db_session, s.manifest_path, commit=True,
                                 token=TOKEN)).status == "COMPLETE"

    rep = await evaluate(db_session, s.manifest_path)
    c = _by_id(rep)
    for cid in ("A1", "A2", "A3", "A4", "A5", "A6", "A8", "B1", "B2", "B3", "B4", "B5"):
        assert c[cid].status == "PASS", (cid, c[cid].evidence)
    assert rep.real_market_data is False
    assert rep.b7["status"] == rep.b8["status"] == "UNRESOLVED"


def _real_looking_session(tmp_path) -> tuple:
    """Grading-logic fixture: an archive whose EVENTS claim the production host
    and whose frames sit inside the pre-open window. It exists to test the
    arithmetic; it is not, and is never reported as, market evidence."""
    header = {"session_date": SESSION.isoformat(), "proto_sha256": PROTO_SHA256,
              "session_id": "f" * 32, "shard_index": 0, "shard_count": 1}
    w = FrameArchiveWriter(tmp_path / "x_c0of1.frames.gz", header)
    w.append_event("authorized", ist(8, 55),
                   endpoint=f"wss://{PRODUCTION_FEED_HOST}/market-data-feeder/v3/x")
    w.append_event("connected", ist(8, 55))
    w.append_frame(status_frame(ist(9, 0), {"NSE_EQ": ("PRE_OPEN_START", ist(9, 0))}),
                   ist(9, 0, 1))
    w.append_event("market_info", ist(9, 0, 1))
    w.append_frame(frame({RELIANCE: market_ff(iep=2450.0, iiq_total=500, iiq_m=200),
                          NIFTYBEES: market_ff(iep=0.0, ieq=0, iiq_total=0, iiq_m=0,
                                               cas=False)}, ist(9, 3)), ist(9, 3, 0, 40))
    w.append_event("subscription_confirmed", ist(9, 3, 0, 40))
    w.append_event("heartbeat", ist(9, 4), ping_rtt_ms=12.5)
    w.append_frame(status_frame(ist(9, 12), {"NSE_EQ": ("PRE_OPEN_END", ist(9, 12))}),
                   ist(9, 12, 1))
    w.close()
    manifest = tmp_path / "x.session.json"
    manifest.write_text(json.dumps({
        "session_id": "f" * 32, "session_date": SESSION.isoformat(), "status": "complete",
        "universe": {"count": 2, "per_connection": 2000, "excluded_by_capacity": []},
        "coverage": {"subscribed": 2, "seen": 2, "never_seen": 0, "never_seen_keys": []},
        "shards": [{"index": 0, "archive": str(w.path), "keys": 2, "error": None}],
    }))
    return manifest


async def test_grading_logic_on_in_window_production_host_evidence(db_session, tmp_path):
    await _seed_session(db_session)
    manifest = _real_looking_session(tmp_path)
    assert (await replay_session(db_session, manifest, commit=True,
                                 token=TOKEN)).status == "COMPLETE"
    rep = await evaluate(db_session, manifest)
    c = _by_id(rep)
    assert rep.real_market_data is True
    assert rep.preopen_window_ist[2] == "vendor transitions"
    assert c["C1"].status == "PASS"
    assert c["C2"].evidence["instruments_with_iep"] == 1
    assert rep.b8["status"] == "RESOLVED"
    assert rep.b8["observation"]["non_cas_with_iep"] == 0
    assert rep.b8["observation"]["cas_eligible_with_iep"] == 1
    assert rep.b7["status"] == "OBSERVED"
    assert rep.b7["observation"]["instruments_with_nonzero_iiq_m"] == 1


async def test_ticks_outside_the_window_do_not_resolve_anything(db_session, tmp_path):
    await _seed_session(db_session)
    manifest = _real_looking_session(tmp_path)
    await replay_session(db_session, manifest, commit=True, token=TOKEN)
    # Pretend the calendar said pre-open was later: no ticks fall inside.
    from sqlalchemy import text
    await db_session.execute(text(
        "delete from preopen_session_status"))
    await db_session.execute(text(
        "update trading_session set preopen_start_ist='10:00', preopen_end_ist='10:15'"))
    rep = await evaluate(db_session, manifest)
    assert rep.preopen_window_ist[2] == "trading_session (derived)"
    assert rep.b8["status"] == "UNRESOLVED" and "window" in rep.b8["reason"]
