"""Stage 3 storage: computed features and the Stage 3 audit trail (append-only)."""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Date

from app.db.base import Base


class FeatureValue(Base):
    """One feature of one instrument (or context) at one snapshot of one session.

    Exactly one of value / reason is set: a missing value always says why.
    Every input used was knowable strictly before as_of (checked). Rows are
    never updated or deleted (trigger); a new definition is a new version.
    """

    __tablename__ = "feature_value"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(12), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("instrument.instrument_id", ondelete="RESTRICT"), nullable=True)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    snapshot: Mapped[str] = mapped_column(String(12), nullable=False)
    as_of: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    feature_id: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[int] = mapped_column(Integer, nullable=False)
    registry_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(), nullable=True)   # exact (0012)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    inputs_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    input_max_knowable_at: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    computed_at: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"), nullable=False)

    __table_args__ = (
        CheckConstraint("scope in ('INSTRUMENT','CONTEXT')", name="ck_feature_scope"),
        CheckConstraint("snapshot in ('PRE_SESSION','PRE_OPEN')", name="ck_feature_snapshot"),
        CheckConstraint("(value is null) <> (reason is null)", name="ck_feature_value_or_reason"),
        CheckConstraint("input_max_knowable_at is null or input_max_knowable_at < as_of",
                        name="ck_feature_pit"),
        UniqueConstraint("instrument_key", "session_date", "snapshot", "feature_id",
                         "feature_version", name="uq_feature_value"),
        Index("ix_feature_value_session", "session_date", "snapshot"),
        Index("ix_feature_value_run", "run_id"),
    )


class Stage3Event(Base):
    """Append-only audit: lock refusals, kill-switch changes, run outcomes."""

    __tablename__ = "stage3_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                             server_default=text("now()"))
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"), nullable=True)

    __table_args__ = (
        CheckConstraint("event in ('REFUSED','KILL_ON','KILL_OFF','RUN_COMPLETE','RUN_FAILED')",
                        name="ck_stage3_event"),
        Index("ix_stage3_event_at", "at"),
    )
