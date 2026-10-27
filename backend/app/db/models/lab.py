"""Strategy Lab records (migration 0030): switches, lab runs, per-day strategy performance,
trade and day forensics, the morning brief. Append-only (trigger); a recomputation is a
new lab_run and readers take the latest run of a session. PAPER/SHADOW research only."""

from __future__ import annotations

import datetime as _dt
import uuid
from decimal import Decimal

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
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import TIMESTAMP as _TS
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TS = _TS(timezone=True)
PX = Numeric(18, 4)
INR = Numeric(18, 2)


def _run_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("lab_run.run_id"), nullable=False)


class StrategySwitch(Base):
    """An admin on/off decision; the latest row per strategy is its current state."""

    __tablename__ = "strategy_switch"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    authz_token_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False,
                                                     server_default=text("clock_timestamp()"))

    __table_args__ = (Index("ix_strategy_switch_strategy", "strategy", "id"),)


class LabRun(Base):
    __tablename__ = "lab_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    lab_version: Mapped[str] = mapped_column(String(32), nullable=False)
    inputs_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    code_git_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False,
                                                     server_default=text("clock_timestamp()"))

    __table_args__ = (
        CheckConstraint("kind in ('DAILY','BRIEF')", name="ck_lab_run_kind"),
        Index("ix_lab_run_session", "kind", "session_date", "created_at"),
    )


class StrategyDay(Base):
    __tablename__ = "strategy_day"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    family: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trades: Mapped[int] = mapped_column(Integer, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_inr: Mapped[Decimal] = mapped_column(INR, nullable=False)
    charges_inr: Mapped[Decimal] = mapped_column(INR, nullable=False)
    net_inr: Mapped[Decimal] = mapped_column(INR, nullable=False)
    net_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    placebo_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    placebo_net_inr: Mapped[Decimal | None] = mapped_column(INR, nullable=True)
    regime_pre: Mapped[str | None] = mapped_column(String(16), nullable=True)
    regime_open: Mapped[str | None] = mapped_column(String(16), nullable=True)
    day_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    equity_inr: Mapped[Decimal] = mapped_column(INR, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "strategy", name="uq_strategy_day_run"),
        Index("ix_strategy_day_session", "session_date", "strategy"),
    )


class TradeForensic(Base):
    __tablename__ = "trade_forensic"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    family: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    side: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_placebo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    signal_at: Mapped[_dt.datetime | None] = mapped_column(TS, nullable=True)
    entry_at: Mapped[_dt.datetime | None] = mapped_column(TS, nullable=True)
    exit_at: Mapped[_dt.datetime | None] = mapped_column(TS, nullable=True)
    entry_px: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    exit_px: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    stop: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    target: Mapped[Decimal | None] = mapped_column(PX, nullable=True)
    qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_inr: Mapped[Decimal | None] = mapped_column(INR, nullable=True)
    net_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome_class: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_rule: Mapped[str] = mapped_column(Text, nullable=False)
    mfe_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_after_exit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    regime_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    day_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    first_news_lag_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_before: Mapped[list] = mapped_column(JSONB, nullable=False)
    news_after: Mapped[list] = mapped_column(JSONB, nullable=False)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False)
    path: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "source", "source_id", name="uq_trade_forensic_run"),
        Index("ix_trade_forensic_session", "session_date", "strategy"),
    )


class DayForensic(Base):
    __tablename__ = "day_forensic"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    thought: Mapped[dict] = mapped_column(JSONB, nullable=False)
    happened: Mapped[dict] = mapped_column(JSONB, nullable=False)
    why: Mapped[list] = mapped_column(JSONB, nullable=False)
    narrative: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "strategy", name="uq_day_forensic_run"),)


class DailyBrief(Base):
    __tablename__ = "daily_brief"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    regime: Mapped[dict] = mapped_column(JSONB, nullable=False)
    events: Mapped[dict] = mapped_column(JSONB, nullable=False)
    candidates: Mapped[dict] = mapped_column(JSONB, nullable=False)
    news: Mapped[list] = mapped_column(JSONB, nullable=False)
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("run_id", name="uq_daily_brief_run"),)
