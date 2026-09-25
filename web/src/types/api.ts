/* Mirrors backend/app/readapi/schemas.py field for field (contract: docs/API_CONTRACT.md).
   src/api/contract.test.ts checks these names against the served OpenAPI document. */

export type ISODateTime = string; // ISO-8601 with offset (UTC)
export type ISODate = string; // YYYY-MM-DD (IST market date)
export type ISOTime = string; // HH:MM:SS (IST)

export interface Meta {
  as_of: ISODateTime;
  generated_at: ISODateTime;
  point_in_time: boolean;
  knowledge_rule: string;
  notes: string[];
  total?: number | null;
}

export interface Envelope<T> {
  data: T;
  meta: Meta;
}

export type SecurityClass = "STOCK" | "FUND_UNIT" | "RIGHTS_ENTITLEMENT" | "OTHER";
export type LifecycleStatus = "ACTIVE" | "INELIGIBLE" | "REMOVED_FROM_MASTER" | "VENDOR_REJECTED";

export interface Instrument {
  instrument_key: string;
  trading_symbol: string;
  name: string | null;
  isin: string | null;
  segment: string;
  exchange: string;
  instrument_type: string | null;
  security_class: SecurityClass | string | null;
  lifecycle_status: LifecycleStatus | string | null;
  lifecycle_since: ISODateTime | null;
  sector: string | null;
}

export interface SearchHit extends Instrument {
  match: "SYMBOL_EXACT" | "SYMBOL_PREFIX" | "ISIN" | "NAME" | string;
}

export interface LifecyclePeriod {
  status: string;
  valid_from: ISODateTime;
  valid_to: ISODateTime | null;
  reason: string | null;
  knowable_at: ISODateTime;
}

export interface Profile {
  instrument: Instrument;
  sector_as_of: string | null;
  security_class_signals: Record<string, unknown> | null;
  lifecycle_periods: LifecyclePeriod[];
  profile: Record<string, unknown> | null;
}

export type Timeframe = "1m" | "5m" | "15m" | "1h" | "1d";
export type PriceBasis = "RAW_OBSERVED" | "VENDOR_ADJUSTED";

export interface Candle {
  timeframe: Timeframe;
  bar_start: ISODateTime;
  market_date: ISODate;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  open_interest: number | null;
  knowable_at: ISODateTime;
  fetched_at: ISODateTime;
  price_basis: PriceBasis | string | null;
  basis_as_of: ISODate | null;
  adjustment_status: "AS_STORED" | "ADJUSTED" | "RECONSTRUCTED" | string | null;
  factor_applied: number | null;
  basis_confidence: "HIGH" | "LOW" | string | null;
}

export interface CandleSeries {
  instrument_key: string;
  timeframe: Timeframe;
  adjusted: boolean;
  candles: Candle[];
  refused: Record<string, number> | null;
}

export interface Quote {
  instrument_key: string;
  source: string;
  last_1m: Candle | null;
  last_1d: Candle | null;
  age_seconds: number | null;
}

export interface Fundamental {
  statement_type: string;
  period_end: ISODate | null;
  period_type: string | null;
  payload: Record<string, unknown> | unknown[] | null;
  knowable_at: ISODateTime;
  fetched_at: ISODateTime;
}

export type FactorStatus = "EXACT" | "UNCERTAIN" | "UNSUPPORTED";

export interface CorporateAction {
  id: number;
  action_type: string;
  announcement_date: ISODate | null;
  ex_date: ISODate | null;
  record_date: ISODate | null;
  amount: number | null;
  ratio_from: number | null;
  ratio_to: number | null;
  face_value_before: number | null;
  face_value_after: number | null;
  knowable_at: ISODateTime;
  factor_status: FactorStatus | string | null;
  factor_price: number | null;
  vendor_applied: "APPLIED" | "NOT_APPLIED" | "UNKNOWN" | "N/A" | string | null;
}

export interface SectorCount {
  sector: string | null;
  stocks: number;
}

