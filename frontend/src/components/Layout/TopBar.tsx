import React, { useState, useEffect } from 'react'
import {
  Search,
  Wifi,
  WifiOff,
  Sun,
  Moon,
  Clock,
  ShieldAlert,
} from 'lucide-react'
import { useTheme } from '../../context/ThemeContext'
import type { MarketStatusData } from '../../types/api'

interface TopBarProps {
  marketState?: MarketStatusData | null
  wsStatus: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'
  onOpenCommandPalette: () => void
  selectedKey?: string
}

export const TopBar: React.FC<TopBarProps> = ({
  marketState,
  wsStatus,
  onOpenCommandPalette,
  selectedKey,
}) => {
  const { theme, toggleTheme } = useTheme()
  const [timeIst, setTimeIst] = useState<string>('')

  // IST live ticking clock
  useEffect(() => {
    const update = () => {
      const now = new Date()
      setTimeIst(
        now.toLocaleTimeString('en-IN', {
          timeZone: 'Asia/Kolkata',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        }) + ' IST'
      )
    }
    update()
    const interval = setInterval(update, 1000)
    return () => clearInterval(interval)
  }, [])

  // Format active instrument key for display
  const activeSymbol = selectedKey
    ? selectedKey.replace('NSE_EQ|', '').replace('NSE_INDEX|', '').replace('GLOBAL_INDEX|', '')
    : null

  // Market status color and label
  const isMarketOpen = marketState?.is_open ?? false
  const sessionMsg = marketState?.message || (isMarketOpen ? 'Market Open' : 'Market Closed')

  return (
    <header className="h-13 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-4 sticky top-0 z-40 select-none">
      {/* Left: Brand + Active Instrument */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="font-extrabold text-sm tracking-wider text-emerald-400">PRAJNA</span>
          <span className="text-slate-400 text-xs hidden sm:inline font-mono">| NSE AI Research</span>
        </div>

        {activeSymbol && (
          <div className="hidden md:flex items-center gap-1.5 bg-slate-800/80 px-2.5 py-0.5 rounded border border-slate-700 text-xs">
            <span className="text-slate-400">Active:</span>
            <span className="font-mono font-semibold text-emerald-300">{activeSymbol}</span>
          </div>
        )}
      </div>

      {/* Middle: Command Palette Quick Trigger */}
      <button
        type="button"
        onClick={onOpenCommandPalette}
        className="flex items-center gap-2.5 bg-slate-950/70 hover:bg-slate-800 text-slate-400 hover:text-slate-200 px-3 py-1.5 rounded-lg border border-slate-800 text-xs transition-all w-48 sm:w-72 justify-between"
      >
        <div className="flex items-center gap-2 truncate">
          <Search className="w-3.5 h-3.5 shrink-0 text-slate-500" />
          <span className="truncate">Search stocks, stages...</span>
        </div>
        <kbd className="hidden sm:inline-flex items-center gap-0.5 text-[10px] font-mono bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded border border-slate-700">
          ⌘K
        </kbd>
      </button>

      {/* Right: Status Pills, Clock, Theme */}
      <div className="flex items-center gap-2.5 text-xs">
        {/* Market Status Pill */}
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded border text-[11px] font-medium ${
            isMarketOpen
              ? 'bg-emerald-950/60 border-emerald-800/80 text-emerald-300'
              : 'bg-slate-800/70 border-slate-700 text-slate-300'
          }`}
          title={sessionMsg}
        >
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${
              isMarketOpen ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
            }`}
          />
          <span className="hidden lg:inline">{sessionMsg}</span>
          <span className="lg:hidden">{isMarketOpen ? 'Open' : 'Closed'}</span>
        </div>

        {/* IST Clock */}
        <div className="hidden md:flex items-center gap-1.5 bg-slate-800/70 border border-slate-700 px-2.5 py-1 rounded text-slate-300 font-mono text-[11px]">
          <Clock className="w-3 h-3 text-slate-400 shrink-0" />
          <span>{timeIst || '— IST'}</span>
        </div>

        {/* WebSocket Feed Status */}
        <div
          className="flex items-center gap-1 bg-slate-800/60 border border-slate-700 px-2 py-1 rounded text-slate-400 text-[11px]"
          title={`WebSocket feed: ${wsStatus}`}
        >
          {wsStatus === 'CONNECTED' ? (
            <Wifi className="w-3.5 h-3.5 text-emerald-400" />
          ) : (
            <WifiOff className="w-3.5 h-3.5 text-amber-400" />
          )}
          <span className="hidden xl:inline font-mono">{wsStatus}</span>
        </div>

        {/* PAPER ONLY Warning Badge */}
        <div className="flex items-center gap-1 px-2.5 py-1 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 font-mono text-[10px] font-semibold tracking-wide uppercase">
          <ShieldAlert className="w-3 h-3 shrink-0" />
          <span className="hidden sm:inline">PAPER ONLY</span>
        </div>

        {/* Theme Toggle */}
        <button
          type="button"
          onClick={toggleTheme}
          className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700"
          title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} mode`}
        >
          {theme === 'dark' ? <Sun className="w-3.5 h-3.5 text-amber-300" /> : <Moon className="w-3.5 h-3.5 text-slate-400" />}
        </button>
      </div>
    </header>
  )
}
