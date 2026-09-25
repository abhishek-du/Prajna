/* Client configuration that encodes backend contracts (not financial data). */

/** Freshness thresholds per data kind, in seconds. The FreshnessBadge reads these;
 * no component hard-codes a threshold. "fresh" means younger than `fresh`,
 * "stale" older than `stale`, in between "aging". */
export type FreshnessKind = "intraday" | "daily" | "global" | "news" | "ops";

export const FRESHNESS: Record<FreshnessKind, { fresh: number; stale: number; note: string }> = {
  // intraday bars are ingested by the 16:05 IST close (no live feed in Stage 1)
  intraday: { fresh: 15 * 60, stale: 26 * 3600, note: "ingested after the session (16:05 IST close)" },
  // a session's daily bar is published the next morning (07:00 IST job)
  daily: { fresh: 26 * 3600, stale: 4 * 86400, note: "published the morning after the session" },
  // global labels become visible only after confirmation (12:40 / 21:10 IST refreshes)
  global: { fresh: 36 * 3600, stale: 5 * 86400, note: "confirmed labels only" },
  news: { fresh: 45 * 60, stale: 12 * 3600, note: "polled every 30 min in market hours" },
  ops: { fresh: 26 * 3600, stale: 50 * 3600, note: "daily jobs" },
};

/** The timeframe contract of the read API: 5m is OUT_OF_SCOPE (decision D2-5m). */
export const TIMEFRAMES = [
  { tf: "1m", label: "1m", available: true, reason: null },
  { tf: "5m", label: "5m", available: false, reason: "Out of scope in Stage 1 (decision D2-5m)" },
  { tf: "15m", label: "15m", available: true, reason: null },
  { tf: "1h", label: "1h", available: true, reason: null },
  { tf: "1d", label: "1D", available: true, reason: null },
] as const;
export type AvailableTimeframe = "1m" | "15m" | "1h" | "1d";

/** Default number of bars requested per timeframe (the API caps at 5,000). */
export const BARS_PER_TIMEFRAME: Record<AvailableTimeframe, number> = {
  "1m": 1500,
  "15m": 1000,
  "1h": 1000,
  "1d": 2000,
};

/** Refresh options (seconds; 0 = off). Only price, news and operations queries
 * follow this setting; reference data never polls. */
export const REFRESH_OPTIONS = [
  { value: 0, label: "Off" },
  { value: 30, label: "30 s" },
  { value: 60, label: "1 min" },
  { value: 300, label: "5 min" },
] as const;

/** Region grouping of the vendor's global instruments. Metadata about the
 * instruments (not market data); unknown keys fall under "Other". */
export const GLOBAL_REGIONS: Record<string, "Asia" | "Europe" | "US" | "FX & commodities" | "India (offshore)"> = {
  "GLOBAL_INDEX|^N225": "Asia",
  "GLOBAL_INDEX|^HSI": "Asia",
  "GLOBAL_INDEX|^FTSE": "Europe",
  "GLOBAL_INDEX|^GDAXI": "Europe",
  "GLOBAL_INDEX|^FCHI": "Europe",
  "GLOBAL_INDEX|^GSPC": "US",
  "GLOBAL_INDEX|^DJI": "US",
  "GLOBAL_INDEX|IXIX": "US",
  "GLOBAL_INDEX|DOW FUTURES": "US",
  "GLOBAL_INDEX|SGX NIFTY": "India (offshore)",
  "GLOBAL_INDICATOR|USDINR": "FX & commodities",
  "GLOBAL_INDICATOR|BZUSD": "FX & commodities",
  "GLOBAL_INDICATOR|CLUSD": "FX & commodities",
};

export const APP_ENV: string = import.meta.env.MODE;
export const APP_VERSION: string = __APP_VERSION__;