export interface GlobalLatest {
  label_date: ISODate;
  close: number;
  finality: string;
  knowable_at: ISODateTime;
}

export interface GlobalInstrument {
  instrument_key: string;
  name: string | null;
  segment: string;
  label_semantics: string | null;
  confirm_hours: number | null;
  latest: GlobalLatest | null;
}

export interface GlobalBar {
  label_date: ISODate;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  finality: string;
  knowable_at: ISODateTime;
  first_fetched_at: ISODateTime;
}

export type Finality = "REVISED" | "PLACEHOLDER" | "UNCONFIRMED" | "CONFIRMED" | "CONFIRMED_BY_AGE";

export interface GlobalLabel {
  label_date: ISODate;
  finality: Finality | string;
  exposed: boolean;
  close: number | null;
  first_fetched_at: ISODateTime;
  confirmed_at: ISODateTime | null;
  revised_at: ISODateTime | null;
}

export interface NewsItem {
  news_id: number;
  instrument_key: string | null;
  headline: string;
  publisher: string | null;
  url: string | null;
  published_at: ISODateTime | null;
  received_at: ISODateTime;
  knowable_at: ISODateTime;
}

export interface Freshness {
  dataset: string;
  last_complete_run_finished: ISODateTime | null;
  age_hours: number | null;
  last_status: string | null;
  expected_cadence: string;
}

export interface CoverageRange {
  instrument_id?: number;
  timeframe: string;
  from_date: ISODate;
  to_date: ISODate;
  state: string;
  sessions: number;
  bars: number;
  quarantined: number;
}

export interface Quality {
  instrument_key: string;
  coverage: Record<string, CoverageRange[]>;
  observations: Record<string, number>;
  price_basis: Record<string, number>;
  quarantined_bars: number;
  provenance: Record<string, unknown>;
}

export interface MarketSession {
  date: ISODate;
  is_trading_day: boolean;
  session_type: string;
  preopen_start_ist: ISOTime | null;
  open_ist: ISOTime | null;
  close_ist: ISOTime | null;
  state: "PRE_OPEN" | "OPEN" | "CLOSED" | "NON_TRADING_DAY" | "SCHEDULED" | string;
  previous_trading_day: ISODate | null;
  next_trading_day: ISODate | null;
  calendar_source: string;
}

export interface LatestPrice {
  instrument_key: string;
  market_date: ISODate;
  close: number;
  previous_market_date: ISODate | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number;
  comparable: boolean;
  comparable_reason: string | null;
  knowable_at: ISODateTime;
  price_basis: string | null;
}

export interface FamilyStatus {
  last_started: ISODateTime | null;
  last_status: string | null;
  runs_24h: number;
  complete_24h: number;
  failed_24h: number;
  aborted_24h: number;
  running_now: number;
  reaped_24h: number;
}

export interface PipelineStatus {
  at: ISODateTime;
  families: Record<string, FamilyStatus>;
  running: { count: number; oldest_age_hours: number | null };
  candles_lock: string;
  upstox_token: { minted_at?: string | null; age_hours?: number | null; note?: string; error?: string } | null;
  disk_free_gb: number;
  recent_markers: string[];
}

export type CriterionStatus =
  | "PASS"
  | "FAIL"
  | "BLOCKED"
  | "WAITING_FOR_EVIDENCE"
  | "DEFERRED"
  | "OUT_OF_SCOPE"
  | "PENDING"
  | string;

export interface AcceptanceCriterion {
  id: string;
  name: string | null;
  status: CriterionStatus;
}

export interface AcceptanceStage {
  generated_at?: ISODateTime;
  overall?: string;
  live_readiness?: string;
  waiting_for_evidence?: string[];
  deferred?: string[];
  failing?: string[];
  criteria: AcceptanceCriterion[];
}

export interface Acceptance {
  stage1: AcceptanceStage | null;
  stage2: AcceptanceStage | null;
  stage3: { status: "LOCKED" | string; reason: string };
}
