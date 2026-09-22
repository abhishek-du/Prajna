"""Alembic environment.

The DSN comes from app.core.config, never from alembic.ini, so a migration is
subject to the same V1-isolation guard as the application.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.core.config import get_settings
from app.db.engine import assert_not_v1
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_dsn = context.get_x_argument(as_dictionary=True).get("dsn") or get_settings().PRAJNA_DATABASE_URL
assert_not_v1(_dsn)
config.set_main_option("sqlalchemy.url", _dsn.replace("%", "%%"))


def _run(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    context.configure(url=_dsn, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(_run_async())
