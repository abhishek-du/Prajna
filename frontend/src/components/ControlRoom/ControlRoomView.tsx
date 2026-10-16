import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  Layers,
  Lock,
  CheckCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  AlertCircle,
  TrendingUp,
  Cpu,
  ShieldAlert,
  DollarSign,
  ArrowRight,
  ShieldCheck,
} from 'lucide-react'
import { api } from '../../services/api'
import { formatDateTimeIST, isDataStale } from '../../utils/formatters'
import type { StageSummary, ScheduledJobItem, SystemAlertItem } from '../../types/api'

export const ControlRoomView: React.FC = () => {
  const navigate = useNavigate()

  const {
    data: envelope,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['stages-control-room'],
    queryFn: () => api.getStagesEnvelope(),
    refetchInterval: 15_000,
  })

  const stagesData = envelope?.data
  const meta = envelope?.meta
  const stale = isDataStale(meta?.as_of, 120)

  // Stage status style helper
  const getStageStatusBadge = (stage: StageSummary) => {
    switch (stage.status) {
      case 'PASS':
      case 'COMPLETE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800">
            <CheckCircle className="w-3 h-3 text-emerald-400" />
            {stage.status_label || stage.status}
          </span>
        )
      case 'LOCKED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-amber-950/80 text-amber-300 border border-amber-800">
            <Lock className="w-3 h-3 text-amber-400" />
            {stage.status_label || 'LOCKED'}
          </span>
        )
      case 'CALIBRATING':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-purple-950/80 text-purple-300 border border-purple-800">
            <Activity className="w-3 h-3 text-purple-400" />
            {stage.status_label || 'CALIBRATING'}
          </span>
        )
      case 'ACTIVE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-cyan-950/80 text-cyan-300 border border-cyan-800">
            <CheckCircle className="w-3 h-3 text-cyan-400" />
            {stage.status_label || 'ACTIVE'}
          </span>
        )
      case 'FAIL':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-red-950/80 text-red-300 border border-red-800">
            <AlertCircle className="w-3 h-3 text-red-400" />
            FAIL
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-800 text-slate-300 border border-slate-700">
            {stage.status}
          </span>
        )
    }
  }

  // Job timeline status badge
  const getJobStatusBadge = (status: string) => {
    switch (status) {
      case 'DONE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
            <CheckCircle className="w-2.5 h-2.5 text-emerald-400" />
            DONE
          </span>
        )
      case 'RUNNING':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-blue-950 text-blue-300 border border-blue-800">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            RUNNING
          </span>
        )
      case 'WAITING_CLOSE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-indigo-950 text-indigo-300 border border-indigo-800">
            <Clock className="w-2.5 h-2.5 text-indigo-400" />
            WAITING_CLOSE
          </span>
        )
      case 'REFUSED → BACKFILLED':
      case 'BACKFILLED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-purple-950 text-purple-300 border border-purple-800">
            <CheckCircle className="w-2.5 h-2.5 text-purple-400" />
            BACKFILLED
          </span>
        )
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-red-950 text-red-300 border border-red-800">
            <AlertCircle className="w-2.5 h-2.5 text-red-400" />
            FAILED
          </span>
        )
      case 'MISSED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-amber-950 text-amber-300 border border-amber-800">
            <AlertTriangle className="w-2.5 h-2.5 text-amber-400" />
            MISSED
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-800 text-slate-400 border border-slate-700">
            <Clock className="w-2.5 h-2.5 text-slate-500" />
            {status || 'PENDING'}
          </span>
        )
    }
  }

  // Loading skeleton state
  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-10 bg-slate-800/60 rounded-lg w-1/3" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-32 bg-slate-800/40 rounded-xl border border-slate-800" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-64 bg-slate-800/40 rounded-xl border border-slate-800" />
          <div className="h-64 bg-slate-800/40 rounded-xl border border-slate-800" />
        </div>
      </div>
    )
  }

  // Error state with retry
  if (isError || !stagesData) {
    return (
      <div className="p-8 rounded-xl bg-red-950/20 border border-red-800/60 text-center space-y-4 my-8">
        <AlertCircle className="w-10 h-10 text-red-400 mx-auto" />
        <div>
          <h2 className="text-lg font-bold text-red-200">Failed to load Control Room state</h2>
          <p className="text-xs text-red-400/90 mt-1 max-w-md mx-auto">
            {error instanceof Error ? error.message : 'Unable to connect to /api/v1/stages.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="px-4 py-2 bg-red-800/40 hover:bg-red-800/60 text-red-100 rounded-lg text-xs font-semibold border border-red-700 transition-colors inline-flex items-center gap-2"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Retry Connection
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header bar with provenance and refresh */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-extrabold text-slate-100 tracking-tight">
              Prajna Control Room
            </h1>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950/70 text-emerald-300 border border-emerald-800/80">
              8 STAGES &bull; PAPER
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Real-time pipeline orchestration, acceptance gates, and scheduled job audit trail
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Stale Warning Indicator */}
          {stale && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-950/60 border border-amber-800 text-[11px] text-amber-300 font-mono">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>Data Stale</span>
            </div>
          )}

          {/* As-Of Timestamp */}
          <div className="text-right text-[11px] text-slate-400 font-mono">
            <div>as_of: <span className="text-slate-200">{formatDateTimeIST(meta?.as_of)}</span></div>
            <div className="text-[10px] text-slate-400">knowledge instant</div>
          </div>

          {/* Refresh Button */}
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="p-2 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 hover:text-slate-100 transition-colors disabled:opacity-50"
            title="Refresh control room state"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin text-emerald-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Row of 8 Stage Cards */}
      <div>
        <div className="flex items-center justify-between mb-2.5 px-0.5">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
            Pipeline Architecture (Stages 1–8)
          </span>
          <span className="text-[11px] text-slate-400 font-mono">
            Click any card to inspect evidence & gate details &rarr;
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {stagesData.stages.map(stage => {
            return (
              <button
                key={stage.stage_number}
                type="button"
                onClick={() => navigate(`/stages/${stage.stage_number}`)}
                className="text-left bg-slate-900/90 hover:bg-slate-850 border border-slate-800 hover:border-slate-700/80 p-3.5 rounded-xl transition-all group flex flex-col justify-between shadow-sm"
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <span className="text-xs font-bold text-slate-100 group-hover:text-emerald-300 transition-colors">
                      Stage {stage.stage_number}: {stage.name}
                    </span>
                    {getStageStatusBadge(stage)}
                  </div>

                  <div className="mt-1">
                    <div className="text-[11px] text-slate-400 font-mono">
                      {stage.key_metric_label}
                    </div>
                    <div className="text-sm font-bold text-slate-200 font-mono truncate mt-0.5">
                      {stage.key_metric_value}
                    </div>
                  </div>
                </div>

                <div className="mt-3.5 pt-2.5 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-400">
                  <div className="truncate font-mono">
                    {stage.last_change ? formatDateTimeIST(stage.last_change) : 'Point-in-time'}
                  </div>

                  {stage.alert_count > 0 ? (
                    <span className="inline-flex items-center gap-1 text-amber-400 font-semibold font-mono">
                      <AlertTriangle className="w-2.5 h-2.5" />
                      {stage.alert_count} Alert
                    </span>
                  ) : (
                    <ArrowRight className="w-3 h-3 text-slate-600 group-hover:text-emerald-400 transition-colors" />
                  )}
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Two Columns: Scheduled Jobs Timeline + System Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: Scheduled Jobs Timeline */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 sm:p-5 flex flex-col">
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-3 mb-3">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-emerald-400" />
              <h2 className="text-sm font-bold text-slate-100">
                Today&apos;s Scheduled Job Timeline
              </h2>
            </div>
            <span className="text-[11px] font-mono text-slate-400">
              {stagesData.timeline.length} Scheduled
            </span>
          </div>

          <div className="space-y-2.5 flex-1 overflow-y-auto max-h-[380px] pr-1">
            {stagesData.timeline.map((job, idx) => (
              <div
                key={idx}
                className="flex flex-col gap-1.5 p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/70 hover:border-slate-700 transition-colors text-xs"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2.5 min-w-0">
                    <span className="font-mono font-bold text-slate-300 text-[11px] px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 shrink-0">
                      {job.time_ist}
                    </span>
                    <div className="truncate">
                      <div className="font-semibold text-slate-100 flex items-center gap-2 flex-wrap">
                        <span className="truncate">{job.name}</span>
                        <span className="text-[9px] font-mono text-slate-400 px-1 rounded bg-slate-900 border border-slate-800 shrink-0">
                          {job.stage}
                        </span>
                        {job.schedule_status && (
                          <span
                            className={`text-[9px] font-mono px-1 rounded shrink-0 border ${
                              job.schedule_status === 'SCHEDULED'
                                ? 'bg-emerald-950/50 text-emerald-400 border-emerald-800/60'
                                : job.schedule_status === 'MANUAL RUN'
                                ? 'bg-amber-950/50 text-amber-300 border-amber-800/60'
                                : job.schedule_status === 'NOT_SCHEDULED'
                                ? 'bg-red-950/50 text-red-400 border-red-800/60'
                                : 'bg-slate-900 text-slate-400 border-slate-800'
                            }`}
                          >
                            {job.schedule_status}
                          </span>
                        )}
                        {job.delay_minutes && job.delay_minutes > 60 && (
                          <span className="text-[9px] font-mono text-amber-300 bg-amber-950/60 border border-amber-800/60 px-1 rounded shrink-0">
                            +{job.delay_minutes}m delay
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400 truncate mt-0.5">
                        {job.detail}
                      </div>
                    </div>
                  </div>

                  <div className="shrink-0 flex items-center">
                    {getJobStatusBadge(job.status)}
                  </div>
                </div>

                {job.attempts && job.attempts.length > 1 && (
                  <div className="flex items-center gap-1.5 pl-11 pt-1 border-t border-slate-900/80 flex-wrap">
                    <span className="text-[10px] text-slate-500 font-mono">Attempts today:</span>
                    {job.attempts.map((att, aIdx) => (
                      <span
                        key={aIdx}
                        className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300"
                        title={att.detail}
                      >
                        <span className="text-slate-400">{att.time_ist}</span>
                        <span
                          className={`font-semibold ${
                            att.status === 'DONE'
                              ? 'text-emerald-400'
                              : att.status === 'FAILED'
                              ? 'text-red-400'
                              : att.status === 'MISSED'
                              ? 'text-amber-400'
                              : att.status === 'RUNNING'
                              ? 'text-blue-400'
                              : 'text-purple-400'
                          }`}
                        >
                          {att.status}
                        </span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Right Column: System Alerts & Operational Feed */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 sm:p-5 flex flex-col">
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-3 mb-3">
            <div className="flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-bold text-slate-100">
                System Alerts &amp; Refusal Audits
              </h2>
            </div>
            <span className="text-[11px] font-mono text-slate-400">
              {stagesData.alerts.length} Active
            </span>
          </div>

          <div className="space-y-2.5 flex-1 overflow-y-auto max-h-[380px] pr-1">
            {stagesData.alerts.length === 0 ? (
              <div className="py-12 text-center text-slate-500 text-xs flex flex-col items-center justify-center">
                <ShieldCheck className="w-8 h-8 text-emerald-500/60 mb-2" />
                <span className="font-semibold text-slate-300">All Systems Clear</span>
                <span className="text-slate-500 mt-0.5">
                  No active supervisor alerts or gate failures recorded.
                </span>
              </div>
            ) : (
              stagesData.alerts.map((alert, idx) => (
                <div
                  key={idx}
                  className={`p-3 rounded-lg border text-xs flex items-start gap-2.5 ${
                    alert.severity === 'ALERT'
                      ? 'bg-red-950/20 border-red-800/60 text-red-200'
                      : 'bg-amber-950/20 border-amber-800/60 text-amber-200'
                  }`}
                >
                  <AlertTriangle
                    className={`w-4 h-4 shrink-0 mt-0.5 ${
                      alert.severity === 'ALERT' ? 'text-red-400' : 'text-amber-400'
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono font-bold text-[10px] uppercase tracking-wider text-slate-400">
                        {alert.source} {alert.stage ? `&bull; Stage ${alert.stage}` : ''}
                      </span>
                      <span className="font-mono text-[10px] text-slate-500">
                        {formatDateTimeIST(alert.timestamp)}
                      </span>
                    </div>
                    <p className="mt-1 text-slate-300 leading-snug break-words font-mono text-[11px]">
                      {alert.message}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
