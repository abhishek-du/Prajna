import { Link } from "react-router";
import { useAcceptance, useFreshness, usePipeline } from "../api/hooks";
import { StatusBadge } from "../components/badges";
import { DataTable } from "../components/DataTable";
import { Metric, MetricGrid, PageHead, Panel } from "../components/layout";
import { QueryState, TableSkeleton } from "../components/states";
import { fmtDateTimeIST, fmtShortIST } from "../lib/format";
import type { FamilyStatus } from "../types/api";
import { DataHealthTable } from "./Overview";

export default function Operations() {
  const p = usePipeline();
  const f = useFreshness();
  const a = useAcceptance();
  return (
    <div className="page">
      <PageHead title="Operations" subtitle="Pipeline health. Credentials are never shown: the API reports only the access token's age."
        actions={<Link className="btn" to="/operations/acceptance">Acceptance status →</Link>} />
      <QueryState q={p} what="Pipeline status" skeleton={<TableSkeleton rows={3} cols={5} />}>
        {({ data: d }) => (
          <>
            <Panel title="System" id="ops-sys">
              <MetricGrid>
                <Metric label="Snapshot" value={fmtShortIST(d.at)} />
                <Metric label="Running runs" value={d.running.count} sub={d.running.oldest_age_hours !== null ? `oldest ${d.running.oldest_age_hours} h` : undefined} />
                <Metric label="Candles lock" value={<StatusBadge status={d.candles_lock} />} sub="HELD = a candle job runs" />
                <Metric label="Upstox token age" value={d.upstox_token?.age_hours !== undefined && d.upstox_token?.age_hours !== null ? `${d.upstox_token.age_hours} h` : "—"}
                  sub={d.upstox_token?.error ? `error: ${d.upstox_token.error}` : d.upstox_token?.note ?? "value never shown"} />
                <Metric label="Disk free" value={`${d.disk_free_gb} GB`} />
                <Metric label="Stage 1 / 2" value={a.data ? `${a.data.data.stage1?.overall ?? "—"} / ${a.data.data.stage2?.overall ?? "—"}` : "…"}
                  sub={a.data ? `Stage 3 ${a.data.data.stage3.status}` : undefined} />
              </MetricGrid>
            </Panel>
            <div className="grid grid-2">
              <Panel title="Jobs (last 24 h)" id="ops-jobs" flush>
                <DataTable rows={Object.entries(d.families).map(([name, s]) => ({ name, ...s }))} rowKey={(r) => r.name} caption="Job families"
                  columns={[
                    { id: "name", header: "Job family", sticky: true, sortValue: (r) => r.name, cell: (r) => <span className="mono">{r.name}</span> },
                    { id: "last", header: "Last", cell: (r: { name: string } & FamilyStatus) => <StatusBadge status={r.last_status} /> },
                    { id: "started", header: "Last started", sortValue: (r) => r.last_started, cell: (r) => <span className="mono faint">{fmtDateTimeIST(r.last_started)}</span> },
                    { id: "runs", header: "Runs", numeric: true, sortValue: (r) => r.runs_24h, cell: (r) => <span className="num">{r.runs_24h}</span> },
                    { id: "ok", header: "Complete", numeric: true, cell: (r) => <span className="num">{r.complete_24h}</span> },
                    { id: "fail", header: "Failed", numeric: true, sortValue: (r) => r.failed_24h,
                      cell: (r) => <span className="num" style={{ color: r.failed_24h ? "var(--negative)" : undefined }}>{r.failed_24h}</span> },
                    { id: "abort", header: "Aborted", numeric: true, cell: (r) => <span className="num">{r.aborted_24h}</span> },
                    { id: "running", header: "Running", numeric: true, cell: (r) => <span className="num">{r.running_now}</span> },
                  ]} />
              </Panel>
              <Panel title="Recent runbook markers" id="ops-markers" flush note="From the runbook logs (cron: close, global refresh, news poll, maintenance, timing monitor).">
                <ul style={{ margin: 0, padding: "var(--sp-4) var(--sp-5)", listStyle: "none", display: "grid", gap: 6, maxHeight: 420, overflow: "auto" }}>
                  {[...d.recent_markers].reverse().map((m, i) => <li key={i} className="mono" style={{ fontSize: "var(--fs-2xs)", overflowWrap: "anywhere" }}>{m}</li>)}
                </ul>
              </Panel>
            </div>
          </>
        )}
      </QueryState>
      <Panel title="Dataset freshness" id="ops-fresh" flush>
        <QueryState q={f} what="Freshness">{(d) => <DataHealthTable rows={d.data} />}</QueryState>
      </Panel>
    </div>
  );
}
