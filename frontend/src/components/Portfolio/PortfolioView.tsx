import React, { useEffect, useState } from 'react'
import {
  DollarSign,
  Lock,
  ShieldAlert,
} from 'lucide-react'
import { api } from '../../services/api'

export const PortfolioView: React.FC = () => {
  const [data, setData] = useState<{
    status: string
    stage: string
    message: string
    holdings: unknown[]
    positions: unknown[]
    orders: unknown[]
  } | null>(null)
  const [loading, setLoading] = useState<boolean>(true)

  const loadPortfolio = async () => {
    try {
      setLoading(true)
      const res = await api.getPortfolio()
      setData(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPortfolio()
  }, [])

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <DollarSign className="w-5 h-5 text-amber-400" />
            Portfolio & Execution Ledger
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Holdings, live open positions, and broker order routing UI contracts
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="px-3 py-1 bg-amber-950/40 text-amber-300 border border-amber-800/60 rounded-lg text-xs font-semibold flex items-center gap-1.5">
            <Lock className="w-3.5 h-3.5" />
            STAGE 4/5 LOCKED
          </span>
        </div>
      </div>

      {/* Compliance Warning */}
      <div className="bg-amber-950/20 border border-amber-800/50 rounded-xl p-5 text-xs text-amber-200/90 space-y-2">
        <div className="flex items-center gap-2 font-bold text-amber-300 text-sm">
          <ShieldAlert className="w-5 h-5 text-amber-400" />
          Execution Engine Locked: Compliance State
        </div>
        <p className="leading-relaxed">
          Live broker order routing and execution interfaces (Stage 4 & 5) are strictly locked.
          No real orders can be placed, and no simulated live orders are generated.
        </p>
      </div>

      {/* Holdings & Positions Table Contract */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 space-y-3">
          <h2 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
            Holdings Contract
          </h2>
          <div className="py-16 text-center text-slate-500 text-xs">
            <Lock className="w-6 h-6 text-amber-500/40 mx-auto mb-2" />
            0 Active Holdings (Execution Locked)
          </div>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 space-y-3">
          <h2 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
            Open Positions Contract
          </h2>
          <div className="py-16 text-center text-slate-500 text-xs">
            <Lock className="w-6 h-6 text-amber-500/40 mx-auto mb-2" />
            0 Open Positions (Execution Locked)
          </div>
        </div>
      </div>
    </div>
  )
}
