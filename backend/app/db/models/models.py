"""Stage 4 E5 model versions and predictions (migration 0024; docs/STAGE4_E5_PREREGISTRATION.md).
Append-only (trigger). PAPER ONLY."""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import TIMESTAMP as _TS
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TS = _TS(timezone=True)


class ModelVersion(Base):
    """One fitted recipe artefact."""

    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    recipe: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    trained_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    trained_to: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    train_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    train_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    artefact_path: Mapped[str] = mapped_column(Text, nullable=False)
    artefact_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    code_git_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    authz_token_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    __table_args__ = (
        CheckConstraint("purpose in ('FORWARD_TEST','RESEARCH')",
                        name="ck_model_version_purpose"),
        CheckConstraint("trained_from <= trained_to", name="ck_model_version_dates"),
        UniqueConstraint("model_sha256", name="uq_model_version_sha"),
    )


class ModelPrediction(Base):
    """One instrument's outputs for one session, written before the open."""

    __tablename__ = "model_prediction"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_sha256: Mapped[str] = mapped_column(CHAR(64), ForeignKey("model_version.model_sha256"),
                                              nullable=False)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    snapshot: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    prob_up: Mapped[float] = mapped_column(Float, nullable=False)
    exp_return: Mapped[float] = mapped_column(Float, nullable=False)
    range_lo: Mapped[float] = mapped_column(Float, nullable=False)
    range_hi: Mapped[float] = mapped_column(Float, nullable=False)
    volatility: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    features_as_of: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    inputs_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    predicted_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    deadline_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint("predicted_at < deadline_at", name="ck_model_prediction_deadline"),
        CheckConstraint("features_as_of <= predicted_at", name="ck_model_prediction_asof"),
        CheckConstraint("prob_up >= 0 and prob_up <= 1 and confidence >= 0 "
                        "and confidence <= 1 and range_lo <= range_hi and volatility >= 0",
                        name="ck_model_prediction_ranges"),
        UniqueConstraint("model_sha256", "session_date", "snapshot", "instrument_key",
                         name="uq_model_prediction"),
        Index("ix_model_prediction_session", "session_date", "model_sha256"),
    )


class GateScanCheckpoint(Base):
    """Stage 1 gate ohlcv_bar check counts up to a cut (migration 0025; GATE-INCR)."""

    __tablename__ = "gate_scan_checkpoint"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    through_finished_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bars: Mapped[dict] = mapped_column(JSONB, nullable=False)
    consistent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    previous_id: Mapped[int | None] = mapped_column(BigInteger,
                                                    ForeignKey("gate_scan_checkpoint.id"),
                                                    nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    code_git_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    authz_token_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    __table_args__ = (
        CheckConstraint("method in ('FULL','INCREMENTAL')", name="ck_gate_scan_method"),
    )
