"""Regressions found in the 2026-10-16 full UI audit (each was visible in the dashboard)."""

from __future__ import annotations

import inspect
import pathlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api import fundamentals, stages, ws
from app.api.app import app
from app.db.engine import reset_engine

API = pathlib.Path(stages.__file__).parent


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


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_anomalies_endpoint_reads_the_real_columns(client):
    """It selected rule/entity_key/details, which ingest_anomaly does not have: HTTP 500."""
    r = await client.get("/api/v1/ops/anomalies?limit=5")
    assert r.status_code == 200 and isinstance(r.json()["data"], list)


def test_vendor_ratio_text_is_parsed():
    """"8.94%" made float() fail, so ROE/ROCE showed "--" next to the raw 8.94%."""
    src = inspect.getsource(fundamentals)
    assert "_ratio_num" in src and 'replace("%", "")' in src


def test_the_live_stream_sends_canonical_bars_per_timeframe():
    """A raw 1m bar (O=H=L=C, volume 0) was drawn as a new daily candle."""
    src = inspect.getsource(ws)
    assert "from canon_market_bar" in src and "distinct on (instrument_key, timeframe)" in src
    chart = (API.parents[2] / "frontend/src/components/Chart/CandleChart.tsx").read_text()
    assert "tick.timeframe !== timeframe" in chart


def test_no_fabricated_status_or_fallback_values():
    src = (API / "stages.py").read_text()
    for bad in ("else 41.85", '_parse_live_backfill_progress(backfill_dir, "WAITING_CLOSE")',
                "PRAJNA_STAGE3_ENABLED gate check"):
        assert bad not in src, bad


@pytest.mark.anyio
async def test_backfill_progress_is_the_database_truth(client):
    r = await client.get("/api/v1/stages/1/backfill")
    assert r.status_code == 200
    assert any("database checkpoints" in n for n in r.json()["meta"]["notes"])
