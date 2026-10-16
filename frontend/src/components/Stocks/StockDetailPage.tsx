import React, { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { CandleChart } from '../Chart/CandleChart'
import { api } from '../../services/api'
import type {
  FeatureCardResponse,
  PreopenHistoryItem,
  StockPaperTradeItem,
  StockLifecycleItem,
} from '../../types/api'
import {
  ArrowLeft,
  Calendar,
  Clock,
  Sliders,
  BookOpen,
  ShieldAlert,
  TrendingUp,
  Layers,
  Database,
  BarChart3,
  History,
  CheckCircle,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Search,
} from 'lucide-react'

type TabType = 'features' | 'preopen' | 'paper' | 'lifecycle'

export const StockDetailPage: React.FC = () => {
  const { key } = useParams<{ key: string }>()
  const instrumentKey = key ? decodeURIComponent(key) : 'NSE_EQ|INE002A01018'

  const [activeTab, setActiveTab] = useState<TabType>('features')
  const [lifecycleData, setLifecycleData] = useState<StockLifecycleItem | null>(null)
  const [_lifecycleLoading, setLifecycleLoading] = useState<boolean>(true)
  const [lifecycleError, setLifecycleError] = useState<string | null>(null)

  // Stage 3 Features state
  const [featureSnapshot, setFeatureSnapshot] = useState<'PRE_OPEN' | 'PRE_SESSION'>('PRE_OPEN')
  const [featureDate, setFeatureDate] = useState<string>('2026-10-16')
  const [featureGroup, setFeatureGroup] = useState<string>('ALL')
  const [featureSearch, setFeatureSearch] = useState<string>('')
  const [featureCard, setFeatureCard] = useState<FeatureCardResponse | null>(null)
  const [featuresLoading, setFeaturesLoading] = useState<boolean>(false)
  const [featuresError, setFeaturesError] = useState<string | null>(null)

  // Pre-Open state
  const [preopenHistory, setPreopenHistory] = useState<PreopenHistoryItem[]>([])
  const [preopenLoading, setPreopenLoading] = useState<boolean>(false)
  const [preopenError, setPreopenError] = useState<string | null>(null)

  // Paper Trades state
  const [paperTrades, setPaperTrades] = useState<StockPaperTradeItem[]>([])
  const [paperStrategyFilter, setPaperStrategyFilter] = useState<string>('ALL')
  const [paperLoading, setPaperLoading] = useState<boolean>(false)
  const [paperError, setPaperError] = useState<string | null>(null)

  // Load lifecycle & core details
  const loadLifecycle = async () => {
    try {
      setLifecycleLoading(true)
      setLifecycleError(null)
      const data = await api.getInstrumentLifecycle(instrumentKey)
      setLifecycleData(data)
    } catch (err: unknown) {
      setLifecycleError(err instanceof Error ? err.message : 'Failed to load instrument details')
    } finally {
      setLifecycleLoading(false)
    }
  }

  // Load Stage 3 features
  const loadFeatures = async () => {
    try {
      setFeaturesLoading(true)
      setFeaturesError(null)
      const data = await api.getFeatureCard(instrumentKey, featureSnapshot, featureDate)
      setFeatureCard(data)
    } catch (err: unknown) {
      setFeaturesError(err instanceof Error ? err.message : 'Failed to load feature card')
    } finally {
      setFeaturesLoading(false)
    }
  }

  // Load Pre-open history
  const loadPreopen = async () => {
    try {
      setPreopenLoading(true)
      setPreopenError(null)
      const data = await api.getInstrumentPreopen(instrumentKey, 60)
      setPreopenHistory(data)
    } catch (err: unknown) {
      setPreopenError(err instanceof Error ? err.message : 'Failed to load pre-open history')
    } finally {
      setPreopenLoading(false)
    }
  }

  // Load Paper trades
  const loadPaperTrades = async () => {
    try {
      setPaperLoading(true)
      setPaperError(null)
      const data = await api.getInstrumentPaperTrades(instrumentKey, 100)
      setPaperTrades(data)
    } catch (err: unknown) {
      setPaperError(err instanceof Error ? err.message : 'Failed to load paper trades')
    } finally {
      setPaperLoading(false)
    }
  }

  useEffect(() => {
    loadLifecycle()
  }, [instrumentKey])

  useEffect(() => {
    if (activeTab === 'features') {
      loadFeatures()
    } else if (activeTab === 'preopen') {
      loadPreopen()
    } else if (activeTab === 'paper') {
      loadPaperTrades()
    }
  }, [instrumentKey, activeTab, featureSnapshot, featureDate])

  const symbol =
    lifecycleData?.trading_symbol ||
    instrumentKey.replace('NSE_EQ|', '').replace('NSE_INDEX|', '').replace('GLOBAL_INDEX|', '')
  const companyName = lifecycleData?.name || symbol
  const isin = lifecycleData?.isin || '—'
  const sector = lifecycleData?.sector || '—'
  const lifecycleStatus = lifecycleData?.lifecycle_status || 'ACTIVE'
  const isIncluded = lifecycleData?.included ?? true

  // Features filtering
  const filteredFeatures = (featureCard?.features || []).filter((f) => {
    const matchesGroup = featureGroup === 'ALL' || f.group === featureGroup
    const matchesSearch =
      !featureSearch ||
      f.feature_id.toLowerCase().includes(featureSearch.toLowerCase()) ||
      (f.definition && f.definition.toLowerCase().includes(featureSearch.toLowerCase()))
    return matchesGroup && matchesSearch
  })

  // Feature groups list
  const availableGroups = Array.from(
    new Set((featureCard?.features || []).map((f) => f.group).filter(Boolean))
  )

  // Paper trades filtering
  const filteredPaperTrades = paperTrades.filter((t) => {
    if (paperStrategyFilter === 'ALL') return true
    return t.strategy === paperStrategyFilter
  })

  const paperStrategies = Array.from(new Set(paperTrades.map((t) => t.strategy)))

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {lifecycleError && (
        <div className="bg-rose-950/60 border border-rose-800/80 rounded-xl p-3 flex items-center gap-2 text-rose-300 text-xs">
          <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{lifecycleError}</span>
        </div>
      )}

      {/* Top Header Card */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-lg backdrop-blur-xs">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <Link
              to="/explorer"
              className="mt-1 p-2 rounded-lg bg-slate-950 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 transition-colors"
              title="Back to Explorer"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>

            <div>
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="text-2xl font-bold text-slate-100 tracking-tight">{symbol}</h1>
                <span className="text-xs font-mono px-2.5 py-0.5 rounded-full bg-slate-800/80 border border-slate-700 text-emerald-400">
                  {instrumentKey}
                </span>

                {/* Status Badges */}
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full font-semibold border ${
                    lifecycleStatus === 'ACTIVE'
                      ? 'bg-emerald-950/60 border-emerald-800/80 text-emerald-400'
                      : lifecycleStatus === 'SUSPENDED'
                        ? 'bg-amber-950/60 border-amber-800/80 text-amber-400'
                        : 'bg-rose-950/60 border-rose-800/80 text-rose-400'
                  }`}
                >
                  {lifecycleStatus}
                </span>

                {isIncluded ? (
                  <span className="text-xs px-2 py-0.5 rounded bg-emerald-950/40 border border-emerald-800/60 text-emerald-400 flex items-center gap-1">
                    <CheckCircle className="w-3 h-3" /> Universe Included
                  </span>
                ) : (
                  <span className="text-xs px-2 py-0.5 rounded bg-amber-950/40 border border-amber-800/60 text-amber-400 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> Filtered Out: {lifecycleData?.filter_reason || 'Criteria not met'}
                  </span>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400 mt-2 font-mono">
                <span className="font-sans text-slate-300 font-medium">{companyName}</span>
                <span>•</span>
                <span>
                  ISIN: <span className="text-slate-200">{isin}</span>
                </span>
                <span>•</span>
                <span>
                  Sector: <span className="text-slate-200">{sector}</span>
                </span>
                {lifecycleData?.segment && (
                  <>
                    <span>•</span>
                    <span>
                      Segment: <span className="text-slate-200">{lifecycleData.segment}</span>
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Quick Action Navigation Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/technicals?key=${encodeURIComponent(instrumentKey)}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-950 hover:bg-slate-800 text-slate-300 hover:text-white text-xs font-medium border border-slate-800 transition-colors"
            >
              <Sliders className="w-3.5 h-3.5 text-amber-400" />
              <span>Technicals</span>
            </Link>
            <Link
              to={`/fundamentals?key=${encodeURIComponent(instrumentKey)}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-950 hover:bg-slate-800 text-slate-300 hover:text-white text-xs font-medium border border-slate-800 transition-colors"
            >
              <BookOpen className="w-3.5 h-3.5 text-indigo-400" />
              <span>Fundamentals</span>
            </Link>
            <button
              onClick={() => {
                loadLifecycle()
                if (activeTab === 'features') loadFeatures()
                if (activeTab === 'preopen') loadPreopen()
                if (activeTab === 'paper') loadPaperTrades()
              }}
              className="p-1.5 rounded-lg bg-slate-950 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 transition-colors"
              title="Refresh All"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* HARD RULE 1: Persistent Paper Trading & Security Notice */}
      <div className="bg-amber-950/40 border border-amber-800/60 rounded-xl px-4 py-3 flex items-start gap-3 text-amber-300 text-xs shadow-sm">
        <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <div className="font-semibold text-amber-200">
            PAPER ONLY — simulated fills, not a profitability claim.
          </div>
          <div className="text-amber-400/90 leading-relaxed">
            All executions and order fills displayed are simulated paper records. Broker orders, modifications, and cancellations
            are strictly disabled. Upstox credentials and secrets never reach the browser or client-side runtime.
          </div>
        </div>
      </div>

      {/* Candlestick Chart with Corporate Action & Excluded Bar Markers */}
      <div className="space-y-2">
        <div className="flex items-center justify-between px-1">
          <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
            <BarChart3 className="w-4 h-4 text-emerald-400" />
            <span>Interactive Chart &amp; Canonical Event Markers</span>
          </div>
          <div className="text-[11px] text-slate-500 font-mono">
            Timeframes: 1m • 15m • 1h • 1d
          </div>
        </div>
        <CandleChart instrumentKey={instrumentKey} tradingSymbol={symbol} />
      </div>

      {/* Detail Navigation Tabs */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
        <div className="flex border-b border-slate-800 bg-slate-950/60 overflow-x-auto">
          <button
            onClick={() => setActiveTab('features')}
            className={`flex items-center gap-2 px-5 py-3 text-xs font-semibold border-b-2 transition select-none whitespace-nowrap ${
              activeTab === 'features'
                ? 'border-emerald-500 text-emerald-400 bg-emerald-500/10'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>Stage 3 Feature Values</span>
            {featureCard && (
              <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-800 text-slate-300 font-mono">
                {featureCard.values_count}/{featureCard.values_count + featureCard.nulls_count}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('preopen')}
            className={`flex items-center gap-2 px-5 py-3 text-xs font-semibold border-b-2 transition select-none whitespace-nowrap ${
              activeTab === 'preopen'
                ? 'border-emerald-500 text-emerald-400 bg-emerald-500/10'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <Clock className="w-4 h-4" />
            <span>Pre-Open Auction History</span>
            {preopenHistory.length > 0 && (
              <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-800 text-slate-300 font-mono">
                {preopenHistory.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('paper')}
            className={`flex items-center gap-2 px-5 py-3 text-xs font-semibold border-b-2 transition select-none whitespace-nowrap ${
              activeTab === 'paper'
                ? 'border-emerald-500 text-emerald-400 bg-emerald-500/10'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <TrendingUp className="w-4 h-4" />
            <span>Paper Trades &amp; Execution</span>
            {paperTrades.length > 0 && (
              <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-800 text-slate-300 font-mono">
                {paperTrades.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('lifecycle')}
            className={`flex items-center gap-2 px-5 py-3 text-xs font-semibold border-b-2 transition select-none whitespace-nowrap ${
              activeTab === 'lifecycle'
                ? 'border-emerald-500 text-emerald-400 bg-emerald-500/10'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
            }`}
          >
            <History className="w-4 h-4" />
            <span>Lifecycle &amp; ISIN History</span>
          </button>
        </div>

        {/* Tab Body Contents */}
        <div className="p-5">
          {/* TAB 1: STAGE 3 FEATURE VALUES */}
          {activeTab === 'features' && (
            <div className="space-y-4">
              {/* Feature Controls Strip */}
              <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-slate-950/60 rounded-lg border border-slate-800 text-xs">
                <div className="flex flex-wrap items-center gap-3">
                  {/* Snapshot selector */}
                  <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800">
                    {(['PRE_OPEN', 'PRE_SESSION'] as const).map((snap) => (
                      <button
                        key={snap}
                        onClick={() => setFeatureSnapshot(snap)}
                        className={`px-3 py-1 rounded text-xs font-semibold transition ${
                          featureSnapshot === snap
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                            : 'text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        {snap}
                      </button>
                    ))}
                  </div>

                  {/* Session Date Selector */}
                  <div className="flex items-center gap-1.5 text-slate-300">
                    <Calendar className="w-3.5 h-3.5 text-slate-400" />
                    <span>Session:</span>
                    <input
                      type="date"
                      value={featureDate}
                      onChange={(e) => setFeatureDate(e.target.value)}
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 font-mono text-xs focus:ring-1 focus:ring-emerald-500 outline-hidden"
                    />
                  </div>
                </div>

                {/* Search & Filter */}
                <div className="flex items-center gap-2">
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-2" />
                    <input
                      type="text"
                      placeholder="Search feature..."
                      value={featureSearch}
                      onChange={(e) => setFeatureSearch(e.target.value)}
                      className="bg-slate-900 border border-slate-800 rounded-lg pl-8 pr-3 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-hidden focus:border-slate-700 w-44"
                    />
                  </div>

                  <button
                    onClick={loadFeatures}
                    className="p-1.5 hover:bg-slate-800 rounded text-slate-400 hover:text-slate-200 transition"
                    title="Reload features"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Group Filter Chips */}
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-slate-400 mr-1 text-[11px] uppercase tracking-wider font-semibold">
                  Group:
                </span>
                <button
                  onClick={() => setFeatureGroup('ALL')}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono transition ${
                    featureGroup === 'ALL'
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      : 'bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800'
                  }`}
                >
                  ALL ({featureCard?.features.length || 0})
                </button>
                {availableGroups.map((grp) => (
                  <button
                    key={grp}
                    onClick={() => setFeatureGroup(grp)}
                    className={`px-2.5 py-1 rounded text-[11px] font-mono transition ${
                      featureGroup === grp
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        : 'bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800'
                    }`}
                  >
                    {grp}
                  </button>
                ))}
              </div>

              {/* Feature Metadata Strip */}
              {featureCard && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                    <div className="text-[11px] text-slate-400">Registry Version</div>
                    <div className="text-sm font-bold text-slate-200 font-mono mt-0.5">
                      {featureCard.feature_version}
                    </div>
                  </div>
                  <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                    <div className="text-[11px] text-slate-400">Registry SHA-256</div>
                    <div
                      className="text-xs font-mono text-emerald-400 truncate mt-0.5"
                      title={featureCard.registry_sha256}
                    >
                      {featureCard.registry_sha256.substring(0, 16)}...
                    </div>
                  </div>
                  <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                    <div className="text-[11px] text-slate-400">Values Computed</div>
                    <div className="text-sm font-bold text-emerald-400 font-mono mt-0.5">
                      {featureCard.values_count} OK
                    </div>
                  </div>
                  <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                    <div className="text-[11px] text-slate-400">Null / Refusal Count</div>
                    <div className="text-sm font-bold text-amber-400 font-mono mt-0.5">
                      {featureCard.nulls_count} Refused
                    </div>
                  </div>
                </div>
              )}

              {/* Features Table */}
              {featuresLoading ? (
                <div className="py-12 flex flex-col items-center justify-center text-slate-400">
                  <RefreshCw className="w-6 h-6 animate-spin text-emerald-400 mb-2" />
                  <span className="text-xs">Computing Point-in-Time features...</span>
                </div>
              ) : featuresError ? (
                <div className="p-4 bg-rose-950/40 border border-rose-800/60 rounded-lg text-rose-300 text-xs">
                  {featuresError}
                </div>
              ) : filteredFeatures.length === 0 ? (
                <div className="py-8 text-center text-slate-500 text-xs bg-slate-950/40 rounded-lg border border-slate-800">
                  No features match the selected snapshot and group filter.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/40">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 font-medium">
                      <tr>
                        <th className="px-3 py-2.5">Feature ID</th>
                        <th className="px-3 py-2.5">Group</th>
                        <th className="px-3 py-2.5">Definition</th>
                        <th className="px-3 py-2.5 text-right">Value</th>
                        <th className="px-3 py-2.5">Status / Refusal Reason</th>
                        <th className="px-3 py-2.5">Knowable At (IST)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                      {filteredFeatures.map((f) => {
                        const hasVal = f.value !== null && f.value !== undefined
                        return (
                          <tr key={f.feature_id} className="hover:bg-slate-900/40 transition">
                            <td className="px-3 py-2 text-slate-100 font-semibold">{f.feature_id}</td>
                            <td className="px-3 py-2 text-slate-400">
                              <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-[10px]">
                                {f.group}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-slate-400 font-sans max-w-xs truncate" title={f.definition || ''}>
                              {f.definition || '—'}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {hasVal ? (
                                <span className="text-emerald-400 font-bold font-mono">
                                  {typeof f.value === 'number' ? f.value.toFixed(4) : f.value}
                                </span>
                              ) : (
                                <span className="text-slate-500 font-mono">—</span>
                              )}
                            </td>
                            <td className="px-3 py-2 font-sans">
                              {hasVal ? (
                                <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/80 text-emerald-400">
                                  <CheckCircle className="w-2.5 h-2.5" /> Computed
                                </span>
                              ) : (
                                <span
                                  className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-amber-950/60 border border-amber-800/80 text-amber-300 max-w-xs truncate"
                                  title={f.reason || 'Input missing or window incomplete'}
                                >
                                  <AlertTriangle className="w-2.5 h-2.5 text-amber-400 shrink-0" />
                                  <span className="truncate">{f.reason || 'Input missing / refused'}</span>
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-slate-400">
                              {f.knowable_at ? (
                                new Date(f.knowable_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
                              ) : (
                                '—'
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: PRE-OPEN AUCTION HISTORY */}
          {activeTab === 'preopen' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <p>
                  Historical Indicative Equilibrium Price (IEP) auction ticks from{' '}
                  <span className="font-mono text-slate-300">canon_preopen</span> (09:00 - 09:08 IST).
                </p>
                <button
                  onClick={loadPreopen}
                  className="flex items-center gap-1 text-slate-300 hover:text-white"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Refresh</span>
                </button>
              </div>

              {preopenLoading ? (
                <div className="py-12 flex flex-col items-center justify-center text-slate-400">
                  <RefreshCw className="w-6 h-6 animate-spin text-emerald-400 mb-2" />
                  <span className="text-xs">Loading pre-open history...</span>
                </div>
              ) : preopenError ? (
                <div className="p-4 bg-rose-950/40 border border-rose-800/60 rounded-lg text-rose-300 text-xs">
                  {preopenError}
                </div>
              ) : preopenHistory.length === 0 ? (
                <div className="py-8 text-center text-slate-500 text-xs bg-slate-950/40 rounded-lg border border-slate-800">
                  No pre-open auction history recorded for {instrumentKey}.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/40">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 font-medium">
                      <tr>
                        <th className="px-3 py-2.5">Date</th>
                        <th className="px-3 py-2.5">Matched Time (IST)</th>
                        <th className="px-3 py-2.5 text-right">IEP (₹)</th>
                        <th className="px-3 py-2.5 text-right">IEQ (Vol)</th>
                        <th className="px-3 py-2.5 text-right">Total Buy (TBQ)</th>
                        <th className="px-3 py-2.5 text-right">Total Sell (TSQ)</th>
                        <th className="px-3 py-2.5 text-right">Order Imbalance</th>
                        <th className="px-3 py-2.5 text-right">Prev Close (₹)</th>
                        <th className="px-3 py-2.5 text-right">Gap %</th>
                        <th className="px-3 py-2.5">CAS Eligible</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                      {preopenHistory.map((item, idx) => {
                        const isUp = item.gap_pct !== null && item.gap_pct >= 0
                        return (
                          <tr key={idx} className="hover:bg-slate-900/40 transition">
                            <td className="px-3 py-2 text-slate-100 font-bold">{item.market_date}</td>
                            <td className="px-3 py-2 text-slate-400">{item.event_ts_ist || item.event_ts}</td>
                            <td className="px-3 py-2 text-right text-emerald-400 font-bold">
                              {item.iep !== null ? `₹${item.iep.toFixed(2)}` : '—'}
                            </td>
                            <td className="px-3 py-2 text-right text-slate-200">
                              {item.ieq !== null ? item.ieq.toLocaleString('en-IN') : '—'}
                            </td>
                            <td className="px-3 py-2 text-right text-slate-300">
                              {item.tbq !== null ? item.tbq.toLocaleString('en-IN') : '—'}
                            </td>
                            <td className="px-3 py-2 text-right text-slate-300">
                              {item.tsq !== null ? item.tsq.toLocaleString('en-IN') : '—'}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {item.imbalance_qty !== null ? (
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                                    item.imbalance_side === 'BUY'
                                      ? 'text-emerald-400 bg-emerald-950/60 border border-emerald-800'
                                      : item.imbalance_side === 'SELL'
                                        ? 'text-rose-400 bg-rose-950/60 border border-rose-800'
                                        : 'text-slate-400 bg-slate-900'
                                  }`}
                                >
                                  {item.imbalance_qty.toLocaleString('en-IN')} {item.imbalance_side}
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="px-3 py-2 text-right text-slate-400">
                              {item.rp !== null ? `₹${item.rp.toFixed(2)}` : '—'}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {item.gap_pct !== null ? (
                                <span className={`font-bold ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                                  {isUp ? `+${item.gap_pct.toFixed(2)}%` : `${item.gap_pct.toFixed(2)}%`}
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="px-3 py-2">
                              {item.cas_eligible ? (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400">
                                  YES
                                </span>
                              ) : (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-900 text-slate-500">
                                  NO
                                </span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: STOCK PAPER TRADES */}
          {activeTab === 'paper' && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-slate-400 uppercase text-[11px] font-semibold">Strategy:</span>
                  <div className="flex items-center gap-1 bg-slate-950 p-0.5 rounded-lg border border-slate-800">
                    <button
                      onClick={() => setPaperStrategyFilter('ALL')}
                      className={`px-2.5 py-1 rounded text-xs transition ${
                        paperStrategyFilter === 'ALL'
                          ? 'bg-emerald-500/20 text-emerald-400 font-semibold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      ALL ({paperTrades.length})
                    </button>
                    {paperStrategies.map((strat) => (
                      <button
                        key={strat}
                        onClick={() => setPaperStrategyFilter(strat)}
                        className={`px-2.5 py-1 rounded text-xs transition ${
                          paperStrategyFilter === strat
                            ? 'bg-emerald-500/20 text-emerald-400 font-semibold'
                            : 'text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        {strat} {strat === 'bench_c0' ? '(Benchmark)' : ''}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="text-[11px] text-slate-400 font-mono">
                  Reported from <span className="text-slate-300 font-bold">paper_fill</span> &amp; <span className="text-slate-300 font-bold">paper_run</span>
                </div>
              </div>

              {paperLoading ? (
                <div className="py-12 flex flex-col items-center justify-center text-slate-400">
                  <RefreshCw className="w-6 h-6 animate-spin text-emerald-400 mb-2" />
                  <span className="text-xs">Loading paper executions...</span>
                </div>
              ) : paperError ? (
                <div className="p-4 bg-rose-950/40 border border-rose-800/60 rounded-lg text-rose-300 text-xs">
                  {paperError}
                </div>
              ) : filteredPaperTrades.length === 0 ? (
                <div className="py-8 text-center text-slate-500 text-xs bg-slate-950/40 rounded-lg border border-slate-800">
                  No simulated paper trades recorded for this instrument in the selected filter.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/40">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 font-medium">
                      <tr>
                        <th className="px-3 py-2.5">Date</th>
                        <th className="px-3 py-2.5">Strategy</th>
                        <th className="px-3 py-2.5">Run ID</th>
                        <th className="px-3 py-2.5">Side</th>
                        <th className="px-3 py-2.5 text-right">Qty</th>
                        <th className="px-3 py-2.5 text-right">Fill Price (₹)</th>
                        <th className="px-3 py-2.5 text-right">Value (INR)</th>
                        <th className="px-3 py-2.5 text-right">Simulated P&amp;L (₹)</th>
                        <th className="px-3 py-2.5">Execution Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                      {filteredPaperTrades.map((t) => {
                        const isBuy = t.buy_px !== null && t.buy_px > 0
                        const px = isBuy ? t.buy_px : t.sell_px
                        const val = isBuy ? t.buy_value_inr : t.sell_value_inr
                        const pnl = t.pnl_inr
                        return (
                          <tr key={t.id} className="hover:bg-slate-900/40 transition">
                            <td className="px-3 py-2 text-slate-100 font-bold">{t.session_date}</td>
                            <td className="px-3 py-2 text-slate-300">
                              <span className="font-semibold text-slate-100">{t.strategy}</span>
                              {t.strategy === 'bench_c0' && (
                                <span className="ml-1 text-[10px] text-amber-400 font-sans">[Benchmark]</span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-slate-500 truncate max-w-[120px]" title={t.run_id}>
                              {t.run_id}
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                  isBuy
                                    ? 'bg-emerald-950/60 border border-emerald-800 text-emerald-400'
                                    : 'bg-rose-950/60 border border-rose-800 text-rose-400'
                                }`}
                              >
                                {isBuy ? 'BUY' : 'SELL'}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right text-slate-200">{t.qty}</td>
                            <td className="px-3 py-2 text-right text-slate-100 font-bold">
                              {px !== null && px !== undefined ? `₹${px.toFixed(2)}` : '—'}
                            </td>
                            <td className="px-3 py-2 text-right text-slate-300">
                              {val !== null && val !== undefined ? `₹${val.toFixed(2)}` : '—'}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {pnl !== null && pnl !== undefined ? (
                                <span className={`font-bold ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                  {pnl >= 0 ? `+₹${pnl.toFixed(2)}` : `-₹${Math.abs(pnl).toFixed(2)}`}
                                </span>
                              ) : (
                                <span className="text-slate-500">—</span>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              <span className="text-[10px] px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300">
                                {t.status}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: LIFECYCLE & ISIN HISTORY */}
          {activeTab === 'lifecycle' && (
            <div className="space-y-6">
              {/* Inclusion Status Card */}
              <div className="p-4 rounded-lg bg-slate-950/60 border border-slate-800 grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
                <div>
                  <span className="text-slate-400 block font-sans text-[11px]">Universe Inclusion</span>
                  <span
                    className={`font-bold text-sm inline-flex items-center gap-1 mt-1 ${
                      isIncluded ? 'text-emerald-400' : 'text-amber-400'
                    }`}
                  >
                    {isIncluded ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    {isIncluded ? 'INCLUDED' : 'EXCLUDED'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block font-sans text-[11px]">Exclusion / Filter Reason</span>
                  <span className="text-slate-300 block mt-1 font-sans">
                    {lifecycleData?.filter_reason || 'Eligible canonical security (no exclusions)'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block font-sans text-[11px]">Tracking Range</span>
                  <span className="text-slate-300 block mt-1">
                    First: {lifecycleData?.first_seen || '—'} • Last: {lifecycleData?.last_seen || '—'}
                  </span>
                </div>
              </div>

              {/* Sub-Section 1: Lifecycle Periods */}
              <div className="space-y-2">
                <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                  <History className="w-3.5 h-3.5 text-emerald-400" />
                  Lifecycle State Transitions (instrument_lifecycle_period)
                </h3>
                {lifecycleData?.lifecycle_periods.length === 0 ? (
                  <div className="text-slate-500 text-xs p-4 bg-slate-950/40 rounded border border-slate-800">
                    No lifecycle state transitions recorded.
                  </div>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/40">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 font-medium">
                        <tr>
                          <th className="px-3 py-2.5">Status</th>
                          <th className="px-3 py-2.5">Valid From</th>
                          <th className="px-3 py-2.5">Valid To</th>
                          <th className="px-3 py-2.5">Reason</th>
                          <th className="px-3 py-2.5">Knowable At</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                        {lifecycleData?.lifecycle_periods.map((p, idx) => (
                          <tr key={idx} className="hover:bg-slate-900/40 transition">
                            <td className="px-3 py-2 font-bold text-emerald-400">{p.status}</td>
                            <td className="px-3 py-2 text-slate-200">{p.valid_from}</td>
                            <td className="px-3 py-2 text-slate-400">{p.valid_to}</td>
                            <td className="px-3 py-2 text-slate-300 font-sans">{p.reason || '—'}</td>
                            <td className="px-3 py-2 text-slate-500">{p.knowable_at || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Sub-Section 2: Attribute & ISIN History */}
              <div className="space-y-2">
                <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-sky-400" />
                  Attribute Versions &amp; ISIN Map (instrument_attribute_version)
                </h3>
                {lifecycleData?.attribute_versions.length === 0 ? (
                  <div className="text-slate-500 text-xs p-4 bg-slate-950/40 rounded border border-slate-800">
                    No attribute changes recorded.
                  </div>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/40">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 font-medium">
                        <tr>
                          <th className="px-3 py-2.5">ID</th>
                          <th className="px-3 py-2.5">Valid From</th>
                          <th className="px-3 py-2.5">Valid To</th>
                          <th className="px-3 py-2.5">Trading Symbol</th>
                          <th className="px-3 py-2.5">ISIN</th>
                          <th className="px-3 py-2.5 text-right">Lot Size</th>
                          <th className="px-3 py-2.5 text-right">Tick Size</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                        {lifecycleData?.attribute_versions.map((a) => (
                          <tr key={a.id} className="hover:bg-slate-900/40 transition">
                            <td className="px-3 py-2 text-slate-500">{a.id}</td>
                            <td className="px-3 py-2 text-slate-200">{a.valid_from}</td>
                            <td className="px-3 py-2 text-slate-400">{a.valid_to}</td>
                            <td className="px-3 py-2 text-emerald-400 font-bold">{a.trading_symbol}</td>
                            <td className="px-3 py-2 text-slate-200">{a.isin || '—'}</td>
                            <td className="px-3 py-2 text-right text-slate-300">{a.lot_size ?? '—'}</td>
                            <td className="px-3 py-2 text-right text-slate-300">{a.tick_size ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
