/* TEST FIXTURES ONLY. Never imported by application code (enforced by
   src/app.boundaries.test.ts). Shapes follow the read-API contract and are
   validated against mocks/openapi.json (dumped from backend/app/readapi).
   Values are illustrative test inputs, not market data. */
import type {
  Acceptance, CandleSeries, CorporateAction, Envelope, Freshness, Fundamental, GlobalBar, GlobalInstrument,
  GlobalLabel, Instrument, LatestPrice, MarketSession, NewsItem, PipelineStatus, Profile, Quality, Quote,
  SearchHit, SectorCount,
} from "../src/types/api";

export const NOW = "2026-09-25T15:00:00Z";
export const meta = (pit = true, total?: number) => ({
  as_of: NOW, generated_at: NOW, point_in_time: pit, knowledge_rule: "knowable_at < as_of", notes: [],
  ...(total !== undefined ? { total } : {}),
});
export const env = <T,>(data: T, pit = true, total?: number): Envelope<T> => ({ data, meta: meta(pit, total) });

export const RIL = "NSE_EQ|INE002A01018";
export const NIFTY = "NSE_INDEX|Nifty 50";
export const N225 = "GLOBAL_INDEX|^N225";

export const instruments: Instrument[] = [
  { instrument_key: RIL, trading_symbol: "RELIANCE", name: "RELIANCE INDUSTRIES LTD", isin: "INE002A01018",
    segment: "NSE_EQ", exchange: "NSE", instrument_type: "EQ", security_class: "STOCK", lifecycle_status: "ACTIVE",
    lifecycle_since: "2026-09-23T07:51:19Z", sector: "Refineries" },
  { instrument_key: "NSE_EQ|INE040A01034", trading_symbol: "HDFCBANK", name: "HDFC BANK LTD", isin: "INE040A01034",
    segment: "NSE_EQ", exchange: "NSE", instrument_type: "EQ", security_class: "STOCK", lifecycle_status: "ACTIVE",
    lifecycle_since: "2026-09-23T07:51:19Z", sector: "Banks" },
];
export const indices: Instrument[] = [
  { instrument_key: NIFTY, trading_symbol: "NIFTY", name: "Nifty 50", isin: null, segment: "NSE_INDEX", exchange: "NSE",
    instrument_type: "INDEX", security_class: null, lifecycle_status: "ACTIVE", lifecycle_since: "2026-09-23T07:51:19Z", sector: null },
];

export const searchHits: SearchHit[] = [{ ...instruments[0]!, match: "SYMBOL_EXACT" }];

export const latest: LatestPrice[] = [
  { instrument_key: RIL, market_date: "2026-09-24", close: 1219.2, previous_market_date: "2026-09-23", previous_close: 1248,
    change: -28.8, change_pct: -2.3077, volume: 13923795, comparable: true, comparable_reason: null,
    knowable_at: "2026-09-25T01:30:05Z", price_basis: "VENDOR_ADJUSTED" },
  { instrument_key: NIFTY, market_date: "2026-09-24", close: 23100.5, previous_market_date: "2026-09-23", previous_close: null,
    change: null, change_pct: null, volume: 0, comparable: false, comparable_reason: "split/bonus ex-date between the sessions",
    knowable_at: "2026-09-25T01:30:05Z", price_basis: "VENDOR_ADJUSTED" },
];

export const session: MarketSession = {
  date: "2026-09-25", is_trading_day: true, session_type: "NORMAL", preopen_start_ist: "09:00:00", open_ist: "09:15:00",
  close_ist: "15:30:00", state: "CLOSED", previous_trading_day: "2026-09-24", next_trading_day: "2026-09-28",
  calendar_source: "UPSTOX_REST_V2",
};

const candle = (i: number, tf: "1d" | "1h" = "1d") => ({
  timeframe: tf, bar_start: `2026-09-${String(10 + i).padStart(2, "0")}T03:45:00Z`, market_date: `2026-09-${String(10 + i).padStart(2, "0")}`,
  open: 100 + i, high: 110 + i, low: 95 + i, close: 105 + i, volume: 1000 * (i + 1), open_interest: null,
  knowable_at: `2026-09-${String(11 + i).padStart(2, "0")}T01:30:00Z`, fetched_at: `2026-09-${String(11 + i).padStart(2, "0")}T01:30:00Z`,
  price_basis: "VENDOR_ADJUSTED", basis_as_of: "2026-09-24", adjustment_status: null, factor_applied: null, basis_confidence: null,
} as const);
export const candles = (tf: "1d" | "1h"): CandleSeries => ({
  instrument_key: RIL, timeframe: tf, adjusted: false, candles: [0, 1, 2, 3].map((i) => ({ ...candle(i, tf) })), refused: null,
});
export const quote: Quote = { instrument_key: RIL, source: "latest stored canonical bars (no live tick store in Stage 1)",
  last_1m: { ...candle(3), timeframe: "1m" }, last_1d: { ...candle(3) }, age_seconds: 3600 };

export const profile: Profile = {
  instrument: instruments[0]!, sector_as_of: "Refineries", security_class_signals: { isin_security_code: "E" },
  lifecycle_periods: [{ status: "ACTIVE", valid_from: "2026-09-23T07:51:19Z", valid_to: "9999-12-31T00:00:00Z", reason: "seeded", knowable_at: "2026-09-23T07:51:19Z" }],
  profile: { sector: "Refineries", company_profile: "Test fixture description.", sector_market_cap_inr: { unit: "crore", value: 1000, formatted: "1,000 Cr" } },
};

