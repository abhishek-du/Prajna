/* Domain clients over /v1. One function per contract endpoint; no transformation
   of values (the UI formats, never alters, what the API returns). */
import type {
  Acceptance,
  CandleSeries,
  CorporateAction,
  Freshness,
  Fundamental,
  GlobalBar,
  GlobalInstrument,
  GlobalLabel,
  Instrument,
  LatestPrice,
  MarketSession,
  NewsItem,
  PipelineStatus,
  Profile,
  Quality,
  Quote,
  SearchHit,
  SectorCount,
  Timeframe,
} from "../types/api";
import { enc, get } from "./http";

type Sig = AbortSignal | undefined;

export const marketApi = {
  session: (date?: string, signal?: Sig) => get<MarketSession>("/market/session", { date }, signal),
  /** callers must not query with no keys (the hooks disable the query instead) */
  latest: (keys: string[], signal?: Sig) =>
    get<LatestPrice[]>("/latest", { keys: keys.slice(0, 200).join(",") }, signal),
  quote: (key: string, signal?: Sig) => get<Quote>(`/instruments/${enc(key)}/quote`, undefined, signal),
};

export interface InstrumentQuery {
  segment?: string;
  security_class?: string;
  lifecycle_status?: string;
  sector?: string;
  limit?: number;
  offset?: number;
}

export const instrumentApi = {
  list: (q: InstrumentQuery, signal?: Sig) => get<Instrument[]>("/instruments", { ...q }, signal),
  search: (q: string, limit = 20, signal?: Sig) => get<SearchHit[]>("/search", { q, limit }, signal),
  profile: (key: string, asOf?: string, signal?: Sig) =>
    get<Profile>(`/instruments/${enc(key)}/profile`, { as_of: asOf }, signal),
  quality: (key: string, signal?: Sig) => get<Quality>(`/instruments/${enc(key)}/quality`, undefined, signal),
};

export interface CandleQuery {
  timeframe: Exclude<Timeframe, "5m">;
  limit?: number;
  start?: string;
  end?: string;
  as_of?: string;
  adjusted?: boolean;
  allow_low_confidence?: boolean;
}

export const chartApi = {
  candles: (key: string, q: CandleQuery, signal?: Sig) =>
    get<CandleSeries>(`/instruments/${enc(key)}/candles`, { ...q }, signal),
};

export const fundamentalApi = {
  all: (key: string, asOf?: string, signal?: Sig) =>
    get<Fundamental[]>(`/instruments/${enc(key)}/fundamentals`, { as_of: asOf }, signal),
  corporateActions: (key: string, asOf?: string, signal?: Sig) =>
    get<CorporateAction[]>(`/instruments/${enc(key)}/corporate-actions`, { as_of: asOf }, signal),
};

export const newsApi = {
  list: (q: { instrument_key?: string; since?: string; limit?: number; as_of?: string }, signal?: Sig) =>
    get<NewsItem[]>("/news", { ...q }, signal),
};

export const sectorApi = {
  list: (signal?: Sig) => get<SectorCount[]>("/sectors", undefined, signal),
};

export const globalApi = {
  list: (signal?: Sig) => get<GlobalInstrument[]>("/global", undefined, signal),
  candles: (key: string, limit = 60, signal?: Sig) =>
    get<GlobalBar[]>(`/global/${enc(key)}/candles`, { limit }, signal),
  finality: (key: string, limit = 30, signal?: Sig) =>
    get<GlobalLabel[]>(`/global/${enc(key)}/finality`, { limit }, signal),
};

export const operationsApi = {
  freshness: (signal?: Sig) => get<Freshness[]>("/freshness", undefined, signal),
  pipeline: (signal?: Sig) => get<PipelineStatus>("/pipeline/status", undefined, signal),
};

export const acceptanceApi = {
  get: (signal?: Sig) => get<Acceptance>("/acceptance", undefined, signal),
};
