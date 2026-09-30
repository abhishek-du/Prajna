/**
 * TypeScript API definitions for Prajna Trading Dashboard.
 * Matches backend Pydantic models.
 */

export interface Meta {
  as_of: string;
  generated_at: string;
  point_in_time: boolean;
  notes: string[];
}

export interface Envelope<T> {
  data: T;
  meta: Meta;
}

export interface TickerCardData {
  instrument_key: string;
  symbol: string;
  name: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  previous_close: number | null;
  volume: number | null;
  market_date: string | null;
  knowable_at: string | null;
  source: string | null;
}

export interface MarketStatusData {
  is_open: boolean;
  session_type: string;
  session_date: string;
  current_time_ist: string;
  session_open_ist: string;
  session_close_ist: string;
  message: string;
}

export interface OverviewData {
  indices: TickerCardData[];
  market_status: MarketStatusData;
  global_markets: Array<{
    instrument_key: string;
    symbol: string;
    name: string;
    label_date: string;
    close: number;
    finality: string;
    knowable_at: string;
  }>;
  recent_news: Array<{
    news_id: number;
    headline: string;
    url: string | null;
    published_at: string | null;
    knowable_at: string | null;
    source: string;
  }>;
  freshness: Array<{
    stream: string;
    last_completed: string | null;
    age_minutes: number | null;
  }>;
  system_health_summary: Record<string, string>;
}

export interface InstrumentItem {
  instrument_key: string;
  trading_symbol: string;
  name: string | null;
  isin: string | null;
  segment: string;
  exchange: string;
  instrument_type: string | null;
  lot_size: number | null;
  tick_size: number | null;
  security_class: string | null;
  lifecycle_status: string | null;
  sector: string | null;
  latest_close: number | null;
  latest_date: string | null;
}

export interface InstrumentListResponse {
  total: number;
  offset: number;
  limit: number;
  instruments: InstrumentItem[];
}

export interface InstrumentDetail {
  instrument: InstrumentItem;
  lifecycle_periods: Array<Record<string, unknown>>;
  attribute_versions: Array<Record<string, unknown>>;
  recent_bars: Array<Record<string, unknown>>;
  corporate_actions: Array<Record<string, unknown>>;
  fundamentals_summary: { ratios?: unknown } | null;
}

export interface Candle {
  timeframe: string;
  bar_start_utc: string;
  bar_start_ist: string;
  market_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  open_interest?: number | null;
  knowable_at: string;
  price_basis?: string | null;
  basis_as_of?: string | null;
  adjustment_status?: string | null;
  factor_applied?: number | null;
  basis_confidence?: string | null;
}

export interface CandleSeriesResponse {
  instrument_key: string;
  timeframe: string;
  adjusted: boolean;
  candles: Candle[];
  refused?: Record<string, number> | null;
  total_count: number;
}

export interface TechnicalValues {
  instrument_key: string;
  timeframe: string;
  market_date: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  day_range: number | null;
  change: number | null;
  change_pct: number | null;
  average_price: number | null;
  computed_at: string;
  stage3_indicators: {
    status: string;
    message: string;
    indicators: Record<string, number | null>;
  };
}

export interface KeyRatios {
  pe: number | null;
  sector_pe: number | null;
  pb: number | null;
  eps: number | null;
  roe: number | null;
  roce: number | null;
  market_cap: number | null;
  dividend_yield: number | null;
  debt_to_equity: number | null;
  price_to_sales: number | null;
  raw_ratios: Array<Record<string, unknown>>;
}

export interface FinancialStatement {
  statement_type: string;
  period_end: string | null;
  period_type: string | null;
  payload: unknown;
  reported_at: string | null;
  knowable_at: string;
}

export interface CorporateActionItem {
  id: number;
  action_type: string;
  ex_date: string | null;
  record_date: string | null;
  amount: number | null;
  ratio_from: number | null;
  ratio_to: number | null;
  face_value_before: number | null;
  face_value_after: number | null;
  factor_price: number | null;
  factor_status: string | null;
  vendor_applied: string | null;
  knowable_at: string;
}

export interface FundamentalsResponse {
  instrument_key: string;
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  description: string | null;
  key_ratios: KeyRatios;
  statements: FinancialStatement[];
  corporate_actions: CorporateActionItem[];
  shareholdings: Record<string, unknown> | null;
}

export interface GlobalMarketItem {
  instrument_key: string;
  trading_symbol: string;
  name: string;
  segment: string;
  label_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  finality: string;
  knowable_at: string;
  confirmed_at: string | null;
  weekend_label_share: number | null;
  semantics: string | null;
  confirm_hours: number;
}

export interface GlobalMarketsResponse {
  markets: GlobalMarketItem[];
  withheld_counts: Record<string, number>;
  contract_notes: string[];
}

export interface NewsArticleItem {
  news_id: number;
  headline: string;
  body: string | null;
  url: string | null;
  publisher: string | null;
  published_at: string | null;
  received_at: string;
  processed_at: string | null;
  latency_seconds: number | null;
  source: string;
  affected_instruments: string[];
  classification: string;
  sentiment_status: string;
}

export interface NewsResponse {
  total: number;
  articles: NewsArticleItem[];
}

export interface ScreenerRow {
  instrument_key: string;
  trading_symbol: string;
  name: string | null;
  sector: string | null;
  security_class: string | null;
  price: number | null;
  change_pct: number | null;
  volume: number | null;
  market_cap: number | null;
  pe: number | null;
  pb: number | null;
  roe: number | null;
  roce: number | null;
  ai_momentum_score: string;
  alpha_signal: string;
  expected_return_pct: string;
}

export interface ScreenerResponse {
  total: number;
  offset: number;
  limit: number;
  stocks: ScreenerRow[];
  sectors: string[];
}

export interface HealthSubsystem {
  name: string;
  status: string;
  details: Record<string, unknown>;
}

export interface SystemHealthResponse {
  overall_status: string;
  database: HealthSubsystem;
  token_auth: HealthSubsystem;
  daily_close: HealthSubsystem;
  instrument_master: HealthSubsystem;
  global_refresh: HealthSubsystem;
  news_polling: HealthSubsystem;
  timing_contract: HealthSubsystem;
  disk_and_backups: HealthSubsystem;
  acceptance_summary: Record<string, unknown>;
  server_time_utc: string;
  server_time_ist: string;
}

export interface IngestRunItem {
  run_id: string;
  source: string;
  stream: string;
  logical_date: string | null;
  status: string;
  rows_written: number;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  error: string | null;
}

export interface AnomalyItem {
  id: number;
  rule: string;
  severity: string;
  entity_key: string | null;
  details: Record<string, unknown>;
  run_id: string | null;
  created_at: string;
}

export interface RevisionItem {
  id: number;
  instrument_key: string;
  timeframe: string;
  session_date: string;
  classification: string;
  reason: string;
  explained_by: Record<string, unknown>;
  created_at: string;
}

export interface BackupItem {
  filename: string;
  size_bytes: number;
  size_human: string;
  sha256_prefix: string;
  modified_at: string;
  verified: boolean;
}

export interface WarmupPlanResponse {
  sessions: number;
  from_date: string;
  to_date: string;
  active_instruments: number;
  fraction: number;
  timeframes: Record<string, unknown>;
  total_requests: number;
  total_hours_at_fraction: number;
  deferred_full_backfill_requests: string;
}
