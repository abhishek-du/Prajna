"""Criterion X decision (pure): B1 and the revised B2 decide; the superseded
B2_original (decision TIMING-B2) is evidence only and never blocks PASS."""

from __future__ import annotations

from app.acceptance.stage1 import BLOCKED, FAIL, PASS, WAITING, x_decision

CLEAN = {"daily_nse_fetched_same_day": 0, "intraday_before_end_plus_margin": 0}


def timing(b1="VERIFIED", b2="VERIFIED", original="CONTRADICTED"):
    return {"B1": {"status": b1}, "B2": {"status": b2},
            "B2_original": {"status": original, "superseded_by": "TIMING-B2"}}


def test_superseded_original_contract_does_not_block_pass():
    assert x_decision(CLEAN, timing()) == (PASS, [])


def test_waiting_until_both_verified():
    assert x_decision(CLEAN, timing(b2="PENDING"))[0] == WAITING
    assert x_decision(CLEAN, timing(b1="UNMEASURED"))[0] == WAITING


def test_contradiction_blocks_and_any_violation_fails():
    assert x_decision(CLEAN, timing(b2="CONTRADICTED")) == (BLOCKED, ["B2"])
    assert x_decision({**CLEAN, "fii_dii_same_day": 1}, timing())[0] == FAIL
    assert x_decision({**CLEAN, "fii_dii_same_day": 1}, timing(b1="CONTRADICTED"))[0] == FAIL
