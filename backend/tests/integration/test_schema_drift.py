"""The ORM models and the migrated database agree (no un-migrated change)."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.models import Base

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def test_models_match_migrated_schema(db_session):
    conn = await db_session.connection()

    def diff(sync_conn):
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(ctx, Base.metadata)

    changes = await conn.run_sync(diff)
    # alembic's own version table is not a model
    changes = [c for c in changes
               if not (c[0] == "remove_table" and c[1].name == "alembic_version")]
    assert changes == [], changes
