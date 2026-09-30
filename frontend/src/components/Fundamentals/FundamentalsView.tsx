import React, { useEffect, useState } from 'react'
import {
  BookOpen,
  Building,
  CheckCircle,
  Clock,
  DollarSign,
  FileText,
  PieChart,
  RefreshCw,
  TrendingUp,
} from 'lucide-react'
import { api } from '../../services/api'
import type { FundamentalsResponse } from '../../types/api'

interface FundamentalsViewProps {
  instrumentKey: string
  tradingSymbol?: string
}

export const FundamentalsView: React.FC<FundamentalsViewProps> = ({
  instrumentKey,
  tradingSymbol,
}) => {
  const [data, setData] = useState<FundamentalsResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'ratios' | 'statements' | 'actions' | 'shareholding'>('ratios')

  const loadFundamentals = async () => {
    if (!instrumentKey) return
    try {
      setLoading(true)
      setError(null)
      const res = await api.getFundamentals(instrumentKey)
      setData(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load fundamentals data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadFundamentals()
  }, [instrumentKey])

  if (loading && !data) {
    return (
      <div className="py-20 text-center text-slate-400">
        <RefreshCw className="w-8 h-8 animate-spin mx-auto text-emerald-400 mb-3" />
        <p className="text-sm">Loading fundamentals for {tradingSymbol || instrumentKey}...</p>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="p-8 max-w-lg mx-auto mt-12 bg-rose-950/20 border border-rose-800/40 rounded-xl text-center">
        <p className="text-rose-400 font-semibold mb-2">Failed to load fundamentals</p>
        <p className="text-xs text-rose-300/80 mb-4">{error}</p>
        <button
          onClick={loadFundamentals}
          className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs transition"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  const ratios = data.key_ratios

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header & Profile Overview */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-3">
          <div>
            <div className="text-xs font-mono text-emerald-400 font-semibold">{instrumentKey}</div>
            <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2 mt-0.5">
              <Building className="w-5 h-5 text-emerald-400" />
              {data.company_name || tradingSymbol || instrumentKey}
            </h1>
            <div className="flex items-center gap-3 text-xs text-slate-400 mt-1">
              <span>Sector: <strong className="text-slate-200">{data.sector || '--'}</strong></span>
              <span>•</span>
              <span>Industry: <strong className="text-slate-200">{data.industry || '--'}</strong></span>
            </div>
          </div>

          <button
            onClick={loadFundamentals}
            className="p-2 self-start bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs flex items-center gap-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
        </div>

        {data.description && (
          <p className="text-xs text-slate-300/90 leading-relaxed mt-3 max-h-24 overflow-y-auto pr-2">
            {data.description}
          </p>
        )}
      </div>

      {/* 2. Sub-Navigation Tabs */}
      <div className="flex border-b border-slate-800 space-x-2 text-xs">
        <button
          onClick={() => setActiveTab('ratios')}
          className={`pb-2.5 px-3 font-semibold transition border-b-2 ${
            activeTab === 'ratios'
              ? 'border-emerald-400 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Key Valuation Ratios
        </button>
        <button
          onClick={() => setActiveTab('statements')}
          className={`pb-2.5 px-3 font-semibold transition border-b-2 ${
            activeTab === 'statements'
              ? 'border-emerald-400 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Financial Statements ({data.statements.length})
        </button>
        <button
          onClick={() => setActiveTab('actions')}
          className={`pb-2.5 px-3 font-semibold transition border-b-2 ${
            activeTab === 'actions'
              ? 'border-emerald-400 text-emerald-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Corporate Actions ({data.corporate_actions.length})
        </button>
        {Boolean(data.shareholdings) && (
          <button
            onClick={() => setActiveTab('shareholding')}
            className={`pb-2.5 px-3 font-semibold transition border-b-2 ${
              activeTab === 'shareholding'
                ? 'border-emerald-400 text-emerald-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            Shareholding Pattern
          </button>
        )}
      </div>

      {/* 3. Tab Contents */}
      {activeTab === 'ratios' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">P/E Ratio</div>
              <div className="text-xl font-bold font-mono text-slate-100 mt-1">
                {ratios.pe?.toFixed(2) ?? '--'}
              </div>
              <div className="text-[10px] text-slate-400 mt-1">
                Sector P/E: <span className="font-mono text-slate-300">{ratios.sector_pe?.toFixed(2) ?? '--'}</span>
              </div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">P/B Ratio</div>
              <div className="text-xl font-bold font-mono text-slate-100 mt-1">
                {ratios.pb?.toFixed(2) ?? '--'}
              </div>
              <div className="text-[10px] text-slate-400 mt-1">Price to Book</div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">ROE (%)</div>
              <div className="text-xl font-bold font-mono text-emerald-400 mt-1">
                {ratios.roe?.toFixed(2) ?? '--'}%
              </div>
              <div className="text-[10px] text-slate-400 mt-1">Return on Equity</div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">ROCE (%)</div>
              <div className="text-xl font-bold font-mono text-emerald-400 mt-1">
                {ratios.roce?.toFixed(2) ?? '--'}%
              </div>
              <div className="text-[10px] text-slate-400 mt-1">Return on Capital Employed</div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">EPS</div>
              <div className="text-xl font-bold font-mono text-cyan-300 mt-1">
                ₹{ratios.eps?.toFixed(2) ?? '--'}
              </div>
              <div className="text-[10px] text-slate-400 mt-1">Earnings Per Share</div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">Dividend Yield</div>
              <div className="text-xl font-bold font-mono text-slate-100 mt-1">
                {ratios.dividend_yield?.toFixed(2) ?? '--'}%
              </div>
              <div className="text-[10px] text-slate-400 mt-1">Annual Yield</div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">Debt / Equity</div>
              <div className="text-xl font-bold font-mono text-slate-100 mt-1">
                {ratios.debt_to_equity?.toFixed(2) ?? '--'}
              </div>
              <div className="text-[10px] text-slate-400 mt-1">Leverage Ratio</div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">Price to Sales</div>
              <div className="text-xl font-bold font-mono text-slate-100 mt-1">
                {ratios.price_to_sales?.toFixed(2) ?? '--'}
              </div>
              <div className="text-[10px] text-slate-400 mt-1">P/S Multiple</div>
            </div>
          </div>

          {/* Full Raw Ratios Table if available */}
          {ratios.raw_ratios.length > 0 && (
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
              <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3">
                Complete Ratio Breakdown
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                {ratios.raw_ratios.map((r: any, i: number) => (
                  <div
                    key={i}
                    className="flex justify-between items-center bg-slate-950/50 border border-slate-800/80 px-3 py-2 rounded text-xs"
                  >
                    <span className="text-slate-400">{String(r.name || r.key || '--')}</span>
                    <span className="font-mono font-bold text-slate-200">
                      {String(r.company_value || r.value || '--')}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'statements' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4">
            {data.statements.map((s, idx) => (
              <div key={idx} className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-xs">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-3">
                  <div className="font-bold text-slate-200 uppercase tracking-wider flex items-center gap-2">
                    <FileText className="w-4 h-4 text-emerald-400" />
                    {s.statement_type.replace(/:/g, ' • ')}
                  </div>
                  <div className="text-slate-500 font-mono text-[11px]">
                    Period: {s.period_end || 'N/A'} ({s.period_type || 'N/A'})
                  </div>
                </div>

                <div className="max-h-60 overflow-y-auto pr-1">
                  <pre className="font-mono text-[11px] text-slate-300 bg-slate-950/80 p-3 rounded-lg overflow-x-auto">
                    {typeof s.payload === 'object'
                      ? JSON.stringify(s.payload, null, 2)
                      : String(s.payload)}
                  </pre>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'actions' && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-slate-800 font-bold text-xs uppercase text-slate-300">
            Recorded Corporate Actions (Splits, Bonuses, Dividends)
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/80 text-slate-400 text-[10px] uppercase border-b border-slate-800">
                <tr>
                  <th className="py-2.5 px-4">Action Type</th>
                  <th className="py-2.5 px-3">Ex-Date</th>
                  <th className="py-2.5 px-3">Record Date</th>
                  <th className="py-2.5 px-3">Factor</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Vendor Treatment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {data.corporate_actions.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-slate-500">
                      No corporate actions recorded for this instrument
                    </td>
                  </tr>
                ) : (
                  data.corporate_actions.map((ca) => (
                    <tr key={ca.id} className="hover:bg-slate-800/40">
                      <td className="py-2.5 px-4 font-bold text-slate-200">{ca.action_type}</td>
                      <td className="py-2.5 px-3 font-mono">{ca.ex_date || '--'}</td>
                      <td className="py-2.5 px-3 font-mono">{ca.record_date || '--'}</td>
                      <td className="py-2.5 px-3 font-mono text-cyan-300">
                        {ca.factor_price !== null ? ca.factor_price.toFixed(4) : '--'}
                      </td>
                      <td className="py-2.5 px-3">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300">
                          {ca.factor_status || 'UNKNOWN'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium ${
                            ca.vendor_applied === 'APPLIED'
                              ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/40'
                              : 'bg-slate-800 text-slate-400'
                          }`}
                        >
                          {ca.vendor_applied || 'UNKNOWN'}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === 'shareholding' && data.shareholdings && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 text-xs">
          <div className="font-bold text-xs uppercase text-slate-300 mb-3 flex items-center gap-2">
            <PieChart className="w-4 h-4 text-emerald-400" />
            Shareholding Distribution
          </div>
          <pre className="font-mono text-[11px] text-slate-300 bg-slate-950/80 p-3 rounded-lg overflow-x-auto">
            {JSON.stringify(data.shareholdings, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
