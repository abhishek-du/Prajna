"""Stage 4 v2 P1 shadow records (migration 0027). Append-only (trigger); every trade row
is mode 'SHADOW' by CHECK: nothing here can describe an order."""

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
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.dialects.postgresql import TIMESTAMP as _TS
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TS = _TS(timezone=True)
PX = Numeric(18, 4)
EXIT_REASONS = ("STOP", "STOP_GAP", "TARGET", "TIME_NOT_WORKING", "EOD", "NO_EXIT_BAR")
SKIP_REASONS = ("SKIP_RRR", "CHECKLIST_LT4", "CAP_OPEN_RISK", "CAP_SECTOR", "CAP_LIQUIDITY",
                "HALT_DAILY", "MOVE_GT_3PCT", "NO_INTRADAY_BARS")
CHECKPOINTS = ("PRE", "OPEN", "0930", "1030", "1200", "1330")
STATES = ("SHOCK", "EVENT_WAIT", "TREND_UP", "TREND_DOWN", "RANGE", "MIXED")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} in (" + ",".join(f"'{v}'" for v in vals) + ")"


def _run_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("shadow_run.run_id"), nullable=False)


class ShadowPolicy(Base):
    """A frozen policy version: the spec, its sha, the code and calendar it froze with."""

    __tablename__ = "shadow_policy"

    policy_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False)
    spec_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    code_git_sha: Mapped[str] = mapped_column(String(48), nullable=False)
    event_calendar_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    forward_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    frozen_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    authz_token_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class ShadowRun(Base):
    """One shadow session of one policy (unique per policy and session)."""

    __tablename__ = "shadow_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    policy_version: Mapped[str] = mapped_column(
        String(32), ForeignKey("shadow_policy.policy_version"), nullable=False)
    market_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cutoff: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    inputs_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    rows_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    code_git_sha: Mapped[str] = mapped_column(String(48), nullable=False)
    authz_token_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        UniqueConstraint("policy_version", "market_date", name="uq_shadow_run_policy_date"),
        CheckConstraint("status in ('DONE','SKIPPED')", name="ck_shadow_run_status"),
        CheckConstraint("(status = 'SKIPPED') = (reason is not null)",
                        name="ck_shadow_run_reason"),
    )


class RegimeSnapshot(Base):
    """The regime state at one checkpoint of a session."""

    __tablename__ = "regime_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    market_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    checkpoint: Mapped[str] = mapped_column(String(8), nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_fired: Mapped[str] = mapped_column(Text, nullable=False)
    risk_mult: Mapped[float] = mapped_column(Float, nullable=False)
    day_type: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        UniqueConstraint("policy_version", "market_date", "checkpoint",
                         name="uq_regime_snapshot_policy_date_cp"),
        CheckConstraint(_in("checkpoint", CHECKPOINTS), name="ck_regime_snapshot_checkpoint"),
        CheckConstraint(_in("state", STATES), name="ck_regime_snapshot_state"),
    )


class ShadowTrade(Base):
    """A trade a strategy would have taken (or its placebo mirror), simulated on 1m bars."""

    __tablename__ = "shadow_trade"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    market_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    side: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_placebo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    signal_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    entry_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    exit_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    time_stop: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    entry_raw: Mapped[Decimal] = mapped_column(PX, nullable=False)
    stop: Mapped[Decimal] = mapped_column(PX, nullable=False)
    target: Mapped[Decimal] = mapped_column(PX, nullable=False)
    atr: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[int] = mapped_column(BigInteger, nullable=False)
    size_factor: Mapped[float] = mapped_column(Float, nullable=False)
    risk_inr: Mapped[Decimal] = mapped_column(PX, nullable=False)
    rrr: Mapped[float] = mapped_column(Float, nullable=False)
    checklist: Mapped[dict] = mapped_column(JSONB, nullable=False)
    checklist_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    exit_raw: Mapped[Decimal] = mapped_column(PX, nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_px: Mapped[Decimal] = mapped_column(PX, nullable=False)
    exit_px: Mapped[Decimal] = mapped_column(PX, nullable=False)
    gross_inr: Mapped[Decimal] = mapped_column(PX, nullable=False)
    charges: Mapped[dict] = mapped_column(JSONB, nullable=False)
    net_inr: Mapped[Decimal] = mapped_column(PX, nullable=False)
    net_r: Mapped[float] = mapped_column(Float, nullable=False)
    by_slippage: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    regime_state: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_mult: Mapped[float] = mapped_column(Float, nullable=False)
    day_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    guard_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)

    __table_args__ = (
        UniqueConstraint("policy_version", "market_date", "strategy", "instrument_key",
                         "is_placebo", name="uq_shadow_trade_natural"),
        CheckConstraint("side in (-1, 1)", name="ck_shadow_trade_side"),
        CheckConstraint("qty > 0", name="ck_shadow_trade_qty"),
        CheckConstraint("entry_at < exit_at", name="ck_shadow_trade_times"),
        CheckConstraint(_in("exit_reason", EXIT_REASONS), name="ck_shadow_trade_exit"),
        CheckConstraint("mode = 'SHADOW'", name="ck_shadow_trade_shadow_only"),
    )


class ShadowSkip(Base):
    """A candidate a strategy rejected, with its closed-list reason."""

    __tablename__ = "shadow_skip"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    market_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    signal_at: Mapped[_dt.datetime | None] = mapped_column(TS, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("policy_version", "market_date", "strategy", "instrument_key",
                         name="uq_shadow_skip_natural"),
        CheckConstraint(_in("reason", SKIP_REASONS), name="ck_shadow_skip_reason"),
    )
