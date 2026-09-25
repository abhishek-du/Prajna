import { useEffect, useState } from "react";
import { FRESHNESS, type FreshnessKind } from "../config/data";
import { ageSeconds, direction, fmtAge, fmtDateTimeIST, fmtSigned } from "../lib/format";

export type Tone = "positive" | "negative" | "warning" | "info" | "neutral" | "accent";

export function Badge({ tone, children, plain, title }: { tone: Tone; children: React.ReactNode; plain?: boolean; title?: string }) {
  return <span className={`badge tone-${tone}${plain ? " plain" : ""}`} title={title}>{children}</span>;
}

/** Status words from the backend mapped to tones; the text is always shown
 * (colour is never the only signal). */
const STATUS_TONE: Record<string, Tone> = {
  PASS: "positive", COMPLETE: "positive", CONFIRMED: "positive", CONFIRMED_BY_AGE: "positive",
  EXACT: "positive", ACTIVE: "positive", APPLIED: "info", DATA: "positive", FREE: "neutral",
  FAIL: "negative", FAILED: "negative", BLOCKED: "negative", REVISED: "negative", ABORTED: "negative",
  VENDOR_REJECTED: "negative", UNEXPLAINED: "negative",
  WAITING_FOR_EVIDENCE: "warning", UNCONFIRMED: "warning", UNCERTAIN: "warning", PLACEHOLDER: "warning",
  PENDING: "warning", RUNNING: "info", HELD: "info", UNKNOWN: "warning", NOT_APPLIED: "warning",
  DEFERRED: "neutral", OUT_OF_SCOPE: "neutral", UNSUPPORTED: "neutral", INELIGIBLE: "neutral",
  REMOVED_FROM_MASTER: "neutral", LOCKED: "accent", EMPTY: "neutral", MISSING: "warning",
  RAW_OBSERVED: "info", VENDOR_ADJUSTED: "warning", CA_ADJUSTMENT: "info", REOBSERVED: "neutral",
  GLOBAL_REVISION: "negative", ROUNDING: "neutral", SETTLEMENT: "neutral",
};

export function StatusBadge({ status, title }: { status: string | null | undefined; title?: string }) {
  if (!status) return <Badge tone="neutral" plain>—</Badge>;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"} title={title}>{status.replace(/_/g, " ")}</Badge>;
}

/** ▲/▼ + sign + colour: direction is never conveyed by colour alone. */
export function Change({ value, pct, unavailableReason }: { value: number | null; pct?: number | null; unavailableReason?: string | null }) {
  if (value === null || value === undefined) {
    return <span className="change flat" title={unavailableReason ?? undefined}>—{unavailableReason ? " *" : ""}</span>;
  }
  const d = direction(value);
  const arrow = d === "up" ? "▲" : d === "down" ? "▼" : "■";
  return (
    <span className={`change ${d}`}>
      <span aria-hidden="true">{arrow} </span>
      {fmtSigned(value)}
      {pct !== undefined && pct !== null && <> ({fmtSigned(pct, 2, "%")})</>}
      <span className="sr-only">{d === "up" ? " up" : d === "down" ? " down" : " unchanged"}</span>
    </span>
  );
}

/** Rerenders every 30 s so relative ages stay truthful without refetching. */
function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function freshnessOf(iso: string | null | undefined, kind: FreshnessKind, now = new Date()):
  { state: "fresh" | "aging" | "stale" | "unavailable"; age: number | null } {
  const age = ageSeconds(iso, now);
  if (age === null) return { state: "unavailable", age };
  const t = FRESHNESS[kind];
  return { state: age < t.fresh ? "fresh" : age > t.stale ? "stale" : "aging", age };
}

/** "Latest stored · 3.2 h ago", with the exact instant (IST) as a tooltip. */
export function FreshnessBadge({ at, kind, prefix }: { at: string | null | undefined; kind: FreshnessKind; prefix?: string }) {
  const now = useNow();
  const { state, age } = freshnessOf(at, kind, now);
  const tone: Tone = state === "fresh" ? "positive" : state === "aging" ? "info" : state === "stale" ? "warning" : "neutral";
  const text = state === "unavailable" ? "Unavailable" : state === "stale" ? `Stale · ${fmtAge(age)}` : `Updated ${fmtAge(age)}`;
  return (
    <Badge tone={tone} title={at ? `${fmtDateTimeIST(at)} — ${FRESHNESS[kind].note}` : "no timestamp"}>
      {prefix ? `${prefix} · ` : ""}{text}
    </Badge>
  );
}
