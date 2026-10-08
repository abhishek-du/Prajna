"""Stage 3 surfaces on the seed world: the read API (stored values only,
point-in-time on computed_at, empty while locked) and the acceptance gate
(levels, never COMPLETE without every prerequisite and production evidence)."""

from __future__ import annotations

import datetime as _dt
import os
import urllib.parse as up

import httpx
import pytest

from app.acceptance import stage3 as S3
from app.canon import process as P
from app.core import clock
from app.features import engine as E
from app.features import locks
from app.readapi import main as M
from tests.stage3.test_engine import unlocked  # noqa: F401  (fixture)
from tests.support import stage3_seed as W

pytestmark = [pytest.mark.db, pytest.mark.integration,
              pytest.mark.isolation("REPEATABLE READ")]   # run_snapshot needs one snapshot
TOKEN = os.environ["PRAJNA_WRITE_TOKEN"]
KEY = up.quote(W.A, safe="")


@pytest.fixture
async def world(db_session, monkeypatch):
    clock.freeze(W.NOW)
    await W.seed(db_session)
    await P.process(db_session, commit=True, token=TOKEN)

    async def not_complete(_s):          # the real Stage 1 gate is not run on the seed world
        return False, "NOT COMPLETE (test world)"
    monkeypatch.setattr(locks, "stage1_status", not_complete)
    yield db_session
    clock.unfreeze()


@pytest.fixture
async def client(world):
    async def bound():
        yield world
    M.api.dependency_overrides[M.session] = bound
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=M.api),
                                 base_url="http://test") as c:
        yield c
    M.api.dependency_overrides.clear()


async def _run(s, kind="PRE_SESSION"):
    from app.features import snapshots as SN
    sn = await SN.resolve(s, W.SESSION, kind)
    return await E.run_snapshot(s, sn, keys=[W.A], mode="RUN", token=TOKEN, operator="pytest")


def q(dt: _dt.datetime) -> str:
    return up.quote(dt.isoformat(), safe="")


class TestReadAPI:
    async def test_registry(self, client):
        d = (await client.get("/v1/stage3/registry")).json()["data"]
        from app.features.registry import FEATURES
        assert d["summary"]["diagram_items"] == 31 and len(d["features"]) == len(FEATURES)
        assert d["decisions"]["FEATURE-PARAMS"]["status"] == "APPROVED"

    async def test_status_is_locked_by_default(self, client):
        d = (await client.get("/v1/stage3/status")).json()["data"]
        assert d["production_execution"] == "LOCKED"
        assert d["flags"] == {"PRAJNA_STAGE3_ENABLED": False,
                              "PRAJNA_STAGE3_BACKFILL_ENABLED": False}
        assert d["stored"]["feature_values"] == 0

    async def test_features_empty_while_locked(self, client):
        r = (await client.get(f"/v1/instruments/{KEY}/features?session=2026-09-24")).json()
        assert r["data"] == [] and r["meta"]["point_in_time"] is True and r["meta"]["notes"]

    async def test_stored_values_are_served_point_in_time(self, client, world, unlocked):  # noqa: F811
        await _run(world)
        url = f"/v1/instruments/{KEY}/features?session=2026-09-24&snapshot=PRE_SESSION"
        # the clock is frozen: a value stored "now" is visible strictly after now
        rows = (await client.get(url + f"&as_of={q(W.NOW + _dt.timedelta(seconds=1))}")
                ).json()["data"]
        assert {r["feature_id"]: r["value"] for r in rows}["pe"] == 20.0
        assert all((r["value"] is None) != (r["reason"] is None) for r in rows)
        assert (await client.get(url)).json()["data"] == []            # as_of == computed_at

    async def test_snapshot_is_validated_and_nothing_is_writable(self, client):
        r = await client.get(f"/v1/instruments/{KEY}/features?session=2026-09-24&snapshot=CLOSE")
        assert r.status_code == 422
        assert (await client.post("/v1/stage3/status")).status_code == 405


class TestAcceptance:
    async def test_locked_world_is_not_production_ready(self, world):
        rep = await S3.evaluate(world, None)
        st = {c["id"]: c["status"] for c in rep["criteria"]}
        assert st["A"] == st["B"] == st["C"] == st["D"] == st["F"] == st["J"] == "PASS"
        assert st["K"] == st["G"] == "NOT_RUN"
        assert st["M"] == "BLOCKED" and st["N"] == "PASS" and st["O"] == "PENDING"
        reached = {lv["level"]: lv["reached"] for lv in rep["levels"]}
        assert reached["IMPLEMENTED"] and not reached["TESTED"]
        assert not reached["PRODUCTION READY"] and not reached["PRODUCTION UNLOCKED"]
        assert rep["overall"].startswith("NOT COMPLETE")
        assert "Overall" in S3.to_markdown(rep)

    async def test_tests_passing_do_not_make_it_complete(self, world):
        rep = await S3.evaluate(world, {"exit": 0, "summary": "1 passed"})
        reached = {lv["level"]: lv["reached"] for lv in rep["levels"]}
        assert reached["TESTED"] and reached["DRY-RUN READY"]
        assert not reached["PRODUCTION READY"]
        assert rep["overall"] == "NOT COMPLETE (DRY-RUN READY)"

    async def test_complete_needs_unlock_and_production_evidence(self, world, unlocked):  # noqa: F811
        ok = {"exit": 0, "summary": "1 passed"}
        rep = await S3.evaluate(world, ok)
        assert rep["overall"] == "NOT COMPLETE (PRODUCTION UNLOCKED)"      # no evidence yet
        await _run(world)
        rep = await S3.evaluate(world, ok)
        assert rep["overall"] == "COMPLETE"
        locks.set_kill_switch(True, "test")
        assert (await S3.evaluate(world, ok))["overall"] == "NOT COMPLETE (PRODUCTION READY)"
