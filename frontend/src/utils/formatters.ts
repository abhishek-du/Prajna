/**
 * Indian Market Number, Currency, and Date Formatters.
 * Adheres strictly to Point-in-time honesty: null is '—' with reason, never 0 or invented.
 */

export function formatCurrencyINR(
  val: number | null | undefined,
  options?: { decimals?: number; showSymbol?: boolean }
): string {
  if (val === null || val === undefined || isNaN(val)) return '—'
  const decimals = options?.decimals ?? 2
  const showSymbol = options?.showSymbol ?? true

  const formatted = new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(val)

  return showSymbol ? `₹${formatted}` : formatted
}

export function formatCompactINR(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return '—'
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''

  if (abs >= 1_00_00_000) {
    return `${sign}₹${(abs / 1_00_00_000).toFixed(2)} Cr`
  }
  if (abs >= 1_00_000) {
    return `${sign}₹${(abs / 1_00_000).toFixed(2)} L`
  }
  if (abs >= 1_000) {
    return `${sign}₹${(abs / 1_000).toFixed(1)} K`
  }
  return `${sign}₹${abs.toFixed(2)}`
}

export function formatNumberIndian(
  val: number | null | undefined,
  decimals: number = 0
): string {
  if (val === null || val === undefined || isNaN(val)) return '—'
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(val)
}

export function formatDateTimeIST(val: string | Date | null | undefined): string {
  if (!val) return '—'
  try {
    const d = typeof val === 'string' ? new Date(val) : val
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }) + ' IST'
  } catch {
    return '—'
  }
}

export function formatTimeIST(val: string | Date | null | undefined): string {
  if (!val) return '—'
  try {
    const d = typeof val === 'string' ? new Date(val) : val
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }) + ' IST'
  } catch {
    return '—'
  }
}

export function formatDateIST(val: string | Date | null | undefined): string {
  if (!val) return '—'
  try {
    const d = typeof val === 'string' ? new Date(val) : val
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleDateString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return '—'
  }
}

export function isDataStale(asOf: string | Date | null | undefined, maxAgeSeconds: number = 180): boolean {
  if (!asOf) return true
  try {
    const dt = typeof asOf === 'string' ? new Date(asOf) : asOf
    const ageSeconds = (Date.now() - dt.getTime()) / 1000
    return ageSeconds > maxAgeSeconds
  } catch {
    return true
  }
}
