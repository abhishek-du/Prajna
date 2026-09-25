/* Loading / empty / error / unavailable states. Every data component renders one. */
import type { CSSProperties, ReactNode } from "react";
import { ApiError } from "../api/http";
import { useSettings } from "../providers/settings";

export function Skeleton({ w = "100%", h = 14, style }: { w?: number | string; h?: number | string; style?: CSSProperties }) {
  return <span className="skeleton" aria-hidden="true" style={{ display: "block", width: w, height: h, ...style }} />;
}

/** Skeleton rows with the geometry of a table (no layout jump when data arrives). */
export function TableSkeleton({ rows = 8, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div role="status" aria-label="Loading" style={{ padding: "var(--sp-4) var(--sp-5)", display: "grid", gap: 10 }}>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 16 }}>
          {Array.from({ length: cols }, (_, c) => <Skeleton key={c} h={12} />)}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state" role="status">
      <strong>{title}</strong>
      {children && <span>{children}</span>}
    </div>
  );
}

/** The backend does not provide this. Names the missing capability; never a fake value. */
export function Unavailable({ what, capability }: { what: string; capability: string }) {
  return (
    <div className="state" role="note" data-testid="unavailable">
      <strong>Data unavailable — {what}</strong>
      <span className="cap">Missing backend capability: {capability}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry, what = "Data" }: { error: unknown; onRetry?: () => void; what?: string }) {
  const { settings } = useSettings();
  const message = error instanceof ApiError ? error.message : "Something went wrong while loading.";
  return (
    <div className="state error" role="alert">
      <strong>{what} could not be loaded.</strong>
      <span>{message}</span>
      {onRetry && <button type="button" className="btn" onClick={onRetry}>Retry</button>}
      {settings.developerMode && (
        <details>
          <summary>Technical details</summary>
          {error instanceof ApiError ? `${error.path}: ${error.detail}` : String(error)}
        </details>
      )}
    </div>
  );
}

interface QueryLike<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

/** Renders the right state for a query; children only get real data. */
export function QueryState<T>({ q, what, skeleton, empty, isEmpty, children }: {
  q: QueryLike<T>;
  what: string;
  skeleton?: ReactNode;
  empty?: ReactNode;
  isEmpty?: (d: T) => boolean;
  children: (d: T) => ReactNode;
}) {
  if (q.isPending) return <>{skeleton ?? <TableSkeleton rows={4} />}</>;
  if (q.isError || q.data === undefined) return <ErrorState error={q.error} what={what} onRetry={() => void q.refetch()} />;
  if (isEmpty?.(q.data)) return <>{empty ?? <EmptyState title="No data" />}</>;
  return <>{children(q.data)}</>;
}
