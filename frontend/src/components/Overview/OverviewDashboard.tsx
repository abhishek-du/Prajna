import React, { useEffect, useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  Clock,
  ExternalLink,
  Globe,
  Newspaper,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react'
import { api } from '../../services/api'
import type { OverviewData, TickerCardData } from '../../types/api'

interface OverviewDashboardProps {
  onSelectInstrument: (key: string) => void
}

export const OverviewDashboard: React.FC<OverviewDashboardProps> = ({ onSelectInstrument }) => {
  const [data, setData] = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.getOverview()
      setData(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load overview data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    const timer = setInterval(loadData, 10000)
    return () => clearInterval(timer)
  }, [])

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center p-16 text-slate-400">
        <RefreshCw className="w-8 h-8 animate-spin text-emerald-400 mb-3" />
        <p className="text-sm">Loading market intelligence overview...</p>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="p-8 max-w-lg mx-auto mt-12 bg-rose-950/20 border border-rose-800/40 rounded-xl text-center">
        <p className="text-rose-400 font-semibold mb-2">Failed to load market overview</p>
        <p className="text-xs text-rose-300/80 mb-4">{error}</p>
        <button
          onClick={loadData}
          className="px-4 py-1.5 bg-rose-800/50 hover:bg-rose-800 text-rose-100 rounded text-xs transition"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* 1. Header Banner & Market Session Status */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-emerald-400" />
            Market Intelligence Overview
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            NSE Live feeds, Global benchmarks, Pipeline telemetry, and Provenance audit
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg flex items-center gap-2.5">
            <Clock className="w-4 h-4 text-emerald-400" />
            <div>
              <div className="text-[10px] text-slate-400 uppercase tracking-wider">Session Status</div>
              <div className="text-xs font-semibold text-slate-200">
                {data.market_status.message}
              </div>
            </div>
          </div>
          <button
            onClick={loadData}
            title="Refresh overview"
            className="p-2 bg-slate-900 hover:bg-slate-800 border border-slate-800 rounded-lg text-slate-400 hover:text-slate-200 transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* 2. Primary Ticker Cards (NIFTY 50, BANK NIFTY, INDIA VIX, GIFT NIFTY) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {data.indices.map((idx: TickerCardData) => {
          const isPositive = (idx.change || 0) >= 0
          return (
            <div
              key={idx.instrument_key}
              onClick={() => onSelectInstrument(idx.instrument_key)}
              className="bg-slate-900/80 hover:bg-slate-800/80 cursor-pointer border border-slate-800 hover:border-slate-700 transition p-4 rounded-xl relative overflow-hidden group"
            >
              <div className="flex justify-between items-start mb-2">
                <div>
                  <div className="text-xs font-semibold text-slate-400 group-hover:text-slate-200 transition">
                    {idx.name}
                  </div>
                  <div className="text-[10px] font-mono text-slate-500">
                    {idx.market_date || 'Session Date'}
                  </div>
                </div>
                <div
                  className={`flex items-center text-xs font-bold px-1.5 py-0.5 rounded ${
                    isPositive
                      ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                      : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                  }`}
                >
                  {isPositive ? (
                    <ArrowUpRight className="w-3.5 h-3.5 mr-0.5" />
                  ) : (
                    <ArrowDownRight className="w-3.5 h-3.5 mr-0.5" />
                  )}
                  {isPositive ? '+' : ''}
                  {idx.change_pct !== null ? `${idx.change_pct}%` : '0.0%'}
                </div>
              </div>

              <div className="text-2xl font-bold font-mono text-slate-100 mb-2">
                {idx.price !== null ? idx.price.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '--'}
              </div>

              <div className="grid grid-cols-3 gap-1 pt-2 border-t border-slate-800/80 text-[10px] text-slate-400">
                <div>
                  <span className="text-slate-500">Open:</span>{' '}
                  <span className="font-mono text-slate-300">{idx.open ?? '--'}</span>
                </div>
                <div>
                  <span className="text-slate-500">High:</span>{' '}
                  <span className="font-mono text-emerald-400">{idx.high ?? '--'}</span>
                </div>
                <div>
                  <span className="text-slate-500">Low:</span>{' '}
                  <span className="font-mono text-rose-400">{idx.low ?? '--'}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* 3. Two Columns: Global Benchmarks & News Intelligence */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column (2 spans): Confirmed Global Benchmarks */}
        <div className="lg:col-span-2 bg-slate-900/60 border border-slate-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-bold text-slate-200 uppercase tracking-wide">
                Confirmed Global Markets
              </h2>
            </div>
            <span className="text-[11px] text-slate-400 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              Finality Contract Enforced (≥ 6h Confirmation)
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {data.global_markets.map((m) => (
              <div
                key={m.instrument_key}
                className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3 hover:border-slate-700 transition"
              >
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="font-bold text-slate-300">{m.symbol}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-800/50 font-mono">
                    {m.finality}
                  </span>
                </div>
                <div className="text-xs text-slate-400 truncate mb-1">{m.name}</div>
                <div className="text-base font-bold font-mono text-slate-100">
                  {m.close.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </div>
                <div className="text-[10px] text-slate-500 font-mono mt-1">Label: {m.label_date}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Column: Latest Provenance-bearing News */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <Newspaper className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-bold text-slate-200 uppercase tracking-wide">
                Market News Feed
              </h2>
            </div>
            <span className="text-[10px] text-slate-500 font-mono">30-min Polled</span>
          </div>

          <div className="space-y-3">
            {data.recent_news.length === 0 ? (
              <div className="text-xs text-slate-500 py-6 text-center">No news articles available</div>
            ) : (
              data.recent_news.map((item) => (
                <div
                  key={item.news_id}
                  className="bg-slate-950/50 border border-slate-800/60 rounded-lg p-3 hover:border-slate-700 transition text-xs space-y-1.5"
                >
                  <div className="font-medium text-slate-200 line-clamp-2 hover:text-emerald-300">
                    {item.headline}
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1">
                    <span>{item.source}</span>
                    <span className="font-mono">
                      {item.published_at ? item.published_at.slice(0, 16).replace('T', ' ') : '--'}
                    </span>
                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-slate-400 hover:text-cyan-400"
                      >
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* 4. Telemetry and Pipeline Freshness Strip */}
      <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3 text-xs">
          <span className="font-bold text-slate-300 uppercase tracking-wide">
            Pipeline Freshness & Ingestion Health
          </span>
          <span className="text-emerald-400 font-semibold text-[11px]">
            ● Operational Status: Normal
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 text-xs">
          {data.freshness.map((f) => (
            <div
              key={f.stream}
              className="bg-slate-950/60 border border-slate-800/80 rounded p-2.5 space-y-1"
            >
              <div className="text-[10px] font-mono text-slate-400 truncate">{f.stream}</div>
              <div className="text-slate-200 font-semibold">
                {f.age_minutes !== null ? `${f.age_minutes}m ago` : 'Active'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
