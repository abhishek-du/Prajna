"""The Stage 2 gate runs read-only and is never PASS without real evidence."""

from __future__ import annotations

import pytest

from app.acceptance import stage2 as S2

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def test_empty_database_is_not_passed(db_session):
    rep = await S2.evaluate(db_session, tests=None)
    by = {c["id"]: c for c in rep["criteria"]}
    assert sorted(by) == [chr(c) for c in range(ord("A"), ord("Q"))]
    assert rep["overall"] == "NOT PASSED"
    assert by["A"]["status"] == "FAIL"          # nothing processed
    assert by["M"]["status"] == "PENDING"       # no real incremental run
    assert by["P"]["status"] == "PENDING"       # tests not run
    md = S2.to_markdown(rep, {"x": "y"})
    assert "## Overall: **NOT PASSED**" in md and "Stage 3 stays locked" in md
