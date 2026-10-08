"""Stage 4 training data (migrations 0016/0017): a historical replay of the Stage 3
engine and future-outcome labels. Separate from the live feature_value; the
feature, label, done-marker and policy tables are append-only (trigger)."""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.dialects.postgresql import TIMESTAMP as _TS
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TS = _TS(timezone=True)
STATUSES = ("'VALID','MISSING_INPUT','STALE_INPUT','INVALID','NOT_APPLICABLE',"
            "'NOT_AVAILABLE_HISTORICALLY'")


class TrainingPolicyParam(Base):
    """A measured knowability parameter of a policy (frozen at first use)."""

    __tablename__ = "training_policy_param"

    policy: Mapped[str] = mapped_column(String(32), primary_key=True)
    family: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    measured_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)


class TrainingDatasetRun(Base):
    """One replay invocation (worker) of a dataset version, with its metadata."""

    __tablename__ = "training_dataset_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(48), nullable=False)
    knowability_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    registry_version: Mapped[str] = mapped_column(String(32), nullable=False)
    registry_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    snapshots: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    instrument_limit: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sessions_done: Mapped[int] = mapped_column(Integer, nullable=False,
                                               server_default=text("0"))
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    symbol_count: Mapped[int | None] = mapped_column(Integer)
    coverage_summary: Mapped[dict | None] = mapped_column(JSONB)
    validation_summary: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    completed_at: Mapped[_dt.datetime | None] = mapped_column(TS)

    __table_args__ = (
        CheckConstraint("status in ('RUNNING','COMPLETE','FAILED','SUPERSEDED')",
                        name="ck_training_run_status"),
        CheckConstraint("knowability_policy in ('STRICT_PIT','AS_IF_LIVE-v1','STRICT_PIT-v2',"
                        "'AS_IF_LIVE-v2')", name="ck_training_run_policy"),
    )


class TrainingFeatureValue(Base):
    """One feature value of a historical snapshot (the production engine's output)."""

    __tablename__ = "training_feature_value"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_version: Mapped[str] = mapped_column(String(48), nullable=False)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    snapshot: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_id: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32))
    inputs_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    input_max_knowable_at: Mapped[_dt.datetime | None] = mapped_column(TS)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("training_dataset_run.run_id", ondelete="RESTRICT"),
        nullable=False)

    __table_args__ = (
        UniqueConstraint("dataset_version", "session_date", "snapshot", "instrument_key",
                         "feature_id", name="uq_training_feature_value"),
        CheckConstraint(f"status in ({STATUSES})", name="ck_training_fv_status"),
        CheckConstraint("(status = 'VALID') = (value is not null)", name="ck_training_fv_value"),
        CheckConstraint("value is null or value::text not in ('NaN','Infinity','-Infinity')",
                        name="ck_training_fv_finite"),
        CheckConstraint("input_max_knowable_at is null or input_max_knowable_at < as_of",
                        name="ck_training_fv_pit"),
    )


class TrainingSessionDone(Base):
    """The resume marker: a snapshot of a dataset version that is complete."""

    __tablename__ = "training_session_done"

    dataset_version: Mapped[str] = mapped_column(String(48), primary_key=True)
    session_date: Mapped[_dt.date] = mapped_column(Date, primary_key=True)
    snapshot: Mapped[str] = mapped_column(String(16), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("training_dataset_run.run_id", ondelete="RESTRICT"),
        nullable=False)
    as_of: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    instruments: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False)
    done_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)


class TrainingLabel(Base):
    """A future-outcome label of a session (label-v1), strictly after its snapshots."""

    __tablename__ = "training_label"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label_version: Mapped[str] = mapped_column(String(32), nullable=False)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label_id: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    label_start_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    label_end_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    inputs_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    computed_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        UniqueConstraint("label_version", "session_date", "instrument_key", "label_id",
                         name="uq_training_label"),
        CheckConstraint("status in ('VALID','MISSING_INPUT')", name="ck_training_label_status"),
        CheckConstraint("(status = 'VALID') = (value is not null)",
                        name="ck_training_label_value"),
        CheckConstraint("label_end_at > label_start_at", name="ck_training_label_window"),
    )