export const fundamentals: Fundamental[] = [
  { statement_type: "key_ratios", period_end: null, period_type: null, knowable_at: NOW, fetched_at: NOW,
    payload: [{ name: "P/E", company_value: "19.14", sector_value: "16.1" }] },
  { statement_type: "income:consolidated:yearly", period_end: null, period_type: null, knowable_at: NOW, fetched_at: NOW,
    payload: { units_in: "crore", full_statement: [{ particular: "Revenue", history: [{ period: "Mar 2026", value: 10 }, { period: "Mar 2025", value: 9 }] }] } },
];

export const corporateActions: CorporateAction[] = [
  { id: 1, action_type: "BONUS", announcement_date: "2026-08-01", ex_date: "2026-09-01", record_date: "2026-09-01", amount: null,
    ratio_from: 1, ratio_to: 1, face_value_before: null, face_value_after: null, knowable_at: "2026-08-02T00:00:00Z",
    factor_status: "EXACT", factor_price: 2, vendor_applied: "APPLIED" },
];

export const news: NewsItem[] = [
  { news_id: 1, instrument_key: RIL, headline: "Fixture headline", publisher: null, url: "https://example.invalid/a",
    published_at: "2026-09-25T08:00:00Z", received_at: "2026-09-25T09:30:00Z", knowable_at: "2026-09-25T08:00:00Z" },
];

export const sectors: SectorCount[] = [{ sector: "Refineries", stocks: 12 }, { sector: "Banks", stocks: 40 }, { sector: null, stocks: 3 }];

export const global: GlobalInstrument[] = [
  { instrument_key: N225, name: "NIKKEI 225", segment: "GLOBAL_INDEX", label_semantics: "labels include weekend dates: ...",
    confirm_hours: 6, latest: { label_date: "2026-09-22", close: 45000, finality: "CONFIRMED", knowable_at: "2026-09-25T15:40:00Z" } },
];
export const globalBars: GlobalBar[] = [
  { label_date: "2026-09-19", open: 1, high: 2, low: 1, close: 44000, volume: 0, finality: "CONFIRMED_BY_AGE", knowable_at: "2026-09-24T00:00:00Z", first_fetched_at: "2026-09-24T00:00:00Z" },
  { label_date: "2026-09-22", open: 1, high: 2, low: 1, close: 45000, volume: 0, finality: "CONFIRMED", knowable_at: "2026-09-25T15:40:00Z", first_fetched_at: "2026-09-23T09:00:00Z" },
];
export const globalLabels: GlobalLabel[] = [
  { label_date: "2026-09-24", finality: "REVISED", exposed: false, close: null, first_fetched_at: "2026-09-25T08:11:44Z", confirmed_at: null, revised_at: "2026-09-25T11:30:53Z" },
  { label_date: "2026-09-23", finality: "PLACEHOLDER", exposed: false, close: null, first_fetched_at: "2026-09-24T09:21:34Z", confirmed_at: null, revised_at: null },
  { label_date: "2026-09-22", finality: "CONFIRMED", exposed: true, close: 45000, first_fetched_at: "2026-09-23T09:00:00Z", confirmed_at: "2026-09-25T15:40:00Z", revised_at: null },
];

export const freshness: Freshness[] = [
  { dataset: "candles_1d", last_complete_run_finished: "2026-09-25T01:40:00Z", age_hours: 13.3, last_status: "COMPLETE", expected_cadence: "daily" },
  { dataset: "news", last_complete_run_finished: "2026-09-25T10:00:00Z", age_hours: 5, last_status: "COMPLETE", expected_cadence: "30 min" },
];

export const pipeline: PipelineStatus = {
  at: NOW, families: { candles_1d: { last_started: NOW, last_status: "COMPLETE", runs_24h: 2, complete_24h: 2, failed_24h: 0, aborted_24h: 0, running_now: 0, reaped_24h: 0 } },
  running: { count: 0, oldest_age_hours: null }, candles_lock: "FREE",
  upstox_token: { minted_at: "2026-09-25T07:00:00+05:30", age_hours: 8.5, note: "Upstox tokens expire at ~03:30 IST" },
  disk_free_gb: 300, recent_markers: ["close_then_backfill_2026-09-25.log: CLOSE_STARTED day=2026-09-25"],
};

export const quality: Quality = {
  instrument_key: RIL, coverage: { "1d": [{ timeframe: "1d", from_date: "2020-01-01", to_date: "2026-09-24", state: "DATA", sessions: 1674, bars: 1674, quarantined: 0 }] },
  observations: { CA_ADJUSTMENT: 4 }, price_basis: { VENDOR_ADJUSTED: 1674 }, quarantined_bars: 0,
  provenance: { source: "Upstox", knowledge_rule: "knowable_at < as_of" },
};

export const acceptance: Acceptance = {
  stage1: { generated_at: NOW, overall: "NOT COMPLETE", live_readiness: "PASS", waiting_for_evidence: ["R", "X"], deferred: ["G"], failing: [],
    criteria: [{ id: "A", name: "Database isolation", status: "PASS" }, { id: "R", name: "Daily incremental ingestion", status: "WAITING_FOR_EVIDENCE" }] },
  stage2: { overall: "NOT PASSED", criteria: [{ id: "A", name: "Can Stage 2 process Stage 1 data?", status: "PASS" }] },
  stage3: { status: "LOCKED", reason: "unlocked only after Stage 1 is COMPLETE" },
};
