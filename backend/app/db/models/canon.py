"""Stage 2 canonical layer: the NSE universe and data-availability ranges.

Market data itself is NOT copied: the canonical views (migration 0005) read
the validated Stage 1 tables. These two tables hold what Stage 2 derives:
  canon_instrument   one row per current instrument: the NSE filter decision
                     (included + reason, rules hash), identifiers, sector and
                     universe membership as enrichment
  canon_coverage     maximal runs of consecutive trading sessions in one
                     data-availability state per (instrument, timeframe)
Both are written only by `prajna stage2 process` (run ledger source
PRAJNA_CANON) and rebuilt idempotently: identical inputs write nothing.
"""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import CHAR, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

COVERAGE_STATES = ("DATA", "QUARANTINED", "EMPTY", "VENDOR_ERROR", "PENDING_BACKFILL",
                   "MISSING")


class CanonInstrument(Base):
    __tablename__ = "canon_instrument"

    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instrument.instrument_id", ondelete="RESTRICT"),
        primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    instrument_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    filter_reason: Mapped[str] = mapped_column(Text, nullable=False)
    rules_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    # enrichment: the CURRENT view (latest profile snapshot = today's sector).
    # Never use these columns for a historical instant; that leaks a sector
    # known only later. Historical sector: canon.pit.sector(key, as_of).
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector_knowable_at: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    sector_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fundamental_snapshot.id", ondelete="RESTRICT"), nullable=True)
    preopen_universe_session: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    # listing lifecycle passthrough (hardening phase 2): coverage of a non-ACTIVE
    # instrument stops at lifecycle_since; its bars stay visible (no survivorship)
    lifecycle_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    lifecycle_since: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"),
        nullable=False)

    __table_args__ = (
        CheckConstraint("(sector is null) = (sector_knowable_at is null)",
                        name="ck_canon_instrument_sector_time"),
        CheckConstraint("not included or segment in ('NSE_EQ', 'NSE_INDEX')",
                        name="ck_canon_instrument_nse_only"),
        Index("ix_canon_instrument_included", "included"),
    )


class CanonCoverage(Base):
    __tablename__ = "canon_coverage"

    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("canon_instrument.instrument_id", ondelete="RESTRICT"),
        primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    from_date: Mapped[_dt.date] = mapped_column(Date, primary_key=True)
    to_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    bars: Mapped[int] = mapped_column(Integer, nullable=False)
    quarantined: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"),
        nullable=False)

    __table_args__ = (
        CheckConstraint("state in ('" + "','".join(COVERAGE_STATES) + "')",
                        name="ck_canon_coverage_state"),
        CheckConstraint("timeframe in ('1d', '1h', '15m', '1m')",
                        name="ck_canon_coverage_timeframe"),
        CheckConstraint("from_date <= to_date and sessions >= 1 and bars >= 0 "
                        "and quarantined >= 0", name="ck_canon_coverage_range"),
        CheckConstraint("(state = 'DATA') = (bars > 0)", name="ck_canon_coverage_data"),
        Index("ix_canon_coverage_state", "timeframe", "state"),
    )
