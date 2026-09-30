import React, { useEffect, useState } from 'react'
import {
  AlertCircle,
  Archive,
  Calculator,
  CheckCircle2,
  Clock,
  Database,
  FileCheck,
  Filter,
  HardDrive,
  History,
  Layers,
  RefreshCw,
  Search,
  ShieldAlert,
  Sliders,
  TrendingDown,
  XCircle,
} from 'lucide-react'
import { api } from '../../services/api'
import type {
  IngestRunItem,
  AnomalyItem,
  RevisionItem,
  BackupItem,
  WarmupPlanResponse,
} from '../../types/api'

type OpsTab = 'runs' | 'anomalies' | 'revisions' | 'backups' | 'warmup'

export const AdminOpsView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<OpsTab>('runs')
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Tab Data States
  const [runs, setRuns] = useState<IngestRunItem[]>([])
  const [anomalies, setAnomalies] = useState<AnomalyItem[]>([])
  const [revisions, setRevisions] = useState<RevisionItem[]>([])
  const [backups, setBackups] = useState<BackupItem[]>([])
  const [warmup, setWarmup] = useState<WarmupPlanResponse | null>(null)

  // Filters
  const [runStatusFilter, setRunStatusFilter] = useState<string>('')
  const [warmupSessions, setWarmupSessions] = useState<number>(20)
  const [warmupTimeframes, setWarmupTimeframes] = useState<string>('1m,15m,1h')
  const [warmupFraction, setWarmupFraction] = useState<number>(0.25)

  const loadTabData = async (tab: OpsTab) => {
    try {
      setLoading(true)
      setError(null)
      if (tab === 'runs') {
        const res = await api.getOpsRuns({ status: runStatusFilter || undefined, limit: 100 })
        setRuns(res)
      } else if (tab === 'anomalies') {
        const res = await api.getOpsAnomalies(100)
        setAnomalies(res)
      } else if (tab === 'revisions') {
        const res = await api.getOpsRevisions(100)
        setRevisions(res)
      } else if (tab === 'backups') {
        const res = await api.getOpsBackups()
        setBackups(res)
      } else if (tab === 'warmup') {
        const res = await api.getOpsWarmup({
          sessions: warmupSessions,
          timeframes: warmupTimeframes,
          fraction: warmupFraction,
        })
        setWarmup(res)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to load ${tab} data`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTabData(activeTab)
  }, [activeTab, runStatusFilter])

  const handleWarmupRecalculate = async () => {
    try {
      setLoading(true)
      const res = await api.getOpsWarmup({
        sessions: warmupSessions,
        timeframes: warmupTimeframes,
        fraction: warmupFraction,
      })
      setWarmup(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to recalculate warm-up')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Layers className="w-5 h-5 text-indigo-400" />
            Operations, Ingestion Ledger & Observability
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Audit logs for ingestion runs, data quality anomalies, price basis revisions, backups & Stage 3 warmup
          </p>
        </div>

        <button
          onClick={() => loadTabData(activeTab)}
          disabled={loading}
          className="p-2 self-start sm:self-auto bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-lg text-xs flex items-center gap-1.5 transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* 2. Navigation Tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-2">
        <button
          onClick={() => setActiveTab('runs')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeTab === 'runs'
              ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <History className="w-3.5 h-3.5" />
          <span>Ingest Runs Ledger</span>
        </button>

        <button
          onClick={() => setActiveTab('anomalies')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeTab === 'anomalies'
              ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <AlertCircle className="w-3.5 h-3.5" />
          <span>Quality Anomalies</span>
        </button>

        <button
          onClick={() => setActiveTab('revisions')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeTab === 'revisions'
              ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <FileCheck className="w-3.5 h-3.5" />
          <span>Price Revisions & Factors</span>
        </button>

        <button
          onClick={() => setActiveTab('backups')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeTab === 'backups'
              ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <HardDrive className="w-3.5 h-3.5" />
          <span>Verified Backups</span>
        </button>

        <button
          onClick={() => setActiveTab('warmup')}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeTab === 'warmup'
              ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
          }`}
        >
          <Calculator className="w-3.5 h-3.5" />
          <span>Stage 3 Warm-up Planner</span>
        </button>
      </div>

      {/* 3. Error Banner */}
      {error && (
        <div className="p-4 bg-rose-950/30 border border-rose-800/50 rounded-xl text-rose-300 text-sm flex items-center gap-2">
          <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
          <span>Error loading operations data: {error}</span>
        </div>
      )}

      {/* 4. Tab Contents */}
      {activeTab === 'runs' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-400">
              Showing recent ingestion runs from <span className="font-mono text-slate-300">app_run</span> table
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">Filter status:</span>
              <select
                value={runStatusFilter}
                onChange={(e) => setRunStatusFilter(e.target.value)}
                className="bg-slate-900 border border-slate-800 text-slate-200 text-xs rounded-lg px-2.5 py-1"
              >
                <option value="">All Statuses</option>
                <option value="SUCCESS">SUCCESS</option>
                <option value="RUNNING">RUNNING</option>
                <option value="FAILED">FAILED</option>
              </select>
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/60 text-slate-400 border-b border-slate-800 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Run ID / Stream</th>
                    <th className="py-3 px-4">Source</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4 text-right">Rows</th>
                    <th className="py-3 px-4">Started At</th>
                    <th className="py-3 px-4 text-right">Duration</th>
                    <th className="py-3 px-4">Error / Notes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {runs.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-slate-500">
                        No ingestion runs found matching filter.
                      </td>
                    </tr>
                  ) : (
                    runs.map((r) => (
                      <tr key={r.run_id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="py-3 px-4">
                          <div className="font-mono text-slate-200 font-medium">{r.stream}</div>
                          <div className="font-mono text-[10px] text-slate-500 truncate max-w-[180px]">
                            {r.run_id}
                          </div>
                        </td>
                        <td className="py-3 px-4 font-mono text-slate-300">{r.source}</td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex px-2 py-0.5 rounded text-[11px] font-medium ${
                              r.status === 'SUCCESS'
                                ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/60'
                                : r.status === 'RUNNING'
                                ? 'bg-indigo-950/80 text-indigo-400 border border-indigo-800/60 animate-pulse'
                                : 'bg-rose-950/80 text-rose-400 border border-rose-800/60'
                            }`}
                          >
                            {r.status}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-right font-mono text-slate-300">
                          {r.rows_written.toLocaleString()}
                        </td>
                        <td className="py-3 px-4 text-slate-400">
                          {new Date(r.started_at).toLocaleTimeString('en-IN', {
                            hour12: false,
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                          })}
                        </td>
                        <td className="py-3 px-4 text-right font-mono text-slate-400">
                          {r.duration_seconds !== null ? `${r.duration_seconds.toFixed(2)}s` : '--'}
                        </td>
                        <td className="py-3 px-4 max-w-[200px] truncate text-slate-400 font-mono text-[11px]">
                          {r.error || '--'}
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

      {activeTab === 'anomalies' && (
        <div className="space-y-4">
          <div className="text-xs text-slate-400">
            Automated anomaly detection records from <span className="font-mono text-slate-300">anomaly</span> ledger
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/60 text-slate-400 border-b border-slate-800 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Rule</th>
                    <th className="py-3 px-4">Severity</th>
                    <th className="py-3 px-4">Entity</th>
                    <th className="py-3 px-4">Details</th>
                    <th className="py-3 px-4">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {anomalies.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-slate-500">
                        <CheckCircle2 className="w-6 h-6 text-emerald-500/50 mx-auto mb-2" />
                        Zero active anomalies recorded in database.
                      </td>
                    </tr>
                  ) : (
                    anomalies.map((a) => (
                      <tr key={a.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="py-3 px-4 font-mono font-medium text-slate-200">{a.rule}</td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex px-2 py-0.5 rounded text-[11px] font-medium ${
                              a.severity === 'FATAL'
                                ? 'bg-rose-950/80 text-rose-400 border border-rose-800/60'
                                : 'bg-amber-950/80 text-amber-400 border border-amber-800/60'
                            }`}
                          >
                            {a.severity}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-mono text-slate-300">{a.entity_key || '--'}</td>
                        <td className="py-3 px-4 font-mono text-[11px] text-slate-400 max-w-[320px] truncate">
                          {JSON.stringify(a.details)}
                        </td>
                        <td className="py-3 px-4 text-slate-400">
                          {new Date(a.created_at).toLocaleString('en-IN', { hour12: false })}
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

      {activeTab === 'revisions' && (
        <div className="space-y-4">
          <div className="text-xs text-slate-400">
            Recorded revisions and corporate action adjustments in <span className="font-mono text-slate-300">data_revision</span> ledger
          </div>

          <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/60 text-slate-400 border-b border-slate-800 font-semibold uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Instrument Key</th>
                    <th className="py-3 px-4">Timeframe</th>
                    <th className="py-3 px-4">Date</th>
                    <th className="py-3 px-4">Classification</th>
                    <th className="py-3 px-4">Reason</th>
                    <th className="py-3 px-4">Logged At</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {revisions.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-slate-500">
                        <CheckCircle2 className="w-6 h-6 text-emerald-500/50 mx-auto mb-2" />
                        No unexplained revisions detected in historical logs.
                      </td>
                    </tr>
                  ) : (
                    revisions.map((rev) => (
                      <tr key={rev.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="py-3 px-4 font-mono text-slate-200">{rev.instrument_key}</td>
                        <td className="py-3 px-4 font-mono text-slate-300">{rev.timeframe}</td>
                        <td className="py-3 px-4 text-slate-400">{rev.session_date}</td>
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-indigo-950/80 text-indigo-400 border border-indigo-800/60">
                            {rev.classification}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-slate-300 max-w-[280px] truncate">{rev.reason}</td>
                        <td className="py-3 px-4 text-slate-400">
                          {new Date(rev.created_at).toLocaleString('en-IN', { hour12: false })}
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

      {activeTab === 'backups' && (
        <div className="space-y-4">
          <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                  <Archive className="w-4 h-4 text-indigo-400" />
                  Verified Production Database Dumps
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Pre-migration and daily backup snapshots with verified SHA256 integrity checks
                </p>
              </div>
            </div>

            <div className="divide-y divide-slate-800/60">
              {backups.length === 0 ? (
                <div className="py-6 text-center text-slate-500 text-xs">No backup files found on disk.</div>
              ) : (
                backups.map((b) => (
                  <div key={b.filename} className="py-3 flex items-center justify-between text-xs">
                    <div className="space-y-0.5">
                      <div className="font-mono text-slate-200 font-medium">{b.filename}</div>
                      <div className="text-[11px] text-slate-500 flex items-center gap-3">
                        <span>SHA256: <code className="text-slate-400">{b.sha256_prefix}</code></span>
                        <span>Date: {new Date(b.modified_at).toLocaleString('en-IN', { hour12: false })}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      <span className="font-mono text-slate-300">{b.size_human}</span>
                      {b.verified ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-950/80 text-emerald-400 border border-emerald-800/60">
                          <CheckCircle2 className="w-3 h-3" />
                          VERIFIED
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-950/80 text-amber-400 border border-amber-800/60">
                          PENDING
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'warmup' && (
        <div className="space-y-6">
          {/* Deferred Warning Banner */}
          <div className="bg-amber-950/20 border border-amber-800/40 rounded-xl p-4 text-xs text-amber-200/90 space-y-1">
            <div className="font-semibold text-amber-300 flex items-center gap-1.5">
              <ShieldAlert className="w-4 h-4 text-amber-400" />
              Full Historical Backfill Deferred (~293k Requests)
            </div>
            <p className="text-amber-200/80 leading-relaxed">
              Full intraday backfill across all history is intentionally DEFERRED to protect broker rate limits and avoid unneeded latency.
              Instead, this read-only planning tool models targeted historical warm-up required for Stage 3 indicators (e.g. 20 sessions of 1m/15m/1h).
            </p>
          </div>

          {/* Calculator Controls */}
          <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
              <Sliders className="w-4 h-4 text-indigo-400" />
              Targeted Warm-Up Parameter Modeling
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Lookback Sessions</label>
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={warmupSessions}
                  onChange={(e) => setWarmupSessions(parseInt(e.target.value) || 20)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono"
                />
                <span className="text-[10px] text-slate-500">Typical Stage 3 feature warm-up: 20 sessions</span>
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1">Timeframes (comma separated)</label>
                <input
                  type="text"
                  value={warmupTimeframes}
                  onChange={(e) => setWarmupTimeframes(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono"
                />
                <span className="text-[10px] text-slate-500">Default: 1m, 15m, 1h</span>
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1">Rate Limit Fraction (1.0 = 10 req/s)</label>
                <input
                  type="number"
                  step="0.05"
                  min="0.05"
                  max="1.0"
                  value={warmupFraction}
                  onChange={(e) => setWarmupFraction(parseFloat(e.target.value) || 0.25)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono"
                />
                <span className="text-[10px] text-slate-500">0.25 = 2.5 req/s safety budget</span>
              </div>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                onClick={handleWarmupRecalculate}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs rounded-lg transition-colors flex items-center gap-1.5"
              >
                <Calculator className="w-3.5 h-3.5" />
                <span>Calculate Requirements</span>
              </button>
            </div>
          </div>

          {/* Warmup Results Display */}
          {warmup && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <span className="text-xs text-slate-400">Total Upstox Requests</span>
                <div className="text-xl font-bold font-mono text-indigo-400 mt-1">
                  {warmup.total_requests.toLocaleString()}
                </div>
                <div className="text-[10px] text-slate-500 mt-1">
                  vs {warmup.deferred_full_backfill_requests} full backfill
                </div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <span className="text-xs text-slate-400">Estimated Duration</span>
                <div className="text-xl font-bold font-mono text-slate-200 mt-1">
                  {warmup.total_hours_at_fraction.toFixed(1)} hrs
                </div>
                <div className="text-[10px] text-slate-500 mt-1">
                  at {(warmup.fraction * 10).toFixed(1)} req/sec ({warmup.fraction * 100}% budget)
                </div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <span className="text-xs text-slate-400">Active Instruments</span>
                <div className="text-xl font-bold font-mono text-slate-200 mt-1">
                  {warmup.active_instruments.toLocaleString()}
                </div>
                <div className="text-[10px] text-slate-500 mt-1">
                  Valid NSE active universe
                </div>
              </div>

              <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
                <span className="text-xs text-slate-400">Lookback Window</span>
                <div className="text-sm font-bold font-mono text-slate-200 mt-1.5">
                  {warmup.sessions} Trading Sessions
                </div>
                <div className="text-[10px] text-slate-500 mt-1 font-mono">
                  {warmup.from_date} &rarr; {warmup.to_date}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
