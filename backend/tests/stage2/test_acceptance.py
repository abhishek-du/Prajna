"""The Stage 2 gate runs read-only and is never PASS without real evidence."""

from __future__ import annotations

import os

import pytest

from app.acceptance import stage2 as S2
from app.canon.process import process
from app.core import clock
from tests.support import stage2_seed as SEED

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def test_empty_database_is_not_passed(db_session):
    rep = await S2.evaluate(db_session, tests=None)
    by = {c["id"]: c for c in rep["criteria"]}
    assert sorted(by) == [chr(c) for c in range(ord("A"), ord("Q"))]
    assert rep["overall"] == "NOT PASSED"
    assert by["A"]["status"] == "FAIL"          # nothing processed
    assert by["M"]["status"] == "PENDING"       # no real incremental run
    assert by["P"]["status"] == "PENDING"       # tests not run
    assert by["L"]["status"] == "PENDING"       # its only evidence is the test suite
    md = S2.to_markdown(rep, {"x": "y"})
    assert "## Overall: **NOT PASSED**" in md and "Stage 3 stays locked" in md


async def test_pending_never_unlocks_and_probes_are_reproducible(db_session):
    """Without --run-tests the gate cannot be PASS, whatever else passes; the
    random samples of E and O record their seed, and the same seed gives the
    same sample."""
    s = db_session
    clock.freeze(SEED.NOW)
    try:
        await SEED.seed(s)
        await process(s, commit=True, token=os.environ["PRAJNA_WRITE_TOKEN"])
        rep = await S2.evaluate(s, tests=None, seed=7)
        by = {c["id"]: c for c in rep["criteria"]}
        assert by["P"]["status"] == "PENDING" and by["L"]["status"] == "PENDING"
        assert rep["overall"] == "NOT PASSED"
        o = by["O"]["evidence"]
        assert o["seed"] == 7 and o["probed"] >= 1 and o["ok"] == o["probed"]
        assert "NSE_EQ|INE002A01018" in o["probes"]
        e = by["E"]["evidence"]["real_db_probes"]
        assert e["seed"] == 7 and e["coverage_point_in_time"] == e["instruments_probed"] > 0
        again = await S2.evaluate(s, tests=None, seed=7)
        assert {c["id"]: c["evidence"] for c in again["criteria"]}["O"] == by["O"]["evidence"]
        ran = await S2.evaluate(s, tests={"exit": 0, "summary": "1 passed"}, seed=7)
        rby = {c["id"]: c["status"] for c in ran["criteria"]}
        assert rby["P"] == "PASS" and rby["L"] == "PASS"
        failed = await S2.evaluate(s, tests={"exit": 1, "summary": "1 failed"}, seed=7)
        fby = {c["id"]: c["status"] for c in failed["criteria"]}
        assert fby["P"] == "FAIL" and fby["L"] == "FAIL" and failed["overall"] == "NOT PASSED"
    finally:
        clock.unfreeze()
