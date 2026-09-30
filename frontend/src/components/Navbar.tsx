import React from 'react'
import {
  Activity,
  BarChart2,
  BookOpen,
  Compass,
  Cpu,
  Database,
  DollarSign,
  Globe,
  Lock,
  Newspaper,
  Sliders,
  TrendingUp,
  Wifi,
  WifiOff,
} from 'lucide-react'

export type NavTab =
  | 'overview'
  | 'explorer'
  | 'chart'
  | 'technicals'
  | 'fundamentals'
  | 'globals'
  | 'news'
  | 'screener'
  | 'signals'
  | 'portfolio'
  | 'health'
  | 'ops'

interface NavbarProps {
  activeTab: NavTab
  setActiveTab: (tab: NavTab) => void
  selectedKey: string
  wsStatus: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'
  marketOpen: boolean
  currentTimeIst: string
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  selectedKey,
  wsStatus,
  marketOpen,
  currentTimeIst,
}) => {
  const tabs: Array<{ id: NavTab; label: string; icon: React.ReactNode; badge?: string }> = [
    { id: 'overview', label: 'Overview', icon: <TrendingUp className="w-4 h-4" /> },
    { id: 'explorer', label: 'Explorer', icon: <Compass className="w-4 h-4" /> },
    { id: 'chart', label: 'Live Chart', icon: <BarChart2 className="w-4 h-4" /> },
    { id: 'technicals', label: 'Technicals', icon: <Sliders className="w-4 h-4" /> },
    { id: 'fundamentals', label: 'Fundamentals', icon: <BookOpen className="w-4 h-4" /> },
    { id: 'globals', label: 'Global Markets', icon: <Globe className="w-4 h-4" /> },
    { id: 'news', label: 'News', icon: <Newspaper className="w-4 h-4" /> },
    { id: 'screener', label: 'Screener', icon: <Activity className="w-4 h-4" /> },
    { id: 'signals', label: 'Signals', icon: <Cpu className="w-4 h-4" />, badge: 'LOCKED' },
    { id: 'portfolio', label: 'Portfolio', icon: <DollarSign className="w-4 h-4" />, badge: 'LOCKED' },
    { id: 'health', label: 'System Health', icon: <Activity className="w-4 h-4" /> },
    { id: 'ops', label: 'Operations', icon: <Database className="w-4 h-4" /> },
  ]

  const formatKeyDisplay = (k: string) => {
    return k.replace('NSE_EQ|', '').replace('NSE_INDEX|', '').replace('GLOBAL_INDEX|', '')
  }

  return (
    <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-50">
      {/* Top bar with branding, live clock, status pills */}
      <div className="flex items-center justify-between px-4 py-2 text-xs border-b border-slate-800/80 bg-slate-950/60">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-2">
            <span className="font-bold text-sm tracking-wider text-emerald-400">PRAJNA</span>
            <span className="text-slate-400 text-xs hidden sm:inline">| NSE AI Trading System</span>
          </div>

          <div className="h-3 w-px bg-slate-700" />

          {/* Active instrument pill */}
          <div className="flex items-center space-x-1.5 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700 text-slate-200">
            <span className="text-slate-400">Active:</span>
            <span className="font-mono font-semibold text-emerald-300">{formatKeyDisplay(selectedKey)}</span>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          {/* Market Status */}
          <div className="flex items-center space-x-1.5 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700">
            <span
              className={`w-2 h-2 rounded-full ${
                marketOpen ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
              }`}
            />
            <span className="text-slate-300 font-medium">
              {marketOpen ? 'Market Open' : 'Market Closed'}
            </span>
          </div>

          {/* IST Time */}
          <div className="font-mono text-slate-400 hidden md:inline">
            {currentTimeIst || 'IST --:--:--'}
          </div>

          {/* WebSocket Status */}
          <div className="flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] bg-slate-800 border border-slate-700">
            {wsStatus === 'CONNECTED' ? (
              <>
                <Wifi className="w-3 h-3 text-emerald-400" />
                <span className="text-emerald-400 font-medium">WS Live</span>
              </>
            ) : wsStatus === 'RECONNECTING' ? (
              <>
                <WifiOff className="w-3 h-3 text-amber-400 animate-pulse" />
                <span className="text-amber-400">Reconnecting</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3 h-3 text-rose-400" />
                <span className="text-rose-400">Disconnected</span>
              </>
            )}
          </div>

          {/* Stage 3 Lock Indicator */}
          <div className="flex items-center space-x-1 bg-amber-950/40 text-amber-300 border border-amber-800/60 px-2 py-0.5 rounded text-[11px] font-semibold">
            <Lock className="w-3 h-3 text-amber-400" />
            <span>Stage 3 Locked</span>
          </div>
        </div>
      </div>

      {/* Navigation tabs bar */}
      <nav className="flex items-center space-x-1 px-3 py-1.5 overflow-x-auto no-scrollbar">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                isActive
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/60 border border-transparent'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
              {tab.badge && (
                <span className="ml-1 text-[9px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 font-semibold">
                  {tab.badge}
                </span>
              )}
            </button>
          )
        })}
      </nav>
    </header>
  )
}
