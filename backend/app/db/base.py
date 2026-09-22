"""Declarative base and the provenance mixin every observation table carries.

Constraint #7: source, run_id, payload_sha256, fetched_at, knowable_at on every
persisted record. Making it a mixin means a new table cannot accidentally omit
it — which is how V1's `candles` ended up with 39 million rows and no `source`
column, leaving its 14 conflicting daily anchors permanently unresolvable.
"""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import CHAR, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


def utc_ts(**kw) -> Mapped[_dt.datetime]:
    """tz-AWARE timestamp. V2 has no naive datetime columns anywhere."""
    return mapped_column(TIMESTAMP(timezone=True), **kw)


class ProvenanceMixin:
    """Where a row came from, and when it could first have been acted on."""

    @declared_attr
    def source(cls) -> Mapped[str]:
        return mapped_column(String(32), nullable=False)

    @declared_attr
    def run_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("ingest_run.run_id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )

    @declared_attr
    def payload_sha256(cls) -> Mapped[str]:
        return mapped_column(
            CHAR(64), ForeignKey("raw_payload.payload_sha256", ondelete="RESTRICT"),
            nullable=False,
        )

    @declared_attr
    def fetched_at(cls) -> Mapped[_dt.datetime]:
        return mapped_column(TIMESTAMP(timezone=True), nullable=False)

    @declared_attr
    def knowable_at(cls) -> Mapped[_dt.datetime]:
        return mapped_column(TIMESTAMP(timezone=True), nullable=False)

    @declared_attr
    def knowable_at_verified(cls) -> Mapped[bool]:
        """False = conservative fallback, not a measurement (constraint #9)."""
        return mapped_column(nullable=False, default=False, server_default="false")

    @declared_attr
    def knowable_at_basis(cls) -> Mapped[str]:
        """Human-readable justification, persisted so it is auditable later."""
        return mapped_column(String(200), nullable=False)

    @declared_attr
    def __table_args__(cls):
        # knowable_at may never postdate the moment we held the bytes.
        return (
            CheckConstraint("knowable_at <= fetched_at", name=f"ck_{cls.__tablename__}_knowable"),
        )
