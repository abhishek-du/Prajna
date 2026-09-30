import React, { useEffect, useState } from 'react'
import {
  Activity,
  AlertCircle,
  Clock,
  Lock,
  RefreshCw,
  Sliders,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { api } from '../../services/api'
import type { TechnicalValues } from '../../types/api'

interface TechnicalDataViewProps {
  instrumentKey: string
  tradingSymbol?: string
}

export const TechnicalDataView: React.FC<TechnicalDataViewProps> = ({
  instrumentKey,
  tradingSymbol,
}) => {
  const [data, setData] = useState<TechnicalValues | null>(null)
  const [timeframe, setTimeframe] = useState<string>('1d')
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const loadData = async () => {
    if (!instrumentKey) return
    try {
      setLoading(true)
      setError(null)
      const res = await api.getTechnicals(instrumentKey, timeframe)
      setData(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load technical values')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [instrumentKey, timeframe])

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header and Timeframe Selector */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Sliders className="w-5 h-5 text-emerald-400" />
            Technical Indicators & Metrics: {tradingSymbol || instrumentKey}
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Real calculated metrics with strict Stage 3 lock enforcement
          </p>
        </div>

        <div className="flex items-center space-x-2">
          {['1m', '15m', '1h', '1d'].map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1 rounded text-xs font-semibold transition ${
                timeframe === tf
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
          <button
            onClick={loadData}
            className="p-1.5 bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div className="py-16 text-center text-slate-400">
          <RefreshCw className="w-7 h-7 animate-spin mx-auto text-emerald-400 mb-2" />
          <p className="text-xs">Computing real technical values...</p>
        </div>
      ) : error && !data ? (
        <div className="p-6 bg-rose-950/20 border border-rose-800/40 rounded-xl text-center">
          <p className="text-xs text-rose-300 mb-3">{error}</p>
          <button
            onClick={loadData}
            className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-xs rounded text-slate-200"
          >
            Retry
          </button>
        </div>
      ) : !data ? null : (
        <>
          {/* 1. Real Available Values */}
          <div>
            <h2 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3">
              Computed Market Metrics (Real Backend Values)
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
                <div className="text-[10px] text-slate-500 uppercase">Open Price</div>
                <div className="text-base font-bold font-mono text-slate-100 mt-1">
                  ₹{data.open?.toFixed(2) ?? '--'}
                </div>
              </div>
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
                <div className="text-[10px] text-slate-500 uppercase">High Price</div>
                <div className="text-base font-bold font-mono text-emerald-400 mt-1">
                  ₹{data.high?.toFixed(2) ?? '--'}
                </div>
              </div>
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
                <div className="text-[10px] text-slate-500 uppercase">Low Price</div>
                <div className="text-base font-bold font-mono text-rose-400 mt-1">
                  ₹{data.low?.toFixed(2) ?? '--'}
                </div>
              </div>
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
                <div className="text-[10px] text-slate-500 uppercase">Close Price</div>
                <div className="text-base font-bold font-mono text-slate-100 mt-1">
                  ₹{data.close?.toFixed(2) ?? '--'}
                </div>
              </div>
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
                <div className="text-[10px] text-slate-500 uppercase">Day Range (H - L)</div>
                <div className="text-base font-bold font-mono text-slate-200 mt-1">
                  ₹{data.day_range?.toFixed(2) ?? '--'}
                </div>
              </div>
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
                <div className="text-[10px] text-slate-500 uppercase">Volume (Shares)</div>
                <div className="text-base font-bold font-mono text-cyan-300 mt-1">
                  {data.volume ? data.volume.toLocaleString('en-IN') : '--'}
                </div>
              </div>
            </div>
          </div>

          {/* 2. Stage 3 Locked Indicators Notice & Placeholders */}
          <div className="space-y-4 pt-2">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                Stage 3 Technical Feature Layer
              </h2>
              <span className="flex items-center gap-1.5 text-xs text-amber-400 font-semibold bg-amber-950/40 border border-amber-800/60 px-2.5 py-0.5 rounded-full">
                <Lock className="w-3 h-3" />
                Stage 3 Locked — Zero Fake Data Policy
              </span>
            </div>

            <div className="bg-amber-950/20 border border-amber-800/40 rounded-xl p-4 text-xs text-amber-300/90 leading-relaxed flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold text-amber-200">Stage 3 Gate Restriction:</span>{' '}
                Advanced mathematical indicators (EMA, SMA, RSI, MACD, ATR, VWAP, Volatility,
                Support/Resistance) require completion of Stage 1 & 2 gate verification, verified
                B2 timing contracts, and historical lookback warm-up. Per system design, indicators
                are not simulated or mocked.
              </div>
            </div>

            {/* Locked Indicator Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {Object.entries(data.stage3_indicators.indicators).map(([indicatorName]) => (
                <div
                  key={indicatorName}
                  className="bg-slate-900/50 border border-slate-800/70 rounded-xl p-3.5 flex flex-col justify-between opacity-80"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono font-semibold text-xs text-slate-300">
                      {indicatorName.replace('_', ' ')}
                    </span>
                    <Lock className="w-3.5 h-3.5 text-amber-400" />
                  </div>
                  <div className="py-2 text-center text-xs font-medium text-amber-400/90 bg-slate-950/60 border border-slate-800/80 rounded">
                    Not available — Stage 3 locked
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
