"""Stage 7 paper execution records (migration 0022). Append-only (trigger); every row is
mode 'PAPER' by CHECK: nothing here can describe a live order."""

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
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import TIMESTAMP as _TS
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TS = _TS(timezone=True)
MONEY = Numeric(18, 4)


def _mode(t: str) -> CheckConstraint:
    return CheckConstraint("mode = 'PAPER'", name=f"ck_{t}_paper_only")


class PaperRun(Base):
    """One simulated session of one strategy (unique per strategy and session)."""

    __tablename__ = "paper_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    targets_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    inputs_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    target_list: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_limits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    bars_knowable_max: Mapped[_dt.datetime | None] = mapped_column(TS, nullable=True)
    code_git_sha: Mapped[str] = mapped_column(String(48), nullable=False)
    authz_token_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        UniqueConstraint("strategy", "session_date", name="uq_paper_run_strategy_session"),
        _mode("paper_run"),
    )


class PaperOrder(Base):
    """A target of the run, in priority order (MIS: buy at the open, sell at the close)."""

    __tablename__ = "paper_order"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                              ForeignKey("paper_run.run_id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    product: Mapped[str] = mapped_column(String(8), nullable=False)
    order_value_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "instrument_key", name="uq_paper_order_run_key"),
        UniqueConstraint("run_id", "seq", name="uq_paper_order_run_seq"),
        CheckConstraint("product = 'MIS'", name="ck_paper_order_mis"),
        _mode("paper_order"),
    )


class PaperFill(Base):
    """The simulated outcome of one order (NOT_FILLED with its reason included)."""

    __tablename__ = "paper_fill"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                              ForeignKey("paper_run.run_id"), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    qty: Mapped[int] = mapped_column(BigInteger, nullable=False)
    buy_px: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    sell_px: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    buy_value_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    sell_value_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    charges: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pnl_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "instrument_key", name="uq_paper_fill_run_key"),
        CheckConstraint("status in ('FILLED','PARTIAL','NOT_FILLED')",
                        name="ck_paper_fill_status"),
        CheckConstraint("(qty > 0) = (status <> 'NOT_FILLED')", name="ck_paper_fill_qty"),
        _mode("paper_fill"),
    )


class PaperDay(Base):
    """The session summary of a run (cash, P&L, charges, turnover, fill counts)."""

    __tablename__ = "paper_day"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                              ForeignKey("paper_run.run_id"), primary_key=True)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    targets: Mapped[int] = mapped_column(Integer, nullable=False)
    filled: Mapped[int] = mapped_column(Integer, nullable=False)
    not_filled: Mapped[dict] = mapped_column(JSONB, nullable=False)
    start_cash_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    end_cash_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    pnl_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    charges_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    turnover_inr: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)

    __table_args__ = (_mode("paper_day"),)


class PaperRiskDecision(Base):
    """The Stage 6 decision on one target of a run (REJECTED carries its reason)."""

    __tablename__ = "paper_risk_decision"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                              ForeignKey("paper_run.run_id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "instrument_key", name="uq_paper_risk_decision_run_key"),
        CheckConstraint("decision in ('APPROVED','REJECTED')",
                        name="ck_paper_risk_decision_decision"),
        CheckConstraint("(decision = 'REJECTED') = (reason is not null)",
                        name="ck_paper_risk_decision_reason"),
        _mode("paper_risk_decision"),
    )
