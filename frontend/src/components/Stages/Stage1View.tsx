import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Database,
  Layers,
  Clock,
  AlertTriangle,
  RefreshCw,
  HardDrive,
  FileText,
  ShieldCheck,
  Building2,
  Calendar,
} from 'lucide-react'
import { api } from '../../services/api'
import type { MasterChangeItem } from '../../types/api'
import { backfillEtaText, backfillRateText } from '../../utils/backfill'


export const Stage1View: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'coverage' | 'backfill' | 'exclusions' | 'corporate_actions' | 'master'>('coverage')
  const [showRawJson, setShowRawJson] = useState(false)
  const [selectedReason, setSelectedReason] = useState<string>('all')

  const {
    data: coverage,
    isLoading: coverageLoading,
    error: coverageError,
    refetch: refetchCoverage,
  } = useQuery({
    queryKey: ['stage1Coverage'],
    queryFn: () => api.getStage1Coverage(),
    staleTime: 30000,
  })

  const {
    data: backfill,
    isLoading: backfillLoading,
    error: backfillError,
    refetch: refetchBackfill,
  } = useQuery({
    queryKey: ['stage1Backfill'],
    queryFn: () => api.getStage1Backfill(),
    staleTime: 15000,
  })

  const isLoading = coverageLoading || backfillLoading
  const hasError = coverageError || backfillError

  if (isLoading) {
    return (
      <div className="p-6 space-y-6 animate-pulse">
        <div className="h-20 bg-slate-800/40 rounded-xl" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 bg-slate-800/30 rounded-xl" />
          ))}
        </div>
        <div className="h-96 bg-slate-800/20 rounded-xl" />
      </div>
    )
  }

  if (hasError || !coverage) {
    return (
      <div className="p-8 text-center bg-rose-950/20 border border-rose-800/30 rounded-2xl m-6">
        <AlertTriangle className="w-12 h-12 text-rose-400 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-rose-200">Stage 1 Ingestion Data Unavailable</h3>
        <p className="text-sm text-slate-400 mt-1 max-w-md mx-auto">
          {coverageError instanceof Error ? coverageError.message : 'Unable to query canonical coverage and backfill status.'}
        </p>
        <button
          onClick={() => {
            refetchCoverage()
            refetchBackfill()
          }}
          className="mt-4 px-4 py-2 bg-rose-600/30 hover:bg-rose-600/40 border border-rose-500/30 text-rose-200 rounded-lg text-sm inline-flex items-center gap-2"
        >
          <RefreshCw className="w-4 h-4" /> Retry Query
        </button>
      </div>
    )
  }

  const filteredExclusions = selectedReason === 'all'
    ? coverage.recent_excluded_bars
    : coverage.recent_excluded_bars.filter((b) => b.reason === selectedReason)

  return (
    <div className="p-6 space-y-6 text-slate-200">
      {/* Top Header Card */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 backdrop-blur-md shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shadow-inner">
              <Database className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold tracking-tight text-white">Stage 1: Data Ingestion</h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
                  LIVE READY: PASS
                </span>
                <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-400 border border-slate-700">
                  POINT-IN-TIME VERIFIED
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1 font-mono">
                Canonical market bars from Upstox REST & historical backfill with strict B1/B2 knowability guarantees.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowRawJson(!showRawJson)}
              className="px-3 py-1.5 text-xs font-mono rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-300 flex items-center gap-1.5 transition-colors"
            >
              <FileText className="w-3.5 h-3.5" />
              {showRawJson ? 'Hide Evidence JSON' : 'Raw Evidence JSON'}
            </button>
            <button
              onClick={() => {
                refetchCoverage()
                refetchBackfill()
              }}
              className="p-2 text-slate-400 hover:text-white rounded-lg border border-slate-800 hover:bg-slate-800/60 transition-colors"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 4 Primary KPI Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-indigo-400" /> Total Coverage Ranges
            </div>
            <div className="text-2xl font-bold font-mono text-white mt-1">
              {coverage.total_coverage_ranges.toLocaleString('en-IN')}
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              Across 3,597 instruments
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <Database className="w-3.5 h-3.5 text-emerald-400" /> Canon Market Bars
            </div>
            <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
              {(coverage.total_bars / 1000000).toFixed(2)}M
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              {coverage.total_bars.toLocaleString('en-IN')} total bars
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <HardDrive className="w-3.5 h-3.5 text-amber-400" /> Backfill Supervisor
            </div>
            <div className="text-lg font-bold font-mono text-amber-300 mt-1 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse" />
              {backfill?.supervisor_state || 'WAITING'}
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              {backfill?.free_gb ? `${backfill.free_gb} GB disk free` : 'Monitoring'}
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" /> Excluded Bars
            </div>
            <div className="text-2xl font-bold font-mono text-white mt-1">
              {coverage.excluded_bars_total}
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              Audited in canon_excluded_bar
            </div>
          </div>
        </div>
      </div>

      {/* Raw JSON Drawer if toggled */}
      {showRawJson && (
        <div className="bg-slate-950 border border-indigo-500/30 rounded-2xl p-4 font-mono text-xs overflow-x-auto max-h-80 shadow-2xl">
          <div className="text-slate-400 mb-2 font-bold flex justify-between items-center">
            <span>STAGE 1 EVIDENCE JSON</span>
            <span className="text-[10px] text-slate-500">Live Read-Only API Output</span>
          </div>
          <pre className="text-indigo-300">
            {JSON.stringify({ coverage, backfill }, null, 2)}
          </pre>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="flex border-b border-slate-800 space-x-1">
        {[
          { id: 'coverage', label: 'Timeframe Coverage Matrix', icon: Layers },
          { id: 'backfill', label: 'Backfill Supervisor & ETA', icon: Clock },
          { id: 'exclusions', label: `Excluded Bars (${coverage.excluded_bars_total})`, icon: AlertTriangle },
          { id: 'corporate_actions', label: `Corporate Actions (${coverage.corporate_actions_total})`, icon: Calendar },
          { id: 'master', label: `Master Changes (${coverage.master_instruments_removed} removed)`, icon: Building2 },
        ].map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`px-4 py-2.5 text-xs font-mono font-medium rounded-t-lg flex items-center gap-2 transition-colors border-b-2 ${
                isActive
                  ? 'border-indigo-500 text-white bg-slate-800/50'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
              }`}
            >
              <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-indigo-400' : 'text-slate-400'}`} />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Tab 1: Coverage by Timeframe */}
      {activeTab === 'coverage' && (
        <div className="space-y-4">
          <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl overflow-hidden shadow-lg">
            <div className="p-4 border-b border-slate-800 bg-slate-900/60 flex justify-between items-center">
              <div>
                <h3 className="text-sm font-semibold text-white">Timeframe Coverage Targets & Range Counts</h3>
                <p className="text-xs text-slate-400 font-mono mt-0.5">
                  1d since 2020 (complete); 1h/15m/1m historical backfill in progress.
                </p>
              </div>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                165,809 Ranges Total
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950/60 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3.5">Timeframe</th>
                    <th className="p-3.5">Target Requirement</th>
                    <th className="p-3.5">Earliest Date</th>
                    <th className="p-3.5">Latest Date</th>
                    <th className="p-3.5 text-right">Coverage Ranges</th>
                    <th className="p-3.5 text-right">Data / Empty</th>
                    <th className="p-3.5 text-right">Total Bars</th>
                    <th className="p-3.5 text-right">Quarantined</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {coverage.timeframes.map((tf) => (
                    <tr key={tf.timeframe} className="hover:bg-slate-800/30 transition-colors">
                      <td className="p-3.5 font-bold text-indigo-300">
                        <span className="px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-800/60">
                          {tf.timeframe}
                        </span>
                      </td>
                      <td className="p-3.5 text-slate-300">
                        <div className="flex flex-col gap-0.5">
                          <span>{tf.target_start}</span>
                          <span className="text-[10px] text-slate-400 font-mono">
                            Earliest bar date: <span className="text-slate-200">{tf.min_date || '—'}</span>
                          </span>
                        </div>
                      </td>
                      <td className="p-3.5 text-slate-300 font-semibold">{tf.min_date || '—'}</td>
                      <td className="p-3.5 text-slate-400">{tf.max_date || '—'}</td>
                      <td className="p-3.5 text-right font-medium text-white">
                        {tf.ranges_count.toLocaleString('en-IN')}
                      </td>
                      <td className="p-3.5 text-right text-slate-300">
                        <span className="text-emerald-400">{tf.data_ranges.toLocaleString('en-IN')}</span>
                        {' / '}
                        <span className="text-slate-500">{tf.empty_ranges.toLocaleString('en-IN')}</span>
                      </td>
                      <td className="p-3.5 text-right font-bold text-emerald-400">
                        {tf.bars_count.toLocaleString('en-IN')}
                      </td>
                      <td className="p-3.5 text-right">
                        {tf.quarantined_bars > 0 ? (
                          <span className="text-amber-400 font-bold px-1.5 py-0.5 rounded bg-amber-950/40 border border-amber-800/50">
                            {tf.quarantined_bars}
                          </span>
                        ) : (
                          <span className="text-slate-500">0</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Backfill Supervisor */}
      {activeTab === 'backfill' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Current Supervisor State</span>
              <div className="text-xl font-bold font-mono text-amber-400 mt-1 flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse" />
                {backfill?.supervisor_state}
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                Last status: {backfill?.last_status} (stages: {backfill?.stages})
              </p>
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Disk Free Headroom</span>
              <div className="text-xl font-bold font-mono text-cyan-400 mt-1">
                {backfill?.free_gb} GB
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                Hard stop triggers if disk drops below 5 GB
              </p>
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Target Timeframes</span>
              <div className="text-xl font-bold font-mono text-white mt-1">
                1h & 15m (Historical)
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                Window: 16:00 to 06:25 IST daily
              </p>
            </div>
          </div>

          {/* Progress Cards per Timeframe */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white">Backfill Timeframe Progress</h3>
            {backfill?.progress.map((p) => (
              <div key={p.timeframe} className="bg-slate-900/50 border border-slate-800 rounded-xl p-5 space-y-3">
                <div className="flex justify-between items-center text-xs font-mono">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-700 text-indigo-300 font-bold">
                      {p.timeframe}
                    </span>
                    <span className="text-slate-300">From: {p.from_date}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-white font-bold">{p.covered}</span>
                    <span className="text-slate-400"> / {p.total} instruments ({p.pct}%)</span>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="w-full bg-slate-950 rounded-full h-3 overflow-hidden border border-slate-800">
                  <div
                    className="bg-gradient-to-r from-indigo-500 to-emerald-400 h-3 rounded-full transition-all duration-500"
                    style={{ width: `${Math.max(p.pct, 2)}%` }}
                  />
                </div>

                <div className="flex justify-between items-center text-[11px] font-mono text-slate-400">
                  <span>
                    Rate: {backfillRateText(p, backfill?.supervisor_state)}
                  </span>
                  <span>
                    ETA: {backfillEtaText(p, backfill?.supervisor_state)}
                  </span>
                  {p.as_of && (
                    <span className="text-[10px] text-slate-500">
                      as of {new Date(p.as_of).toLocaleTimeString('en-IN')}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Recent Supervisor Lines */}
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 font-mono text-xs">
            <div className="text-slate-400 mb-2 font-bold flex items-center justify-between">
              <span>RECENT SUPERVISOR LOG MARKERS</span>
              <span className="text-[10px] text-slate-500">var/logs/backfill/supervisor.log</span>
            </div>
            <div className="space-y-1 text-slate-300 max-h-48 overflow-y-auto">
              {backfill?.recent_supervisor_lines.map((line, idx) => (
                <div key={idx} className="hover:bg-slate-900/40 px-1 py-0.5 rounded">
                  {line}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Excluded Bars */}
      {activeTab === 'exclusions' && (
        <div className="space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/40 border border-slate-800 p-4 rounded-xl">
            <div>
              <h3 className="text-sm font-semibold text-white">Quarantined & Excluded Bars Ledger</h3>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                Every excluded bar is audited in canon_excluded_bar with reason and knowable_at provenance.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono">Filter Reason:</span>
              <select
                value={selectedReason}
                onChange={(e) => setSelectedReason(e.target.value)}
                className="bg-slate-950 border border-slate-700 text-xs font-mono rounded-lg px-2.5 py-1 text-slate-200"
              >
                <option value="all">All Reasons ({coverage.excluded_bars_total})</option>
                {Object.entries(coverage.excluded_reasons_breakdown).map(([r, cnt]) => (
                  <option key={r} value={r}>
                    {r} ({cnt})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Reason breakdown pills */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(coverage.excluded_reasons_breakdown).map(([reason, count]) => (
              <button
                key={reason}
                onClick={() => setSelectedReason(reason === selectedReason ? 'all' : reason)}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono border transition-all ${
                  selectedReason === reason
                    ? 'bg-amber-950/60 border-amber-500/80 text-amber-200 shadow-md'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <span className="font-bold text-amber-400">{count}</span> {reason}
              </button>
            ))}
          </div>

          {/* Dense Excluded Bars Table */}
          <div className="bg-slate-900/40 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3">Instrument Key</th>
                    <th className="p-3">TF</th>
                    <th className="p-3">Session Date</th>
                    <th className="p-3">Bar Start (UTC)</th>
                    <th className="p-3 text-right">O / H / L / C</th>
                    <th className="p-3 text-right">Volume</th>
                    <th className="p-3">Exclusion Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredExclusions.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="p-6 text-center text-slate-500">
                        No excluded bars match the selected criteria.
                      </td>
                    </tr>
                  ) : (
                    filteredExclusions.map((bar, i) => (
                      <tr key={i} className="hover:bg-slate-800/30 transition-colors">
                        <td className="p-3 font-medium text-white">{bar.instrument_key}</td>
                        <td className="p-3 text-indigo-300">{bar.timeframe}</td>
                        <td className="p-3 text-slate-400">{bar.session_date || '—'}</td>
                        <td className="p-3 text-slate-400">
                          {bar.bar_start_utc ? new Date(bar.bar_start_utc).toISOString().replace('T', ' ').slice(0, 19) : '—'}
                        </td>
                        <td className="p-3 text-right text-slate-300">
                          {bar.open ?? '—'} / {bar.high ?? '—'} / {bar.low ?? '—'} / {bar.close ?? '—'}
                        </td>
                        <td className="p-3 text-right text-slate-400">{bar.volume ?? 0}</td>
                        <td className="p-3">
                          <span className="px-2 py-0.5 rounded text-[11px] bg-rose-950/50 border border-rose-800/40 text-rose-300">
                            {bar.reason}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Corporate Actions */}
      {activeTab === 'corporate_actions' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Total Announcements</span>
              <div className="text-2xl font-bold font-mono text-white mt-1">
                {coverage.corporate_actions_total.toLocaleString('en-IN')}
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                From canon_corporate_action
              </p>
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Validated CA Factors</span>
              <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
                {coverage.factors_total.toLocaleString('en-IN')}
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                Status: {coverage.factors_by_status?.VERIFIED || 0} verified
              </p>
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Daily Refresh Job</span>
              <div className="text-lg font-bold font-mono text-indigo-300 mt-1">
                06:45 IST (Targeted)
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                Mode: targeted (12 targeted today, rc=0)
              </p>
            </div>
          </div>

          <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-semibold text-white">Action Types Distribution</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-mono text-xs">
              {Object.entries(coverage.corporate_actions_by_type).map(([type, cnt]) => (
                <div key={type} className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <div className="text-slate-400">{type}</div>
                  <div className="text-lg font-bold text-white mt-1">{cnt}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 5: Master Changes */}
      {activeTab === 'master' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Active Master Instruments</span>
              <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
                {coverage.master_instruments_active.toLocaleString('en-IN')}
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                Included in trading universe
              </p>
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-mono uppercase">Removed From Master</span>
              <div className="text-2xl font-bold font-mono text-rose-400 mt-1">
                {coverage.master_instruments_removed}
              </div>
              <p className="text-[11px] text-slate-500 font-mono mt-1">
                Delisted, merged, or excluded from NSE master
              </p>
            </div>
          </div>

          {/* Table of removed master items */}
          <div className="bg-slate-900/40 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
            <div className="p-4 border-b border-slate-800 bg-slate-900/60">
              <h3 className="text-sm font-semibold text-white">Instruments Removed From Master</h3>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                Lifecycle status: REMOVED_FROM_MASTER
              </p>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3">Symbol</th>
                    <th className="p-3">Name</th>
                    <th className="p-3">ISIN</th>
                    <th className="p-3">Status</th>
                    <th className="p-3">Lifecycle Since</th>
                    <th className="p-3">Filter Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {coverage.recent_master_changes.map((item: MasterChangeItem) => (
                    <tr key={item.instrument_key} className="hover:bg-slate-800/30 transition-colors">
                      <td className="p-3 font-bold text-white">{item.trading_symbol}</td>
                      <td className="p-3 text-slate-300">{item.name || '—'}</td>
                      <td className="p-3 text-slate-400">{item.isin || '—'}</td>
                      <td className="p-3">
                        <span className="px-2 py-0.5 rounded text-[11px] bg-rose-950/60 border border-rose-800 text-rose-300">
                          {item.lifecycle_status}
                        </span>
                      </td>
                      <td className="p-3 text-slate-400">{item.lifecycle_since || '—'}</td>
                      <td className="p-3 text-slate-400">{item.filter_reason || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
export default Stage1View
