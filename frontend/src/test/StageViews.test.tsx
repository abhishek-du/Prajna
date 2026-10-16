import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Stage1View } from '../components/Stages/Stage1View'
import { Stage2View } from '../components/Stages/Stage2View'
import { Stage3View } from '../components/Stages/Stage3View'
import { api } from '../services/api'
import type {
  Stage1BackfillResponse,
  Stage1CoverageResponse,
  Stage2GateResponse,
  Stage3GateResponse,
  Stage3RegistryResponse,
  Stage3SnapshotsResponse,
} from '../types/api'

vi.mock('../services/api', () => ({
  api: {
    getStage1Coverage: vi.fn(),
    getStage1Backfill: vi.fn(),
    getStage2Gate: vi.fn(),
    getStage3Gate: vi.fn(),
    getStage3Registry: vi.fn(),
    getStage3Snapshots: vi.fn(),
  },
}))

describe('Stage 1, 2, 3 Deep-Dive Views', () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  it('renders Stage 1 Data Ingestion with coverage and backfill metrics', async () => {
    const mockCoverage: Stage1CoverageResponse = {
      timeframes: [
        {
          timeframe: '1d',
          target_start: '2020-01-01 (since 2020)',
          min_date: '2020-01-01',
          max_date: '2026-10-15',
          ranges_count: 93521,
          bars_count: 3710254,
          quarantined_bars: 2,
          data_ranges: 47423,
          empty_ranges: 46075,
          pending_ranges: 19,
        },
      ],
      total_coverage_ranges: 165809,
      total_bars: 29872214,
      excluded_bars_total: 109,
      excluded_reasons_breakdown: { 'no trading session on this date (WEEKEND)': 82 },
      recent_excluded_bars: [],
      corporate_actions_total: 2347,
      corporate_actions_by_type: { SPLIT: 450 },
      factors_total: 2346,
      factors_by_status: { VERIFIED: 2346 },
      master_instruments_active: 3576,
      master_instruments_removed: 21,
      master_sectors_breakdown: { Banking: 45 },
      recent_master_changes: [],
    }

    const mockBackfill: Stage1BackfillResponse = {
      supervisor_state: 'WAITING_CLOSE',
      free_gb: 141.0,
      stages: '1h,15m',
      process: 'none',
      last_status: 'time_limit_resumable',
      progress: [
        {
          timeframe: '1h',
          from_date: '2022-01-01',
          covered: 1295,
          total: 3581,
          pct: 36.16,
          rate_per_hour: 180.0,
          eta_hours: 12.7,
        },
      ],
      recent_progress_lines: [],
      recent_supervisor_lines: [],
    }

    vi.mocked(api.getStage1Coverage).mockResolvedValue(mockCoverage)
    vi.mocked(api.getStage1Backfill).mockResolvedValue(mockBackfill)

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Stage1View />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(await screen.findByText('Stage 1: Data Ingestion')).toBeInTheDocument()
    expect(screen.getByText(/1,65,809/)).toBeInTheDocument()
    expect(screen.getByText('29.87M')).toBeInTheDocument()
    expect(screen.getByText('WAITING_CLOSE')).toBeInTheDocument()

  })

  it('renders Stage 2 Gate with Criteria A–P and coverage matrix', async () => {
    const mockGate: Stage2GateResponse = {
      overall: 'PASS',
      generated_at: '2026-10-16T08:17:07Z',
      age_hours: 5.7,
      criteria: [
        {
          id: 'A',
          name: 'Stage 1 data read',
          question: 'Can Stage 2 process Stage 1 data?',
          status: 'PASS',
          notes: '',
          evidence: { coverage_ranges: 165809 },
          db_state: {},
        },
        {
          id: 'B',
          name: 'Data normalization',
          question: 'Is data normalized consistently?',
          status: 'PASS',
          notes: '',
          evidence: { duplicate_bars: 0 },
          db_state: {},
        },
      ],
      coverage_state_matrix: {
        '1d': { DATA: 47423, EMPTY: 46075 },
      },
      quarantined_total: 54,
    }

    vi.mocked(api.getStage2Gate).mockResolvedValue(mockGate)

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Stage2View />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(await screen.findByText('Stage 2: Processing and Storage')).toBeInTheDocument()
    expect(screen.getByText('OVERALL: PASS')).toBeInTheDocument()
    expect(screen.getByText('Can Stage 2 process Stage 1 data?')).toBeInTheDocument()
    expect(screen.getByText('Coverage State Matrix')).toBeInTheDocument()
  })

  it('renders Stage 3 Feature Engineering with 104-feature registry and refusal audit', async () => {
    const mockGate: Stage3GateResponse = {
      overall: 'PASS',
      generated_at: '2026-10-13T08:16:39Z',
      criteria: [
        {
          id: 'A',
          name: 'Feature registry',
          question: 'Every item of the Stage 3 diagram is registered',
          status: 'PASS',
          notes: '',
          evidence: { features: 104 },
          db_state: {},
        },
      ],
      refusal_audit: [
        {
          id: 80,
          at: '2026-10-16T10:59:31Z',
          event: 'RUN_COMPLETE',
          mode: 'BACKFILL',
          operator: 'cli',
          detail: { rows: 220939 },
          run_id: 'test-run-123',
        },
      ],
      refusal_count_today: 2,
      events_count_total: 80,
    }

    const mockRegistry: Stage3RegistryResponse = {
      version: 'features-v4',
      registry_sha256: '6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3',
      feature_count: 104,
      implemented_count: 104,
      proposed_parameters: 68,
      diagram_items: 31,
      diagram_items_by_status: { IMPLEMENTED: 19, PARTIAL: 6, UNSUPPORTED: 4, UNKNOWN: 2 },
      groups: {
        price_technical: ['ret_1d', 'ret_5d', 'sma_20'],
      },
      features: [
        {
          id: 'ret_1d',
          group: 'price_technical',
          definition: 'close / close 1 session earlier - 1',
          status: 'IMPLEMENTED',
          param_status: 'SPECIFIED',
          params: {},
          inputs: ['daily_bars'],
          lookback_sessions: 2,
          scope: 'INSTRUMENT',
          snapshots: ['PRE_SESSION', 'PRE_OPEN'],
          version: 1,
        },
      ],
    }

    const mockSnapshots: Stage3SnapshotsResponse = {
      session_date: '2026-10-16',
      snapshots_available: ['PRE_SESSION', 'PRE_OPEN'],
      distinct_instruments_count: 3563,
      total_values: 272731,
      total_nulls: 154895,
      null_reasons_breakdown: { MISSING_INPUT: 136584 },
      snapshot_details: {
        PRE_SESSION: {
          total_rows: 206687,
          values_count: 129879,
          nulls_count: 76808,
          instruments_count: 3563,
          completeness_pct: 62.84,
        },
        PRE_OPEN: {
          total_rows: 220939,
          values_count: 142852,
          nulls_count: 78087,
          instruments_count: 3563,
          completeness_pct: 64.66,
        },
      },
    }

    vi.mocked(api.getStage3Gate).mockResolvedValue(mockGate)
    vi.mocked(api.getStage3Registry).mockResolvedValue(mockRegistry)
    vi.mocked(api.getStage3Snapshots).mockResolvedValue(mockSnapshots)

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Stage3View />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(await screen.findByText('Stage 3: Feature Engineering')).toBeInTheDocument()
    expect(screen.getByText('COMPLETE & RUNNING DAILY')).toBeInTheDocument()
    expect(screen.getByText('ret_1d')).toBeInTheDocument()
    expect(screen.getByText('features-v4')).toBeInTheDocument()
  })
})
