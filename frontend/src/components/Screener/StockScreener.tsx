import React, { useEffect, useState } from 'react'
import {
  Activity,
  ArrowRight,
  Filter,
  Lock,
  RefreshCw,
  Search,
  Sliders,
} from 'lucide-react'
import { api } from '../../services/api'
import type { ScreenerRow } from '../../types/api'

interface StockScreenerProps {
  onSelectInstrument: (key: string) => void
}

export const StockScreener: React.FC<StockScreenerProps> = ({ onSelectInstrument }) => {
  const [stocks, setStocks] = useState<ScreenerRow[]>([])
  const [sectors, setSectors] = useState<string[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Filter States
  const [selectedSector, setSelectedSector] = useState<string>('')
  const [minPrice, setMinPrice] = useState<string>('')
  const [maxPrice, setMaxPrice] = useState<string>('')
  const [maxPe, setMaxPe] = useState<string>('')

  const loadScreener = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.getScreener({
        sector: selectedSector || undefined,
        min_price: minPrice ? parseFloat(minPrice) : undefined,
        max_price: maxPrice ? parseFloat(maxPrice) : undefined,
        max_pe: maxPe ? parseFloat(maxPe) : undefined,
        limit: 100,
      })
      setStocks(res.stocks)
      setSectors(res.sectors)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to execute stock screener')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadScreener()
  }, [selectedSector, minPrice, maxPrice, maxPe])

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header & Description */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Activity className="w-5 h-5 text-emerald-400" />
            Quantitative Multi-Factor Stock Screener
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Filter NSE equities across valuation, liquidity, and balance sheet metrics
          </p>
        </div>

        <button
          onClick={loadScreener}
          className="p-2 self-start bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-lg text-xs flex items-center gap-1.5"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Apply Filters</span>
        </button>
      </div>

      {/* 2. Interactive Filter Controls Strip */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
        <div className="flex items-center gap-2 text-xs font-bold text-slate-300 uppercase tracking-wider">
          <Filter className="w-3.5 h-3.5 text-emerald-400" />
          Screener Criteria
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          {/* Sector filter */}
          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Sector</label>
            <select
              value={selectedSector}
              onChange={(e) => setSelectedSector(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-emerald-500"
            >
              <option value="">All Sectors</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          {/* Min Price */}
          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Min Price (₹)</label>
            <input
              type="number"
              placeholder="e.g. 100"
              value={minPrice}
              onChange={(e) => setMinPrice(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-emerald-500"
            />
          </div>

          {/* Max Price */}
          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Max Price (₹)</label>
            <input
              type="number"
              placeholder="e.g. 5000"
              value={maxPrice}
              onChange={(e) => setMaxPrice(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-emerald-500"
            />
          </div>

          {/* Max P/E */}
          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Max P/E Multiple</label>
            <input
              type="number"
              placeholder="e.g. 30"
              value={maxPe}
              onChange={(e) => setMaxPe(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-emerald-500"
            />
          </div>
        </div>
      </div>

      {/* 3. Results Table */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
        <div className="p-3.5 border-b border-slate-800 flex items-center justify-between text-xs bg-slate-950/60">
          <span className="font-bold text-slate-300">
            Matched Stocks ({stocks.length})
          </span>
          <span className="text-[11px] text-slate-500 font-mono">
            Sorted by Liquidity (Volume)
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/80 text-slate-400 text-[10px] uppercase border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Symbol / Name</th>
                <th className="py-3 px-3">Sector</th>
                <th className="py-3 px-3 text-right">Price (₹)</th>
                <th className="py-3 px-3 text-right">Change %</th>
                <th className="py-3 px-3 text-right">Volume</th>
                <th className="py-3 px-3 text-right">P/E</th>
                <th className="py-3 px-3 text-right">P/B</th>
                <th className="py-3 px-3 text-right">ROE %</th>
                {/* Future Stage 3/4/5 Placeholder Columns */}
                <th className="py-3 px-3 text-center text-amber-400/80">
                  <div className="flex items-center justify-center gap-1">
                    <Lock className="w-3 h-3 text-amber-400" />
                    <span>AI Momentum</span>
                  </div>
                </th>
                <th className="py-3 px-3 text-center text-amber-400/80">
                  <div className="flex items-center justify-center gap-1">
                    <Lock className="w-3 h-3 text-amber-400" />
                    <span>Alpha Factor</span>
                  </div>
                </th>
                <th className="py-3 px-4 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {loading ? (
                <tr>
                  <td colSpan={11} className="py-16 text-center text-slate-500">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-emerald-400 mb-2" />
                    Screening universe...
                  </td>
                </tr>
              ) : stocks.length === 0 ? (
                <tr>
                  <td colSpan={11} className="py-16 text-center text-slate-500">
                    No stocks matched current screening filters
                  </td>
                </tr>
              ) : (
                stocks.map((stock) => {
                  const isUp = (stock.change_pct || 0) >= 0
                  return (
                    <tr
                      key={stock.instrument_key}
                      onClick={() => onSelectInstrument(stock.instrument_key)}
                      className="cursor-pointer hover:bg-slate-800/40 transition"
                    >
                      <td className="py-2.5 px-4">
                        <div className="font-bold text-slate-200">{stock.trading_symbol}</div>
                        <div className="text-[10px] text-slate-500 truncate max-w-[150px]">
                          {stock.name || '--'}
                        </div>
                      </td>
                      <td className="py-2.5 px-3">
                        <span className="text-[11px] text-slate-400 truncate max-w-[120px] block">
                          {stock.sector || 'Unassigned'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono font-bold text-slate-100">
                        {stock.price !== null
                          ? stock.price.toLocaleString('en-IN', { minimumFractionDigits: 2 })
                          : '--'}
                      </td>
                      <td
                        className={`py-2.5 px-3 text-right font-mono font-bold ${
                          isUp ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {isUp ? '+' : ''}
                        {stock.change_pct?.toFixed(2) ?? '0.00'}%
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-slate-400">
                        {stock.volume ? stock.volume.toLocaleString('en-IN') : '--'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-slate-200">
                        {stock.pe?.toFixed(2) ?? '--'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-slate-200">
                        {stock.pb?.toFixed(2) ?? '--'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-emerald-400">
                        {stock.roe ? `${stock.roe.toFixed(2)}%` : '--'}
                      </td>
                      {/* Disabled Stage 3/4/5 Placeholders */}
                      <td className="py-2.5 px-3 text-center">
                        <span className="px-2 py-0.5 rounded text-[10px] bg-slate-950 text-amber-400/80 border border-slate-800 font-mono">
                          Locked
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <span className="px-2 py-0.5 rounded text-[10px] bg-slate-950 text-amber-400/80 border border-slate-800 font-mono">
                          Locked
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            onSelectInstrument(stock.instrument_key)
                          }}
                          className="p-1 hover:bg-slate-700 rounded text-slate-400 hover:text-emerald-400"
                        >
                          <ArrowRight className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
