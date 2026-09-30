import { useState, useEffect } from 'react'
import { Navbar, type NavTab } from './components/Navbar'
import { OverviewDashboard } from './components/Overview/OverviewDashboard'
import { StockExplorer } from './components/Explorer/StockExplorer'
import { CandleChart } from './components/Chart/CandleChart'
import { TechnicalDataView } from './components/Technicals/TechnicalDataView'
import { FundamentalsView } from './components/Fundamentals/FundamentalsView'
import { GlobalMarketsView } from './components/GlobalMarkets/GlobalMarketsView'
import { NewsIntelligenceView } from './components/News/NewsIntelligenceView'
import { StockScreener } from './components/Screener/StockScreener'
import { SignalsView } from './components/Signals/SignalsView'
import { PortfolioView } from './components/Portfolio/PortfolioView'
import { SystemHealthView } from './components/Health/SystemHealthView'
import { AdminOpsView } from './components/Admin/AdminOpsView'
import { wsService } from './services/websocket'

export function App() {
  const [activeTab, setActiveTab] = useState<NavTab>('overview')
  const [selectedKey, setSelectedKey] = useState<string>('NSE_INDEX|Nifty 50')
  const [wsStatus, setWsStatus] = useState<'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'>('DISCONNECTED')
  const [currentTimeIst, setCurrentTimeIst] = useState<string>('')
  const [marketOpen, setMarketOpen] = useState<boolean>(false)

  // IST Clock and Market Open check
  useEffect(() => {
    const updateTime = () => {
      const now = new Date()
      // Convert to IST
      const istString = now.toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
      setCurrentTimeIst(istString)

      // Market hours IST: 09:15 to 15:30 on weekdays (Mon=1, Fri=5)
      const istDate = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
      const day = istDate.getDay()
      const hours = istDate.getHours()
      const mins = istDate.getMinutes()
      const totalMins = hours * 60 + mins

      const isOpen = day >= 1 && day <= 5 && totalMins >= 555 && totalMins <= 930
      setMarketOpen(isOpen)
    }

    updateTime()
    const timer = setInterval(updateTime, 1000)
    return () => clearInterval(timer)
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

  const handleSelectInstrument = (key: string, targetTab?: NavTab) => {
    setSelectedKey(key)
    if (targetTab) {
      setActiveTab(targetTab)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-600/30 selection:text-indigo-200">
      {/* Top Navbar */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        selectedKey={selectedKey}
        wsStatus={wsStatus}
        marketOpen={marketOpen}
        currentTimeIst={currentTimeIst}
      />

      {/* Main Content Area */}
      <main className="flex-1 pb-12">
        {activeTab === 'overview' && (
          <OverviewDashboard
            onSelectInstrument={(key: string) => handleSelectInstrument(key, 'chart')}
          />
        )}

        {activeTab === 'explorer' && (
          <StockExplorer
            selectedKey={selectedKey}
            onSelectInstrument={(key: string) => handleSelectInstrument(key, 'chart')}
          />
        )}

        {activeTab === 'chart' && (
          <div className="p-6 max-w-7xl mx-auto space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-xl font-bold text-slate-100">Live & Historical Candlestick Chart</h1>
                <p className="text-xs text-slate-400 mt-0.5">
                  High-frequency multi-timeframe rendering (1m, 15m, 1h, 1D) with Point-in-Time adjustments
                </p>
              </div>
            </div>
            <CandleChart instrumentKey={selectedKey} />
          </div>
        )}

        {activeTab === 'technicals' && (
          <TechnicalDataView
            instrumentKey={selectedKey}
          />
        )}

        {activeTab === 'fundamentals' && (
          <FundamentalsView
            instrumentKey={selectedKey.startsWith('NSE_EQ') ? selectedKey : 'NSE_EQ|INE002A01018'}
          />
        )}

        {activeTab === 'globals' && <GlobalMarketsView />}

        {activeTab === 'news' && (
          <NewsIntelligenceView
            onSelectInstrument={(key: string) => handleSelectInstrument(key, 'chart')}
          />
        )}

        {activeTab === 'screener' && (
          <StockScreener
            onSelectInstrument={(key: string) => handleSelectInstrument(key, 'chart')}
          />
        )}

        {activeTab === 'signals' && <SignalsView />}

        {activeTab === 'portfolio' && <PortfolioView />}

        {activeTab === 'health' && <SystemHealthView />}

        {activeTab === 'ops' && <AdminOpsView />}
      </main>

      {/* Footer / System Provenance Strip */}
      <footer className="border-t border-slate-900 bg-slate-950/80 px-6 py-3 text-[11px] text-slate-500 flex flex-col sm:flex-row items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <span>Prajna AI Trading System &bull; AutoTrade Pro V2</span>
          <span>&bull;</span>
          <span className="font-mono">V1 Database Isolation: ENFORCED</span>
          <span>&bull;</span>
          <span className="font-mono">Stage 3: STRICTLY LOCKED</span>
        </div>
        <div className="flex items-center gap-3">
          <span>Target Market: NSE India</span>
          <span>&bull;</span>
          <span>Broker Gateway: Upstox REST V3 / WS (Secure Backend Proxy)</span>
        </div>
      </footer>
    </div>
  )
}

export default App
