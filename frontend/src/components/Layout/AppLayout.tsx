import React, { useState, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { CommandPalette } from '../CommandPalette/CommandPalette'
import { wsService } from '../../services/websocket'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../services/api'

export const AppLayout: React.FC = () => {
  const location = useLocation()
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const [wsStatus, setWsStatus] = useState<'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'>('DISCONNECTED')

  // Query stage status overview (includes market state from trading_session)
  const { data: stagesData } = useQuery({
    queryKey: ['stages-overview'],
    queryFn: () => api.getStages(),
    refetchInterval: 30_000,
  })

  // Extract selectedKey from search params or URL if on /stocks/:key or /chart?key=
  const searchParams = new URLSearchParams(location.search)
  let selectedKey = searchParams.get('key') || undefined
  if (!selectedKey && location.pathname.startsWith('/stocks/')) {
    const rawKey = location.pathname.replace('/stocks/', '')
    if (rawKey) {
      selectedKey = decodeURIComponent(rawKey)
    }
  }

  // Keyboard shortcut listener for ⌘K and Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCommandPaletteOpen(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Live WebSocket Connection
  useEffect(() => {
    wsService.connect()
    const statusSub = wsService.onStatusChange((status: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED') => {
      setWsStatus(status)
    })

    return () => {
      statusSub()
      wsService.disconnect()
    }
  }, [])

  // Subscribe selected instrument to WebSocket feed
  useEffect(() => {
    if (selectedKey) {
      wsService.subscribe([selectedKey])
    }
  }, [selectedKey])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-600/30 selection:text-indigo-200">
      {/* Top Bar */}
      <TopBar
        marketState={stagesData?.market_state}
        wsStatus={wsStatus}
        onOpenCommandPalette={() => setCommandPaletteOpen(true)}
        selectedKey={selectedKey}
      />

      {/* Main Body with Sidebar + Outlet */}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar stages={stagesData?.stages} />

        <main className="flex-1 overflow-y-auto bg-slate-950/90 flex flex-col">
          {/* Paper Trading Compliance Banner */}
          <div className="bg-amber-950/40 border-b border-amber-900/50 px-4 py-1.5 text-xs text-amber-300/90 flex items-center justify-between font-mono">
            <span>
              <strong>PAPER ONLY:</strong> Simulated paper execution records only &bull; Not a live trading or profitability claim.
            </span>
            <span className="text-[10px] text-amber-400/60 hidden sm:inline">
              NO BROKER ORDER ROUTING &bull; READ-ONLY DATABASE GATEWAY
            </span>
          </div>

          <div className="flex-1 p-4 sm:p-6 max-w-7xl w-full mx-auto">
            <Outlet />
          </div>

          {/* Footer Provenance Strip */}
          <footer className="border-t border-slate-900 bg-slate-950/90 px-6 py-3 text-[11px] text-slate-400 flex flex-col sm:flex-row items-center justify-between gap-2 mt-auto">
            <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
              <span>Prajna AI Trading System &bull; 8-Stage Research Platform</span>
              <span>&bull;</span>
              <span className="font-mono text-amber-300/90">PAPER ONLY &bull; read-only API</span>
            </div>
            <div className="flex items-center gap-3">
              <span>NSE India (Upstox REST V3 / WS Proxy)</span>
              <span>&bull;</span>
              <span>Point-in-Time Honest</span>
            </div>
          </footer>
        </main>
      </div>

      {/* Command Palette Modal */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
      />
    </div>
  )
}
