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

export interface CorporateActionMarker {
  id: number | null;
  action_type: string;
  ex_date: string;
  record_date: string | null;
  announcement_date: string | null;
  amount: number | null;
  ratio_from: number | null;
  ratio_to: number | null;
  factor: number | null;
  vendor_applied: boolean | null;
  factor_status: string | null;
  source: string | null;
}

export interface ExcludedBarMarker {
  instrument_key: string;
  timeframe: string;
  session_date: string;
  bar_start_utc: string;
  bar_start_ist: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  reason: string;
  knowable_at: string | null;
}

export interface CandleSeriesResponse {
  instrument_key: string;
  timeframe: string;
  adjusted: boolean;
  candles: Candle[];
  corporate_actions?: CorporateActionMarker[];
  excluded_bars?: ExcludedBarMarker[];
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

export interface StageSummary {
  stage_number: number;
  name: string;
  status: string;
  status_label: string;
  last_change: string | null;
  key_metric_label: string;
  key_metric_value: string;
  alert_count: number;
  alerts: string[];
  evidence_summary: Record<string, unknown>;
  as_of: string | null;
}

export interface JobAttemptItem {
  time_ist: string;
  status: string;
  detail: string;
  delay_minutes?: number | null;
}

export interface ScheduledJobItem {
  time_ist: string;
  name: string;
  stage: string;
  status: string;
  detail: string;
  last_run_at: string | null;
  schedule_status?: string;
  delay_minutes?: number | null;
  attempts?: JobAttemptItem[];
}

export interface SystemAlertItem {
  timestamp: string | null;
  source: string;
  severity: 'ALERT' | 'WARNING' | 'INFO';
  message: string;
  stage: number | null;
}

export interface StagesOverviewResponse {
  stages: StageSummary[];
  timeline: ScheduledJobItem[];
  alerts: SystemAlertItem[];
  market_state: MarketStatusData;
}

// ── Stages 1–3 Detailed Interfaces ──────────────────────────────────────────

export interface TimeframeCoverageItem {
  timeframe: string;
  target_start: string;
  min_date: string | null;
  max_date: string | null;
  ranges_count: number;
  bars_count: number;
  quarantined_bars: number;
  data_ranges: number;
  empty_ranges: number;
  pending_ranges: number;
  backfill_pct?: number | null;
}

export interface ExcludedBarItem {
  instrument_key: string;
  timeframe: string;
  session_date: string | null;
  bar_start_utc: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  reason: string;
  knowable_at: string | null;
}

export interface MasterChangeItem {
  instrument_key: string;
  trading_symbol: string;
  name: string | null;
  isin: string | null;
  lifecycle_status: string;
  lifecycle_since: string | null;
  filter_reason: string | null;
}

export interface Stage1CoverageResponse {
  timeframes: TimeframeCoverageItem[];
  total_coverage_ranges: number;
  total_bars: number;
  excluded_bars_total: number;
  excluded_reasons_breakdown: Record<string, number>;
  recent_excluded_bars: ExcludedBarItem[];
  corporate_actions_total: number;
  corporate_actions_by_type: Record<string, number>;
  factors_total: number;
  factors_by_status: Record<string, number>;
  master_instruments_active: number;
  master_instruments_removed: number;
  master_sectors_breakdown: Record<string, number>;
  recent_master_changes: MasterChangeItem[];
}

export interface BackfillTimeframeProgress {
  timeframe: string;
  from_date: string;
  covered: number;
  total: number;
  pct: number;
  rate_per_hour: number | null;
  eta_hours: number | null;
  as_of?: string | null;
  runs_last_hour?: number | null;
  bars_last_hour?: number | null;
}

export interface Stage1BackfillResponse {
  supervisor_state: string;
  free_gb: number | null;
  stages: string | null;
  process: string | null;
  last_status: string | null;
  progress: BackfillTimeframeProgress[];
  recent_progress_lines: string[];
  recent_supervisor_lines: string[];
}

export interface GateCriterionItem {
  id: string;
  name: string | null;
  question: string | null;
  status: string;
  notes: string;
  evidence: Record<string, unknown>;
  db_state: Record<string, unknown>;
}

export interface Stage2GateResponse {
  overall: string;
  generated_at: string | null;
  age_hours: number | null;
  criteria: GateCriterionItem[];
  coverage_state_matrix: Record<string, Record<string, number>>;
  quarantined_total: number;
}

export interface Stage3EventItem {
  id: number;
  at: string;
  event: string;
  mode: string;
  operator: string | null;
  detail: Record<string, unknown>;
  run_id: string | null;
}

export interface Stage3GateResponse {
  overall: string;
  generated_at: string | null;
  criteria: GateCriterionItem[];
  refusal_audit: Stage3EventItem[];
  refusal_count_today: number;
  events_count_total: number;
}

export interface FeatureRegistryItem {
  id: string;
  group: string;
  definition: string;
  status: string;
  param_status: string;
  params: Record<string, unknown>;
  inputs: string[];
  lookback_sessions: number;
  scope: string;
  snapshots: string[];
  version: number;
}

export interface Stage3RegistryResponse {
  version: string;
  registry_sha256: string;
  feature_count: number;
  implemented_count: number;
  proposed_parameters: number;
  diagram_items: number;
  diagram_items_by_status: Record<string, number>;
  groups: Record<string, string[]>;
  features: FeatureRegistryItem[];
}

export interface SnapshotDetail {
  total_rows: number;
  values_count: number;
  nulls_count: number;
  instruments_count: number;
  completeness_pct: number;
}

export interface Stage3SnapshotsResponse {
  session_date: string;
  snapshots_available: string[];
  distinct_instruments_count: number;
  total_values: number;
  total_nulls: number;
  null_reasons_breakdown: Record<string, number>;
  snapshot_details: Record<string, SnapshotDetail>;
}

export interface FeatureValueItem {
  feature_id: string;
  group: string;
  definition: string | null;
  value: number | null;
  reason: string | null;
  knowable_at: string | null;
  computed_at: string | null;
}

export interface FeatureCardResponse {
  instrument_key: string;
  session_date: string;
  snapshot: string;
  feature_version: string;
  registry_sha256: string;
  values_count: number;
  nulls_count: number;
  features: FeatureValueItem[];
}

// ── Stock Page Upgrade (Step 3) ──────────────────────────────────────────────

export interface PreopenHistoryItem {
  market_date: string;
  event_ts: string;
  event_ts_ist: string;
  iep: number | null;
  ieq: number | null;
  tbq: number | null;
  tsq: number | null;
  imbalance_qty: number | null;
  imbalance_side: 'BUY' | 'SELL' | 'BALANCED' | null;
  rp: number | null;
  ltp: number | null;
  gap_pct: number | null;
  cas_eligible: boolean | null;
  knowable_at: string | null;
}

export interface StockPaperTradeItem {
  id: number;
  run_id: string;
  strategy: string;
  session_date: string;
  status: string;
  reason: string | null;
  qty: number;
  buy_px: number | null;
  sell_px: number | null;
  buy_value_inr: number | null;
  sell_value_inr: number | null;
  pnl_inr: number | null;
  charges: {
    dp?: number;
    brokerage?: number;
    statutory?: number;
    exchange?: number;
    sebi?: number;
    gst?: number;
    stt?: number;
  } | null;
  mode: string;
}

export interface StockLifecyclePeriod {
  status: string;
  valid_from: string;
  valid_to: string;
  reason: string | null;
  knowable_at: string | null;
}

export interface StockAttributeVersion {
  id: number;
  valid_from: string;
  valid_to: string;
  trading_symbol: string;
  isin: string | null;
  lot_size: number | null;
  tick_size: string | number | null;
}

export interface StockLifecycleItem {
  instrument_id: number;
  instrument_key: string;
  trading_symbol: string;
  name: string | null;
  isin: string | null;
  segment: string | null;
  exchange: string | null;
  instrument_type: string | null;
  lifecycle_status: string | null;
  first_seen: string | null;
  last_seen: string | null;
  included: boolean | null;
  filter_reason: string | null;
  sector: string | null;
  lifecycle_periods: StockLifecyclePeriod[];
  attribute_versions: StockAttributeVersion[];
}


