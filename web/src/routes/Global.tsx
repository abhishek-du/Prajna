import { useState } from "react";
import { useGlobalFinality } from "../api/hooks";
import { StatusBadge } from "../components/badges";
import { DataTable } from "../components/DataTable";
import { globalColumns, useGlobalBoard } from "../components/global";
import { PageHead, Panel } from "../components/layout";
import { QueryState, TableSkeleton } from "../components/states";
import { fmtDate, fmtDateTimeIST, fmtPrice } from "../lib/format";

const WITHHELD_TEXT: Record<string, string> = {
  REVISED: "Bar withheld — later vendor revision detected.",
  PLACEHOLDER: "Withheld — flat repeat of the previous close with no volume (vendor placeholder).",
  UNCONFIRMED: "Withheld — first observation not yet confirmed by a later unchanged re-observation.",
};

function FinalityHistory({ instrumentKey, name }: { instrumentKey: string; name: string }) {
  const f = useGlobalFinality(instrumentKey, 20);
  return (
    <Panel title={`Label history · ${name}`} id="finality" flush
      note="Every recent vendor label with its finality. Withheld labels carry no values: they are never presented as confirmed data.">
      <QueryState q={f} what="Finality history" skeleton={<TableSkeleton rows={8} cols={4} />}>
        {(d) => (
          <DataTable rows={d.data} rowKey={(r) => r.label_date} caption="Label finality" columns={[
            { id: "label", header: "Vendor label", sticky: true, cell: (r) => <span className="mono">{fmtDate(r.label_date)}</span> },
            { id: "finality", header: "Finality", cell: (r) => <StatusBadge status={r.finality} /> },
            { id: "close", header: "Close", numeric: true,
              cell: (r) => r.exposed ? <span className="num">{fmtPrice(r.close)}</span> : <span className="faint">WITHHELD</span> },
            { id: "why", header: "Detail", cell: (r) => r.exposed
              ? <span className="faint">confirmed {fmtDateTimeIST(r.confirmed_at ?? r.first_fetched_at)}</span>
              : <span className="muted">{WITHHELD_TEXT[r.finality] ?? "Withheld"}{r.revised_at ? ` (revised ${fmtDateTimeIST(r.revised_at)})` : ""}</span> },
          ]} />
        )}
      </QueryState>
    </Panel>
  );
}

export default function Global() {
  const { list, rows, loadingBars } = useGlobalBoard();
  const [sel, setSel] = useState<string | null>(null);
  const selected = rows.find((r) => r.inst.instrument_key === sel) ?? rows[0] ?? null;
  const regions = [...new Set(rows.map((r) => r.region))].sort();
  return (
    <div className="page">
      <PageHead title="Global markets"
        subtitle="Vendor labels are not necessarily trading dates (some instruments label sessions on a shifted calendar). Only confirmed labels are shown as data." />
      <div className="grid grid-main-side">
        <div className="stack">
          {list.isPending || loadingBars ? <Panel title="Global markets" id="g"><TableSkeleton rows={10} cols={7} /></Panel> :
            <QueryState q={list} what="Global markets">
              {() => (
                <>
                  {regions.map((region) => (
                    <Panel key={region} title={region} id={`g-${region}`} flush>
                      <DataTable rows={rows.filter((r) => r.region === region)} columns={globalColumns()}
                        rowKey={(r) => r.inst.instrument_key} caption={`${region} global instruments`}
                        onRowActivate={(r) => setSel(r.inst.instrument_key)} />
                    </Panel>
                  ))}
                </>
              )}
            </QueryState>}
        </div>
        <div className="stack">
          {selected && <FinalityHistory instrumentKey={selected.inst.instrument_key} name={selected.inst.name ?? selected.inst.instrument_key} />}
          <Panel title="Finality states" id="g-help">
            <dl className="kv" style={{ fontSize: "var(--fs-xs)" }}>
              <dt><StatusBadge status="CONFIRMED" /></dt><dd className="muted">re-observed unchanged ≥ confirm window after the first fetch; known from the confirmation</dd>
              <dt><StatusBadge status="CONFIRMED_BY_AGE" /></dt><dd className="muted">first fetched ≥ 4 days after the label</dd>
              <dt><StatusBadge status="UNCONFIRMED" /></dt><dd className="muted">withheld until confirmed</dd>
              <dt><StatusBadge status="REVISED" /></dt><dd className="muted">a later fetch returned different values — never exposed</dd>
              <dt><StatusBadge status="PLACEHOLDER" /></dt><dd className="muted">flat repeat with no volume — never exposed</dd>
            </dl>
          </Panel>
        </div>
      </div>
    </div>
  );
}
