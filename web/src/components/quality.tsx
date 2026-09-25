import { Fragment } from "react";
import type { Quality } from "../types/api";
import { fmtDate } from "../lib/format";
import { StatusBadge } from "./badges";
import { DataTable } from "./DataTable";
import { Metric, MetricGrid, Panel } from "./layout";
import { EmptyState } from "./states";

const OBS_HELP: Record<string, string> = {
  CA_ADJUSTMENT: "a later vendor observation equals the stored bar divided by a recorded split/bonus factor",
  ROUNDING: "within one tick",
  SETTLEMENT: "last bar of the session adjusted after the close",
  GLOBAL_REVISION: "a global label changed after first observation (withheld)",
  REOBSERVED: "an identical re-observation (confirms finality)",
  UNEXPLAINED: "no rule explains it: the ingestion failed closed",
};

/** Per-instrument diagnostics. Current state (not point-in-time). */
export function DataQualityPanel({ q }: { q: Quality }) {
  const cov = Object.entries(q.coverage).flatMap(([tf, rows]) => rows.map((r, i) => ({ ...r, tf, id: `${tf}-${i}` })));
  const obs = Object.entries(q.observations);
  const basis = Object.entries(q.price_basis);
  return (
    <div className="grid grid-main-side">
      <Panel title="Coverage by timeframe" id="dq-cov" flush note="DATA = bars stored; EMPTY = the vendor returned no bars; other states are gaps with their cause.">
        {cov.length === 0 ? <EmptyState title="No coverage ranges recorded." /> : (
          <DataTable rows={cov} rowKey={(r) => r.id} caption="Coverage ranges" columns={[
            { id: "tf", header: "TF", sticky: true, sortValue: (r) => r.tf, cell: (r) => <span className="mono">{r.tf}</span> },
            { id: "state", header: "State", sortValue: (r) => r.state, cell: (r) => <StatusBadge status={r.state} /> },
            { id: "from", header: "From", sortValue: (r) => r.from_date, cell: (r) => <span className="mono">{fmtDate(r.from_date)}</span> },
            { id: "to", header: "To", cell: (r) => <span className="mono">{fmtDate(r.to_date)}</span> },
            { id: "sessions", header: "Sessions", numeric: true, cell: (r) => <span className="num">{r.sessions}</span> },
            { id: "bars", header: "Bars", numeric: true, cell: (r) => <span className="num">{r.bars}</span> },
            { id: "q", header: "Quarantined", numeric: true, cell: (r) => <span className="num">{r.quarantined}</span> },
          ]} />
        )}
      </Panel>
      <div className="stack">
        <Panel title="Price basis of stored bars" id="dq-basis">
          {basis.length === 0 ? <EmptyState title="No bars." /> : (
            <MetricGrid>{basis.map(([k, n]) => <Metric key={k} label={k.replace(/_/g, " ")} value={n.toLocaleString("en-IN")} sub="bars" />)}</MetricGrid>
          )}
          <p className="faint" style={{ fontSize: "var(--fs-xs)", margin: "var(--sp-4) 0 0" }}>
            RAW OBSERVED: as traded (intraday endpoint). VENDOR ADJUSTED: history as the vendor served it on its fetch date, already adjusted for earlier corporate actions.
          </p>
        </Panel>
        <Panel title="Vendor revisions (append-only observations)" id="dq-obs">
          {obs.length === 0 ? <EmptyState title="No later vendor observation differed from the stored bars." /> : (
            <dl className="kv">{obs.map(([k, n]) => (<Fragment key={k}><dt><StatusBadge status={k} /></dt><dd>{n} · <span className="faint">{OBS_HELP[k] ?? ""}</span></dd></Fragment>))}</dl>
          )}
        </Panel>
        <Panel title="Quarantine & provenance" id="dq-prov">
          <dl className="kv">
            <dt>Quarantined bars</dt><dd className="mono">{q.quarantined_bars}</dd>
            {Object.entries(q.provenance).map(([k, v]) => (<Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd className="muted">{String(v)}</dd></Fragment>))}
          </dl>
        </Panel>
      </div>
    </div>
  );
}
