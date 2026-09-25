/* Formatting only: never computes or alters a financial value. */

const IST = "Asia/Kolkata";
const EM_DASH = "—";

const num = (digits: number) =>
  new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const nf2 = num(2);
const nf0 = num(0);

export function fmtPrice(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return EM_DASH;
  return digits === 2 ? nf2.format(v) : num(digits).format(v);
}

/** Volumes: Indian grouping; large values compacted as L (lakh) / Cr (crore). */
export function fmtVolume(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return EM_DASH;
  const a = Math.abs(v);
  if (a >= 1e7) return `${num(2).format(v / 1e7)} Cr`;
  if (a >= 1e5) return `${num(2).format(v / 1e5)} L`;
  return nf0.format(v);
}

export function fmtSigned(v: number | null | undefined, digits = 2, suffix = ""): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return EM_DASH;
  const s = num(digits).format(Math.abs(v));
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}${suffix}`;
}

export function direction(v: number | null | undefined): "up" | "down" | "flat" {
  if (v === null || v === undefined || v === 0 || !Number.isFinite(v)) return "flat";
  return v > 0 ? "up" : "down";
}

const dtf = new Intl.DateTimeFormat("en-IN", {
  timeZone: IST, day: "2-digit", month: "short", year: "numeric",
  hour: "2-digit", minute: "2-digit", hour12: false,
});
const tf = new Intl.DateTimeFormat("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const df = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" });

/** An instant, shown in IST. */
export function fmtDateTimeIST(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? EM_DASH : `${dtf.format(d)} IST`;
}

const sdf = new Intl.DateTimeFormat("en-IN", { timeZone: IST, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });

/** Compact instant: "25 Sept, 21:13 IST". */
export function fmtShortIST(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? EM_DASH : `${sdf.format(d)} IST`;
}

export function fmtTimeIST(d: Date): string {
  return `${tf.format(d)} IST`;
}

/** A market date (YYYY-MM-DD) is a calendar label, not an instant: no timezone shift. */
export function fmtDate(isoDate: string | null | undefined): string {
  if (!isoDate) return EM_DASH;
  const d = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? EM_DASH : df.format(d);
}

export function ageSeconds(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : Math.max(0, (now.getTime() - t) / 1000);
}

export function fmtAge(seconds: number | null): string {
  if (seconds === null) return EM_DASH;
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 48 * 3600) return `${(seconds / 3600).toFixed(1)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function fmtDuration(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return EM_DASH;
  if (s < 0) return "before publication";
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 48 * 3600) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} d`;
}

/** Latency between two instants (e.g. published -> received), human-readable. */
export function fmtLatency(fromIso: string | null, toIso: string | null): string {
  if (!fromIso || !toIso) return EM_DASH;
  return fmtDuration((new Date(toIso).getTime() - new Date(fromIso).getTime()) / 1000);
}

export const humanize = (s: string | null | undefined): string =>
  s ? s.replace(/_/g, " ").replace(/:/g, " · ").toLowerCase().replace(/^./, (c) => c.toUpperCase()) : EM_DASH;

export { EM_DASH };
