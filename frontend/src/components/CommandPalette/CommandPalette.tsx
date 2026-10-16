import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search,
  Activity,
  Layers,
  BarChart2,
  Sliders,
  BookOpen,
  Globe,
  Newspaper,
  Compass,
  Cpu,
  DollarSign,
  ShieldAlert,
  Database,
  ArrowRight,
  TrendingUp,
} from 'lucide-react'
import { api } from '../../services/api'
import type { InstrumentItem } from '../../types/api'

interface CommandPaletteProps {
  isOpen: boolean
  onClose: () => void
}

interface QuickAction {
  id: string
  title: string
  subtitle: string
  path: string
  icon: React.ReactNode
  category: 'Stage' | 'Market' | 'System'
}

const STATIC_ACTIONS: QuickAction[] = [
  { id: 'home', title: 'Control Room (Overview)', subtitle: '8-stage pipeline overview & schedule', path: '/', icon: <Activity className="w-4 h-4 text-emerald-400" />, category: 'System' },
  { id: 'stage-1', title: 'Stage 1: Data Ingestion', subtitle: 'Coverage matrix, backfill supervisor & master changes', path: '/stages/1', icon: <Layers className="w-4 h-4 text-cyan-400" />, category: 'Stage' },
  { id: 'stage-2', title: 'Stage 2: Storage & Quality', subtitle: 'Gate criteria A–P, normalized data bars', path: '/stages/2', icon: <Layers className="w-4 h-4 text-blue-400" />, category: 'Stage' },
  { id: 'stage-3', title: 'Stage 3: Feature Engineering', subtitle: 'Feature registry v4, refusal audit & cards', path: '/stages/3', icon: <Layers className="w-4 h-4 text-amber-400" />, category: 'Stage' },
  { id: 'stage-4', title: 'Stage 4: Prediction Research', subtitle: 'Experiments E1–E4, Wilson CIs, disclosures', path: '/stages/4', icon: <Layers className="w-4 h-4 text-purple-400" />, category: 'Stage' },
  { id: 'stage-5', title: 'Stage 5: Signals / Targets', subtitle: 'TargetList per strategy, scores & diffs', path: '/stages/5', icon: <Cpu className="w-4 h-4 text-indigo-400" />, category: 'Stage' },
  { id: 'stage-6', title: 'Stage 6: Risk Management', subtitle: 'Limits in force, drawdown halts & approvals', path: '/stages/6', icon: <ShieldAlert className="w-4 h-4 text-red-400" />, category: 'Stage' },
  { id: 'stage-7', title: 'Stage 7: Paper Execution', subtitle: 'Simulated fills, fill rate & charges breakdown', path: '/stages/7', icon: <DollarSign className="w-4 h-4 text-emerald-400" />, category: 'Stage' },
  { id: 'stage-8', title: 'Stage 8: Monitoring & KPIs', subtitle: 'Equity curve vs Nifty 50, forward replay', path: '/stages/8', icon: <TrendingUp className="w-4 h-4 text-teal-400" />, category: 'Stage' },
  { id: 'explorer', title: 'Stock Explorer', subtitle: 'Browse 3,500+ NSE master instruments', path: '/explorer', icon: <Compass className="w-4 h-4 text-slate-400" />, category: 'Market' },
  { id: 'chart', title: 'Interactive Candle Chart', subtitle: '1m / 15m / 1h / 1d multi-timeframe chart', path: '/chart', icon: <BarChart2 className="w-4 h-4 text-blue-400" />, category: 'Market' },
  { id: 'technicals', title: 'Technicals & Indicators', subtitle: 'EMA, Supertrend, ATR, RSI calculations', path: '/technicals', icon: <Sliders className="w-4 h-4 text-amber-400" />, category: 'Market' },
  { id: 'fundamentals', title: 'Fundamentals & Corporate Actions', subtitle: 'Financial statements, dividends & splits', path: '/fundamentals', icon: <BookOpen className="w-4 h-4 text-indigo-400" />, category: 'Market' },
  { id: 'globals', title: 'Global Markets & Macro', subtitle: 'GIFT Nifty, S&P 500, Nikkei & USDINR finality', path: '/globals', icon: <Globe className="w-4 h-4 text-cyan-400" />, category: 'Market' },
  { id: 'news', title: 'News Intelligence', subtitle: 'Real-time multi-source news stream & links', path: '/news', icon: <Newspaper className="w-4 h-4 text-orange-400" />, category: 'Market' },
  { id: 'screener', title: 'Stock Screener', subtitle: 'Multi-variable market filters & saved screens', path: '/screener', icon: <Activity className="w-4 h-4 text-emerald-400" />, category: 'Market' },
  { id: 'health', title: 'System Health', subtitle: 'DB connection, Upstox token age & subsystems', path: '/health', icon: <Activity className="w-4 h-4 text-slate-400" />, category: 'System' },
  { id: 'ops', title: 'Admin & Operations', subtitle: 'Backfill supervisor logs, anomalies & revisions', path: '/ops', icon: <Database className="w-4 h-4 text-slate-400" />, category: 'System' },
]

