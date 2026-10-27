"""Research Desk records (migration 0031): runs, dossiers, verdicts, the watchlist event
log and the suggestion tracking events. Append-only (trigger). PAPER ONLY."""

from __future__ import annotations

import datetime as _dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
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
PX = Numeric(18, 4)
NOW = text("clock_timestamp()")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} in (" + ",".join(f"'{v}'" for v in vals) + ")"


class DeskRun(Base):
    __tablename__ = "desk_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    desk_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    code_git_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False, server_default=NOW)

    __table_args__ = (
        CheckConstraint(_in("kind", ("EVENING", "MORNING", "INTRADAY")), name="ck_desk_run_kind"),
        Index("ix_desk_run_session", "session_date", "created_at"),
    )


class DeskDossier(Base):
    __tablename__ = "desk_dossier"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("desk_run.run_id"),
                                              nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    packet: Mapped[dict] = mapped_column(JSONB, nullable=False)
    packet_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    __table_args__ = (UniqueConstraint("run_id", "instrument_key", name="uq_desk_dossier_run"),)


class DeskVerdict(Base):
    __tablename__ = "desk_verdict"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("desk_run.run_id"),
                                              nullable=False)
    dossier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("desk_dossier.id"),
                                            nullable=False)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    horizon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    pov: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    entry_lo: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    entry_hi: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    stop: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    t1: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    t2: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    levels_basis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    why_moved: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    risks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    invalidation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    rule_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    rule_plan: Mapped[dict] = mapped_column(JSONB, nullable=False)
    conflicts: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    response_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("run_id", "instrument_key", name="uq_desk_verdict_run"),
        CheckConstraint(_in("status", ("OK", "INVALID", "ERROR")), name="ck_desk_verdict_status"),
        CheckConstraint("decision is null or " + _in("decision", (
            "STRONG_BUY", "BUY", "WATCH", "AVOID", "SELL")), name="ck_desk_verdict_decision"),
        CheckConstraint("status <> 'OK' or decision is not null",
                        name="ck_desk_verdict_ok_has_decision"),
        Index("ix_desk_verdict_key", "instrument_key", "created_at"),
        Index("ix_desk_verdict_session", "session_date", "score"),
    )


class DeskWatchEvent(Base):
    __tablename__ = "desk_watch_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_key: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    verdict_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("desk_verdict.id"),
                                                   nullable=True)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False, server_default=NOW)

    __table_args__ = (
        CheckConstraint(_in("event", ("ADD", "REMOVE", "UPDATE")), name="ck_desk_watch_event"),
        Index("ix_desk_watch_key", "instrument_key", "id"),
    )


class DeskTrackEvent(Base):
    __tablename__ = "desk_track_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    verdict_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("desk_verdict.id"),
                                            nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("verdict_id", "kind", name="uq_desk_track_once"),
        CheckConstraint(_in("kind", ("ENTRY_TRIGGERED", "T1", "T2", "STOP", "EXPIRED",
                                     "INVALIDATED")), name="ck_desk_track_kind"),
    )
