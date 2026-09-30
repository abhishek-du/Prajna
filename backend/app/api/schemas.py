"""Typed API schemas for Prajna trading intelligence dashboard (/api/v1).

Strict adherence to data contracts:
  - All timestamps timezone-aware ISO-8601 (UTC or IST as marked)
  - Raw numbers and exact decimal conversions
  - No simulated predictions, fake signals, or hardcoded mock data
  - Stage 3 features explicitly flagged as LOCKED where appropriate
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Meta(BaseModel):
    as_of: _dt.datetime = Field(description="knowledge instant (UTC)")
    generated_at: _dt.datetime
    point_in_time: bool = Field(description="true: only rows knowable before as_of")
    notes: list[str] = Field(default_factory=list)


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


# ── Section 1: Overview Dashboard ──────────────────────────────────────────

class TickerCard(BaseModel):
    instrument_key: str
    symbol: str
    name: str
    price: float | None
    change: float | None
    change_pct: float | None
    open: float | None
    high: float | None
    low: float | None
    previous_close: float | None
    volume: float | None
    market_date: _dt.date | None
    knowable_at: _dt.datetime | None
    source: str | None


class MarketStatus(BaseModel):
    is_open: bool
    session_type: str
    session_date: _dt.date
    current_time_ist: str
    session_open_ist: str = "09:15"
    session_close_ist: str = "15:30"
    message: str


class OverviewData(BaseModel):
    indices: list[TickerCard]
    market_status: MarketStatus
    global_markets: list[dict[str, Any]]
    recent_news: list[dict[str, Any]]
    freshness: list[dict[str, Any]]
    system_health_summary: dict[str, Any]


# ── Section 2: Stock Explorer ──────────────────────────────────────────────

class InstrumentItem(BaseModel):
    instrument_key: str
    trading_symbol: str
    name: str | None
    isin: str | None
    segment: str
    exchange: str
    instrument_type: str | None
    lot_size: int | None
    tick_size: float | None
    security_class: str | None
    lifecycle_status: str | None
    sector: str | None
    latest_close: float | None
    latest_date: _dt.date | None


class InstrumentDetail(BaseModel):
    instrument: InstrumentItem
    lifecycle_periods: list[dict[str, Any]]
    attribute_versions: list[dict[str, Any]]
    recent_bars: list[dict[str, Any]]
    corporate_actions: list[dict[str, Any]]
    fundamentals_summary: dict[str, Any] | None


class InstrumentListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    instruments: list[InstrumentItem]


# ── Section 3: Live Candle Chart ───────────────────────────────────────────

class Candle(BaseModel):
    timeframe: str
    bar_start_utc: _dt.datetime
    bar_start_ist: str
    market_date: _dt.date
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None = None
    knowable_at: _dt.datetime
    price_basis: str | None = None
    basis_as_of: _dt.date | None = None
    adjustment_status: str | None = None
    factor_applied: float | None = None
    basis_confidence: str | None = None


class CandleSeriesResponse(BaseModel):
    instrument_key: str
    timeframe: str
    adjusted: bool
    candles: list[Candle]
    refused: dict[str, int] | None = None
    total_count: int


# ── Section 4: Technical Data View ─────────────────────────────────────────

class TechnicalValues(BaseModel):
    instrument_key: str
    timeframe: str
    market_date: _dt.date | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    day_range: float | None
    change: float | None
    change_pct: float | None
    average_price: float | None
    computed_at: _dt.datetime
    # Stage 3 indicators (displayed honestly as locked)
    stage3_indicators: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "LOCKED",
            "message": "Not available — Stage 3 locked",
            "indicators": {
                "EMA_20": None,
                "EMA_50": None,
                "EMA_200": None,
                "SMA_50": None,
                "RSI_14": None,
                "MACD": None,
                "MACD_signal": None,
                "ATR_14": None,
                "VWAP": None,
                "volatility_30d": None,
                "support_1": None,
                "resistance_1": None,
            },
        }
    )


# ── Section 5: Fundamentals ────────────────────────────────────────────────

class KeyRatios(BaseModel):
    pe: float | None = None
    sector_pe: float | None = None
    pb: float | None = None
    eps: float | None = None
    roe: float | None = None
    roce: float | None = None
    market_cap: float | None = None
    dividend_yield: float | None = None
    debt_to_equity: float | None = None
    price_to_sales: float | None = None
    raw_ratios: list[dict[str, Any]] = Field(default_factory=list)


class FinancialStatement(BaseModel):
    statement_type: str
    period_end: _dt.date | None
    period_type: str | None
    payload: Any
    reported_at: _dt.datetime | None
    knowable_at: _dt.datetime


class CorporateActionItem(BaseModel):
    id: int
    action_type: str
    ex_date: _dt.date | None
    record_date: _dt.date | None
    amount: float | None
    ratio_from: float | None
    ratio_to: float | None
    face_value_before: float | None
    face_value_after: float | None
    factor_price: float | None
    factor_status: str | None
    vendor_applied: str | None
    knowable_at: _dt.datetime


class FundamentalsResponse(BaseModel):
    instrument_key: str
    company_name: str | None
    sector: str | None
    industry: str | None
    description: str | None
    key_ratios: KeyRatios
    statements: list[FinancialStatement]
    corporate_actions: list[CorporateActionItem]
    shareholdings: Any = None


# ── Section 6: Global Markets ──────────────────────────────────────────────

class GlobalMarketItem(BaseModel):
    instrument_key: str
    trading_symbol: str
    name: str
    segment: str
    label_date: _dt.date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    finality: str = Field(description="CONFIRMED / CONFIRMED_BY_AGE (REVISED/PLACEHOLDER withheld)")
    knowable_at: _dt.datetime
    confirmed_at: _dt.datetime | None
    weekend_label_share: float | None
    semantics: str | None
    confirm_hours: int = 6


class GlobalMarketsResponse(BaseModel):
    markets: list[GlobalMarketItem]
    withheld_counts: dict[str, int]
    contract_notes: list[str]


# ── Section 7: News Intelligence ───────────────────────────────────────────

class NewsArticleItem(BaseModel):
    news_id: int
    headline: str
    body: str | None
    url: str | None
    publisher: str | None
    published_at: _dt.datetime | None
    received_at: _dt.datetime
    processed_at: _dt.datetime | None
    latency_seconds: float | None
    source: str
    affected_instruments: list[str]
    classification: str = Field(description="MARKET / SECTOR / STOCK")
    sentiment_status: str = Field(
        default="NOT_AVAILABLE",
        description="Not available — Stage 3 locked (no fake sentiment scores)",
    )


class NewsResponse(BaseModel):
    total: int
    articles: list[NewsArticleItem]


# ── Section 8: Stock Screener ──────────────────────────────────────────────

class ScreenerRow(BaseModel):
    instrument_key: str
    trading_symbol: str
    name: str | None
    sector: str | None
    security_class: str | None
    price: float | None
    change_pct: float | None
    volume: float | None
    market_cap: float | None
    pe: float | None
    pb: float | None
    roe: float | None
    roce: float | None
    # Stage 3/4/5 placeholders
    ai_momentum_score: str = "Stage 3 Locked"
    alpha_signal: str = "Stage 3 Locked"
    expected_return_pct: str = "Stage 3 Locked"


class ScreenerResponse(BaseModel):
    total: int
    offset: int
    limit: int
    stocks: list[ScreenerRow]
    sectors: list[str]


# ── Section 9: Signals (UI Contract Only) ──────────────────────────────────

class SignalContractItem(BaseModel):
    id: str | None = None
    instrument_key: str
    symbol: str
    timeframe: str
    direction: str = Field(description="LONG / SHORT")
    signal_type: str
    confidence: float | None = None
    knowable_at: _dt.datetime | None = None


class SignalsResponse(BaseModel):
    status: str = "LOCKED"
    stage: str = "STAGE_3_LOCKED"
    message: str = (
        "Stage 3 remains strictly LOCKED in production. No trading signals, "
        "prediction models, AI scores, or fake BUY/SELL recommendations are generated."
    )
    signals: list[SignalContractItem] = Field(default_factory=list)


# ── Section 10: Portfolio / Execution (UI Contract Only) ───────────────────

class PortfolioResponse(BaseModel):
    status: str = "LOCKED"
    stage: str = "STAGE_4_5_LOCKED"
    message: str = (
        "Order execution and live broker routing are strictly LOCKED. "
        "System is in read-only compliance observation mode."
    )
    holdings: list[dict[str, Any]] = Field(default_factory=list)
    positions: list[dict[str, Any]] = Field(default_factory=list)
    orders: list[dict[str, Any]] = Field(default_factory=list)


# ── Section 11: System Health ──────────────────────────────────────────────

class HealthSubsystem(BaseModel):
    name: str
    status: str  # PASS / WARNING / FAIL / UNKNOWN
    details: dict[str, Any]


class SystemHealthResponse(BaseModel):
    overall_status: str
    database: HealthSubsystem
    token_auth: HealthSubsystem
    daily_close: HealthSubsystem
    instrument_master: HealthSubsystem
    global_refresh: HealthSubsystem
    news_polling: HealthSubsystem
    timing_contract: HealthSubsystem
    disk_and_backups: HealthSubsystem
    acceptance_summary: dict[str, Any]
    server_time_utc: _dt.datetime
    server_time_ist: str


# ── Section 12: Admin / Operations ─────────────────────────────────────────

class IngestRunItem(BaseModel):
    run_id: str
    source: str
    stream: str
    logical_date: _dt.date | None
    status: str
    rows_written: int
    started_at: _dt.datetime
    finished_at: _dt.datetime | None
    duration_seconds: float | None
    error: str | None


class AnomalyItem(BaseModel):
    id: int
    rule: str
    severity: str
    entity_key: str | None
    details: dict[str, Any]
    run_id: str | None
    created_at: _dt.datetime


class RevisionItem(BaseModel):
    id: int
    instrument_key: str
    timeframe: str
    session_date: _dt.date
    classification: str
    reason: str
    explained_by: dict[str, Any]
    created_at: _dt.datetime


class BackupItem(BaseModel):
    filename: str
    size_bytes: int
    size_human: str
    sha256_prefix: str
    modified_at: _dt.datetime
    verified: bool


class WarmupPlanResponse(BaseModel):
    sessions: int
    from_date: str
    to_date: str
    active_instruments: int
    fraction: float
    timeframes: dict[str, Any]
    total_requests: int
    total_hours_at_fraction: float
    deferred_full_backfill_requests: str
