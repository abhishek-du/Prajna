import React, { useEffect, useState } from 'react'
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Compass,
  Filter,
  RefreshCw,
  Search,
  Tag,
} from 'lucide-react'
import { api } from '../../services/api'
import type { InstrumentDetail, InstrumentItem } from '../../types/api'

interface StockExplorerProps {
  onSelectInstrument: (key: string) => void
  selectedKey: string
}

export const StockExplorer: React.FC<StockExplorerProps> = ({
  onSelectInstrument,
  selectedKey,
}) => {
  const [instruments, setInstruments] = useState<InstrumentItem[]>([])
  const [total, setTotal] = useState<number>(0)
  const [loading, setLoading] = useState<boolean>(true)
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [selectedClass, setSelectedClass] = useState<string>('')
  const [selectedSegment, setSelectedSegment] = useState<string>('NSE_EQ')
  const [page, setPage] = useState<number>(0)
  const limit = 25

  const [detailLoading, setDetailLoading] = useState<boolean>(false)
  const [detailData, setDetailData] = useState<InstrumentDetail | null>(null)

  const loadInstruments = async () => {
    try {
      setLoading(true)
      const res = await api.getInstruments({
        q: searchQuery || undefined,
        security_class: selectedClass || undefined,
        segment: selectedSegment || undefined,
        limit,
        offset: page * limit,
      })
      setInstruments(res.instruments)
      setTotal(res.total)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const loadDetail = async (key: string) => {
    try {
      setDetailLoading(true)
      const res = await api.getInstrumentDetail(key)
      setDetailData(res)
    } catch {
      setDetailData(null)
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => {
    loadInstruments()
  }, [searchQuery, selectedClass, selectedSegment, page])

  useEffect(() => {
    if (selectedKey) {
      loadDetail(selectedKey)
    }
  }, [selectedKey])

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header & Filters */}
      <div className="flex flex-col md:flex-row md:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Compass className="w-5 h-5 text-emerald-400" />
            NSE Stock Explorer & Universe Directory
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Searchable NSE equities, indices, and SCD2 instrument lifecycle management
          </p>
        </div>

        {/* Search input */}
        <div className="flex items-center gap-3">
          <div className="relative w-64 sm:w-80">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search symbol, company name, ISIN..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
                setPage(0)
              }}
              className="w-full bg-slate-900 border border-slate-700/80 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition"
            />
          </div>

          <button
            onClick={loadInstruments}
            className="p-2 bg-slate-900 hover:bg-slate-800 border border-slate-800 rounded-lg text-slate-400 hover:text-slate-200 transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Filter Chips Bar */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-400 flex items-center gap-1 font-semibold text-[11px] mr-2">
          <Filter className="w-3.5 h-3.5" /> Filter by:
        </span>

        {/* Segment selector */}
        <select
          value={selectedSegment}
          onChange={(e) => {
            setSelectedSegment(e.target.value)
            setPage(0)
          }}
          className="bg-slate-900 border border-slate-800 rounded px-2.5 py-1 text-slate-300 text-xs focus:outline-none focus:border-emerald-500"
        >
          <option value="">All Segments</option>
          <option value="NSE_EQ">NSE Equities (NSE_EQ)</option>
          <option value="NSE_INDEX">NSE Indices (NSE_INDEX)</option>
        </select>

        {/* Security Class selector */}
        <select
          value={selectedClass}
          onChange={(e) => {
            setSelectedClass(e.target.value)
            setPage(0)
          }}
          className="bg-slate-900 border border-slate-800 rounded px-2.5 py-1 text-slate-300 text-xs focus:outline-none focus:border-emerald-500"
        >
          <option value="">All Security Classes</option>
          <option value="STOCK">STOCK (Phase 3)</option>
          <option value="FUND_UNIT">FUND_UNIT</option>
          <option value="RIGHTS_ENTITLEMENT">RIGHTS_ENTITLEMENT</option>
          <option value="OTHER">OTHER (InvIT/REIT)</option>
        </select>

        <span className="ml-auto text-slate-500 text-xs font-mono">
          Showing {instruments.length} of {total} instruments
        </span>
      </div>

      {/* 2. Main Content: Table and Detail Drawer */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Instruments Table (2 Spans) */}
        <div className="lg:col-span-2 bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/70 border-b border-slate-800 text-slate-400 uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="py-3 px-4">Symbol / Name</th>
                  <th className="py-3 px-3">Sector</th>
                  <th className="py-3 px-3">Class</th>
                  <th className="py-3 px-3">Status</th>
                  <th className="py-3 px-3 text-right">Latest Close</th>
                  <th className="py-3 px-4 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {loading ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto text-emerald-400 mb-2" />
                      Loading instruments...
                    </td>
                  </tr>
                ) : instruments.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500">
                      No instruments matched the query.
                    </td>
                  </tr>
                ) : (
                  instruments.map((inst) => {
                    const isSelected = selectedKey === inst.instrument_key
                    return (
                      <tr
                        key={inst.instrument_key}
                        onClick={() => onSelectInstrument(inst.instrument_key)}
                        className={`cursor-pointer transition hover:bg-slate-800/50 ${
                          isSelected ? 'bg-emerald-500/10 border-l-2 border-emerald-400' : ''
                        }`}
                      >
                        <td className="py-2.5 px-4">
                          <div className="font-bold text-slate-200">{inst.trading_symbol}</div>
                          <div className="text-[10px] text-slate-400 truncate max-w-[180px]">
                            {inst.name || inst.isin || '--'}
                          </div>
                        </td>
                        <td className="py-2.5 px-3">
                          <span className="text-[11px] text-slate-400 truncate max-w-[120px] block">
                            {inst.sector || 'Unassigned'}
                          </span>
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium ${
                              inst.security_class === 'STOCK'
                                ? 'bg-blue-950/60 text-blue-300 border border-blue-800/40'
                                : 'bg-slate-800 text-slate-400'
                            }`}
                          >
                            {inst.security_class || 'INDEX'}
                          </span>
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                              inst.lifecycle_status === 'ACTIVE'
                                ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/40'
                                : 'bg-amber-950/60 text-amber-300 border border-amber-800/40'
                            }`}
                          >
                            {inst.lifecycle_status || 'UNKNOWN'}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono font-bold text-slate-200">
                          {inst.latest_close !== null
                            ? inst.latest_close.toLocaleString('en-IN', {
                                minimumFractionDigits: 2,
                              })
                            : '--'}
                        </td>
                        <td className="py-2.5 px-4 text-center">
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              onSelectInstrument(inst.instrument_key)
                            }}
                            className="p-1 hover:bg-slate-700 rounded text-slate-400 hover:text-emerald-400 transition"
                            title="Select instrument"
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

          {/* Pagination bar */}
          <div className="flex items-center justify-between p-3 border-t border-slate-800 bg-slate-950/40 text-xs">
            <span className="text-slate-500 font-mono">
              Page {page + 1} of {Math.ceil(total / limit) || 1}
            </span>
            <div className="flex items-center space-x-2">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="p-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed rounded text-slate-300"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                disabled={(page + 1) * limit >= total}
                onClick={() => setPage((p) => p + 1)}
                className="p-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed rounded text-slate-300"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Right Column: Instrument Deep Metadata Detail */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 space-y-4">
          <div className="border-b border-slate-800 pb-3 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-200 uppercase tracking-wide flex items-center gap-2">
              <Tag className="w-4 h-4 text-emerald-400" />
              Instrument Details
            </h2>
            <span className="text-[11px] font-mono text-slate-400">{selectedKey}</span>
          </div>

          {detailLoading ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              <RefreshCw className="w-5 h-5 animate-spin mx-auto text-emerald-400 mb-2" />
              Loading metadata...
            </div>
          ) : !detailData ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              Select an instrument to view details
            </div>
          ) : (
            <div className="space-y-4 text-xs">
              <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3.5 space-y-2">
                <div className="text-base font-bold text-slate-100">
                  {detailData.instrument.trading_symbol}
                </div>
                <div className="text-slate-400">{detailData.instrument.name || '--'}</div>
                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-800 text-[11px]">
                  <div>
                    <span className="text-slate-500">ISIN:</span>{' '}
                    <span className="font-mono text-slate-300">{detailData.instrument.isin || '--'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Sector:</span>{' '}
                    <span className="text-slate-300">{detailData.instrument.sector || '--'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Exchange:</span>{' '}
                    <span className="font-mono text-slate-300">{detailData.instrument.exchange}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Class:</span>{' '}
                    <span className="font-mono text-cyan-300">
                      {detailData.instrument.security_class || 'INDEX'}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">Lot Size:</span>{' '}
                    <span className="font-mono text-slate-300">{detailData.instrument.lot_size ?? '--'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Tick Size:</span>{' '}
                    <span className="font-mono text-slate-300">
                      {detailData.instrument.tick_size ? `₹${detailData.instrument.tick_size}` : '--'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Lifecycle Periods (SCD2 audit) */}
              <div>
                <h3 className="font-semibold text-slate-300 text-[11px] uppercase tracking-wider mb-2">
                  Lifecycle History (SCD2)
                </h3>
                <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                  {detailData.lifecycle_periods.map((p, i) => (
                    <div
                      key={i}
                      className="bg-slate-950/50 border border-slate-800/80 rounded p-2 text-[10px] space-y-0.5"
                    >
                      <div className="flex justify-between font-mono">
                        <span className="text-emerald-400 font-bold">{p.status as string}</span>
                        <span className="text-slate-500">
                          {p.valid_from ? String(p.valid_from).slice(0, 10) : ''} →{' '}
                          {p.valid_to ? String(p.valid_to).slice(0, 10) : 'Active'}
                        </span>
                      </div>
                      {Boolean(p.reason) && <div className="text-slate-400">{String(p.reason)}</div>}
                    </div>
                  ))}
                </div>
              </div>

              {/* Quick Actions */}
              <div className="pt-2">
                <button
                  onClick={() => onSelectInstrument(detailData.instrument.instrument_key)}
                  className="w-full py-2 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-300 font-semibold rounded text-xs transition"
                >
                  View Candlestick Chart for {detailData.instrument.trading_symbol}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