export const CommandPalette: React.FC<CommandPaletteProps> = ({ isOpen, onClose }) => {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [instruments, setInstruments] = useState<InstrumentItem[]>([])
  const [loadingInstruments, setLoadingInstruments] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  // Search instruments when query changes
  useEffect(() => {
    if (!query.trim() || query.length < 2) {
      setInstruments([])
      setLoadingInstruments(false)
      return
    }

    let isMounted = true
    setLoadingInstruments(true)

    const timer = setTimeout(async () => {
      try {
        const resp = await api.getInstruments({ q: query.trim(), limit: 8 })
        if (isMounted) {
          setInstruments(resp.instruments)
          setLoadingInstruments(false)
        }
      } catch {
        if (isMounted) {
          setInstruments([])
          setLoadingInstruments(false)
        }
      }
    }, 200)

    return () => {
      isMounted = false
      clearTimeout(timer)
    }
  }, [query])

  // Filter static actions
  const filteredActions = query.trim()
    ? STATIC_ACTIONS.filter(
        a =>
          a.title.toLowerCase().includes(query.toLowerCase()) ||
          a.subtitle.toLowerCase().includes(query.toLowerCase()) ||
          a.category.toLowerCase().includes(query.toLowerCase())
      )
    : STATIC_ACTIONS

  // Combined items list for keyboard navigation
  const allItems: Array<
    | { type: 'action'; item: QuickAction }
    | { type: 'instrument'; item: InstrumentItem }
  > = [
    ...instruments.map(inst => ({ type: 'instrument' as const, item: inst })),
    ...filteredActions.map(action => ({ type: 'action' as const, item: action })),
  ]

  // Reset selected index when items change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query, instruments.length])

  // Handle keyboard events
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(prev => (prev + 1 < allItems.length ? prev + 1 : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(prev => (prev - 1 >= 0 ? prev - 1 : allItems.length - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const selected = allItems[selectedIndex]
      if (selected) {
        if (selected.type === 'action') {
          navigate(selected.item.path)
        } else {
          navigate(`/stocks/${encodeURIComponent(selected.item.instrument_key)}`)
        }
        onClose()
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-start justify-center pt-20 px-4 sm:px-6"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[75vh]"
        onClick={e => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Search Input Bar */}
        <div className="flex items-center px-4 py-3.5 border-b border-slate-800 bg-slate-950/70">
          <Search className="w-5 h-5 text-slate-400 mr-3 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            className="w-full bg-transparent text-slate-100 placeholder-slate-500 text-sm focus:outline-none"
            placeholder="Type a stock symbol (e.g. RELIANCE, TCS) or command..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <kbd className="hidden sm:inline-flex items-center gap-1 text-[10px] font-mono bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-0.5 rounded">
            ESC
          </kbd>
        </div>

        {/* Results List */}
        <div className="flex-1 overflow-y-auto p-2 divide-y divide-slate-800/60">
          {/* Instruments Section if query returned any */}
          {instruments.length > 0 && (
            <div className="pb-2">
              <div className="px-3 py-1 text-[11px] font-semibold text-emerald-400 uppercase tracking-wider">
                Stocks & Indices ({instruments.length})
              </div>
              {instruments.map((inst, idx) => {
                const isSelected = idx === selectedIndex
                return (
                  <button
                    key={inst.instrument_key}
                    type="button"
                    className={`w-full text-left px-3 py-2 rounded-lg flex items-center justify-between transition-colors ${
                      isSelected
                        ? 'bg-emerald-600/20 text-emerald-200 border border-emerald-500/30'
                        : 'text-slate-300 hover:bg-slate-800/60'
                    }`}
                    onClick={() => {
                      navigate(`/stocks/${encodeURIComponent(inst.instrument_key)}`)
                      onClose()
                    }}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="w-7 h-7 rounded bg-slate-800 flex items-center justify-center shrink-0 text-xs font-mono font-bold text-emerald-400 border border-slate-700">
                        {inst.trading_symbol.slice(0, 2)}
                      </div>
                      <div className="truncate">
                        <div className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                          <span>{inst.trading_symbol}</span>
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700">
                            {inst.security_class}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 truncate">
                          {inst.name || 'NSE Instrument'} &bull; {inst.sector || 'General'}
                        </div>
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-slate-500 shrink-0 ml-2" />
                  </button>
                )
              })}
            </div>
          )}

          {/* Navigation / Actions Section */}
          <div className="pt-2">
            <div className="px-3 py-1 text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center justify-between">
              <span>Control Room & Pages</span>
              {loadingInstruments && <span className="text-emerald-400">Searching...</span>}
            </div>
            {filteredActions.map((action, idx) => {
              const actualIndex = instruments.length + idx
              const isSelected = actualIndex === selectedIndex
              return (
                <button
                  key={action.id}
                  type="button"
                  className={`w-full text-left px-3 py-2 rounded-lg flex items-center justify-between transition-colors ${
                    isSelected
                      ? 'bg-indigo-600/20 text-indigo-200 border border-indigo-500/30'
                      : 'text-slate-300 hover:bg-slate-800/60'
                  }`}
                  onClick={() => {
                    navigate(action.path)
                    onClose()
                  }}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="p-1.5 rounded bg-slate-800/80 border border-slate-700 shrink-0">
                      {action.icon}
                    </div>
                    <div className="truncate">
                      <div className="text-sm font-medium text-slate-100">{action.title}</div>
                      <div className="text-xs text-slate-400 truncate">{action.subtitle}</div>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono text-slate-500 bg-slate-800/60 px-1.5 py-0.5 rounded border border-slate-800 shrink-0 ml-2">
                    {action.category}
                  </span>
                </button>
              )
            })}
          </div>

          {allItems.length === 0 && !loadingInstruments && (
            <div className="py-8 text-center text-slate-500 text-sm">
              No matching pages or instruments found for &ldquo;{query}&rdquo;
            </div>
          )}
        </div>

        {/* Footer shortcuts helper */}
        <div className="px-4 py-2 border-t border-slate-800 bg-slate-950/80 text-[11px] text-slate-500 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span>&uarr;&darr; Navigate</span>
            <span>&crarr; Select</span>
            <span>ESC Close</span>
          </div>
          <span className="text-amber-400/80 font-mono text-[10px]">PAPER ONLY &bull; NO BROKER ORDERS</span>
        </div>
      </div>
    </div>
  )
}
