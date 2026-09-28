"""Multi-source news (decision NEWS-SOURCES, 2026-09-28): polls, source items,
their later observations, and versioned enrichments. Everything is append-only
(trigger); a later classification or mapping is a new row, so a past as_of
always sees what was knowable then. knowable_at of an item is when PRAJNA first
saw it (discovered_at), never the publisher's published_at."""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TS = TIMESTAMP(timezone=True)


class NewsPoll(Base):
    """One request to one source (a 304 is a poll too)."""

    __tablename__ = "news_poll"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.run_id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    finished_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_new: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_changed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    backlog: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    payload_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("mode in ('SHADOW','PRODUCTION')", name="ck_news_poll_mode"),
        CheckConstraint("outcome in ('OK','NOT_MODIFIED','RATE_LIMITED','BLOCKED',"
                        "'AUTH_FAILED','ERROR','MALFORMED')", name="ck_news_poll_outcome"),
        CheckConstraint("finished_at >= started_at", name="ck_news_poll_time"),
        Index("ix_news_poll_source_time", "source", "started_at"),
    )


class NewsItem(Base):
    """One article/filing of one source, as first seen by Prajna."""

    __tablename__ = "news_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_article_id: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_norm_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    category_raw: Mapped[str | None] = mapped_column(Text)
    symbol_raw: Mapped[str | None] = mapped_column(String(64))
    attachment_url: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(8))
    region: Mapped[str | None] = mapped_column(String(8))
    published_at: Mapped[_dt.datetime | None] = mapped_column(TS)
    published_at_raw: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[_dt.datetime | None] = mapped_column(TS)
    discovered_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    backlog: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    first_poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_poll.id", ondelete="RESTRICT"), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "source_article_id", name="uq_news_item_source_id"),
        CheckConstraint("knowable_at >= discovered_at", name="ck_news_item_knowable"),
        Index("ix_news_item_knowable", "knowable_at"),
        Index("ix_news_item_title_hash", "title_norm_hash"),
    )


class NewsItemObservation(Base):
    """A later sighting whose title / times / summary DIFFER from the stored item."""

    __tablename__ = "news_item_observation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_poll.id", ondelete="RESTRICT"), nullable=False)
    observed_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[_dt.datetime | None] = mapped_column(TS)
    source_updated_at: Mapped[_dt.datetime | None] = mapped_column(TS)
    changed: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)

    __table_args__ = (Index("ix_news_obs_item", "item_id"),)


class NewsClassification(Base):
    __tablename__ = "news_classification"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    classified_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("confidence between 0 and 1", name="ck_news_class_conf"),
        CheckConstraint("knowable_at >= classified_at", name="ck_news_class_knowable"),
        UniqueConstraint("item_id", "method", "version", name="uq_news_class"),
    )


class NewsEntityLink(Base):
    __tablename__ = "news_entity_link"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    instrument_key: Mapped[str | None] = mapped_column(String(80))
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    matched_text: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    mapped_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("method in ('EXACT_SYMBOL','ISIN','COMPANY_NAME','ALIAS',"
                        "'MANUAL_RULE','ENTITY_MODEL','UNRESOLVED')", name="ck_news_link_method"),
        CheckConstraint("(method = 'UNRESOLVED') = (instrument_key is null)",
                        name="ck_news_link_unresolved"),
        CheckConstraint("confidence between 0 and 1", name="ck_news_link_conf"),
        CheckConstraint("knowable_at >= mapped_at", name="ck_news_link_knowable"),
        UniqueConstraint("item_id", "version", "instrument_key", name="uq_news_link"),
        Index("ix_news_link_instrument", "instrument_key"),
    )


class NewsAudit(Base):
    """Refusals, kill-switch changes and mode changes of the news collector."""

    __tablename__ = "news_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False, server_default=text("now()"))
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str | None] = mapped_column(String(40))
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        CheckConstraint("event in ('REFUSED','KILL_ON','KILL_OFF','BLOCKED')",
                        name="ck_news_audit_event"),
    )
