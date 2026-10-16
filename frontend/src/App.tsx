import React from 'react'
import { BrowserRouter, Routes, Route, useNavigate, useSearchParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './context/ThemeContext'
import { AppLayout } from './components/Layout/AppLayout'
import { ControlRoomView } from './components/ControlRoom/ControlRoomView'
import { StagePlaceholderView } from './components/Stages/StagePlaceholderView'
import { Stage1View } from './components/Stages/Stage1View'
import { Stage2View } from './components/Stages/Stage2View'
import { Stage3View } from './components/Stages/Stage3View'
import { StockDetailPage } from './components/Stocks/StockDetailPage'
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

// Create TanStack Query Client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
})

// Route wrapper components to handle navigation & query params cleanly
function ExplorerPage() {
  const navigate = useNavigate()
  return (
    <StockExplorer
      selectedKey="NSE_INDEX|Nifty 50"
      onSelectInstrument={(key: string) => navigate(`/stocks/${encodeURIComponent(key)}`)}
    />
  )
}

function ChartPage() {
  const [params] = useSearchParams()
  const key = params.get('key') || 'NSE_INDEX|Nifty 50'
  return (
    <div className="space-y-4">
      <div className="border-b border-slate-800 pb-3">
        <h1 className="text-xl font-bold text-slate-100">Live &amp; Historical Candlestick Chart</h1>
        <p className="text-xs text-slate-400 mt-0.5">
          High-frequency multi-timeframe rendering (1m, 15m, 1h, 1D) with Point-in-Time adjustments
        </p>
      </div>
      <CandleChart instrumentKey={key} />
    </div>
  )
}

function TechnicalsPage() {
  const [params] = useSearchParams()
  const key = params.get('key') || 'NSE_INDEX|Nifty 50'
  return <TechnicalDataView instrumentKey={key} />
}

function FundamentalsPage() {
  const [params] = useSearchParams()
  const rawKey = params.get('key') || 'NSE_EQ|INE002A01018'
  const key = rawKey.startsWith('NSE_EQ') ? rawKey : 'NSE_EQ|INE002A01018'
  return <FundamentalsView instrumentKey={key} />
}

function NewsPage() {
  const navigate = useNavigate()
  return (
    <NewsIntelligenceView
      onSelectInstrument={(key: string) => navigate(`/stocks/${encodeURIComponent(key)}`)}
    />
  )
}

function ScreenerPage() {
  const navigate = useNavigate()
  return (
    <StockScreener
      onSelectInstrument={(key: string) => navigate(`/stocks/${encodeURIComponent(key)}`)}
    />
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<ControlRoomView />} />
              <Route path="stages/1" element={<Stage1View />} />
              <Route path="stages/2" element={<Stage2View />} />
              <Route path="stages/3" element={<Stage3View />} />
              <Route path="stages/:stageId" element={<StagePlaceholderView />} />
              <Route path="stocks/:key" element={<StockDetailPage />} />

              <Route path="explorer" element={<ExplorerPage />} />
              <Route path="chart" element={<ChartPage />} />
              <Route path="technicals" element={<TechnicalsPage />} />
              <Route path="fundamentals" element={<FundamentalsPage />} />
              <Route path="globals" element={<GlobalMarketsView />} />
              <Route path="news" element={<NewsPage />} />
              <Route path="screener" element={<ScreenerPage />} />
              <Route path="signals" element={<SignalsView />} />
              <Route path="portfolio" element={<PortfolioView />} />
              <Route path="health" element={<SystemHealthView />} />
              <Route path="ops" element={<AdminOpsView />} />
              <Route path="*" element={<ControlRoomView />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

export default App
