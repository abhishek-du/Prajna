"""Contract tables: the trading calendar and temporal instrument identity."""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, ProvenanceMixin

LIFECYCLE_STATES = ("ACTIVE", "REMOVED_FROM_MASTER", "VENDOR_REJECTED", "INELIGIBLE")
LIFECYCLE_SQL = ", ".join(f"'{s}'" for s in LIFECYCLE_STATES)


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

    # Listing lifecycle (hardening phase 2). valid_from/valid_to above are the
    # IDENTITY version and are never closed because a key left the master; the
    # listing state is the current row of instrument_lifecycle_period, cached
    # here. Jobs and completeness gates use lifecycle_status = 'ACTIVE'.
    lifecycle_status: Mapped[str] = mapped_column(String(24), nullable=False,
                                                  server_default="ACTIVE")
    first_seen: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    last_seen: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        CheckConstraint(f"lifecycle_status in ({LIFECYCLE_SQL})",
                        name="ck_instrument_lifecycle_status"),
        Index("ix_instrument_lifecycle", "lifecycle_status"),
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


class InstrumentLifecyclePeriod(Base, ProvenanceMixin):
    """Append-only history of an instrument's listing state.

    One row per period [valid_from, valid_to) in one state, never overlapping
    for an instrument (GiST). A transition closes the open period and opens a
    new one; nothing is deleted, so "was X listed at T" stays answerable.
    knowable_at is when Prajna held the master (or vendor evidence) that
    established the state.

      ACTIVE               in the vendor master and selectable
      REMOVED_FROM_MASTER  absent from a fully parsed vendor master
      INELIGIBLE           still in the master, no longer in the S1 selection
      VENDOR_REJECTED      in the master, but the vendor rejects its key
                           (UDAPI100011 on >= 2 distinct sessions)
    """

    __tablename__ = "instrument_lifecycle_period"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instrument.instrument_id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    valid_from: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    valid_to: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                   server_default="infinity")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        ExcludeConstraint(
            ("instrument_id", "="),
            (text("tstzrange(valid_from, valid_to, '[)')"), "&&"),
            name="ex_lifecycle_no_overlap", using="gist",
        ),
        CheckConstraint("valid_from < valid_to", name="ck_lifecycle_order"),
        CheckConstraint(f"status in ({LIFECYCLE_SQL})", name="ck_lifecycle_status"),
        CheckConstraint("knowable_at <= fetched_at", name="ck_lifecycle_knowable"),
        Index("ix_lifecycle_instrument", "instrument_id", "valid_from"),
    )


class InstrumentAttributeVersion(Base, ProvenanceMixin):
    """Append-only history of an instrument's vendor attributes.

    The vendor changes attributes often (2026-09-23 -> 09-25: 16 instruments,
    e.g. EQ<->BE series moves, SME->EQ migration, PCA flags, CHAVDA lot size
    1000 -> 2000 after its bonus). instrument_id stays stable; each attribute
    state is a version [valid_from, valid_to), non-overlapping (GiST). The
    instrument row's attribute columns are a cache of the open version, kept
    in the same transaction and checked by a consistency gate.
    """

    __tablename__ = "instrument_attribute_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instrument.instrument_id", ondelete="RESTRICT"), nullable=False)
    trading_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    instrument_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    security_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exchange_token: Mapped[str | None] = mapped_column(String(24), nullable=True)
    lot_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    freeze_quantity: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    qty_multiplier: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    cas_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    valid_to: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                   server_default="infinity")

    __table_args__ = (
        ExcludeConstraint(
            ("instrument_id", "="),
            (text("tstzrange(valid_from, valid_to, '[)')"), "&&"),
            name="ex_attr_version_no_overlap", using="gist",
        ),
        CheckConstraint("valid_from < valid_to", name="ck_attr_version_order"),
        CheckConstraint("knowable_at <= fetched_at", name="ck_attr_version_knowable"),
        Index("ix_attr_version_instrument", "instrument_id", "valid_from"),
    )


SECURITY_CLASSES = ("STOCK", "FUND_UNIT", "RIGHTS_ENTITLEMENT", "OTHER")
CLASS_STATUSES = ("CLASSIFIED", "REVIEW", "UNCLASSIFIED")


class InstrumentSecurityClass(Base):
    """What kind of security an instrument is (hardening phase 3). Derived.

    STOCK               equity of an operating company (the D sector universe)
    FUND_UNIT           a mutual-fund / ETF scheme unit
    RIGHTS_ENTITLEMENT  a tradeable rights entitlement (-RE)
    OTHER               anything else, with a subclass (INVIT_UNIT, INDEX, GLOBAL)

    A class needs >= 2 agreeing independent signals and no contradicting one;
    a contradiction is REVIEW, too little evidence UNCLASSIFIED (class NULL).
    Every signal's raw value and vote is kept in `signals`, so each decision
    is explainable. Current-state metadata (not point-in-time): recomputed by
    `prajna classify securities` after each master refresh / fundamentals sweep.
    """

    __tablename__ = "instrument_security_class"

    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instrument.instrument_id", ondelete="RESTRICT"),
        primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    security_class: Mapped[str | None] = mapped_column(String(24), nullable=True)
    subclass: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    signals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    method_version: Mapped[str] = mapped_column(String(32), nullable=False)
    classified_at: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"), nullable=False)

    __table_args__ = (
        CheckConstraint("security_class is null or security_class in "
                        "('STOCK','FUND_UNIT','RIGHTS_ENTITLEMENT','OTHER')",
                        name="ck_secclass_class"),
        CheckConstraint("status in ('CLASSIFIED','REVIEW','UNCLASSIFIED')",
                        name="ck_secclass_status"),
        CheckConstraint("(status = 'CLASSIFIED') = (security_class is not null)",
                        name="ck_secclass_classified_has_class"),
        Index("ix_secclass_class", "security_class", "status"),
    )
