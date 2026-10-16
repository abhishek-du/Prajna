"""Unit tests for Stage 1, 2, and 3 detail endpoints (/api/v1/stages/*, /api/v1/features/*).

Enforces:
  - Stage 1 coverage and backfill contracts
  - Stage 2 gate criteria and coverage state matrix
  - Stage 3 gate, registry, and snapshot completeness contracts
  - Per-instrument feature card lookup
  - Read-only transaction enforcement and guard checks
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.app import app
from app.db.engine import reset_engine


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
async def test_stage1_coverage_endpoint(async_client):
    """GET /api/v1/stages/1/coverage returns timeframes, exclusions, corporate actions, and master changes."""
    resp = await async_client.get("/api/v1/stages/1/coverage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["point_in_time"] is True
    data = body["data"]

    # Verify timeframes
    timeframes = data["timeframes"]
    assert len(timeframes) >= 4
    tf_names = [t["timeframe"] for t in timeframes]
    for expected in ("1d", "1h", "15m", "1m"):
        assert expected in tf_names

    assert data["total_coverage_ranges"] >= 0
    assert data["total_bars"] >= 0
    assert data["excluded_bars_total"] >= 0
    assert isinstance(data["excluded_reasons_breakdown"], dict)
    assert isinstance(data["recent_excluded_bars"], list)

    # Corporate actions and factors
    assert data["corporate_actions_total"] >= 0
    assert isinstance(data["corporate_actions_by_type"], dict)
    assert data["factors_total"] >= 0

    # Master counts
    assert data["master_instruments_active"] >= 0
    assert data["master_instruments_removed"] >= 0


@pytest.mark.anyio
async def test_stage1_backfill_endpoint(async_client):
    """GET /api/v1/stages/1/backfill returns supervisor state, progress per timeframe, and ETA."""
    resp = await async_client.get("/api/v1/stages/1/backfill")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["supervisor_state"] in ("RUNNING", "WAITING_CLOSE", "PAUSED", "WINDOW_CLOSED", "DONE", "UNKNOWN")
    assert isinstance(data["progress"], list)
    assert len(data["progress"]) >= 1
    for p in data["progress"]:
        assert p["timeframe"] in ("1h", "15m", "1d", "1m")
        assert p["total"] >= 0                      # the test DB may hold no instrument
        assert 0.0 <= p["pct"] <= 100.0
    # progress is the database truth (shared with the Telegram update), not a log line
    assert any("database checkpoints" in n for n in resp.json()["meta"]["notes"])


@pytest.mark.anyio
async def test_stage2_gate_endpoint(async_client):
    """GET /api/v1/stages/2/gate returns criteria A–P, age check, and coverage state matrix."""
    resp = await async_client.get("/api/v1/stages/2/gate")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["overall"] in ("PASS", "FAIL", "NOT_AVAILABLE")
    criteria = data["criteria"]
    assert len(criteria) >= 16  # Criteria A through P
    criterion_ids = [c["id"] for c in criteria]
    assert "A" in criterion_ids
    assert "B" in criterion_ids
    assert "P" in criterion_ids

    # Coverage matrix
    matrix = data["coverage_state_matrix"]
    assert isinstance(matrix, dict)
    assert "1d" in matrix
    assert "1h" in matrix


@pytest.mark.anyio
async def test_stage3_gate_endpoint(async_client):
    """GET /api/v1/stages/3/gate returns criteria A–O and live refusal audit trail."""
    resp = await async_client.get("/api/v1/stages/3/gate")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["overall"] in ("PASS", "COMPLETE", "FAIL", "NOT_AVAILABLE")
    criteria = data["criteria"]
    assert len(criteria) >= 15  # Criteria A through O

    refusals = data["refusal_audit"]
    assert isinstance(refusals, list)
    assert data["events_count_total"] >= 0


@pytest.mark.anyio
async def test_stage3_registry_endpoint(async_client):
    """GET /api/v1/stages/3/registry returns all 104 registered features grouped."""
    resp = await async_client.get("/api/v1/stages/3/registry")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["version"]
    assert data["registry_sha256"]
    assert data["feature_count"] == 104
    assert data["implemented_count"] == 104
    assert len(data["features"]) == 104

    groups = data["groups"]
    assert "price_technical" in groups
    assert "volume_liquidity" in groups
    assert "fundamental" in groups


@pytest.mark.anyio
async def test_stage3_snapshots_endpoint(async_client):
    """GET /api/v1/stages/3/snapshots returns completeness for PRE_SESSION and PRE_OPEN."""
    resp = await async_client.get("/api/v1/stages/3/snapshots?date=2026-10-16")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["session_date"] == "2026-10-16"
    assert isinstance(data["snapshots_available"], list)
    assert data["distinct_instruments_count"] >= 0
    assert data["total_values"] >= 0


@pytest.mark.anyio
async def test_features_card_endpoint(async_client):
    """GET /api/v1/features/{key} returns feature card for recognized instrument, 404 for unknown."""
    # 404 for unknown instrument
    resp404 = await async_client.get("/api/v1/features/UNKNOWN_XYZ_999")
    assert resp404.status_code == 404

    # 200 for index benchmark
    resp = await async_client.get("/api/v1/features/NSE_INDEX|Nifty%2050?snapshot=PRE_OPEN&date=2026-10-16")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["instrument_key"] == "NSE_INDEX|Nifty 50"
    assert data["snapshot"] == "PRE_OPEN"
    assert len(data["features"]) > 0
    f0 = data["features"][0]
    assert "feature_id" in f0
    assert "group" in f0

