import React, { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Layers,
  CheckCircle,
  AlertTriangle,
  Lock,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  Database,
  Cpu,
  TrendingUp,
  DollarSign,
} from 'lucide-react'
import { api } from '../../services/api'
import { formatDateTimeIST } from '../../utils/formatters'

const STAGE_DESCRIPTIONS: Record<number, { title: string; subtitle: string; description: string }> = {
  1: {
    title: 'Stage 1: Data Ingestion',
    subtitle: 'High-frequency & Daily Market Data Ingestion for NSE',
    description: 'Coverage by timeframe (1d since 2020; 1h and 15m since 2022; 1m for last 92 days), backfill supervisor progress, quarantined and excluded bars with reasons, corporate-action freshness, and instrument master changes.',
  },
  2: {
    title: 'Stage 2: Processing & Storage',
    subtitle: 'Data Normalization and Quality Gate Verification',
    description: 'Stage 2 acceptance gate criteria A–P, Point-in-Time timestamp contracts, excluded bar audits, and canonical storage consistency across 3,584 included master instruments.',
  },
  3: {
    title: 'Stage 3: Feature Engineering',
    subtitle: 'Point-in-Time Feature Calculation & Registry Locks',
    description: 'Stage 3 gate criteria A–O, Feature registry v4 (104 features), per-snapshot completeness (PRE_SESSION & PRE_OPEN), refusal audit (stage3_event), and strict lock enforcement.',
  },
  4: {
    title: 'Stage 4: Prediction Research',
    subtitle: 'Scientific Experiment Ledger & Calibration (E1–E4)',
    description: 'Experiment ledger E1–E4: hypothesis, pre-registration, status (LOOK TAKEN / CALIBRATING), Wilson confidence interval calibration tables, and strict no-profitability claim disclosures.',
  },
  5: {
    title: 'Stage 5: Signals / Targets',
    subtitle: 'Daily Strategy Target Lists & Score Provenance',
    description: 'Daily TargetList per strategy (baseline_gap_fade, baseline_c0, bench_c0), ranked keys, scores, decision timestamps, and inter-day target list diffs.',
  },
  6: {
    title: 'Stage 6: Risk Management',
    subtitle: 'Pre-Trade Limits, Sector Caps & Drawdown Halts',
    description: 'Active limits in force, every APPROVED/REJECTED risk decision with rule rationale (drawdown halt, daily loss halt, min price, min turnover, sector cap, max positions).',
  },
  7: {
    title: 'Stage 7: Paper Execution',
    subtitle: 'Simulated Order Routing & Execution Quality',
    description: 'Simulated fills per day, fill rate %, prices, comprehensive charges breakdown (brokerage, STT, stamp duty, exchange turnover fee, SEBI turnover fee, GST), and un-filled reasons.',
  },
  8: {
    title: 'Stage 8: Monitoring & KPIs',
    subtitle: 'Equity Tracking, Drawdown Curves & Forward Replay',
    description: 'Simulated equity curve vs Nifty 50 and bench_c0, drawdown curve, Sharpe ratio, hit rate, cost share, fill rate, score drift (PSI), and forward-only replay toggle (from 2026-10-16).',
  },
}

export const StagePlaceholderView: React.FC = () => {
  const { stageId } = useParams<{ stageId: string }>()
  const stageNum = parseInt(stageId || '1', 10)
  const [expandJson, setExpandJson] = useState(false)

  const { data: stagesData, isLoading } = useQuery({
    queryKey: ['stages-overview'],
    queryFn: () => api.getStages(),
  })

  const stage = stagesData?.stages.find(s => s.stage_number === stageNum)
  const metaInfo = STAGE_DESCRIPTIONS[stageNum] || {
    title: `Stage ${stageNum}`,
    subtitle: 'Pipeline Stage Detail',
    description: 'Detailed view of stage metrics and gate evidence.',
  }

  return (
    <div className="space-y-6">
      {/* Header with breadcrumb */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 transition-colors"
            title="Back to Control Room"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-bold text-slate-100">{metaInfo.title}</h1>
              {stage && (
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-800 border border-slate-700 text-emerald-400">
                  {stage.status_label || stage.status}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">{metaInfo.subtitle}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {stageNum > 1 && (
            <Link
              to={`/stages/${stageNum - 1}`}
              className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-850 text-slate-300 text-xs font-medium border border-slate-800 transition-colors"
            >
              &larr; Stage {stageNum - 1}
            </Link>
          )}
          {stageNum < 8 && (
            <Link
              to={`/stages/${stageNum + 1}`}
              className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-850 text-slate-300 text-xs font-medium border border-slate-800 transition-colors"
            >
              Stage {stageNum + 1} &rarr;
            </Link>
          )}
        </div>
      </div>

      {/* Stage Description & Compliance Banner */}
      <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 text-xs text-slate-300">
        <div className="font-semibold text-slate-100">Stage Overview & Mandate:</div>
        <p className="text-slate-400 leading-relaxed">{metaInfo.description}</p>
      </div>

      {/* Key Metric & Status Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
          <div className="text-[11px] font-mono text-slate-400">Current Status</div>
          <div className="text-lg font-bold text-slate-100 mt-1 flex items-center gap-2">
            {stage?.status === 'LOCKED' ? (
              <Lock className="w-4 h-4 text-amber-400" />
            ) : (
              <CheckCircle className="w-4 h-4 text-emerald-400" />
            )}
            <span>{stage?.status_label || stage?.status || 'Active'}</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            Last update: {formatDateTimeIST(stage?.last_change)}
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
          <div className="text-[11px] font-mono text-slate-400">{stage?.key_metric_label || 'Key Metric'}</div>
          <div className="text-lg font-bold text-emerald-400 font-mono mt-1">
            {stage?.key_metric_value || '—'}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Point-in-time verified</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
          <div className="text-[11px] font-mono text-slate-400">Stage Alerts</div>
          <div className="text-lg font-bold text-slate-100 mt-1 flex items-center gap-2">
            {stage && stage.alert_count > 0 ? (
              <span className="text-amber-400 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4" />
                {stage.alert_count} Alert(s)
              </span>
            ) : (
              <span className="text-emerald-400 flex items-center gap-1.5">
                <CheckCircle className="w-4 h-4" />
                0 Alerts
              </span>
            )}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            {stage?.alerts.length ? stage.alerts[0] : 'No alert reported by the API for this stage'}
          </div>
        </div>
      </div>

      {/* Expandable Evidence Summary */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <button
          type="button"
          onClick={() => setExpandJson(!expandJson)}
          className="w-full px-4 py-3 bg-slate-900 hover:bg-slate-850 flex items-center justify-between text-xs font-semibold text-slate-200 transition-colors"
        >
          <div className="flex items-center gap-2">
            {expandJson ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
            <span>Gate Evidence &amp; Verification JSON ({stageNum})</span>
          </div>
          <span className="font-mono text-[10px] text-slate-400">
            {expandJson ? 'Collapse JSON' : 'Expand Raw JSON'}
          </span>
        </button>

        {expandJson && (
          <div className="p-4 bg-slate-950 border-t border-slate-800">
            <pre className="text-[11px] font-mono text-slate-300 overflow-x-auto p-3 bg-slate-900/80 rounded-lg border border-slate-800">
              {JSON.stringify(stage?.evidence_summary || {}, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
