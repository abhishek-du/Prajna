"""Tests for Prajna Trading Dashboard API endpoints.

Covers all 12 trading intelligence sections, security isolation,
Stage 3 lock enforcement, P5 global finality contract, error handling, and provenance.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.app import app
from app.db.engine import get_engine, reset_engine


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db():
    yield
    try:
        eng = get_engine()
        if eng:
            await eng.dispose()
    finally:
        reset_engine()


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_signals_strictly_locked(async_client):
    """Signals endpoint must return locked status with 0 fake signals."""
    resp = await async_client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "LOCKED"
    assert data["stage"] == "STAGE_3_LOCKED"
    assert "Stage 3 remains strictly LOCKED" in data["message"]
    assert data["signals"] == []


@pytest.mark.anyio
async def test_portfolio_strictly_locked(async_client):
    """Portfolio endpoint must return locked compliance status with 0 orders."""
    resp = await async_client.get("/api/v1/portfolio")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "LOCKED"
    assert data["stage"] == "STAGE_4_5_LOCKED"
    assert "Order execution and live broker routing are strictly LOCKED" in data["message"]
    assert data["orders"] == []
    assert data["positions"] == []
    assert data["holdings"] == []


@pytest.mark.anyio
async def test_candles_invalid_timeframe_rejected(async_client):
    """Unsupported timeframes must return 400."""
    resp = await async_client.get("/api/v1/candles/NSE_INDEX|Nifty%2050?timeframe=2m")
    assert resp.status_code == 400
    assert "not supported" in resp.json()["detail"]


@pytest.mark.anyio
async def test_candles_valid_timeframe(async_client):
    """Valid timeframe returns envelope with candle items."""
    resp = await async_client.get("/api/v1/candles/NSE_INDEX|Nifty%2050?timeframe=1d&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert body["data"]["instrument_key"] == "NSE_INDEX|Nifty 50"
    assert body["data"]["timeframe"] == "1d"
    assert isinstance(body["data"]["candles"], list)


@pytest.mark.anyio
async def test_health_no_secrets_exposed(async_client):
    """Health endpoint must never expose secrets or credentials."""
    resp = await async_client.get("/api/v1/health")
    assert resp.status_code == 200
    body_str = resp.text
    # Verify no secret keywords leaked
    assert "PRAJNA_WRITE_TOKEN" not in body_str
    assert "UPSTOX_API_SECRET" not in body_str
    assert "UPSTOX_PIN" not in body_str
    assert "UPSTOX_TOTP_SECRET" not in body_str
    data = resp.json()["data"]
    assert "database" in data
    assert "token_auth" in data
    assert "daily_close" in data
    assert "instrument_master" in data
    assert "global_refresh" in data
    assert "timing_contract" in data
    assert "acceptance_summary" in data


@pytest.mark.anyio
async def test_overview_endpoint(async_client):
    """Overview dashboard provides indices, session status, global benchmarks, and freshness."""
    resp = await async_client.get("/api/v1/overview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "indices" in data
    assert "market_status" in data
    assert "global_markets" in data
    assert "recent_news" in data
    assert "freshness" in data
    assert "system_health_summary" in data
    assert isinstance(data["indices"], list)
    assert isinstance(data["market_status"]["is_open"], bool)


@pytest.mark.anyio
async def test_instruments_list_and_search(async_client):
    """Instruments endpoint supports searching, filtering, and pagination."""
    resp = await async_client.get("/api/v1/instruments?limit=10")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "instruments" in data
    assert "total" in data
    assert isinstance(data["instruments"], list)
    assert data["total"] >= 0


@pytest.mark.anyio
async def test_instruments_not_found(async_client):
    """Querying an unknown instrument returns 404."""
    resp = await async_client.get("/api/v1/instruments/UNKNOWN_INSTRUMENT_XYZ")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_technicals_not_found(async_client):
    """Technicals for an unknown instrument returns 404."""
    resp = await async_client.get("/api/v1/technicals/UNKNOWN_INSTRUMENT_XYZ")
    assert resp.status_code == 404
    assert any(term in resp.json()["detail"].lower() for term in ("not found", "no bars found"))


@pytest.mark.anyio
async def test_fundamentals_not_found(async_client):
    """Fundamentals for an unknown instrument returns 404."""
    resp = await async_client.get("/api/v1/fundamentals/UNKNOWN_INSTRUMENT_XYZ")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_global_markets_finality_contract(async_client):
    """Global markets endpoint enforces P5 finality (CONFIRMED only)."""
    resp = await async_client.get("/api/v1/global-markets")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "markets" in data
    assert "withheld_counts" in data
    # Verify no unconfirmed or placeholder bars leaked
    for m in data["markets"]:
        assert m["finality"] in ("CONFIRMED", "CONFIRMED_BY_AGE")


@pytest.mark.anyio
async def test_news_provenance(async_client):
    """News articles have strict provenance timestamps and unpredicted sentiment."""
    resp = await async_client.get("/api/v1/news?limit=10")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "articles" in data
    for art in data["articles"]:
        assert "received_at" in art
        assert "source" in art
        assert art["sentiment_status"] == "NOT_COMPUTED_STAGE_3_LOCKED"


@pytest.mark.anyio
async def test_screener_endpoint(async_client):
    """Screener returns stock rows with disabled Stage 3/4/5 columns."""
    resp = await async_client.get("/api/v1/screener?limit=10")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "stocks" in data
    assert "sectors" in data
    for s in data["stocks"]:
        assert s["alpha_signal"] == "Stage 3 locked"
        assert s["ai_momentum_score"] == "Stage 3 locked"


@pytest.mark.anyio
async def test_ops_warmup_validation(async_client):
    """Ops warm-up planner handles completed sessions requests safely."""
    # When test database does not have 100 historical sessions, it fails closed with 400
    resp = await async_client.get("/api/v1/ops/warmup?sessions=100&timeframes=1m,15m,1h&fraction=0.25")
    # Must be either 200 (if enough sessions) or 400 (if insufficient completed sessions)
    assert resp.status_code in (200, 400)


@pytest.mark.anyio
async def test_backups_list(async_client):
    """Ops backups endpoint returns verified backup entries."""
    resp = await async_client.get("/api/v1/ops/backups")
    assert resp.status_code == 200
    res = resp.json()
    assert "data" in res
    assert "meta" in res
    assert isinstance(res["data"], list)
