import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  FileText,
  ChevronDown,
  ChevronRight,
  Layers,
  Clock,
  Search,
} from 'lucide-react'
import { api } from '../../services/api'


export const Stage2View: React.FC = () => {
  const [expandedCriteria, setExpandedCriteria] = useState<Record<string, boolean>>({})
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [showRawJson, setShowRawJson] = useState(false)

  const {
    data: gate,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['stage2Gate'],
    queryFn: () => api.getStage2Gate(),
    staleTime: 30000,
  })

  const toggleExpand = (id: string) => {
    setExpandedCriteria((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const toggleAll = (expand: boolean) => {
    if (!gate) return
    const next: Record<string, boolean> = {}
    gate.criteria.forEach((c) => {
      next[c.id] = expand
    })
    setExpandedCriteria(next)
  }

  if (isLoading) {
    return (
      <div className="p-6 space-y-6 animate-pulse">
        <div className="h-20 bg-slate-800/40 rounded-xl" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-28 bg-slate-800/30 rounded-xl" />
          ))}
        </div>
        <div className="h-96 bg-slate-800/20 rounded-xl" />
      </div>
    )
  }

  if (error || !gate) {
    return (
      <div className="p-8 text-center bg-rose-950/20 border border-rose-800/30 rounded-2xl m-6">
        <AlertTriangle className="w-12 h-12 text-rose-400 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-rose-200">Stage 2 Gate Data Unavailable</h3>
        <p className="text-sm text-slate-400 mt-1 max-w-md mx-auto">
          {error instanceof Error ? error.message : 'Unable to query Stage 2 acceptance gate.'}
        </p>
        <button
          onClick={() => refetch()}
          className="mt-4 px-4 py-2 bg-rose-600/30 hover:bg-rose-600/40 border border-rose-500/30 text-rose-200 rounded-lg text-sm inline-flex items-center gap-2"
        >
          <RefreshCw className="w-4 h-4" /> Retry Query
        </button>
      </div>
    )
  }

  const filteredCriteria = gate.criteria.filter((c) => {
    const matchesStatus = filterStatus === 'all' || c.status === filterStatus
    const matchesSearch =
      searchQuery === '' ||
      c.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (c.question && c.question.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (c.notes && c.notes.toLowerCase().includes(searchQuery.toLowerCase()))
    return matchesStatus && matchesSearch
  })

  const passCount = gate.criteria.filter((c) => c.status === 'PASS').length
  const failCount = gate.criteria.filter((c) => c.status === 'FAIL').length
  const totalCount = gate.criteria.length

  return (
    <div className="p-6 space-y-6 text-slate-200">
      {/* Top Header Card */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 backdrop-blur-md shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-inner">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold tracking-tight text-white">Stage 2: Processing and Storage</h1>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                  gate.overall === 'PASS'
                    ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400'
                    : 'bg-rose-500/10 border border-rose-500/30 text-rose-400'
                }`}>
                  OVERALL: {gate.overall}
                </span>
                <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-400 border border-slate-700">
                  CRITERIA A–P
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1 font-mono">
                Acceptance gate: 16 strict validation rules, data consistency proofs, and coverage state matrix.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowRawJson(!showRawJson)}
              className="px-3 py-1.5 text-xs font-mono rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-300 flex items-center gap-1.5 transition-colors"
            >
              <FileText className="w-3.5 h-3.5" />
              {showRawJson ? 'Hide Evidence JSON' : 'Raw Gate JSON'}
            </button>
            <button
              onClick={() => refetch()}
              className="p-2 text-slate-400 hover:text-white rounded-lg border border-slate-800 hover:bg-slate-800/60 transition-colors"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 3 KPI Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Criteria Verification
            </div>
            <div className="text-2xl font-bold font-mono text-white mt-1">
              <span className="text-emerald-400">{passCount}</span> / {totalCount} Passed
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              {failCount === 0 ? 'Zero failures across criteria A–P' : `${failCount} failing criteria`}
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-indigo-400" /> Report Freshness
            </div>
            <div className="text-xl font-bold font-mono text-indigo-300 mt-1">
              {gate.age_hours !== null ? `${gate.age_hours} hrs ago` : 'Unknown'}
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              Generated: {gate.generated_at ? new Date(gate.generated_at).toISOString().replace('T', ' ').slice(0, 19) : '—'}
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-amber-400" /> Quarantined Bars Total
            </div>
            <div className="text-2xl font-bold font-mono text-white mt-1">
              {gate.quarantined_total}
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              Tracked in canon_coverage
            </div>
          </div>
        </div>
      </div>

      {/* Raw JSON Drawer if toggled */}
      {showRawJson && (
        <div className="bg-slate-950 border border-emerald-500/30 rounded-2xl p-4 font-mono text-xs overflow-x-auto max-h-80 shadow-2xl">
          <div className="text-slate-400 mb-2 font-bold flex justify-between items-center">
            <span>STAGE 2 ACCEPTANCE GATE EVIDENCE JSON</span>
            <span className="text-[10px] text-slate-500">backend/var/acceptance/stage2.json</span>
          </div>
          <pre className="text-emerald-300">
            {JSON.stringify(gate, null, 2)}
          </pre>
        </div>
      )}

      {/* Section 1: Coverage State Matrix */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
        <div className="p-4 border-b border-slate-800 bg-slate-900/60 flex justify-between items-center">
          <div>
            <h3 className="text-sm font-semibold text-white">Coverage State Matrix</h3>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              Distribution of coverage states across timeframes in canon_coverage.
            </p>
          </div>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
            Database State Proof
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider border-b border-slate-800">
              <tr>
                <th className="p-3">Timeframe</th>
                <th className="p-3 text-right">DATA</th>
                <th className="p-3 text-right">EMPTY</th>
                <th className="p-3 text-right">PENDING_BACKFILL</th>
                <th className="p-3 text-right">QUARANTINED</th>
                <th className="p-3 text-right">VENDOR_ERROR</th>
                <th className="p-3 text-right font-bold text-white">Total Ranges</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {['1d', '1h', '15m', '1m'].map((tf) => {
                const row = gate.coverage_state_matrix[tf] || {}
                const dataCount = row['DATA'] || 0
                const emptyCount = row['EMPTY'] || 0
                const pendingCount = row['PENDING_BACKFILL'] || 0
                const quarCount = row['QUARANTINED'] || 0
                const errorCount = row['VENDOR_ERROR'] || 0
                const total = dataCount + emptyCount + pendingCount + quarCount + errorCount

                return (
                  <tr key={tf} className="hover:bg-slate-800/30 transition-colors">
                    <td className="p-3 font-bold text-indigo-300">
                      <span className="px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-800/60">
                        {tf}
                      </span>
                    </td>
                    <td className="p-3 text-right font-medium text-emerald-400">
                      {dataCount.toLocaleString('en-IN')}
                    </td>
                    <td className="p-3 text-right text-slate-400">
                      {emptyCount.toLocaleString('en-IN')}
                    </td>
                    <td className="p-3 text-right text-amber-300">
                      {pendingCount.toLocaleString('en-IN')}
                    </td>
                    <td className="p-3 text-right">
                      {quarCount > 0 ? (
                        <span className="text-amber-400 font-bold px-1.5 py-0.5 rounded bg-amber-950/40 border border-amber-800/50">
                          {quarCount}
                        </span>
                      ) : (
                        <span className="text-slate-500">0</span>
                      )}
                    </td>
                    <td className="p-3 text-right text-rose-400">
                      {errorCount > 0 ? errorCount : <span className="text-slate-500">0</span>}
                    </td>
                    <td className="p-3 text-right font-bold text-white">
                      {total.toLocaleString('en-IN')}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Section 2: Gate Criteria Ledger (Criteria A–P) */}
      <div className="space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/40 border border-slate-800 p-4 rounded-xl">
          <div>
            <h3 className="text-sm font-semibold text-white">Gate Criteria Ledger (A–P)</h3>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              16 point-in-time criteria evaluated by the Stage 2 supervisor script.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Search criteria..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 pr-3 py-1 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-500 w-44"
              />
            </div>

            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-xs font-mono rounded-lg px-2.5 py-1 text-slate-200"
            >
              <option value="all">All ({gate.criteria.length})</option>
              <option value="PASS">PASS ({passCount})</option>
              <option value="FAIL">FAIL ({failCount})</option>
            </select>

            <button
              onClick={() => toggleAll(true)}
              className="px-2 py-1 text-[11px] font-mono rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            >
              Expand All
            </button>
            <button
              onClick={() => toggleAll(false)}
              className="px-2 py-1 text-[11px] font-mono rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            >
              Collapse
            </button>
          </div>
        </div>

        {/* Criteria List Accordion */}
        <div className="space-y-2">
          {filteredCriteria.map((c) => {
            const isExpanded = !!expandedCriteria[c.id]
            const isPass = c.status === 'PASS'

            return (
              <div
                key={c.id}
                className="bg-slate-900/50 border border-slate-800/80 rounded-xl overflow-hidden transition-colors"
              >
                <div
                  onClick={() => toggleExpand(c.id)}
                  className="p-4 flex items-center justify-between cursor-pointer hover:bg-slate-800/30 select-none"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-7 h-7 rounded-lg bg-slate-950 border border-slate-700 font-mono text-xs font-bold flex items-center justify-center text-indigo-300">
                      {c.id}
                    </span>
                    <div>
                      <div className="text-xs font-semibold text-white">
                        {c.question || c.name || `Criterion ${c.id}`}
                      </div>
                      {c.notes && (
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                          {c.notes}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <span
                      className={`px-2.5 py-0.5 rounded text-xs font-mono font-bold flex items-center gap-1.5 ${
                        isPass
                          ? 'bg-emerald-950/60 border border-emerald-800 text-emerald-400'
                          : 'bg-rose-950/60 border border-rose-800 text-rose-400'
                      }`}
                    >
                      {isPass ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                      {c.status}
                    </span>
                    {isExpanded ? (
                      <ChevronDown className="w-4 h-4 text-slate-400" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-slate-400" />
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="p-4 bg-slate-950 border-t border-slate-800/80 font-mono text-xs space-y-3">
                    <div className="text-slate-400 font-bold">EVIDENCE & TELEMETRY:</div>
                    <pre className="text-emerald-300 bg-slate-900/60 p-3 rounded-lg border border-slate-800 overflow-x-auto">
                      {JSON.stringify(c.evidence, null, 2)}
                    </pre>

                    {Object.keys(c.db_state || {}).length > 0 && (
                      <>
                        <div className="text-slate-400 font-bold mt-2">DATABASE AUDIT STATE:</div>
                        <pre className="text-indigo-300 bg-slate-900/60 p-3 rounded-lg border border-slate-800 overflow-x-auto">
                          {JSON.stringify(c.db_state, null, 2)}
                        </pre>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
export default Stage2View
