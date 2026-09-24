"""The Stage-1 gate runs read-only and is never COMPLETE on an empty database."""

from __future__ import annotations

import pytest

from app.acceptance.stage1 import BLOCKED, DECISIONS, FAIL, PASS, evaluate, to_markdown

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def test_empty_database_is_not_complete(db_session):
    rep = await evaluate(db_session)
    assert rep["overall"] == "NOT COMPLETE"
    by = {c["id"]: c for c in rep["criteria"]}
    assert sorted(by) == [chr(c) for c in range(ord("A"), ord("Z"))]
    assert by["B"]["status"] == PASS and by["C"]["status"] == PASS   # nothing to violate
    assert by["N"]["status"] == FAIL and by["R"]["status"] == FAIL   # no data is not a pass
    for c in rep["criteria"]:                                          # a pending decision
        assert all(DECISIONS[d]["status"] == "PENDING" for d in c["decisions"])
        if c["decisions"]:
            assert c["status"] in (BLOCKED, PASS)
    md = to_markdown(rep)
    assert "## Overall: **NOT COMPLETE**" in md and "Decision register" in md


def test_register_only_approves_with_a_reference():
    for k, d in DECISIONS.items():
        if d["status"] == "APPROVED":
            assert d["ref"] not in ("", "-"), k
