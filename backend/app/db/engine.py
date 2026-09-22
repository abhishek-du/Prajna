"""Async engine, with V1 isolation enforced before a connection can exist.

The check runs at engine construction, not at query time, and it raises rather
than warns. This is the structural counterpart to the database-level proof that
`prajna_rw` holds no privileges on `autotrade_pro`: even if the role were
widened by accident, the application still refuses to address that database.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import FORBIDDEN_DATABASES, database_name, get_settings
from app.core.errors import DatabaseIsolationError

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def assert_not_v1(dsn: str) -> None:
    """Refuse any DSN addressing a V1 database. Raises DatabaseIsolationError."""
    name = database_name(dsn)
    if name in FORBIDDEN_DATABASES:
        raise DatabaseIsolationError(
            f"refusing to connect: DSN targets V1 database '{name}'. "
            f"V2 must never read or write it."
        )
    if not name:
        raise DatabaseIsolationError(f"DSN names no database: {dsn!r}")


def build_engine(dsn: str | None = None, **kwargs) -> AsyncEngine:
    dsn = dsn or get_settings().PRAJNA_DATABASE_URL
    assert_not_v1(dsn)
    return create_async_engine(
        dsn,
        pool_pre_ping=True,
        pool_size=kwargs.pop("pool_size", 5),
        max_overflow=kwargs.pop("max_overflow", 5),
        future=True,
        **kwargs,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


def reset_engine() -> None:
    """Drop cached engine/sessionmaker. Used by tests after rebinding the DSN."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
