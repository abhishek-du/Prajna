"""Corporate actions, fundamentals, macro observations, news."""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, ProvenanceMixin

# The eight action types the strategy must distinguish. V1's detector had a
# four-value vocabulary {SPLIT, BONUS, SPLIT_OR_BONUS, UNKNOWN_ADJUSTMENT}
# inferred from a >23% price drop, so dividends, rights, mergers, demergers and
# symbol/ISIN changes were INVISIBLE to it — while it mutated live position
# sizes on that inference. V2 takes the vendor's own typed feed instead.
ACTION_TYPES = (
    "SPLIT", "BONUS", "DIVIDEND", "RIGHTS", "MERGER", "DEMERGER",
    "SYMBOL_CHANGE", "ISIN_CHANGE", "OTHER",
)


class CorporateAction(Base, ProvenanceMixin):
    """ISIN-keyed, from Upstox's authoritative corporate-actions feed.

    Note the two distinct times: `ex_date` is when the action takes effect,
    `knowable_at` is when it was announced. A 1:5 split effective next Tuesday
    was knowable the day it was declared — conflating the two is a look-ahead
    in one direction and a missed signal in the other.
    """

    __tablename__ = "corporate_action"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    isin: Mapped[str] = mapped_column(String(12), nullable=False)
    instrument_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trading_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)

    action_type: Mapped[str] = mapped_column(String(16), nullable=False)
    ex_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    record_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    announced_at: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    ratio_from: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    ratio_to: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    face_value_before: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    face_value_after: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    vendor_action_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vendor_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        CheckConstraint(
            "action_type in ('" + "','".join(ACTION_TYPES) + "')", name="ck_ca_action_type"
        ),
        CheckConstraint("knowable_at <= fetched_at", name="ck_ca_knowable"),
        UniqueConstraint(
            "isin", "action_type", "ex_date", "vendor_action_id", "source",
            name="uq_ca_observation",
        ),
        Index("ix_ca_isin_ex", "isin", "ex_date"),
        Index("ix_ca_ex_date", "ex_date"),
    )


class FundamentalSnapshot(Base, ProvenanceMixin):
    """Append-only fundamentals.

    V1's fundamental_data was UNIQUE(symbol) with a single last_updated column,
    so every refresh OVERWROTE the previous figures. The history is permanently
    destroyed there, and no backtest using fundamentals can be point-in-time.

    Here, `knowable_at` is part of the key, so successive observations of the
    same statement coexist and "what did we know on date X" is answerable by
    construction. Revisions and restatements are preserved rather than lost.
    """

    __tablename__ = "fundamental_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)

    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_end: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    period_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # Q / H / FY
    reported_at: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Kept as the vendor's own structure. Flattening into fixed columns is a
    # Stage 2 concern; inventing a schema at ingest would lose fields.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        CheckConstraint("knowable_at <= fetched_at", name="ck_fund_knowable"),
        UniqueConstraint(
            "instrument_key", "statement_type", "period_end", "knowable_at", "source",
            name="uq_fundamental_observation",
        ),
        Index("ix_fund_key_type", "instrument_key", "statement_type"),
    )


class MacroObservation(Base, ProvenanceMixin):
    """Generic point series: index levels, INDIA VIX, FX, flows.

    One table rather than one per series because the shape is identical and the
    set of series will grow. V1 never persisted INDIA VIX at all — it fetched a
    spot value and fell back to a hardcoded 15.0 on failure, feeding a
    fabricated number into a risk gate.
    """

    __tablename__ = "macro_observation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    series_code: Mapped[str] = mapped_column(String(48), nullable=False)
    observation_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    observation_ts: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    value: Mapped[float] = mapped_column(Numeric(24, 6), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    vendor_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        CheckConstraint("knowable_at <= fetched_at", name="ck_macro_knowable"),
        UniqueConstraint(
            "series_code", "observation_date", "knowable_at", "source",
            name="uq_macro_observation",
        ),
        Index("ix_macro_series_date", "series_code", "observation_date"),
    )


class NewsArticle(Base, ProvenanceMixin):
    """Raw news. Deliberately carries NO ticker column.

    Entity resolution is NOT an ingestion concern. V1 resolved tickers at crawl
    time with substring matching and the result is that DOLLAR.NS (an innerwear
    maker) is the most news-mapped symbol in its database, with 294 articles —
    every headline containing the word "dollar", i.e. the USD/INR rate. Also in
    its top ten: WORTHPERI ("project worth Rs 351 cr"), FAZE3Q ("falls to
    three"), SILVER, DEFENCE.

    Resolution belongs in Stage 2/3 where it can be versioned, evaluated and
    corrected without re-crawling. Ingestion stores what was published.
    """

    __tablename__ = "news_article"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The vendor's publication instant. NULL means the vendor did not supply
    # one — recorded honestly rather than defaulted to now(), which is what V1's
    # media crawler did for six feeds.
    published_at: Mapped[_dt.datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    headline_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    vendor_article_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vendor_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        CheckConstraint("knowable_at <= fetched_at", name="ck_news_knowable"),
        UniqueConstraint("headline_sha256", "published_at", "source", name="uq_news_observation"),
        Index("ix_news_published", "published_at"),
        Index("ix_news_publisher", "publisher"),
    )


class NewsInstrument(Base, ProvenanceMixin):
    """The VENDOR's association of an article with an instrument.

    This is not entity resolution (see NewsArticle): Upstox's /v2/news answers
    a query for instrument keys with articles grouped BY key, and that grouping
    is a vendor observation, stored as received. One article can belong to
    several instruments, so the association cannot live on the article row.

    knowable_at is the fetch time (unverified): the vendor does not say when it
    tagged the article, only when the article was published.
    """

    __tablename__ = "news_instrument"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    news_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_article.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_key: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (
        CheckConstraint("knowable_at <= fetched_at", name="ck_news_instrument_knowable"),
        UniqueConstraint("news_id", "instrument_key", "source", name="uq_news_instrument"),
        Index("ix_news_instrument_key", "instrument_key"),
    )
