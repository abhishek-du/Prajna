"""Tests for Stages & Control Room API endpoint (/api/v1/stages).

Enforces:
  - All 8 pipeline stages present with point-in-time provenance
  - Today's scheduled jobs timeline and system alerts feed
  - Guard test: Read-only API verification (zero POST/PUT/PATCH/DELETE)
  - Guard test: No broker order placement imports in app/api/
"""

from __future__ import annotations

import ast
import pathlib
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.app import app
from app.db.engine import get_engine, reset_engine


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db():
    import app.db.engine as engine_mod
    if engine_mod._engine is not None:
        try:
            await engine_mod._engine.dispose()
        except Exception:
            pass
    reset_engine()
    yield
    if engine_mod._engine is not None:
        try:
            await engine_mod._engine.dispose()
        except Exception:
            pass
    reset_engine()




@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_stages_overview_endpoint(async_client):
    """GET /api/v1/stages returns all 8 stages, job timeline, and alerts."""
    resp = await async_client.get("/api/v1/stages")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    meta = body["meta"]
    assert meta["point_in_time"] is True
    assert "as_of" in meta

    data = body["data"]
    assert "stages" in data
    assert "timeline" in data
    assert "alerts" in data
    assert "market_state" in data

    stages = data["stages"]
    assert len(stages) == 8
    stage_numbers = [s["stage_number"] for s in stages]
    assert stage_numbers == [1, 2, 3, 4, 5, 6, 7, 8]

    # Verify each stage has required fields
    for s in stages:
        assert s["name"]
        assert s["status"]
        assert s["status_label"]
        assert s["key_metric_label"]
        assert s["key_metric_value"]
        assert isinstance(s["alert_count"], int)
        assert isinstance(s["alerts"], list)
        assert isinstance(s["evidence_summary"], dict)

    # Stage 3 status derived from stage3.json + stage3_event (COMPLETE and running daily)
    stage3 = next(s for s in stages if s["stage_number"] == 3)
    assert stage3["status"] in ("COMPLETE", "RUNNING", "FAILED", "NOT_AVAILABLE")

    # Timeline has today's canonical scheduled jobs
    timeline = data["timeline"]
    assert len(timeline) >= 8
    job_times = [j["time_ist"] for j in timeline]
    assert "06:30" in job_times
    assert "08:25" in job_times
    assert "09:00" in job_times
    assert "15:40" in job_times
    assert "16:05" in job_times

    for job in timeline:
        assert job["status"] in ("DONE", "RUNNING", "FAILED", "MISSED", "PENDING", "WAITING_CLOSE", "BACKFILLED", "REFUSED → BACKFILLED")


@pytest.mark.anyio
async def test_guard_no_mutation_routes():
    """Guard test: Verify that app router exposes NO POST, PUT, PATCH, or DELETE routes."""
    forbidden_methods = {"POST", "PUT", "PATCH", "DELETE"}
    mutation_routes: list[str] = []

    for route in app.router.routes:
        methods = set(getattr(route, "methods", set()) or set())
        if methods & forbidden_methods:
            mutation_routes.append(f"{getattr(route, 'path', str(route))} {methods}")
        if hasattr(route, "original_router"):
            for sub in route.original_router.routes:
                sub_methods = set(getattr(sub, "methods", set()) or set())
                if sub_methods & forbidden_methods:
                    mutation_routes.append(f"{sub.path} {sub_methods}")

    assert mutation_routes == [], f"Found forbidden mutation routes: {mutation_routes}"


@pytest.mark.anyio
async def test_guard_no_broker_order_imports():
    """Guard test: Verify that no module in app/api/ imports broker order execution clients."""
    api_dir = pathlib.Path(__file__).resolve().parents[2] / "app" / "api"
    forbidden_terms = {
        "place_order",
        "modify_order",
        "cancel_order",
        "order_api",
        "order_client",
        "broker_client",
        "order_service",
    }

    violations: list[str] = []
    for py_file in api_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for term in forbidden_terms:
                        if term in alias.name.lower():
                            violations.append(f"{py_file.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    full = f"{mod}.{alias.name}".lower()
                    for term in forbidden_terms:
                        if term in full:
                            violations.append(f"{py_file.name}: from {mod} import {alias.name}")

    assert violations == [], f"Found forbidden broker order imports in API: {violations}"
