"""Results events and the event-driven fundamentals refresh (migration 0023; docs/
STAGE1_FUNDAMENTALS_RND.md F1/F2/F4/F5b). Append-only (trigger)."""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
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


class ResultsEvent(Base):
    """INTIMATION (results calendar), OUTCOME (results disseminated), HISTORICAL_FILING
    (a user-exported NSE CSV row) or ESTIMATE_NEWS (beat / miss / in-line headline)."""

    __tablename__ = "results_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    news_item_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("news_item.id"),
                                                     nullable=True)
    meeting_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    period_kind: Mapped[str | None] = mapped_column(String(4), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False,
                                             server_default=text("'{}'::text[]"))
    event_at: Mapped[_dt.datetime | None] = mapped_column(TS, nullable=True)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    text_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("kind in ('INTIMATION','OUTCOME','HISTORICAL_FILING','ESTIMATE_NEWS')",
                        name="ck_results_event_kind"),
        CheckConstraint("verdict is null or verdict in ('BEAT','MISS','INLINE','MIXED')",
                        name="ck_results_event_verdict"),
        CheckConstraint("(kind = 'ESTIMATE_NEWS') = (verdict is not null)",
                        name="ck_results_event_verdict_kind"),
        CheckConstraint("(kind = 'HISTORICAL_FILING') = (news_item_id is null)",
                        name="ck_results_event_news"),
        CheckConstraint("event_at is null or event_at <= knowable_at",
                        name="ck_results_event_knowable"),
        UniqueConstraint("kind", "instrument_key", "text_sha256", "parser_version",
                         name="uq_results_event_text"),
        Index("ix_results_event_key_kind", "instrument_key", "kind", "knowable_at"),
        Index("ix_results_event_news", "news_item_id"),
    )


class FundamentalRefresh(Base):
    """One event-driven refresh of one instrument's fundamentals (F1)."""

    __tablename__ = "fundamental_refresh"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("results_event.id"),
                                          nullable=False)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    isin: Mapped[str] = mapped_column(String(12), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshots_inserted: Mapped[int] = mapped_column(Integer, nullable=False)
    refreshed_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    authz_token_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", "instrument_key", name="uq_fundamental_refresh_event"),
    )
