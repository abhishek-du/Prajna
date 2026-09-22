"""Control plane: the run ledger, the payload archive, watermarks, anomalies."""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    ARRAY, BigInteger, CheckConstraint, ForeignKey, Index, Integer, Interval, String, Text,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestRun(Base):
    """One row per ingestion attempt, opened BEFORE the fetch.

    V1's equivalent could not be trusted: run c4332067 sat in RUNNING for six
    days reporting rows_written = 0 while 269,642 rows from it were actually in
    the table, and 99.3% of all its provenance rows came from runs marked
    ABORTED or stuck RUNNING. The CHECK constraints below make those states
    unrepresentable, and the runner finalises this row in the SAME transaction
    as the data (constraint: atomic).
    """

    __tablename__ = "ingest_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    stream: Mapped[str] = mapped_column(String(64), nullable=False)
    logical_date: Mapped[_dt.date | None] = mapped_column(nullable=True)

    vendor_endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    request_params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    code_git_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    config_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    argv: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)

    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(9), nullable=False)
    # sha256 of the write token. Presence is required for a COMMIT run.
    authz_token_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    started_at: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    rows_written: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("mode in ('DRY_RUN','COMMIT')", name="ck_run_mode"),
        CheckConstraint("status in ('RUNNING','COMPLETE','FAILED','ABORTED')", name="ck_run_status"),
        # A committed run must have been authorized. Not advisory — structural.
        CheckConstraint("mode <> 'COMMIT' or authz_token_sha256 is not null",
                        name="ck_run_commit_requires_authz"),
        # A run cannot be COMPLETE without having finished.
        CheckConstraint("status <> 'COMPLETE' or finished_at is not null",
                        name="ck_run_complete_has_finish"),
        # A DRY_RUN must never claim to have written rows.
        CheckConstraint("mode <> 'DRY_RUN' or rows_written = 0",
                        name="ck_run_dryrun_writes_nothing"),
        Index("ix_run_source_status", "source", "status"),
        Index("ix_run_stream_logical", "stream", "logical_date"),
    )


class RawPayload(Base):
    """Content-addressed archive index. The bytes live on disk, gzipped.

    Primary key IS the hash, so re-ingesting an identical vendor response is
    naturally idempotent and costs one row, not a duplicate.
    """

    __tablename__ = "raw_payload"

    payload_sha256: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    vendor_endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    request_params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)

    first_seen_run: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"), nullable=False
    )
    fetched_at: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    vendor_reported_at: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_payload_source_fetched", "source", "fetched_at"),)


class IngestWatermark(Base):
    """How far each (source, stream) has got, and whether it is failing."""

    __tablename__ = "ingest_watermark"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    stream: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_logical_date: Mapped[_dt.date | None] = mapped_column(nullable=True)
    last_success_at: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    expected_cadence: Mapped[_dt.timedelta | None] = mapped_column(Interval, nullable=True)
    rows_last_run: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")


class IngestAnomaly(Base):
    """Nothing is dropped silently (constraint #9).

    V1's contract enforcement dropped the daily bars of 1,083 symbols — 28.7% of
    its universe — and the only trace was a log line in a 318 MB file. Every
    rejection, cap, gap and schema change becomes a row here, and a FAIL
    severity fails the run.
    """

    __tablename__ = "ingest_anomaly"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(4), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("severity in ('WARN','FAIL')", name="ck_anomaly_severity"),
        Index("ix_anomaly_run", "run_id"),
        Index("ix_anomaly_kind_created", "kind", "created_at"),
    )
