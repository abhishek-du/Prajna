import React from 'react'
import { NavLink } from 'react-router-dom'
import type { StageSummary } from '../../types/api'
import {
  Activity,
  Layers,
  Cpu,
  ShieldAlert,
  DollarSign,
  TrendingUp,
  Compass,
  BarChart2,
  Sliders,
  BookOpen,
  Globe,
  Newspaper,
  Database,
  Lock,
} from 'lucide-react'

interface NavItemConfig {
  label: string
  path: string
  icon: React.ReactNode
  stageNumber?: number
  badge?: string
  badgeColor?: string
}

const STAGE_ITEMS: NavItemConfig[] = [
  { stageNumber: 1, label: '1. Data Ingestion', path: '/stages/1', icon: <Layers className="w-4 h-4 text-cyan-400" /> },
  { stageNumber: 2, label: '2. Storage & Quality', path: '/stages/2', icon: <Layers className="w-4 h-4 text-blue-400" /> },
  { stageNumber: 3, label: '3. Feature Engineering', path: '/stages/3', icon: <Layers className="w-4 h-4 text-amber-400" /> },
  { stageNumber: 4, label: '4. Prediction Research', path: '/stages/4', icon: <Layers className="w-4 h-4 text-purple-400" /> },
  { stageNumber: 5, label: '5. Signals / Targets', path: '/stages/5', icon: <Cpu className="w-4 h-4 text-indigo-400" /> },
  { stageNumber: 6, label: '6. Risk Management', path: '/stages/6', icon: <ShieldAlert className="w-4 h-4 text-red-400" /> },
  { stageNumber: 7, label: '7. Paper Execution', path: '/stages/7', icon: <DollarSign className="w-4 h-4 text-emerald-400" /> },
  { stageNumber: 8, label: '8. Monitoring & KPIs', path: '/stages/8', icon: <TrendingUp className="w-4 h-4 text-teal-400" /> },
]

const MARKET_ITEMS: NavItemConfig[] = [
  { label: 'Stock Explorer', path: '/explorer', icon: <Compass className="w-4 h-4 text-slate-400" /> },
  { label: 'Stock Screener', path: '/screener', icon: <Activity className="w-4 h-4 text-emerald-400" /> },
  { label: 'Live Candle Chart', path: '/chart', icon: <BarChart2 className="w-4 h-4 text-blue-400" /> },
  { label: 'Technicals', path: '/technicals', icon: <Sliders className="w-4 h-4 text-amber-400" /> },
  { label: 'Fundamentals', path: '/fundamentals', icon: <BookOpen className="w-4 h-4 text-indigo-400" /> },
  { label: 'Global Markets', path: '/globals', icon: <Globe className="w-4 h-4 text-cyan-400" /> },
  { label: 'News Intelligence', path: '/news', icon: <Newspaper className="w-4 h-4 text-orange-400" /> },
]

const OPS_ITEMS: NavItemConfig[] = [
  { label: 'System Health', path: '/health', icon: <Activity className="w-4 h-4 text-slate-400" /> },
  { label: 'Operations & Logs', path: '/ops', icon: <Database className="w-4 h-4 text-slate-400" /> },
]

/** The badge is the stage's status from /api/v1/stages (never a constant: the earlier
 *  hard-coded "Stage 3 LOCKED" stayed wrong after Stage 3 went live). */
function stageBadge(st: StageSummary | undefined): { text: string; color: string } {
  if (!st) return { text: '…', color: 'bg-slate-800 text-slate-400 border-slate-700' }
  const s = st.status.toUpperCase()
  const color = /FAIL|ERROR|INADEQUATE|REFUSED/.test(s)
    ? 'bg-red-900/60 text-red-300 border-red-700/60'
    : /WARN|CALIBRAT|PENDING|NOT_AVAILABLE|UNKNOWN/.test(s)
      ? 'bg-amber-900/60 text-amber-300 border-amber-700/60'
      : /LOCK/.test(s)
        ? 'bg-slate-800 text-slate-300 border-slate-600'
        : 'bg-emerald-900/50 text-emerald-300 border-emerald-700/60'
  return { text: s.replace(/_/g, ' ').slice(0, 12), color }
}

