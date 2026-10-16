import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { TopBar } from '../components/Layout/TopBar'
import { ThemeProvider } from '../context/ThemeContext'
import type { MarketStatusData } from '../types/api'

describe('TopBar Component', () => {
  const mockMarketState: MarketStatusData = {
    is_open: true,
    session_type: 'NORMAL',
    session_date: '2026-10-16',
    current_time_ist: '10:30:00 IST',
    session_open_ist: '09:15',
    session_close_ist: '15:30',
    message: 'Market Open (Regular Trading Session)',
  }

  it('renders branding, market state, and PAPER ONLY badge', () => {
    render(
      <ThemeProvider>
        <TopBar
          marketState={mockMarketState}
          wsStatus="CONNECTED"
          onOpenCommandPalette={vi.fn()}
          selectedKey="NSE_EQ|INE002A01018"
        />
      </ThemeProvider>
    )

    expect(screen.getByText('PRAJNA')).toBeInTheDocument()
    expect(screen.getByText('Market Open (Regular Trading Session)')).toBeInTheDocument()
    expect(screen.getByText('PAPER ONLY')).toBeInTheDocument()
    expect(screen.getByText('CONNECTED')).toBeInTheDocument()
  })

  it('renders command palette trigger', () => {
    const onOpen = vi.fn()
    render(
      <ThemeProvider>
        <TopBar
          marketState={mockMarketState}
          wsStatus="DISCONNECTED"
          onOpenCommandPalette={onOpen}
        />
      </ThemeProvider>
    )

    const searchButton = screen.getByText('Search stocks, stages...')
    expect(searchButton).toBeInTheDocument()
  })
})
