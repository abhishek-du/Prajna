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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TS = TIMESTAMP(timezone=True)
_CONTENT = ("'AVAILABLE','NOT_AVAILABLE','ROBOTS_BLOCKED','TERMS_BLOCKED','PAYWALL',"
            "'HTTP_BLOCKED','ERROR'")


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
    # 0014: normalisation fields (NULL = not provided / not checked, never guessed)
    source_priority: Mapped[int | None] = mapped_column(SmallInteger)
    terms_status: Mapped[str | None] = mapped_column(String(12))
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    content_fetch_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                                      server_default="NOT_AVAILABLE")
    metadata_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    processed_at: Mapped[_dt.datetime | None] = mapped_column(TS)

    __table_args__ = (
        UniqueConstraint("source", "source_article_id", name="uq_news_item_source_id"),
        CheckConstraint("knowable_at >= discovered_at", name="ck_news_item_knowable"),
        CheckConstraint(f"content_fetch_status in ({_CONTENT})",
                        name="ck_news_item_content_status"),
        CheckConstraint("processed_at is null or processed_at >= discovered_at",
                        name="ck_news_item_processed"),
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


class NewsStory(Base):
    """One underlying event reported by one or more articles (grouping rules versioned)."""

    __tablename__ = "news_story"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    first_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (CheckConstraint("knowable_at >= created_at", name="ck_news_story_knowable"),)


class NewsStoryMember(Base):
    """An article joining a story, WHEN (knowable_at) and WHY (method, score, evidence)."""

    __tablename__ = "news_story_member"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_story.id", ondelete="RESTRICT"), nullable=False)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    joined_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("method in ('FOUNDER','SAME_URL','SAME_TITLE','SIMILAR')",
                        name="ck_news_story_member_method"),
        CheckConstraint("score between 0 and 1", name="ck_news_story_member_score"),
        CheckConstraint("knowable_at >= joined_at", name="ck_news_story_member_knowable"),
        UniqueConstraint("item_id", "rule_version", name="uq_news_story_member"),
        Index("ix_news_story_member_story", "story_id"),
    )


class NewsEntityMention(Base):
    """A non-company entity (index, sector, commodity, currency, regulator, ...)."""

    __tablename__ = "news_entity_mention"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    mapped_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("entity_type in ('INDEX','SECTOR','COMMODITY','CURRENCY','BOND_YIELD',"
                        "'GEOPOLITICAL','REGULATOR','GOVERNMENT','CENTRAL_BANK','MACRO_INDICATOR',"
                        "'EXCHANGE','COURT')", name="ck_news_mention_type"),
        CheckConstraint("confidence between 0 and 1", name="ck_news_mention_conf"),
        CheckConstraint("knowable_at >= mapped_at", name="ck_news_mention_knowable"),
        UniqueConstraint("item_id", "entity_type", "entity_id", "version", name="uq_news_mention"),
    )


class NewsAssessment(Base):
    """Potential relevance (NOT a price prediction): scope, impact, direction, breaking."""

    __tablename__ = "news_assessment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    basis: Mapped[str] = mapped_column(String(8), nullable=False)
    market_scope: Mapped[str] = mapped_column(String(8), nullable=False)
    potential_impact: Mapped[str] = mapped_column(String(8), nullable=False)
    impact_direction: Mapped[str] = mapped_column(String(8), nullable=False)
    is_breaking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    breaking_reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    assessed_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("basis in ('RULES','AI')", name="ck_news_assess_basis"),
        CheckConstraint("market_scope in ('STOCK','SECTOR','INDEX','MARKET','MACRO','GLOBAL',"
                        "'UNKNOWN')", name="ck_news_assess_scope"),
        CheckConstraint("potential_impact in ('LOW','MEDIUM','HIGH','UNKNOWN')",
                        name="ck_news_assess_impact"),
        CheckConstraint("impact_direction in ('POSITIVE','NEGATIVE','MIXED','NEUTRAL','UNKNOWN')",
                        name="ck_news_assess_direction"),
        CheckConstraint("knowable_at >= assessed_at", name="ck_news_assess_knowable"),
        UniqueConstraint("item_id", "basis", "rule_version", name="uq_news_assessment"),
    )


class NewsContent(Base):
    """An article-body fetch attempt; the body is stored only when AVAILABLE."""

    __tablename__ = "news_content"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    terms_status: Mapped[str | None] = mapped_column(String(12))
    body: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    error: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint(f"status in ({_CONTENT})", name="ck_news_content_status"),
        CheckConstraint("(status = 'AVAILABLE') = (body is not null)", name="ck_news_content_body"),
        CheckConstraint("knowable_at >= fetched_at", name="ck_news_content_knowable"),
    )


class NewsAIEnrichment(Base):
    """AI output (Bedrock): enrichment only, never a source fact; fully versioned."""

    __tablename__ = "news_ai_enrichment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("status in ('OK','ERROR','TIMEOUT','INVALID')", name="ck_news_ai_status"),
        CheckConstraint("(status = 'OK') = (output is not null)", name="ck_news_ai_output"),
        CheckConstraint("knowable_at >= generated_at", name="ck_news_ai_knowable"),
        UniqueConstraint("item_id", "model_id", "prompt_version", "input_sha256",
                         name="uq_news_ai"),
    )


class NewsDecision(Base):
    """Why an article or an edit was classified NEW / DUPLICATE / RELATED / UPDATE /
    CORRECTION (rule, version, evidence). Marks only: nothing is ever deleted."""

    __tablename__ = "news_decision"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"), nullable=False)
    observation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("news_item_observation.id", ondelete="RESTRICT"))
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_poll.id", ondelete="RESTRICT"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    rule: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    related_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("news_item.id", ondelete="RESTRICT"))
    story_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("news_story.id", ondelete="RESTRICT"))
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    decided_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)
    knowable_at: Mapped[_dt.datetime] = mapped_column(TS, nullable=False)

    __table_args__ = (
        CheckConstraint("decision in ('NEW_ARTICLE','DUPLICATE_ARTICLE','STORY_RELATED',"
                        "'STORY_UPDATE','STORY_CORRECTION')", name="ck_news_decision_kind"),
        CheckConstraint("observation_id is null or decision in ('STORY_UPDATE',"
                        "'STORY_CORRECTION')", name="ck_news_decision_observation"),
        CheckConstraint("decision <> 'STORY_UPDATE' or observation_id is not null",
                        name="ck_news_decision_update"),
        CheckConstraint("decision <> 'DUPLICATE_ARTICLE' or related_item_id is not null",
                        name="ck_news_decision_duplicate_of"),
        CheckConstraint("knowable_at >= decided_at", name="ck_news_decision_knowable"),
        Index("uq_news_decision_item", "item_id", "rule_version", unique=True,
              postgresql_where=text("observation_id is null")),
        Index("uq_news_decision_observation", "observation_id", "rule_version", unique=True,
              postgresql_where=text("observation_id is not null")),
        Index("ix_news_decision_poll", "poll_id"),
    )
