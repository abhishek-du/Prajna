import React, { useEffect, useState } from 'react'
import {
  AlertTriangle,
  Calendar,
  CheckCircle,
  Clock,
  Globe,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { api } from '../../services/api'
import type { GlobalMarketsResponse } from '../../types/api'

export const GlobalMarketsView: React.FC = () => {
  const [data, setData] = useState<GlobalMarketsResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.getGlobalMarkets()
      setData(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load global market data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header & Contract Rules */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Globe className="w-5 h-5 text-cyan-400" />
            Global Markets & Benchmark Intelligence
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            13 Global Indices and FX Indicators with P5 Global Finality Contract Enforcement
          </p>
        </div>

        <button
          onClick={loadData}
          className="p-2 self-start bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-lg text-xs flex items-center gap-1.5"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh</span>
        </button>
      </div>

      {/* Contract Banner */}
      <div className="bg-cyan-950/20 border border-cyan-800/40 rounded-xl p-4 text-xs text-cyan-200/90 space-y-2">
        <div className="flex items-center gap-2 font-bold text-cyan-300">
          <ShieldCheck className="w-4 h-4 text-cyan-400" />
          P5 Global Finality Contract (Strict Exposure Rules)
        </div>
        <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px]">
          <li>
            <strong>CONFIRMED:</strong> First observed bar re-observed unchanged at least 6 hours
            later (or 4 days by age).
          </li>
          <li>
            <strong>WITHHELD:</strong> Any bar identified as <code>REVISED</code>, flat{' '}
            <code>PLACEHOLDER</code>, or awaiting second poll (<code>UNCONFIRMED</code>) is
            strictly hidden from execution and analysis.
          </li>
          <li>
            <strong>Vendor Semantics:</strong> USDINR labels Monday sessions on Sunday; N225 labels
            Friday sessions on Saturday. Shifted calendars are explicitly measured.
          </li>
        </ul>
      </div>

      {loading && !data ? (
        <div className="py-20 text-center text-slate-400">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto text-cyan-400 mb-3" />
          <p className="text-xs">Loading confirmed global market benchmarks...</p>
        </div>
      ) : error && !data ? (
        <div className="p-8 max-w-lg mx-auto bg-rose-950/20 border border-rose-800/40 rounded-xl text-center">
          <p className="text-rose-400 text-xs mb-3">{error}</p>
          <button
            onClick={loadData}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs"
          >
            Retry
          </button>
        </div>
      ) : !data ? null : (
        <>
          {/* Transparency Metrics Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase">Confirmed Instruments</div>
              <div className="text-xl font-bold font-mono text-emerald-400 mt-1">
                {data.markets.length} / 13
              </div>
            </div>
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase">Withheld Revisions</div>
              <div className="text-xl font-bold font-mono text-amber-400 mt-1">
                {data.withheld_counts['REVISED'] ?? 0}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">e.g. N225 2026-09-24</div>
            </div>
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase">Withheld Placeholders</div>
              <div className="text-xl font-bold font-mono text-slate-300 mt-1">
                {data.withheld_counts['PLACEHOLDER'] ?? 0}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">Flat holiday bars</div>
            </div>
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase">Pending Confirmation</div>
              <div className="text-xl font-bold font-mono text-cyan-300 mt-1">
                {data.withheld_counts['UNCONFIRMED'] ?? 0}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5">Awaiting 21:10 poll</div>
            </div>
          </div>

          {/* Global Markets Table */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between text-xs">
              <span className="font-bold text-slate-300 uppercase tracking-wider">
                Confirmed Global Instruments
              </span>
              <span className="text-slate-500 text-[11px] font-mono">
                Refresh Cadence: 12:40 & 21:10 IST
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/80 text-slate-400 text-[10px] uppercase border-b border-slate-800">
                  <tr>
                    <th className="py-3 px-4">Instrument</th>
                    <th className="py-3 px-3">Label Date</th>
                    <th className="py-3 px-3 text-right">Close</th>
                    <th className="py-3 px-3 text-right">High</th>
                    <th className="py-3 px-3 text-right">Low</th>
                    <th className="py-3 px-3">Finality Status</th>
                    <th className="py-3 px-3">Calendar Semantics</th>
                    <th className="py-3 px-4">Confirmed At</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-300">
                  {data.markets.map((m) => (
                    <tr key={m.instrument_key} className="hover:bg-slate-800/40">
                      <td className="py-3 px-4">
                        <div className="font-bold text-slate-200">{m.trading_symbol}</div>
                        <div className="text-[10px] text-slate-400">{m.name}</div>
                      </td>
                      <td className="py-3 px-3 font-mono text-slate-300">{m.label_date}</td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-slate-100">
                        {m.close.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-3 text-right font-mono text-emerald-400">
                        {m.high.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-3 text-right font-mono text-rose-400">
                        {m.low.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-3">
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-950/60 text-emerald-300 border border-emerald-800/50">
                          {m.finality}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-[11px] text-slate-400">
                        {m.semantics || 'weekdays'}
                        {m.weekend_label_share ? ` (${(m.weekend_label_share * 100).toFixed(1)}% wknd)` : ''}
                      </td>
                      <td className="py-3 px-4 font-mono text-[10px] text-slate-400">
                        {m.confirmed_at ? m.confirmed_at.slice(0, 16).replace('T', ' ') : '--'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
