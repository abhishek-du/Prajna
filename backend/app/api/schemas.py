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


class CorporateActionMarker(BaseModel):
    id: int | None = None
    action_type: str
    ex_date: _dt.date
    record_date: _dt.date | None = None
    announcement_date: _dt.date | None = None
    amount: float | None = None
    ratio_from: float | None = None
    ratio_to: float | None = None
    factor: float | None = None
    vendor_applied: bool | None = None
    factor_status: str | None = None
    source: str | None = None


class ExcludedBarMarker(BaseModel):
    instrument_key: str
    timeframe: str
    session_date: _dt.date
    bar_start_utc: _dt.datetime
    bar_start_ist: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    reason: str
    knowable_at: _dt.datetime | None = None


class CandleSeriesResponse(BaseModel):
    instrument_key: str
    timeframe: str
    adjusted: bool
    candles: list[Candle]
    corporate_actions: list[CorporateActionMarker] = Field(default_factory=list)
    excluded_bars: list[ExcludedBarMarker] = Field(default_factory=list)
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


# ── Section 13: 8 Stages Control Room ──────────────────────────────────────

class StageSummary(BaseModel):
    stage_number: int
    name: str
    status: str  # "PASS" | "COMPLETE" | "LOCKED" | "ACTIVE" | "CALIBRATING" | "WARNING" | "FAIL"
    status_label: str
    last_change: _dt.datetime | None = None
    key_metric_label: str
    key_metric_value: str
    alert_count: int = 0
    alerts: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    as_of: _dt.datetime | None = None


class JobAttemptItem(BaseModel):
    time_ist: str
    status: str  # "DONE" | "RUNNING" | "FAILED" | "MISSED" | "LATE/MANUAL" | "BACKFILLED" | "WAITING_CLOSE"
    detail: str
    delay_minutes: int | None = None


class ScheduledJobItem(BaseModel):
    time_ist: str
    name: str
    stage: str
    status: str  # "DONE" | "RUNNING" | "FAILED" | "MISSED" | "PENDING" | "WAITING_CLOSE" | "BACKFILLED"
    detail: str
    last_run_at: _dt.datetime | None = None
    schedule_status: str = "UNKNOWN"  # "SCHEDULED" | "NOT_SCHEDULED" | "MANUAL RUN" | "UNKNOWN"
    delay_minutes: int | None = None
    attempts: list[JobAttemptItem] = Field(default_factory=list)


class SystemAlertItem(BaseModel):
    timestamp: _dt.datetime | None = None
    source: str  # "supervisor" | "gate" | "stage3_event" | "ingest"
    severity: str  # "ALERT" | "WARNING" | "INFO"
    message: str
    stage: int | None = None


class StagesOverviewResponse(BaseModel):
    stages: list[StageSummary]
    timeline: list[ScheduledJobItem]
    alerts: list[SystemAlertItem]
    market_state: MarketStatus


# ── Section 14: Stages 1–3 Detailed Schemas ─────────────────────────────────

class TimeframeCoverageItem(BaseModel):
    timeframe: str
    target_start: str
    min_date: _dt.date | None = None
    max_date: _dt.date | None = None
    ranges_count: int
    bars_count: int
    quarantined_bars: int
    data_ranges: int = 0
    empty_ranges: int = 0
    pending_ranges: int = 0
    backfill_pct: float | None = None


class ExcludedBarItem(BaseModel):
    instrument_key: str
    timeframe: str
    session_date: _dt.date | None = None
    bar_start_utc: _dt.datetime | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    reason: str
    knowable_at: _dt.datetime | None = None


class Stage1CoverageResponse(BaseModel):
    timeframes: list[TimeframeCoverageItem]
    total_coverage_ranges: int
    total_bars: int
    excluded_bars_total: int
    excluded_reasons_breakdown: dict[str, int]
    recent_excluded_bars: list[ExcludedBarItem]
    corporate_actions_total: int
    corporate_actions_by_type: dict[str, int]
    factors_total: int
    factors_by_status: dict[str, int]
    master_instruments_active: int
    master_instruments_removed: int
    master_sectors_breakdown: dict[str, int]
    recent_master_changes: list[dict[str, Any]]


class BackfillTimeframeProgress(BaseModel):
    timeframe: str
    from_date: str
    covered: int
    total: int
    pct: float
    rate_per_hour: float | None = None
    eta_hours: float | None = None
    as_of: _dt.datetime | None = None
    runs_last_hour: int | None = None
    bars_last_hour: int | None = None


