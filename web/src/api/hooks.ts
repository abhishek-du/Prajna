/* TanStack Query hooks: server state lives here, never in UI state. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useMarketData } from "../providers/marketData";
import { useRefetchInterval, useSettings } from "../providers/settings";
import {
  acceptanceApi,
  fundamentalApi,
  globalApi,
  instrumentApi,
  marketApi,
  newsApi,
  operationsApi,
  sectorApi,
  type CandleQuery,
  type InstrumentQuery,
} from "./clients";

const MIN = 60_000;
const REFERENCE = { staleTime: 10 * MIN, gcTime: 30 * MIN } as const;
const PRICES = { staleTime: MIN } as const;
const OPS = { staleTime: 30_000 } as const;

/** Polled queries report their last success to the top bar ("Last refreshed"). */
function usePolled(dataUpdatedAt: number, isSuccess: boolean) {
  const { markRefreshed } = useSettings();
  useEffect(() => {
    if (isSuccess && dataUpdatedAt) markRefreshed();
  }, [dataUpdatedAt, isSuccess, markRefreshed]);
}

export function useSession() {
  const refetchInterval = useRefetchInterval();
  const q = useQuery({ queryKey: ["session"], queryFn: ({ signal }) => marketApi.session(undefined, signal),
    ...PRICES, refetchInterval });
  usePolled(q.dataUpdatedAt, q.isSuccess);
  return q;
}

export function useLatest(keys: string[]) {
  const md = useMarketData();
  const refetchInterval = useRefetchInterval();
  const sorted = [...keys].sort();
  const q = useQuery({
    queryKey: ["latest", md.mode, sorted],
    queryFn: ({ signal }) => md.latest(sorted, signal),
    enabled: sorted.length > 0,
    ...PRICES,
    refetchInterval,
    placeholderData: keepPreviousData,
  });
  usePolled(q.dataUpdatedAt, q.isSuccess);
  return q;
}

export function useQuote(key: string) {
  const refetchInterval = useRefetchInterval();
  return useQuery({ queryKey: ["quote", key], queryFn: ({ signal }) => marketApi.quote(key, signal),
    ...PRICES, refetchInterval });
}

export function useCandles(key: string, q: CandleQuery) {
  const md = useMarketData();
  return useQuery({
    queryKey: ["candles", md.mode, key, q],
    queryFn: ({ signal }) => md.candles(key, q, signal),
    ...PRICES,
    placeholderData: keepPreviousData,
  });
}

export function useInstruments(q: InstrumentQuery) {
  return useQuery({ queryKey: ["instruments", q], queryFn: ({ signal }) => instrumentApi.list(q, signal),
    ...REFERENCE, placeholderData: keepPreviousData });
}

export function useSearch(text: string) {
  const t = text.trim();
  return useQuery({ queryKey: ["search", t], queryFn: ({ signal }) => instrumentApi.search(t, 12, signal),
    enabled: t.length >= 1, ...REFERENCE, placeholderData: keepPreviousData });
}

export function useProfile(key: string, asOf?: string) {
  return useQuery({ queryKey: ["profile", key, asOf], queryFn: ({ signal }) => instrumentApi.profile(key, asOf, signal),
    ...REFERENCE });
}

export function useQuality(key: string | null) {
  return useQuery({ queryKey: ["quality", key], queryFn: ({ signal }) => instrumentApi.quality(key ?? "", signal),
    enabled: !!key, ...OPS });
}

export function useFundamentals(key: string, asOf?: string) {
  return useQuery({ queryKey: ["fundamentals", key, asOf],
    queryFn: ({ signal }) => fundamentalApi.all(key, asOf, signal), ...REFERENCE });
}

export function useCorporateActions(key: string | null, asOf?: string) {
  return useQuery({ queryKey: ["corporate-actions", key, asOf],
    queryFn: ({ signal }) => fundamentalApi.corporateActions(key ?? "", asOf, signal), enabled: !!key, ...REFERENCE });
}

export function useNews(q: { instrument_key?: string; since?: string; limit?: number }) {
  const refetchInterval = useRefetchInterval();
  const r = useQuery({ queryKey: ["news", q], queryFn: ({ signal }) => newsApi.list(q, signal),
    staleTime: MIN, refetchInterval, placeholderData: keepPreviousData });
  usePolled(r.dataUpdatedAt, r.isSuccess);
  return r;
}

export function useSectors() {
  return useQuery({ queryKey: ["sectors"], queryFn: ({ signal }) => sectorApi.list(signal), ...REFERENCE });
}

export function useGlobal() {
  const refetchInterval = useRefetchInterval();
  return useQuery({ queryKey: ["global"], queryFn: ({ signal }) => globalApi.list(signal), ...PRICES, refetchInterval });
}

export function useGlobalCandles(key: string, limit = 60) {
  return useQuery({ queryKey: ["global-candles", key, limit],
    queryFn: ({ signal }) => globalApi.candles(key, limit, signal), ...PRICES });
}

export function useGlobalFinality(key: string, limit = 30) {
  return useQuery({ queryKey: ["global-finality", key, limit],
    queryFn: ({ signal }) => globalApi.finality(key, limit, signal), ...OPS });
}

export function useFreshness() {
  const refetchInterval = useRefetchInterval();
  const q = useQuery({ queryKey: ["freshness"], queryFn: ({ signal }) => operationsApi.freshness(signal),
    ...OPS, refetchInterval });
  usePolled(q.dataUpdatedAt, q.isSuccess);
  return q;
}

export function usePipeline() {
  const refetchInterval = useRefetchInterval();
  return useQuery({ queryKey: ["pipeline"], queryFn: ({ signal }) => operationsApi.pipeline(signal),
    ...OPS, refetchInterval });
}

export function useAcceptance() {
  return useQuery({ queryKey: ["acceptance"], queryFn: ({ signal }) => acceptanceApi.get(signal), ...OPS });
}
