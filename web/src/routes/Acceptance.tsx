import { useAcceptance } from "../api/hooks";
import { StatusBadge } from "../components/badges";
import { DataTable } from "../components/DataTable";
import { Metric, MetricGrid, PageHead, Panel } from "../components/layout";
import { EmptyState, QueryState, TableSkeleton } from "../components/states";
import { fmtDateTimeIST } from "../lib/format";
import type { AcceptanceStage } from "../types/api";

function StageTable({ title, stage, id }: { title: string; stage: AcceptanceStage | null; id: string }) {
  if (!stage) return <Panel title={title} id={id}><EmptyState title="No gate report has been generated." /></Panel>;
  return (
    <Panel title={title} id={id} flush
      aside={<span className="inline"><StatusBadge status={stage.overall === "COMPLETE" ? "PASS" : stage.overall} title="overall" />
        {stage.overall ?? "—"}{stage.generated_at ? ` · checked ${fmtDateTimeIST(stage.generated_at)}` : ""}</span>}
      note="Statuses come from the acceptance gate report; this page never re-evaluates them. Evidence: docs/STAGE_1_FINAL_ACCEPTANCE.md, docs/STAGE_2_ACCEPTANCE.md.">
      {(stage.live_readiness || stage.waiting_for_evidence) && (
        <MetricGrid>
          {stage.live_readiness && <Metric label="Live readiness" value={<StatusBadge status={stage.live_readiness} />} />}
          {stage.waiting_for_evidence && <Metric label="Waiting for evidence" value={stage.waiting_for_evidence.join(" ") || "none"} />}
          {stage.deferred && <Metric label="Deferred" value={stage.deferred.join(" ") || "none"} />}
          {stage.failing && <Metric label="Failing / blocked" value={stage.failing.join(" ") || "none"} />}
        </MetricGrid>
      )}
      <DataTable rows={stage.criteria} rowKey={(c) => c.id} caption={title} columns={[
        { id: "id", header: "Criterion", sticky: true, sortValue: (c) => c.id, cell: (c) => <span className="mono">{c.id}</span> },
        { id: "name", header: "Name", cell: (c) => c.name ?? "—" },
        { id: "status", header: "Status", sortValue: (c) => c.status, cell: (c) => <StatusBadge status={c.status} /> },
      ]} />
    </Panel>
  );
}

export default function Acceptance() {
  const a = useAcceptance();
  return (
    <div className="page">
      <PageHead title="Acceptance status" subtitle="PASS · FAIL · BLOCKED · WAITING FOR EVIDENCE · DEFERRED · OUT OF SCOPE — as recorded by the gates." />
      <QueryState q={a} what="Acceptance status" skeleton={<TableSkeleton rows={12} cols={3} />}>
        {({ data: d }) => (
          <div className="stack">
            <StageTable title="Stage 1 — ingestion foundation" stage={d.stage1} id="s1" />
            <StageTable title="Stage 2 — canonical layer" stage={d.stage2} id="s2" />
            <Panel title="Stage 3" id="s3">
              <div className="lock" data-testid="stage3-lock">
                <div className="inline"><StatusBadge status={d.stage3.status} /> <strong>Stage 3 Locked</strong></div>
                <p style={{ margin: "var(--sp-4) 0 0" }}>{d.stage3.reason}</p>
                <p className="faint" style={{ margin: "var(--sp-3) 0 0" }}>This client shows no Stage 3 metrics or outputs.</p>
              </div>
            </Panel>
          </div>
        )}
      </QueryState>
    </div>
  );
}