class Stage1BackfillResponse(BaseModel):
    supervisor_state: str  # "RUNNING" | "WAITING_CLOSE" | "PAUSED" | "WINDOW_CLOSED" | "DONE"
    free_gb: float | None = None
    stages: str | None = None
    process: str | None = None
    last_status: str | None = None
    progress: list[BackfillTimeframeProgress]
    recent_progress_lines: list[str]
    recent_supervisor_lines: list[str]


class GateCriterionItem(BaseModel):
    id: str
    name: str | None = None
    question: str | None = None
    status: str  # "PASS" | "FAIL" | "DEFERRED" | "WAITING"
    notes: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    db_state: dict[str, Any] = Field(default_factory=dict)


class Stage2GateResponse(BaseModel):
    overall: str
    generated_at: _dt.datetime | None = None
    age_hours: float | None = None
    criteria: list[GateCriterionItem]
    coverage_state_matrix: dict[str, dict[str, int]]
    quarantined_total: int


class Stage3EventItem(BaseModel):
    id: int
    at: _dt.datetime
    event: str
    mode: str
    operator: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


class Stage3GateResponse(BaseModel):
    overall: str
    generated_at: _dt.datetime | None = None
    criteria: list[GateCriterionItem]
    refusal_audit: list[Stage3EventItem]
    refusal_count_today: int
    events_count_total: int


class FeatureRegistryItem(BaseModel):
    id: str
    group: str
    definition: str
    status: str
    param_status: str
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    lookback_sessions: int = 0
    scope: str = "INSTRUMENT"
    snapshots: list[str] = Field(default_factory=list)
    version: int = 1


class Stage3RegistryResponse(BaseModel):
    version: str
    registry_sha256: str
    feature_count: int
    implemented_count: int
    proposed_parameters: int
    diagram_items: int
    diagram_items_by_status: dict[str, int]
    groups: dict[str, list[str]]
    features: list[FeatureRegistryItem]


class Stage3SnapshotsResponse(BaseModel):
    session_date: _dt.date
    snapshots_available: list[str]
    distinct_instruments_count: int
    total_values: int
    total_nulls: int
    null_reasons_breakdown: dict[str, int]
    snapshot_details: dict[str, Any]


class FeatureValueItem(BaseModel):
    feature_id: str
    group: str
    definition: str | None = None
    value: float | None = None
    reason: str | None = None
    knowable_at: _dt.datetime | None = None
    computed_at: _dt.datetime | None = None


class FeatureCardResponse(BaseModel):
    instrument_key: str
    session_date: _dt.date
    snapshot: str
    feature_version: str
    registry_sha256: str
    values_count: int
    nulls_count: int
    features: list[FeatureValueItem]


# ── Section 11: Stock Page Upgrade (Step 3) ─────────────────────────────────

class PreopenHistoryItem(BaseModel):
    market_date: _dt.date
    event_ts: _dt.datetime
    event_ts_ist: str
    iep: float | None = None
    ieq: int | None = None
    tbq: float | None = None
    tsq: float | None = None
    imbalance_qty: int | None = None
    imbalance_side: str | None = None
    rp: float | None = None
    ltp: float | None = None
    gap_pct: float | None = None
    cas_eligible: bool | None = None
    knowable_at: _dt.datetime | None = None


class StockPaperTradeItem(BaseModel):
    id: int
    run_id: str
    strategy: str
    session_date: _dt.date
    status: str
    reason: str | None = None
    qty: int
    buy_px: float | None = None
    sell_px: float | None = None
    buy_value_inr: float | None = None
    sell_value_inr: float | None = None
    pnl_inr: float | None = None
    charges: dict[str, Any] | None = None
    mode: str = "PAPER"


class StockLifecycleItem(BaseModel):
    instrument_id: int
    instrument_key: str
    trading_symbol: str
    name: str | None = None
    isin: str | None = None
    segment: str | None = None
    exchange: str | None = None
    instrument_type: str | None = None
    lifecycle_status: str | None = None
    first_seen: _dt.date | None = None
    last_seen: _dt.date | None = None
    included: bool | None = None
    filter_reason: str | None = None
    sector: str | None = None
    lifecycle_periods: list[dict[str, Any]] = Field(default_factory=list)
    attribute_versions: list[dict[str, Any]] = Field(default_factory=list)