export const Sidebar: React.FC<{ stages?: StageSummary[] }> = ({ stages }) => {
  return (
    <aside className="w-64 bg-slate-900/95 border-r border-slate-800 flex flex-col shrink-0 overflow-y-auto select-none">
      {/* Brand & Control Room Direct Link */}
      <div className="p-3.5 border-b border-slate-800/80 bg-slate-950/40">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `flex items-center justify-between px-3 py-2.5 rounded-lg border transition-all ${
              isActive
                ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-200'
                : 'bg-slate-800/60 border-slate-700/70 text-slate-200 hover:bg-slate-800'
            }`
          }
        >
          <div className="flex items-center gap-2.5">
            <Activity className="w-4 h-4 text-emerald-400 shrink-0" />
            <div>
              <div className="text-xs font-bold uppercase tracking-wider text-slate-100">Control Room</div>
              <div className="text-[10px] text-slate-400">8-Stage Central Overview</div>
            </div>
          </div>
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        </NavLink>
      </div>

      {/* Navigation Sections */}
      <div className="flex-1 py-3 px-2 space-y-5 text-xs">
        {/* Section 1: The 8 Stages */}
        <div>
          <div className="px-3 pb-1.5 text-[10px] font-bold tracking-wider uppercase text-slate-400 flex items-center justify-between">
            <span>Research Pipeline (1–8)</span>
            <span className="font-mono text-[9px] text-slate-400">PAPER</span>
          </div>
          <nav className="space-y-0.5">
            {STAGE_ITEMS.map(item => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center justify-between px-3 py-1.5 rounded-md font-medium transition-colors ${
                    isActive
                      ? 'bg-indigo-600/25 text-indigo-200 border border-indigo-500/40'
                      : 'text-slate-300 hover:bg-slate-800/70 hover:text-slate-100'
                  }`
                }
              >
                <div className="flex items-center gap-2.5 truncate">
                  {item.icon}
                  <span className="truncate">{item.label}</span>
                </div>
                {(() => {
                  const b = stageBadge(stages?.find(x => x.stage_number === item.stageNumber))
                  return (
                    <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded border shrink-0 ${b.color}`}
                          data-testid={`stage-badge-${item.stageNumber}`}>
                      {b.text.startsWith('LOCK') && <Lock className="w-2.5 h-2.5 inline mr-0.5" />}
                      {b.text}
                    </span>
                  )
                })()}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* Section 2: Market Intelligence */}
        <div>
          <div className="px-3 pb-1.5 text-[10px] font-bold tracking-wider uppercase text-slate-400">
            Market Intelligence
          </div>
          <nav className="space-y-0.5">
            {MARKET_ITEMS.map(item => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center justify-between px-3 py-1.5 rounded-md font-medium transition-colors ${
                    isActive
                      ? 'bg-slate-800 text-emerald-300 border border-slate-700'
                      : 'text-slate-300 hover:bg-slate-800/70 hover:text-slate-100'
                  }`
                }
              >
                <div className="flex items-center gap-2.5 truncate">
                  {item.icon}
                  <span className="truncate">{item.label}</span>
                </div>
              </NavLink>
            ))}
          </nav>
        </div>

        {/* Section 3: Operations & Monitoring */}
        <div>
          <div className="px-3 pb-1.5 text-[10px] font-bold tracking-wider uppercase text-slate-400">
            System & Operations
          </div>
          <nav className="space-y-0.5">
            {OPS_ITEMS.map(item => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center justify-between px-3 py-1.5 rounded-md font-medium transition-colors ${
                    isActive
                      ? 'bg-slate-800 text-emerald-300 border border-slate-700'
                      : 'text-slate-300 hover:bg-slate-800/70 hover:text-slate-100'
                  }`
                }
              >
                <div className="flex items-center gap-2.5 truncate">
                  {item.icon}
                  <span className="truncate">{item.label}</span>
                </div>
              </NavLink>
            ))}
          </nav>
        </div>
      </div>

      {/* Strict Compliance Box at Bottom */}
      <div className="p-3 border-t border-slate-800/80 bg-slate-950/70 text-[10px] space-y-1 text-slate-400 font-mono">
        <div className="text-amber-400 font-semibold flex items-center gap-1">
          <ShieldAlert className="w-3 h-3 text-amber-400" />
          <span>PAPER SIMULATION ONLY</span>
        </div>
        <p className="text-slate-400 leading-tight">
          No broker orders or profitability claims. Read-only API gateway.
        </p>
      </div>
    </aside>
  )
}
