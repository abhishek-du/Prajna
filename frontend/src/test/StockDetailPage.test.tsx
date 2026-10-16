import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { StockDetailPage } from '../components/Stocks/StockDetailPage'
import { api } from '../services/api'
import type {
  FeatureCardResponse,
  PreopenHistoryItem,
  StockLifecycleItem,
  StockPaperTradeItem,
} from '../types/api'

// Mock CandleChart to isolate StockDetailPage logic in jsdom
vi.mock('../components/Chart/CandleChart', () => ({
  CandleChart: ({ instrumentKey }: { instrumentKey: string }) => (
    <div data-testid="candle-chart-mock">CandleChart for {instrumentKey}</div>
  ),
}))

// Mock API client
vi.mock('../services/api', () => ({
  api: {
    getInstrumentLifecycle: vi.fn(),
    getFeatureCard: vi.fn(),
    getInstrumentPreopen: vi.fn(),
    getInstrumentPaperTrades: vi.fn(),
  },
}))

describe('StockDetailPage Component', () => {
  const mockLifecycle: StockLifecycleItem = {
    instrument_id: 101,
    instrument_key: 'NSE_EQ|INE002A01018',
    trading_symbol: 'RELIANCE',
    name: 'Reliance Industries Limited',
    isin: 'INE002A01018',
    segment: 'NSE_EQ',
    exchange: 'NSE',
    instrument_type: 'EQUITY',
    lifecycle_status: 'ACTIVE',
    first_seen: '2022-01-01',
    last_seen: '2026-10-16',
    included: true,
    filter_reason: null,
    sector: 'Oil & Gas / Energy',
    lifecycle_periods: [
      {
        status: 'ACTIVE',
        valid_from: '2022-01-01',
        valid_to: 'infinity',
        reason: 'INITIAL_INGEST',
        knowable_at: '2022-01-01T09:00:00Z',
      },
    ],
    attribute_versions: [
      {
        id: 1,
        valid_from: '2022-01-01',
        valid_to: 'infinity',
        trading_symbol: 'RELIANCE',
        isin: 'INE002A01018',
        lot_size: 1,
        tick_size: 0.05,
      },
    ],
  }

  const mockFeatureCard: FeatureCardResponse = {
    instrument_key: 'NSE_EQ|INE002A01018',
    session_date: '2026-10-16',
    snapshot: 'PRE_OPEN',
    feature_version: 'features-v4',
    registry_sha256: '6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3',
    values_count: 1,
    nulls_count: 1,
    features: [
      {
        feature_id: 'atr_14',
        group: 'price_technical',
        definition: 'Wilder average true range (14 period)',
        value: 24.1905,
        reason: null,
        knowable_at: '2026-10-16T09:08:00Z',
        computed_at: '2026-10-16T09:08:05Z',
      },
      {
        feature_id: 'order_flow_imbalance',
        group: 'orderbook_microstructure',
        definition: 'Normalized bid-ask depth imbalance',
        value: null,
        reason: 'Orderbook snapshot rejected: book depth < 5 levels',
        knowable_at: '2026-10-16T09:08:00Z',
        computed_at: '2026-10-16T09:08:05Z',
      },
    ],
  }

  const mockPreopen: PreopenHistoryItem[] = [
    {
      market_date: '2026-10-16',
      event_ts: '2026-10-16T03:38:00Z',
      event_ts_ist: '2026-10-16 09:08:00 IST',
      iep: 2750.5,
      ieq: 145000,
      tbq: 200000,
      tsq: 145000,
      imbalance_qty: 55000,
      imbalance_side: 'BUY',
      rp: 2720.0,
      ltp: 2750.5,
      gap_pct: 1.12,
      cas_eligible: true,
      knowable_at: '2026-10-16T03:38:00Z',
    },
  ]

  const mockPaperTrades: StockPaperTradeItem[] = [
    {
      id: 501,
      run_id: 'paper-20261016-01',
      strategy: 'bench_c0',
      session_date: '2026-10-16',
      status: 'FILLED',
      reason: 'REBALANCE',
      qty: 10,
      buy_px: 2750.0,
      sell_px: null,
      buy_value_inr: 27500.0,
      sell_value_inr: null,
      pnl_inr: 150.0,
      charges: { dp: 0, brokerage: 0, statutory: 5.5 },
      mode: 'SIMULATED',
    },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getInstrumentLifecycle).mockResolvedValue(mockLifecycle)
    vi.mocked(api.getFeatureCard).mockResolvedValue(mockFeatureCard)
    vi.mocked(api.getInstrumentPreopen).mockResolvedValue(mockPreopen)
    vi.mocked(api.getInstrumentPaperTrades).mockResolvedValue(mockPaperTrades)
  })

  it('renders header, persistent paper banner, and candlestick chart', async () => {
    render(
      <MemoryRouter initialEntries={['/stocks/NSE_EQ|INE002A01018']}>
        <Routes>
          <Route path="/stocks/:key" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    // Verify instrument header
    expect(await screen.findByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('NSE_EQ|INE002A01018')).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(screen.getByText(/Reliance Industries Limited/i)).toBeInTheDocument()

    // Verify Hard Rule 1 Persistent Paper Banner
    expect(
      screen.getByText(/PAPER ONLY — simulated fills, not a profitability claim/i)
    ).toBeInTheDocument()
    expect(screen.getByText(/Broker orders, modifications, and cancellations are strictly disabled/i)).toBeInTheDocument()

    // Verify Mock Chart
    expect(screen.getByTestId('candle-chart-mock')).toBeInTheDocument()
  })

  it('renders Stage 3 feature values with point-in-time honesty', async () => {
    render(
      <MemoryRouter initialEntries={['/stocks/NSE_EQ|INE002A01018']}>
        <Routes>
          <Route path="/stocks/:key" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    // Verify Stage 3 features table loads by default
    expect(await screen.findByText('atr_14')).toBeInTheDocument()
    expect(screen.getByText('24.1905')).toBeInTheDocument()
    expect(screen.getByText('Computed')).toBeInTheDocument()

    // Verify refused feature with explicit reason
    expect(screen.getByText('order_flow_imbalance')).toBeInTheDocument()
    expect(screen.getByText(/Orderbook snapshot rejected/i)).toBeInTheDocument()
  })

  it('switches to Pre-Open Auction History tab and displays preopen metrics', async () => {
    render(
      <MemoryRouter initialEntries={['/stocks/NSE_EQ|INE002A01018']}>
        <Routes>
          <Route path="/stocks/:key" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    // Click Pre-Open Auction History tab
    const preopenTab = await screen.findByText(/Pre-Open Auction History/i)
    fireEvent.click(preopenTab)

    // Verify preopen row
    expect(await screen.findByText('₹2750.50')).toBeInTheDocument()
    expect(screen.getByText(/55,000 BUY/i)).toBeInTheDocument()
    expect(screen.getByText('+1.12%')).toBeInTheDocument()
    expect(screen.getByText('YES')).toBeInTheDocument()
  })

  it('switches to Paper Trades tab and labels benchmark strategy', async () => {
    render(
      <MemoryRouter initialEntries={['/stocks/NSE_EQ|INE002A01018']}>
        <Routes>
          <Route path="/stocks/:key" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    // Click Paper Trades tab
    const paperTab = await screen.findByText(/Paper Trades & Execution/i)
    fireEvent.click(paperTab)

    // Verify paper trade row and benchmark label
    expect(await screen.findByText('bench_c0')).toBeInTheDocument()
    expect(screen.getByText('[Benchmark]')).toBeInTheDocument()
    expect(screen.getByText('₹2750.00')).toBeInTheDocument()
    expect(screen.getByText('+₹150.00')).toBeInTheDocument()
  })

  it('switches to Lifecycle & ISIN History tab', async () => {
    render(
      <MemoryRouter initialEntries={['/stocks/NSE_EQ|INE002A01018']}>
        <Routes>
          <Route path="/stocks/:key" element={<StockDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    // Click Lifecycle tab
    const lifecycleTab = await screen.findByText(/Lifecycle & ISIN History/i)
    fireEvent.click(lifecycleTab)

    // Verify lifecycle transitions table
    expect(await screen.findByText('INITIAL_INGEST')).toBeInTheDocument()
    expect(screen.getByText('Lifecycle State Transitions (instrument_lifecycle_period)')).toBeInTheDocument()
    expect(screen.getByText('Attribute Versions & ISIN Map (instrument_attribute_version)')).toBeInTheDocument()
  })
})
