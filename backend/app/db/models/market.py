"""Market data: OHLCV bars and the (dormant) tick archive."""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, ProvenanceMixin

_PRICE = Numeric(18, 4)


class OhlcvBar(Base, ProvenanceMixin):
    """One vendor's observation of one bar.

    THREE DESIGN DECISIONS, EACH FIXING A MEASURED V1 FAILURE:

    1. `session_date` is a STORED column, not `timestamp::date`. V1 derived it
       and ended up with 14 distinct daily anchors in one table, 1,106,322
       duplicated symbol-days, and 79,617 of those disagreeing on the close.

    2. `source` is part of the PRIMARY KEY. Two vendors observing the same bar
       produce two rows; neither can overwrite the other. Resolution is a
       read-time precedence decision in Stage 2, not a silent write-time race.
       (V2 is Upstox-only today, but the same instrument can legitimately be
       observed via REST v3 historical and via the WS feed.)

    3. `vendor_ts_raw` keeps the vendor's own string verbatim. Upstox stamps a
       daily bar '2026-09-01T00:00:00+05:30' — a DATE LABEL, not an instant.
       Converting it as an instant yields 18:30 UTC on the PREVIOUS day, which
       is the single defect that produced V1's legacy series. Keeping the raw
       string means the conversion is always re-checkable.
    """

    __tablename__ = "ohlcv_bar"

    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instrument.instrument_id", ondelete="RESTRICT"), primary_key=True
    )
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    session_date: Mapped[_dt.date] = mapped_column(Date, primary_key=True)
    bar_start_utc: Mapped[_dt.datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)  # noqa: F811

    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)

    open: Mapped[float] = mapped_column(_PRICE, nullable=False)
    high: Mapped[float] = mapped_column(_PRICE, nullable=False)
    low: Mapped[float] = mapped_column(_PRICE, nullable=False)
    close: Mapped[float] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(22, 0), nullable=False)
    open_interest: Mapped[float | None] = mapped_column(Numeric(22, 0), nullable=True)

    vendor_ts_raw: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "high >= low and high >= open and high >= close "
            "and low <= open and low <= close and volume >= 0",
            name="ck_ohlcv_sane",
        ),
        CheckConstraint("knowable_at <= fetched_at", name="ck_ohlcv_knowable"),
        Index("ix_ohlcv_instrument_tf_session", "instrument_id", "timeframe", "session_date"),
        Index("ix_ohlcv_tf_session", "timeframe", "session_date"),
        Index("ix_ohlcv_key_tf", "instrument_key", "timeframe"),
    )


class TickArchive(Base, ProvenanceMixin):
    """Full-universe tick persistence.

    SCHEMA ONLY. The writer is disabled by PRAJNA_TICK_PERSISTENCE_ENABLED
    (default false) and stays off until Stage 7 execution justifies the volume.
    The table exists from migration 0001 so the contract is fixed now rather
    than bolted on later.
    """

    __tablename__ = "tick_archive"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    vendor_ts: Mapped[_dt.datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ltp: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    ltq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vtt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    atp: Mapped[float | None] = mapped_column(_PRICE, nullable=True)
    tbq: Mapped[float | None] = mapped_column(Numeric(22, 2), nullable=True)
    tsq: Mapped[float | None] = mapped_column(Numeric(22, 2), nullable=True)

    __table_args__ = (
        CheckConstraint("knowable_at <= fetched_at", name="ck_tick_knowable"),
        Index("ix_tick_session_instr", "session_date", "instrument_key"),
    )
