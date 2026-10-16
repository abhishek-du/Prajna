import type { BackfillTimeframeProgress } from '../types/api'

/** "Running" comes from the supervisor state only, never from the rate: a fresh run has
 *  no completed instrument yet (2026-10-16: the panel said "not running" while it ran). */
export function isBackfillRunning(state: string | null | undefined): boolean {
  return state === 'RUNNING' || state === 'STARTED'
}

export function backfillRateText(p: BackfillTimeframeProgress, state?: string | null): string {
  if (p.total > 0 && p.covered >= p.total) return 'complete'
  const running = isBackfillRunning(state)
  if (p.rate_per_hour && p.rate_per_hour > 0) {
    return `~${p.rate_per_hour} instruments/hr (last hour, ${p.runs_last_hour ?? '?'} runs)`
  }
  if (running && (p.runs_last_hour ?? 0) > 0) return `running — ${p.runs_last_hour} runs in the last hour, no instrument finished yet`
  if (running) return 'running — measuring (no completed run in the last hour)'
  return `— (${state ? state.toLowerCase().replace(/_/g, ' ') : 'state unknown'})`
}

export function backfillEtaText(p: BackfillTimeframeProgress, state?: string | null): string {
  if (p.total > 0 && p.covered >= p.total) return 'done'
  if (p.eta_hours !== null && p.eta_hours !== undefined) return `~${p.eta_hours} h at the last hour's pace`
  if (isBackfillRunning(state)) return 'not measurable yet'
  return `— (${state ? state.toLowerCase().replace(/_/g, ' ') : 'state unknown'})`
}
