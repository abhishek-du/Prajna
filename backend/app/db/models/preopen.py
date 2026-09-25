"""NSE pre-open, captured from the Upstox Market Data Feed V3 WebSocket.

WHY WEBSOCKET AND NOT REST — verified 2026-09-22: the REST Full Market Quote
(/v2/market-quote/quotes) returns none of iep / ieq / iiqTotal / iiqM / rp /
casEligible. Its schema stops at total_buy_quantity, total_sell_quantity and a
5-level depth. The equilibrium data exists ONLY on the WS v3 `full` feed, so
capture is a stream recording, not a poll.

Column names mirror the vendor's protobuf exactly (MarketFullFeed, pinned at
assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto) so a reader can
map a column to a wire field with no guesswork:

    iep=11  rp=12  ieq=13  iiqTotal=14  iiqM=15  casEligible=16  tbq=9  tsq=10

Each frame becomes a row. We therefore retain the whole 09:00->09:15 evolution
of the equilibrium price and the order imbalance, which is itself the signal —
not a single end-state snapshot.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, ProvenanceMixin

# Prices as NUMERIC, never double precision. V1's own V2 module recorded that
# float casting destroys the decimals the vendor sent.
_PRICE = Numeric(18, 4)
_QTY = Numeric(22, 2)


class PreopenTick(Base, ProvenanceMixin):
    __tablename__ = "preopen_tick"

    tick_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    session_date: Mapped[_dt.date] = mapped_column(
        Date, ForeignKey("trading_session.session_date", ondelete="RESTRICT"), nullable=False
    )
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("instrument.instrument_id", ondelete="RESTRICT"), nullable=True
    )

    frame_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # FeedResponse.currentTs — epoch ms, converted to tz-aware UTC.
    vendor_ts: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    feed_type: Mapped[str] = mapped_column(String(16), nullable=False)      # initial_feed|live_feed
    request_mode: Mapped[str] = mapped_column(String(16), nullable=False)   # full_d5|full_d30

    # ── equilibrium / imbalance (MarketFullFeed) ────────────────────────────
    iep: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    ieq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    iiq_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    iiq_m: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rp: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    tbq: Mapped[float | None] = mapped_column(_QTY, nullable=True)
    tsq: Mapped[float | None] = mapped_column(_QTY, nullable=True)
    cas_eligible: Mapped[bool | None] = mapped_column(nullable=True)

    # ── auxiliary market state ──────────────────────────────────────────────
    atp: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    vtt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi: Mapped[float | None] = mapped_column(_QTY, nullable=True)
    iv: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)

    # ── LTPC ────────────────────────────────────────────────────────────────
    ltp: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    ltt: Mapped[_dt.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    ltq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cp: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    # LTPC.iep is a DoubleValue wrapper (nullable on the wire), kept separately
    # from MarketFullFeed.iep so we never conflate "absent" with "zero".
    ltpc_iep: Mapped[float | None] = mapped_column(_PRICE, nullable=True)

    __table_args__ = (
        # Frames at distinct vendor timestamps are distinct observations and
        # BOTH are kept. Re-ingesting the same frame is a no-op.
        UniqueConstraint(
            "session_date", "instrument_key", "vendor_ts", "source",
            name="uq_preopen_tick_observation",
        ),
        CheckConstraint("knowable_at <= fetched_at", name="ck_preopen_tick_knowable"),
        CheckConstraint("iep is null or iep >= 0", name="ck_preopen_tick_iep_sign"),
        Index("ix_preopen_tick_session_instr", "session_date", "instrument_key"),
        Index("ix_preopen_tick_session_vendor_ts", "session_date", "vendor_ts"),
    )


class PreopenBook(Base):
    """The depth ladder for one tick.

    Upstox pairs bid and ask in a single `Quote` message, so each rung carries
    both sides — richer than NSE's own single-sided pre-open ladder. 5 rungs on
    the `full` feed, 30 on `full_d30` (Upstox Plus only; open blocker B3).

    No ProvenanceMixin: a rung's provenance is its parent tick's, and
    duplicating it would invite the two to disagree.
    """

    __tablename__ = "preopen_book"

    tick_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("preopen_tick.tick_id", ondelete="RESTRICT"), primary_key=True
    )
    rung_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    bid_qty: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bid_price: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    ask_qty: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ask_price: Mapped[float | None] = mapped_column(_PRICE, nullable=True)

    __table_args__ = (
        CheckConstraint("rung_no >= 0 and rung_no < 30", name="ck_preopen_book_rung_range"),
    )


class PreopenSessionStatus(Base, ProvenanceMixin):
    """MarketInfo.preOpenSessionStatus transitions.

    The vendor reports these as StatusInfo{status, updatedTime} keyed by
    segment. `status` is stored as the vendor's own string (PRE_OPEN_START,
    PRE_OPEN_M_END, PRE_OPEN_END) rather than mapped to an enum: the proto's
    MarketStatus enum does not contain PRE_OPEN_M_END, so an enum here would
    silently drop a real transition.
    """

    __tablename__ = "preopen_session_status"

    session_date: Mapped[_dt.date] = mapped_column(
        Date, ForeignKey("trading_session.session_date", ondelete="RESTRICT"), primary_key=True
    )
    segment: Mapped[str] = mapped_column(String(24), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), primary_key=True)
    vendor_updated_at: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True
    )
    observed_at: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("knowable_at <= fetched_at", name="ck_preopen_status_knowable"),
        Index("ix_preopen_status_session", "session_date"),
    )
