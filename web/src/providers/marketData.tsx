/* MarketDataProvider: the one seam through which screens obtain prices and bars.

   Today: StoredBarProvider - the latest STORED bars from the read API (Stage 1
   has no live tick store). Future: a LiveTickProvider (WebSocket / SSE) can be
   selected here without touching any screen. Screens must render `mode` so a
   stored value is never presented as live. */
import { createContext, useContext, type ReactNode } from "react";
import { chartApi, marketApi, type CandleQuery } from "../api/clients";
import type { CandleSeries, Envelope, LatestPrice } from "../types/api";

export type DataMode = "STORED" | "LIVE";

export interface MarketDataProvider {
  readonly mode: DataMode;
  readonly label: string;
  latest(keys: string[], signal?: AbortSignal): Promise<Envelope<LatestPrice[]>>;
  candles(key: string, q: CandleQuery, signal?: AbortSignal): Promise<Envelope<CandleSeries>>;
}

export const StoredBarProvider: MarketDataProvider = {
  mode: "STORED",
  label: "Latest stored",
  latest: (keys, signal) => marketApi.latest(keys, signal),
  candles: (key, q, signal) => chartApi.candles(key, q, signal),
};

/** Not available in Stage 1. Present so the seam exists; never selected. */
export const LiveTickProvider: MarketDataProvider = {
  mode: "LIVE",
  label: "Live",
  latest: () => Promise.reject(new Error("Live ticks are not available in Stage 1 (no live tick store).")),
  candles: () => Promise.reject(new Error("Live ticks are not available in Stage 1 (no live tick store).")),
};

const Ctx = createContext<MarketDataProvider>(StoredBarProvider);

export function MarketDataProviderRoot({ children, provider = StoredBarProvider }:
  { children: ReactNode; provider?: MarketDataProvider }) {
  return <Ctx.Provider value={provider}>{children}</Ctx.Provider>;
}

export const useMarketData = (): MarketDataProvider => useContext(Ctx);
