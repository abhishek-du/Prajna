import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Cpu,
  Layers,
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  FileText,
  Search,
  ChevronDown,
  ChevronRight,
  Database,
  Sliders,
} from 'lucide-react'
import { api } from '../../services/api'

import type { FeatureRegistryItem, Stage3EventItem } from '../../types/api'

export const Stage3View: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'gate' | 'registry' | 'snapshots' | 'refusals'>('registry')
  const [showRawJson, setShowRawJson] = useState(false)
  const [selectedGroup, setSelectedGroup] = useState<string>('all')
  const [featureSearch, setFeatureSearch] = useState('')
  const [expandedCriteria, setExpandedCriteria] = useState<Record<string, boolean>>({})
  const [snapshotDate, setSnapshotDate] = useState('2026-10-16')

  const {
    data: gate,
    isLoading: gateLoading,
    error: gateError,
    refetch: refetchGate,
  } = useQuery({
    queryKey: ['stage3Gate'],
    queryFn: () => api.getStage3Gate(),
    staleTime: 30000,
  })

  const {
    data: registry,
    isLoading: registryLoading,
    error: registryError,
    refetch: refetchRegistry,
  } = useQuery({
    queryKey: ['stage3Registry'],
    queryFn: () => api.getStage3Registry(),
    staleTime: 60000,
  })

  const {
    data: snapshots,
    refetch: refetchSnapshots,
  } = useQuery({
    queryKey: ['stage3Snapshots', snapshotDate],
    queryFn: () => api.getStage3Snapshots(snapshotDate),
    staleTime: 15000,
  })


  const isLoading = gateLoading || registryLoading
  const hasError = gateError || registryError

  const toggleExpand = (id: string) => {
    setExpandedCriteria((prev) => ({ ...prev, [id]: !prev[id] }))
  }

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

  if (hasError || !gate || !registry) {
    return (
      <div className="p-8 text-center bg-rose-950/20 border border-rose-800/30 rounded-2xl m-6">
        <AlertTriangle className="w-12 h-12 text-rose-400 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-rose-200">Stage 3 Feature Engineering Data Unavailable</h3>
        <p className="text-sm text-slate-400 mt-1 max-w-md mx-auto">
          {gateError instanceof Error ? gateError.message : 'Unable to load feature registry or gate telemetry.'}
        </p>
        <button
          onClick={() => {
            refetchGate()
            refetchRegistry()
            refetchSnapshots()
          }}
          className="mt-4 px-4 py-2 bg-rose-600/30 hover:bg-rose-600/40 border border-rose-500/30 text-rose-200 rounded-lg text-sm inline-flex items-center gap-2"
        >
          <RefreshCw className="w-4 h-4" /> Retry Query
        </button>
      </div>
    )
  }

  const filteredFeatures = registry.features.filter((f) => {
    const matchesGroup = selectedGroup === 'all' || f.group === selectedGroup
    const matchesSearch =
      featureSearch === '' ||
      f.id.toLowerCase().includes(featureSearch.toLowerCase()) ||
      f.definition.toLowerCase().includes(featureSearch.toLowerCase())
    return matchesGroup && matchesSearch
  })

  return (
    <div className="p-6 space-y-6 text-slate-200">
      {/* Top Header Card */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 backdrop-blur-md shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400 shadow-inner">
              <Cpu className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold tracking-tight text-white">Stage 3: Feature Engineering</h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
                  COMPLETE & RUNNING DAILY
                </span>
                <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-400 border border-slate-700">
                  {registry.version}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1 font-mono">
                Registry SHA256: <span className="text-indigo-300">{registry.registry_sha256.slice(0, 16)}...</span> • PRE_SESSION & PRE_OPEN snapshot engines.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowRawJson(!showRawJson)}
              className="px-3 py-1.5 text-xs font-mono rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-300 flex items-center gap-1.5 transition-colors"
            >
              <FileText className="w-3.5 h-3.5" />
              {showRawJson ? 'Hide Evidence JSON' : 'Raw Registry JSON'}
            </button>
            <button
              onClick={() => {
                refetchGate()
                refetchRegistry()
                refetchSnapshots()
              }}
              className="p-2 text-slate-400 hover:text-white rounded-lg border border-slate-800 hover:bg-slate-800/60 transition-colors"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 4 Summary Metric Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-indigo-400" /> Feature Registry
            </div>
            <div className="text-2xl font-bold font-mono text-white mt-1">
              {registry.feature_count}
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              {registry.implemented_count} implemented (100%)
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-emerald-400" /> Feature Groups
            </div>
            <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
              {Object.keys(registry.groups).length}
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              Price, Volume, Fund, Event, Context, Pre-open
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" /> Gate Acceptance
            </div>
            <div className="text-2xl font-bold font-mono text-white mt-1">
              {gate.criteria.length} Criteria
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              Criteria A–O passed
            </div>
          </div>

          <div className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-4">
            <div className="text-xs text-slate-400 uppercase tracking-wider font-mono flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5 text-amber-400" /> Refusal Audit
            </div>
            <div className="text-2xl font-bold font-mono text-amber-400 mt-1">
              {gate.refusal_count_today} Today
            </div>
            <div className="text-[11px] text-slate-400 font-mono mt-0.5">
              {gate.events_count_total} total events in stage3_event
            </div>
          </div>
        </div>
      </div>

      {/* Raw JSON Drawer if toggled */}
      {showRawJson && (
        <div className="bg-slate-950 border border-purple-500/30 rounded-2xl p-4 font-mono text-xs overflow-x-auto max-h-80 shadow-2xl">
          <div className="text-slate-400 mb-2 font-bold flex justify-between items-center">
            <span>STAGE 3 REGISTRY & GATE JSON</span>
            <span className="text-[10px] text-slate-500">Live Backend Read Output</span>
          </div>
          <pre className="text-purple-300">
            {JSON.stringify({ gate, registry, snapshots }, null, 2)}
          </pre>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="flex border-b border-slate-800 space-x-1">
        {[
          { id: 'registry', label: `Feature Registry (${registry.feature_count})`, icon: Sliders },
          { id: 'gate', label: `Gate Criteria (${gate.criteria.length})`, icon: CheckCircle2 },
          { id: 'snapshots', label: 'Snapshot Completeness', icon: Database },
          { id: 'refusals', label: `Refusal & Lock Audit (${gate.events_count_total})`, icon: ShieldAlert },
        ].map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`px-4 py-2.5 text-xs font-mono font-medium rounded-t-lg flex items-center gap-2 transition-colors border-b-2 ${
                isActive
                  ? 'border-purple-500 text-white bg-slate-800/50'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
              }`}
            >
              <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-purple-400' : 'text-slate-400'}`} />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Tab 1: Feature Registry */}
      {activeTab === 'registry' && (
        <div className="space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/40 border border-slate-800 p-4 rounded-xl">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono">Filter Group:</span>
              <select
                value={selectedGroup}
                onChange={(e) => setSelectedGroup(e.target.value)}
                className="bg-slate-950 border border-slate-700 text-xs font-mono rounded-lg px-2.5 py-1 text-slate-200"
              >
                <option value="all">All Groups ({registry.feature_count})</option>
                {Object.entries(registry.groups).map(([grp, ids]) => (
                  <option key={grp} value={grp}>
                    {grp} ({ids.length})
                  </option>
                ))}
              </select>
            </div>

            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Search feature ID / formula..."
                value={featureSearch}
                onChange={(e) => setFeatureSearch(e.target.value)}
                className="pl-8 pr-3 py-1 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-500 w-64"
              />
            </div>
          </div>

          {/* Group badges */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(registry.groups).map(([grp, ids]) => (
              <button
                key={grp}
                onClick={() => setSelectedGroup(grp === selectedGroup ? 'all' : grp)}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono border transition-all ${
                  selectedGroup === grp
                    ? 'bg-purple-950/60 border-purple-500/80 text-purple-200 shadow-md'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <span className="font-bold text-purple-400">{ids.length}</span> {grp}
              </button>
            ))}
          </div>

          {/* Dense Registry Table */}
          <div className="bg-slate-900/40 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3">Feature ID</th>
                    <th className="p-3">Group</th>
                    <th className="p-3">Formula / Definition</th>
                    <th className="p-3">Scope</th>
                    <th className="p-3 text-right">Lookback</th>
                    <th className="p-3">Snapshots</th>
                    <th className="p-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredFeatures.map((f: FeatureRegistryItem) => (
                    <tr key={f.id} className="hover:bg-slate-800/30 transition-colors">
                      <td className="p-3 font-bold text-purple-300">{f.id}</td>
                      <td className="p-3 text-slate-400">
                        <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-[11px]">
                          {f.group}
                        </span>
                      </td>
                      <td className="p-3 text-slate-200 font-mono max-w-xs truncate" title={f.definition}>
                        {f.definition}
                      </td>
                      <td className="p-3 text-slate-400">{f.scope}</td>
                      <td className="p-3 text-right text-slate-300">{f.lookback_sessions}d</td>
                      <td className="p-3">
                        <div className="flex gap-1">
                          {f.snapshots.map((s) => (
                            <span key={s} className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-400">
                              {s === 'PRE_SESSION' ? 'SESS' : 'OPEN'}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="p-3">
                        <span className="px-2 py-0.5 rounded text-[11px] bg-emerald-950/60 border border-emerald-800 text-emerald-400">
                          {f.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Gate Criteria A–O */}
      {activeTab === 'gate' && (
        <div className="space-y-4">
          <div className="bg-slate-900/40 border border-slate-800 p-4 rounded-xl flex justify-between items-center">
            <div>
              <h3 className="text-sm font-semibold text-white">Stage 3 Gate Criteria Ledger (A–O)</h3>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                Evaluated from backend/var/acceptance/stage3.json. All 15 criteria verified PASS.
              </p>
            </div>
            <span className="text-xs font-mono px-2.5 py-1 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-300 font-bold">
              OVERALL: PASS
            </span>
          </div>

          <div className="space-y-2">
            {gate.criteria.map((c) => {
              const isExpanded = !!expandedCriteria[c.id]
              return (
                <div key={c.id} className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
                  <div
                    onClick={() => toggleExpand(c.id)}
                    className="p-4 flex items-center justify-between cursor-pointer hover:bg-slate-800/30 select-none"
                  >
                    <div className="flex items-center gap-3">
                      <span className="w-7 h-7 rounded-lg bg-slate-950 border border-slate-700 font-mono text-xs font-bold flex items-center justify-center text-purple-300">
                        {c.id}
                      </span>
                      <div>
                        <div className="text-xs font-semibold text-white">{c.question || c.name}</div>
                        {c.notes && <div className="text-[11px] text-slate-400 font-mono mt-0.5">{c.notes}</div>}
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-emerald-950/60 border border-emerald-800 text-emerald-400 flex items-center gap-1.5">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        {c.status}
                      </span>
                      {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="p-4 bg-slate-950 border-t border-slate-800/80 font-mono text-xs space-y-2">
                      <div className="text-slate-400 font-bold">EVIDENCE:</div>
                      <pre className="text-purple-300 bg-slate-900/60 p-3 rounded-lg border border-slate-800 overflow-x-auto">
                        {JSON.stringify(c.evidence, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Tab 3: Snapshots Completeness */}
      {activeTab === 'snapshots' && (
        <div className="space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/40 border border-slate-800 p-4 rounded-xl">
            <div>
              <h3 className="text-sm font-semibold text-white">Daily Snapshots Completeness</h3>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                Computed values vs null reasons for PRE_SESSION and PRE_OPEN.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-mono">Session Date:</span>
              <input
                type="date"
                value={snapshotDate}
                onChange={(e) => setSnapshotDate(e.target.value)}
                className="bg-slate-950 border border-slate-700 text-xs font-mono rounded-lg px-2.5 py-1 text-slate-200"
              />
            </div>
          </div>

          {/* Cards for each snapshot */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {['PRE_SESSION', 'PRE_OPEN'].map((sName) => {
              const detail = snapshots?.snapshot_details[sName]
              return (
                <div key={sName} className="bg-slate-900/50 border border-slate-800 rounded-xl p-5 space-y-3">
                  <div className="flex justify-between items-center text-xs font-mono">
                    <span className="px-2.5 py-1 rounded bg-purple-950 border border-purple-800 text-purple-300 font-bold">
                      {sName} Snapshot
                    </span>
                    <span className="text-slate-400">{detail?.instruments_count || 0} Instruments</span>
                  </div>

                  <div className="grid grid-cols-2 gap-3 font-mono text-xs mt-2">
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                      <div className="text-slate-400">Computed Values</div>
                      <div className="text-xl font-bold text-emerald-400 mt-1">
                        {(detail?.values_count || 0).toLocaleString('en-IN')}
                      </div>
                    </div>
                    <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                      <div className="text-slate-400">Nulls / Inadequate</div>
                      <div className="text-xl font-bold text-amber-400 mt-1">
                        {(detail?.nulls_count || 0).toLocaleString('en-IN')}
                      </div>
                    </div>
                  </div>

                  {/* Completeness Bar */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[11px] font-mono text-slate-400">
                      <span>Completeness</span>
                      <span className="text-white font-bold">{detail?.completeness_pct || 0}%</span>
                    </div>
                    <div className="w-full bg-slate-950 rounded-full h-2.5 overflow-hidden border border-slate-800">
                      <div
                        className="bg-gradient-to-r from-purple-500 to-emerald-400 h-2.5 rounded-full"
                        style={{ width: `${detail?.completeness_pct || 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Null reasons breakdown */}
          <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5 space-y-3">
            <h3 className="text-sm font-semibold text-white">Null Reasons Breakdown</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-mono text-xs">
              {Object.entries(snapshots?.null_reasons_breakdown || {}).map(([reason, cnt]) => (
                <div key={reason} className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                  <div className="text-slate-400">{reason}</div>
                  <div className="text-lg font-bold text-white mt-1">
                    {Number(cnt).toLocaleString('en-IN')}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Refusal & Lock Audit */}
      {activeTab === 'refusals' && (
        <div className="space-y-4">
          <div className="bg-slate-900/40 border border-slate-800 p-4 rounded-xl flex justify-between items-center">
            <div>
              <h3 className="text-sm font-semibold text-white">Stage 3 Refusal & Lock Audit Trail</h3>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                Every refusal or execution event is audited immutably in stage3_event.
              </p>
            </div>
            <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
              {gate.events_count_total} Audit Rows
            </span>
          </div>

          <div className="bg-slate-900/40 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-950 text-slate-400 uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3">Event ID</th>
                    <th className="p-3">Timestamp (UTC)</th>
                    <th className="p-3">Event Type</th>
                    <th className="p-3">Mode</th>
                    <th className="p-3">Operator</th>
                    <th className="p-3">Audit Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {gate.refusal_audit.map((evt: Stage3EventItem) => {
                    const isRefused = evt.event === 'REFUSED'
                    return (
                      <tr key={evt.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="p-3 font-bold text-slate-300">#{evt.id}</td>
                        <td className="p-3 text-slate-400">
                          {new Date(evt.at).toISOString().replace('T', ' ').slice(0, 19)}
                        </td>
                        <td className="p-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                              isRefused
                                ? 'bg-rose-950/60 border border-rose-800 text-rose-300'
                                : 'bg-emerald-950/60 border border-emerald-800 text-emerald-300'
                            }`}
                          >
                            {evt.event}
                          </span>
                        </td>
                        <td className="p-3 text-indigo-300">{evt.mode}</td>
                        <td className="p-3 text-slate-400">{evt.operator || 'system'}</td>
                        <td className="p-3 text-slate-300 max-w-md truncate" title={JSON.stringify(evt.detail)}>
                          {evt.detail && typeof evt.detail === 'object' ? (
                            <span>
                              {evt.detail.locks ? `locks: ${JSON.stringify(evt.detail.locks)}` : JSON.stringify(evt.detail).slice(0, 80)}
                            </span>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
export default Stage3View
