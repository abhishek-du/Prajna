import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import { Sidebar } from '../components/Layout/Sidebar'

describe('Sidebar Component', () => {
  it('renders all 8 stage links and their numbers', () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    )

    // Check all 8 stages are listed
    expect(screen.getByText('1. Data Ingestion')).toBeInTheDocument()
    expect(screen.getByText('2. Storage & Quality')).toBeInTheDocument()
    expect(screen.getByText('3. Feature Engineering')).toBeInTheDocument()
    expect(screen.getByText('4. Prediction Research')).toBeInTheDocument()
    expect(screen.getByText('5. Signals / Targets')).toBeInTheDocument()
    expect(screen.getByText('6. Risk Management')).toBeInTheDocument()
    expect(screen.getByText('7. Paper Execution')).toBeInTheDocument()
    expect(screen.getByText('8. Monitoring & KPIs')).toBeInTheDocument()
  })

  it('shows each stage status from the API, never a constant', () => {
    const st = (n: number, status: string) => ({ stage_number: n, name: '', status,
      status_label: '', last_change: null, key_metric_label: '', key_metric_value: '',
      alert_count: 0, alerts: [], evidence_summary: {}, as_of: null })
    render(
      <MemoryRouter>
        <Sidebar stages={[st(3, 'COMPLETE'), st(4, 'CALIBRATING')]} />
      </MemoryRouter>
    )
    expect(screen.getByTestId('stage-badge-3')).toHaveTextContent('COMPLETE')
    expect(screen.getByTestId('stage-badge-4')).toHaveTextContent('CALIBRATING')
    expect(screen.getByTestId('stage-badge-1')).toHaveTextContent('…')   // not loaded yet
    expect(screen.queryByText(/LOCKED/)).toBeNull()
    expect(screen.getByText('Control Room')).toBeInTheDocument()
  })

  it('renders compliance warning in footer', () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    )

    expect(screen.getByText('PAPER SIMULATION ONLY')).toBeInTheDocument()
    expect(screen.getByText(/No broker orders or profitability claims/)).toBeInTheDocument()
  })
})
