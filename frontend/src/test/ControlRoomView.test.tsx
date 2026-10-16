import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ControlRoomView } from '../components/ControlRoom/ControlRoomView'
import { api } from '../services/api'
import type { Envelope, StagesOverviewResponse } from '../types/api'

// Mock api service
vi.mock('../services/api', () => ({
  api: {
    getStagesEnvelope: vi.fn(),
  },
}))

describe('ControlRoomView Component', () => {
  const mockEnvelope: Envelope<StagesOverviewResponse> = {
    data: {
      stages: [
        {
          stage_number: 1,
          name: 'Data Ingestion',
          status: 'PASS',
          status_label: 'Live Ready',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Coverage Pairs',
          key_metric_value: '14,336 pairs',
          alert_count: 0,
          alerts: [],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
        {
          stage_number: 2,
          name: 'Storage & Quality',
          status: 'PASS',
          status_label: 'Criteria A–P',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Included Instruments',
          key_metric_value: '3,584 included',
          alert_count: 0,
          alerts: [],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
        {
          stage_number: 3,
          name: 'Feature Engineering',
          status: 'LOCKED',
          status_label: 'Strictly Locked',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Feature Registry',
          key_metric_value: '104 features',
          alert_count: 1,
          alerts: ['Snapshot refused'],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
        {
          stage_number: 4,
          name: 'Prediction Research',
          status: 'CALIBRATING',
          status_label: 'E4 Calibrating',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Experiments Ledger',
          key_metric_value: 'E1/E2 evaluated',
          alert_count: 0,
          alerts: [],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
        {
          stage_number: 5,
          name: 'Signals / Targets',
          status: 'ACTIVE',
          status_label: 'Daily TargetList',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Active Strategies',
          key_metric_value: '3 strategies',
          alert_count: 0,
          alerts: [],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
        {
          stage_number: 6,
          name: 'Risk Management',
          status: 'PASS',
          status_label: 'Limits Enforced',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Risk Decisions',
          key_metric_value: '1,579 Approved',
          alert_count: 0,
          alerts: [],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
        {
          stage_number: 7,
          name: 'Paper Execution',
          status: 'ACTIVE',
          status_label: 'Simulated Fills',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Fill Rate',
          key_metric_value: '98.5% fill rate',
          alert_count: 0,
          alerts: [],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
        {
          stage_number: 8,
          name: 'Monitoring & KPIs',
          status: 'ACTIVE',
          status_label: 'Equity Tracking',
          last_change: '2026-10-16T08:00:00Z',
          key_metric_label: 'Replayed Days',
          key_metric_value: '60 days',
          alert_count: 0,
          alerts: [],
          evidence_summary: {},
          as_of: '2026-10-16T08:00:00Z',
        },
      ],
      timeline: [
        {
          time_ist: '06:30',
          name: 'Daily Master Refresh',
          stage: 'Stage 1',
          status: 'DONE',
          detail: 'NSE Instrument Master synchronization',
          last_run_at: '2026-10-16T01:00:00Z',
        },
        {
          time_ist: '15:40',
          name: 'Paper Trading Execution',
          stage: 'Stages 5–7',
          status: 'PENDING',
          detail: 'Target generation, risk checks, simulated fills',
          last_run_at: null,
        },
      ],
      alerts: [
        {
          timestamp: '2026-10-16T04:00:00Z',
          source: 'supervisor',
          severity: 'ALERT',
          message: 'health_stage3_refused: Stage 3 snapshot refused today',
          stage: 3,
        },
      ],
      market_state: {
        is_open: true,
        session_type: 'NORMAL',
        session_date: '2026-10-16',
        current_time_ist: '10:30:00 IST',
        session_open_ist: '09:15',
        session_close_ist: '15:30',
        message: 'Market Open',
      },
    },
    meta: {
      as_of: '2026-10-16T08:00:00Z',
      generated_at: '2026-10-16T08:00:00Z',
      point_in_time: true,
      notes: ['Mock envelope'],
    },
  }

  it('renders all 8 stage cards with key metrics and statuses', async () => {
    vi.mocked(api.getStagesEnvelope).mockResolvedValue(mockEnvelope)

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ControlRoomView />
        </MemoryRouter>
      </QueryClientProvider>
    )

    // Check title
    expect(await screen.findByText('Prajna Control Room')).toBeInTheDocument()

    // Check stage cards
    expect(screen.getByText('Stage 1: Data Ingestion')).toBeInTheDocument()
    expect(screen.getByText('14,336 pairs')).toBeInTheDocument()

    expect(screen.getByText('Stage 3: Feature Engineering')).toBeInTheDocument()
    expect(screen.getByText('104 features')).toBeInTheDocument()

    expect(screen.getByText('Stage 7: Paper Execution')).toBeInTheDocument()
    expect(screen.getByText('98.5% fill rate')).toBeInTheDocument()

    // Check job timeline
    expect(screen.getByText("Today's Scheduled Job Timeline")).toBeInTheDocument()
    expect(screen.getByText('Daily Master Refresh')).toBeInTheDocument()

    // Check alert feed
    expect(screen.getByText(/health_stage3_refused/)).toBeInTheDocument()
  })
})
