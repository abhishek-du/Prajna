/**
 * Prajna API Client.
 * All requests route through the backend API.
 * NO UPSTOX CREDENTIALS EVER REACH THE BROWSER.
 */

import type {
  AnomalyItem,
  BackupItem,
  CandleSeriesResponse,
  Envelope,
  FeatureCardResponse,
  FundamentalsResponse,
  GlobalMarketsResponse,
  IngestRunItem,
  InstrumentDetail,
  InstrumentListResponse,
  NewsResponse,
  OverviewData,
  PreopenHistoryItem,
  RevisionItem,
  ScreenerResponse,
  Stage1BackfillResponse,
  Stage1CoverageResponse,
  Stage2GateResponse,
  Stage3GateResponse,
  Stage3RegistryResponse,
  Stage3SnapshotsResponse,
  StagesOverviewResponse,
  StockLifecycleItem,
  StockPaperTradeItem,
  SystemHealthResponse,
  TechnicalValues,
  WarmupPlanResponse,
} from '../types/api'


const API_BASE = '/api/v1'

async function fetchEnvelope<T>(url: string): Promise<Envelope<T>> {
  const resp = await fetch(url)
  if (!resp.ok) {
    let errDetail = resp.statusText
    try {
      const errJson = await resp.json()
      if (errJson.detail) errDetail = errJson.detail
    } catch {
      // ignore
    }
    throw new Error(`API Error [${resp.status}]: ${errDetail}`)
  }
  return await resp.json()
}

async function fetchJson<T>(url: string): Promise<T> {
  const env = await fetchEnvelope<T>(url)
  return env.data
}

