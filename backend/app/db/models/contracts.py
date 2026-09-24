"""Contract tables: the trading calendar and temporal instrument identity."""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, Index, Integer, Numeric, String, Text, Time, text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, ProvenanceMixin


class TradingSession(Base, ProvenanceMixin):
    """One row per calendar date, trading or not.

    A session is an explicit assertion with a source, never the absence of a
    row. V1 could not distinguish "2026-09-14 was a holiday" from "ingestion
    failed on 2026-09-14" because its calendar was an 8-line text file.

    Session times are per-row because NSE's are not constant: 2026-11-08 is a
    Sunday Muhurat session running 18:00-19:00 IST, and 2026-02-01 was a full
    Sunday Budget-day session.
    """

    __tablename__ = "trading_session"

    session_date: Mapped[_dt.date] = mapped_column(Date, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(nullable=False)
    session_type: Mapped[str] = mapped_column(String(16), nullable=False)
    preopen_start_ist: Mapped[_dt.time | None] = mapped_column(Time, nullable=True)
    preopen_end_ist: Mapped[_dt.time | None] = mapped_column(Time, nullable=True)
    open_ist: Mapped[_dt.time | None] = mapped_column(Time, nullable=True)
    close_ist: Mapped[_dt.time | None] = mapped_column(Time, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "session_type in ('NORMAL','MUHURAT','SPECIAL','HOLIDAY','WEEKEND')",
            name="ck_session_type",
        ),
        # A trading day has hours, except a PAST special session (Budget
        # Saturday, Muhurat, DR drill) whose hours Upstox does not give for past
        # dates: NULL = unknown, with the reason in `note` (never invented).
        CheckConstraint(
            "not is_trading_day or session_type = 'SPECIAL' "
            "or (open_ist is not null and close_ist is not null)",
            name="ck_session_trading_has_hours",
        ),
        CheckConstraint("knowable_at <= fetched_at", name="ck_trading_session_knowable"),
    )


class Instrument(Base, ProvenanceMixin):
    """SCD2 instrument identity, keyed on the Upstox instrument_key.

    NO KITE FIELDS (constraint #1 and #4). `exchange_token` is NSE's own token
    as published in Upstox's master — an exchange identifier, not a broker one.

    The EXCLUDE constraint makes overlapping validity ranges for one
    instrument_key *impossible at the database level*. V1 overwrote this table
    daily, so a rename silently changed the meaning of every historical
    reference, and two real ISIN collisions (CRESTO/SILLYMONKS,
    KDGREEN/MANBRO) had nowhere to live.
    """

    __tablename__ = "instrument"

    instrument_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)

    # NSE series (EQ/BE/SM/BZ/ST/IV/SG/...) as Upstox publishes it.
    instrument_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    security_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exchange_token: Mapped[str | None] = mapped_column(String(24), nullable=True)

    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    freeze_quantity: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    qty_multiplier: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    cas_eligible: Mapped[bool | None] = mapped_column(nullable=True)

    valid_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[_dt.date] = mapped_column(Date, nullable=False, server_default="infinity")

    __table_args__ = (
        ExcludeConstraint(
            ("instrument_key", "="),
            (text("daterange(valid_from, valid_to, '[)')"), "&&"),
            name="ex_instrument_no_overlap",
            using="gist",
        ),
        CheckConstraint("valid_from < valid_to", name="ck_instrument_validity_order"),
        CheckConstraint("knowable_at <= fetched_at", name="ck_instrument_knowable"),
        Index("ix_instrument_key", "instrument_key"),
        Index("ix_instrument_symbol", "trading_symbol"),
        Index("ix_instrument_isin", "isin"),
        Index("ix_instrument_segment_type", "segment", "instrument_type"),
    )


class InstrumentUniverseMembership(Base, ProvenanceMixin):
    """Which instruments a named universe contained on a given session.

    Recorded so a historical run can be reproduced against the universe as it
    was. V1 persisted only the COUNT of its V1 universe, never the member list,
    which is why its own rca_universe.md could not reconstruct it exactly.
    """

    __tablename__ = "instrument_universe_membership"

    universe: Mapped[str] = mapped_column(String(48), primary_key=True)
    session_date: Mapped[_dt.date] = mapped_column(Date, primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("knowable_at <= fetched_at", name="ck_universe_knowable"),
        Index("ix_universe_session", "universe", "session_date"),
    )
