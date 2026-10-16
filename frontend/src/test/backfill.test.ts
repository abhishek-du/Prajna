import { describe, expect, it } from 'vitest'
import { backfillEtaText, backfillRateText } from '../utils/backfill'

const p = { timeframe: '1h', from_date: '2022-01-01', covered: 1500, total: 3584, pct: 41.85,
  rate_per_hour: null, eta_hours: null, runs_last_hour: 0 }

describe('backfill progress text', () => {
  it('never says idle or not running while the supervisor runs', () => {
    for (const s of ['RUNNING', 'STARTED']) {
      expect(backfillRateText(p, s)).not.toMatch(/idle|not running/)
      expect(backfillEtaText(p, s)).not.toMatch(/idle|not running/)
    }
    expect(backfillRateText({ ...p, runs_last_hour: 120 }, 'RUNNING')).toMatch(/120 runs/)
  })
  it('names the supervisor state when it is not running', () => {
    expect(backfillRateText(p, 'WAITING_CLOSE')).toBe('— (waiting close)')
    expect(backfillEtaText(p, undefined)).toBe('— (state unknown)')
  })
  it('reports the measured pace and done', () => {
    expect(backfillRateText({ ...p, rate_per_hour: 101, runs_last_hour: 1952 }, 'RUNNING')).toMatch(/~101/)
    expect(backfillEtaText({ ...p, eta_hours: 19.7 }, 'RUNNING')).toMatch(/19.7/)
    expect(backfillEtaText({ ...p, covered: 3584 }, 'DONE')).toBe('done')
  })
})