export const api = {
  getOverview: (): Promise<OverviewData> => {
    return fetchJson<OverviewData>(`${API_BASE}/overview`)
  },

  getStages: (): Promise<StagesOverviewResponse> => {
    return fetchJson<StagesOverviewResponse>(`${API_BASE}/stages`)
  },

  getStagesEnvelope: (): Promise<Envelope<StagesOverviewResponse>> => {
    return fetchEnvelope<StagesOverviewResponse>(`${API_BASE}/stages`)
  },

  getInstruments: (params?: {
    q?: string
    sector?: string
    security_class?: string
    segment?: string
    status?: string
    limit?: number
    offset?: number
  }): Promise<InstrumentListResponse> => {
    const sp = new URLSearchParams()
    if (params?.q) sp.append('q', params.q)
    if (params?.sector) sp.append('sector', params.sector)
    if (params?.security_class) sp.append('security_class', params.security_class)
    if (params?.segment) sp.append('segment', params.segment)
    if (params?.status) sp.append('status', params.status)
    if (params?.limit) sp.append('limit', params.limit.toString())
    if (params?.offset) sp.append('offset', params.offset.toString())
    return fetchJson<InstrumentListResponse>(`${API_BASE}/instruments?${sp.toString()}`)
  },

  getInstrumentDetail: (key: string): Promise<InstrumentDetail> => {
    return fetchJson<InstrumentDetail>(`${API_BASE}/instruments/${encodeURIComponent(key)}`)
  },

  getInstrumentPreopen: (key: string, limit: number = 60): Promise<PreopenHistoryItem[]> => {
    return fetchJson<PreopenHistoryItem[]>(
      `${API_BASE}/instruments/${encodeURIComponent(key)}/preopen?limit=${limit}`
    )
  },

  getInstrumentPaperTrades: (key: string, limit: number = 100): Promise<StockPaperTradeItem[]> => {
    return fetchJson<StockPaperTradeItem[]>(
      `${API_BASE}/instruments/${encodeURIComponent(key)}/paper-trades?limit=${limit}`
    )
  },

  getInstrumentLifecycle: (key: string): Promise<StockLifecycleItem> => {
    return fetchJson<StockLifecycleItem>(
      `${API_BASE}/instruments/${encodeURIComponent(key)}/lifecycle`
    )
  },

  getCandles: (
    key: string,
    timeframe: string = '1d',
    options?: {
      start?: string
      end?: string
      limit?: number
      adjusted?: boolean
      allow_low_confidence?: boolean
    }
  ): Promise<CandleSeriesResponse> => {
    const sp = new URLSearchParams()
    sp.append('timeframe', timeframe)
    if (options?.start) sp.append('start', options.start)
    if (options?.end) sp.append('end', options.end)
    if (options?.limit) sp.append('limit', options.limit.toString())
    if (options?.adjusted) sp.append('adjusted', 'true')
    if (options?.allow_low_confidence) sp.append('allow_low_confidence', 'true')
    return fetchJson<CandleSeriesResponse>(
      `${API_BASE}/candles/${encodeURIComponent(key)}?${sp.toString()}`
    )
  },

  getTechnicals: (key: string, timeframe: string = '1d'): Promise<TechnicalValues> => {
    return fetchJson<TechnicalValues>(
      `${API_BASE}/technicals/${encodeURIComponent(key)}?timeframe=${timeframe}`
    )
  },

  getFundamentals: (key: string): Promise<FundamentalsResponse> => {
    return fetchJson<FundamentalsResponse>(`${API_BASE}/fundamentals/${encodeURIComponent(key)}`)
  },

  getGlobalMarkets: (): Promise<GlobalMarketsResponse> => {
    return fetchJson<GlobalMarketsResponse>(`${API_BASE}/global-markets`)
  },

  getNews: (params?: { instrument_key?: string; limit?: number }): Promise<NewsResponse> => {
    const sp = new URLSearchParams()
    if (params?.instrument_key) sp.append('instrument_key', params.instrument_key)
    if (params?.limit) sp.append('limit', params.limit.toString())
    return fetchJson<NewsResponse>(`${API_BASE}/news?${sp.toString()}`)
  },

  getScreener: (params?: {
    sector?: string
    min_price?: number
    max_price?: number
    min_pe?: number
    max_pe?: number
    limit?: number
    offset?: number
  }): Promise<ScreenerResponse> => {
    const sp = new URLSearchParams()
    if (params?.sector) sp.append('sector', params.sector)
    if (params?.min_price !== undefined) sp.append('min_price', params.min_price.toString())
    if (params?.max_price !== undefined) sp.append('max_price', params.max_price.toString())
    if (params?.min_pe !== undefined) sp.append('min_pe', params.min_pe.toString())
    if (params?.max_pe !== undefined) sp.append('max_pe', params.max_pe.toString())
    if (params?.limit) sp.append('limit', params.limit.toString())
    if (params?.offset) sp.append('offset', params.offset.toString())
    return fetchJson<ScreenerResponse>(`${API_BASE}/screener?${sp.toString()}`)
  },

  getSignals: (): Promise<{ status: string; stage: string; message: string; signals: unknown[] }> => {
    return fetchJson(`${API_BASE}/signals`)
  },

  getPortfolio: (): Promise<{
    status: string
    stage: string
    message: string
    holdings: unknown[]
    positions: unknown[]
    orders: unknown[]
  }> => {
    return fetchJson(`${API_BASE}/portfolio`)
  },

  getHealth: (): Promise<SystemHealthResponse> => {
    return fetchJson<SystemHealthResponse>(`${API_BASE}/health`)
  },

  getOpsRuns: (params?: { status?: string; stream?: string; limit?: number }): Promise<IngestRunItem[]> => {
    const sp = new URLSearchParams()
    if (params?.status) sp.append('status', params.status)
    if (params?.stream) sp.append('stream', params.stream)
    if (params?.limit) sp.append('limit', params.limit.toString())
    return fetchJson<IngestRunItem[]>(`${API_BASE}/ops/runs?${sp.toString()}`)
  },

  getOpsAnomalies: (limit: number = 50): Promise<AnomalyItem[]> => {
    return fetchJson<AnomalyItem[]>(`${API_BASE}/ops/anomalies?limit=${limit}`)
  },

  getOpsRevisions: (limit: number = 50): Promise<RevisionItem[]> => {
    return fetchJson<RevisionItem[]>(`${API_BASE}/ops/revisions?limit=${limit}`)
  },

  getOpsBackups: (): Promise<BackupItem[]> => {
    return fetchJson<BackupItem[]>(`${API_BASE}/ops/backups`)
  },

  getOpsWarmup: (params?: {
    sessions?: number
    timeframes?: string
    fraction?: number
  }): Promise<WarmupPlanResponse> => {
    const sp = new URLSearchParams()
    if (params?.sessions) sp.append('sessions', params.sessions.toString())
    if (params?.timeframes) sp.append('timeframes', params.timeframes)
    if (params?.fraction) sp.append('fraction', params.fraction.toString())
    return fetchJson<WarmupPlanResponse>(`${API_BASE}/ops/warmup?${sp.toString()}`)
  },

  getStage1Coverage: (): Promise<Stage1CoverageResponse> => {
    return fetchJson<Stage1CoverageResponse>(`${API_BASE}/stages/1/coverage`)
  },

  getStage1Backfill: (): Promise<Stage1BackfillResponse> => {
    return fetchJson<Stage1BackfillResponse>(`${API_BASE}/stages/1/backfill`)
  },

  getStage2Gate: (): Promise<Stage2GateResponse> => {
    return fetchJson<Stage2GateResponse>(`${API_BASE}/stages/2/gate`)
  },

  getStage3Gate: (): Promise<Stage3GateResponse> => {
    return fetchJson<Stage3GateResponse>(`${API_BASE}/stages/3/gate`)
  },

  getStage3Registry: (): Promise<Stage3RegistryResponse> => {
    return fetchJson<Stage3RegistryResponse>(`${API_BASE}/stages/3/registry`)
  },

  getStage3Snapshots: (date?: string): Promise<Stage3SnapshotsResponse> => {
    const q = date ? `?date=${encodeURIComponent(date)}` : ''
    return fetchJson<Stage3SnapshotsResponse>(`${API_BASE}/stages/3/snapshots${q}`)
  },

  getFeatureCard: (key: string, snapshot: string = 'PRE_OPEN', date?: string): Promise<FeatureCardResponse> => {
    const sp = new URLSearchParams({ snapshot })
    if (date) sp.append('date', date)
    return fetchJson<FeatureCardResponse>(`${API_BASE}/features/${encodeURIComponent(key)}?${sp.toString()}`)
  },
}

