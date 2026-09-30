import React, { useEffect, useState } from 'react'
import {
  AlertCircle,
  Cpu,
  Lock,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'
import { api } from '../../services/api'

export const SignalsView: React.FC = () => {
  const [data, setData] = useState<{
    status: string
    stage: string
    message: string
    signals: unknown[]
  } | null>(null)
  const [loading, setLoading] = useState<boolean>(true)

  const loadSignals = async () => {
    try {
      setLoading(true)
      const res = await api.getSignals()
      setData(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSignals()
  }, [])

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Cpu className="w-5 h-5 text-amber-400" />
            Stage 3 Trading Signals Engine
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Model inference, alpha generation, and trading signal UI contracts
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="px-3 py-1 bg-amber-950/40 text-amber-300 border border-amber-800/60 rounded-lg text-xs font-semibold flex items-center gap-1.5">
            <Lock className="w-3.5 h-3.5" />
            STAGE 3 LOCKED
          </span>
        </div>
      </div>

      {/* Strict Compliance Warning Box */}
      <div className="bg-amber-950/20 border border-amber-800/50 rounded-xl p-5 text-xs text-amber-200/90 space-y-3">
        <div className="flex items-center gap-2 font-bold text-amber-300 text-sm">
          <ShieldAlert className="w-5 h-5 text-amber-400" />
          Strict Zero-Simulation Compliance Policy
        </div>
        <p className="leading-relaxed">
          Stage 3 implementation remains locked. The system strictly prohibits:
        </p>
        <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px] font-mono">
          <li>Creating mock, random or simulated trading signals</li>
          <li>Training or serving unverified prediction models</li>
          <li>Inventing AI scores, probabilities, or fake expected returns</li>
          <li>Displaying fake BUY or SELL recommendations</li>
        </ul>
        <div className="text-[11px] text-amber-400/80 pt-1">
          {data?.message || 'Awaiting Stage 1 and Stage 2 formal signoff and historical warmup plan.'}
        </div>
      </div>

      {/* UI Contract Schema Preview */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between text-xs">
          <span className="font-bold text-slate-300 uppercase tracking-wider">
            Signals Ledger UI Contract
          </span>
          <span className="text-[11px] text-slate-500 font-mono">0 Live Signals (Compliant)</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/80 text-slate-400 text-[10px] uppercase border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Signal ID</th>
                <th className="py-3 px-3">Instrument</th>
                <th className="py-3 px-3">Timeframe</th>
                <th className="py-3 px-3">Direction</th>
                <th className="py-3 px-3">Strategy Type</th>
                <th className="py-3 px-3">Knowable At</th>
                <th className="py-3 px-4">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={7} className="py-20 text-center text-slate-500">
                  <div className="flex flex-col items-center justify-center space-y-2">
                    <Lock className="w-8 h-8 text-amber-500/50 mb-1" />
                    <p className="font-medium text-slate-400">No active signals</p>
                    <p className="text-xs text-slate-500 max-w-md">
                      Stage 3 trading signals will be populated here once feature definitions, point-in-time causality, and validation gates are satisfied.
                    </p>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
