"""Test harness. Three guards, all FAIL-CLOSED, all active before collection.

V1's lessons, encoded:

  * Its `pytest` run fired live HTTPS crawls DURING COLLECTION, because ~54
    scratch scripts at the package root called asyncio.run() at module scope.
    Measured in its own pytest.ini: 3m26s and 8 errors, versus 12s for tests/.
      -> here, network is blocked by default; only @pytest.mark.live lifts it.

  * Its test suite wrote to the PRODUCTION database, and still has 144
    TESTCO.NS rows in production simulation_logs to prove it.
      -> here, the DSN is rebound to the test database before any app module
         can bind an engine, and the run aborts if that is not configured.

  * It had --strict-markers and zero markers, so its DB and network tests could
    not be deselected: all-or-nothing.
      -> here, markers are real and `-m "not live"` is the default.
"""

from __future__ import annotations

import os
import pathlib
import socket
import sys

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

FORBIDDEN_DATABASES = {"autotrade_pro", "autotrade_test"}


def _database_name(dsn: str) -> str:
    return dsn.rsplit("/", 1)[-1].split("?", 1)[0].strip() if "/" in dsn else ""


# ── GUARD 1 + 2: rebind the DSN before anything imports app.core.config ─────
#
# This runs at conftest import, i.e. before collection. app.db.engine binds its
# engine from settings at first use, and settings are cached with lru_cache, so
# the only safe moment to redirect is now.
def _install_database_guard() -> None:
    from dotenv import dotenv_values

    env = {**dotenv_values(BACKEND_ROOT / ".env"), **os.environ}
    test_dsn = env.get("PRAJNA_TEST_DATABASE_URL", "").strip()

    if not test_dsn:
        pytest.exit(
            "PRAJNA_TEST_DATABASE_URL is not configured. Tests refuse to run without "
            "an explicit test database (fail-closed).",
            returncode=4,
        )
    name = _database_name(test_dsn)
    if name in FORBIDDEN_DATABASES:
        pytest.exit(
            f"PRAJNA_TEST_DATABASE_URL targets '{name}', which belongs to V1. Refusing.",
            returncode=4,
        )
    if not name.startswith("prajna"):
        pytest.exit(
            f"test database '{name}' does not look like a prajna test database. Refusing.",
            returncode=4,
        )
    # Every app import from here on sees the test database.
    os.environ["PRAJNA_DATABASE_URL"] = test_dsn
    os.environ["PRAJNA_TEST_DATABASE_URL"] = test_dsn
    os.environ.setdefault("PRAJNA_WRITE_TOKEN", "test-token-not-a-real-secret")


_install_database_guard()

TEST_DSN = os.environ["PRAJNA_DATABASE_URL"]


# ── GUARD 3: no outbound network unless the test asks for it ────────────────
_real_socket_connect = socket.socket.connect
_real_create_connection = socket.create_connection


class NetworkAccessBlocked(RuntimeError):
    """A test attempted an outbound connection without @pytest.mark.live."""


def _blocked_connect(self, address, *a, **kw):
    host = address[0] if isinstance(address, tuple) else address
    # Unix sockets and loopback (the test database) stay reachable.
    if isinstance(host, str) and (host.startswith("/") or host in ("127.0.0.1", "::1", "localhost")):
        return _real_socket_connect(self, address, *a, **kw)
    raise NetworkAccessBlocked(
        f"outbound network to {host!r} blocked. Mark the test @pytest.mark.live "
        f"if it is genuinely meant to call a vendor."
    )


def _blocked_create_connection(address, *a, **kw):
    host = address[0] if isinstance(address, tuple) else address
    if host in ("127.0.0.1", "::1", "localhost"):
        return _real_create_connection(address, *a, **kw)
    raise NetworkAccessBlocked(f"outbound network to {host!r} blocked.")


@pytest.fixture(autouse=True)
def _network_guard(request):
    if request.node.get_closest_marker("live"):
        yield
        return
    socket.socket.connect = _blocked_connect
    socket.create_connection = _blocked_create_connection
    try:
        yield
    finally:
        socket.socket.connect = _real_socket_connect
        socket.create_connection = _real_create_connection


def pytest_collection_modifyitems(config, items):
    """Deselect live tests unless explicitly requested with -m live."""
    if "live" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live test; run with -m live")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


# ── session fixtures ────────────────────────────────────────────────────────
@pytest.fixture
async def db_session(request):
    """An AsyncSession bound to a transaction that is ALWAYS rolled back.

    Ported from V1's scripts/phase5_isolation.py, which got this right: bind the
    session to an outer transaction with join_transaction_mode='create_savepoint'
    so the code under test can call commit() and still leave nothing behind.
    Its predecessor patched commit() into a no-op, which silently invalidated
    every read-back and therefore the whole experiment.

    @pytest.mark.isolation("REPEATABLE READ") runs the enclosing transaction at that
    level, as code that begins its own consistent snapshot (Stage 3) needs: inside
    a savepoint it cannot set the level itself.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(TEST_DSN, poolclass=None)
    conn = await engine.connect()
    level = request.node.get_closest_marker("isolation")
    if level is not None:
        await conn.execution_options(isolation_level=level.args[0])
    trans = await conn.begin()
    session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint",
                           expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()
