import { useQueries } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { globalApi } from "../api/clients";
import { useCorporateActions, useFreshness, useGlobal, useQuality, useSearch } from "../api/hooks";
import { StatusBadge } from "../components/badges";
import { DataTable } from "../components/DataTable";
import { CorporateActionTable } from "../components/fundamentals";
import { PageHead, Panel } from "../components/layout";
import { DataQualityPanel } from "../components/quality";
import { EmptyState, QueryState, TableSkeleton } from "../components/states";
import { DataHealthTable } from "./Overview";

function GlobalFinalitySummary() {
  const g = useGlobal();
  const keys = (g.data?.data ?? []).map((x) => x.instrument_key);
  const fin = useQueries({ queries: keys.map((k) => ({ queryKey: ["global-finality", k, 10],
    queryFn: ({ signal }: { signal: AbortSignal }) => globalApi.finality(k, 10, signal), staleTime: 30_000 })) });
  const rows = keys.map((k, i) => {
    const labels = fin[i]?.data?.data ?? [];
    const count = (s: string) => labels.filter((l) => l.finality === s).length;
    return { key: k, confirmed: count("CONFIRMED") + count("CONFIRMED_BY_AGE"), unconfirmed: count("UNCONFIRMED"),
      revised: count("REVISED"), placeholder: count("PLACEHOLDER"), loading: fin[i]?.isPending ?? true };
  });
  return (
    <Panel title="Global finality (last 10 labels per instrument)" id="dq-global" flush
      note="Revised and placeholder labels are withheld from all data views; unconfirmed labels wait for a confirming re-observation.">
      <QueryState q={g} what="Global instruments" skeleton={<TableSkeleton rows={8} cols={5} />}>
        {() => (
          <DataTable rows={rows} rowKey={(r) => r.key} caption="Global finality summary" columns={[
            { id: "key", header: "Instrument", sticky: true, cell: (r) => <span className="symbol">{r.key.split("|")[1]}</span> },
            { id: "c", header: "Confirmed", numeric: true, sortValue: (r) => r.confirmed, cell: (r) => <span className="num">{r.loading ? "…" : r.confirmed}</span> },
            { id: "u", header: "Unconfirmed", numeric: true, sortValue: (r) => r.unconfirmed, cell: (r) => <span className="num">{r.loading ? "…" : r.unconfirmed}</span> },
            { id: "r", header: "Revised", numeric: true, sortValue: (r) => r.revised,
              cell: (r) => r.revised > 0 ? <StatusBadge status="REVISED" title={`${r.revised} withheld`} /> : <span className="num">{r.loading ? "…" : 0}</span> },
            { id: "p", header: "Placeholder", numeric: true, sortValue: (r) => r.placeholder, cell: (r) => <span className="num">{r.loading ? "…" : r.placeholder}</span> },
          ]} />
        )}
      </QueryState>
    </Panel>
  );
}

function InstrumentDiagnostics() {
  const [sp, setSp] = useSearchParams();
  const symbol = sp.get("symbol") ?? "CHAVDA";
  const [text, setText] = useState(symbol);
  const hit = useSearch(symbol);
  const key = hit.data?.data.find((h) => h.trading_symbol.toUpperCase() === symbol.toUpperCase())?.instrument_key ?? null;
  const q = useQuality(key);
  const ca = useCorporateActions(key);
  return (
    <div className="stack">
      <Panel title="Instrument diagnostics" id="dq-inst"
        aside={<form className="inline" onSubmit={(e) => { e.preventDefault(); setSp({ symbol: text.trim().toUpperCase() }, { replace: true }); }}>
          <input className="input" aria-label="Symbol" value={text} onChange={(e) => setText(e.target.value)} style={{ width: 140 }} />
          <button type="submit" className="btn">Inspect</button>
        </form>}>
        {hit.isPending ? <TableSkeleton rows={2} cols={3} /> : !key ? (
          <EmptyState title={`No instrument with the symbol “${symbol}”.`} />
        ) : (
          <span className="inline">
            <span className="symbol">{symbol}</span>
            <span className="mono faint">{key}</span>
            <Link to={`/stocks/${encodeURIComponent(key)}?tab=chart`}>Open chart →</Link>
          </span>
        )}
      </Panel>
      {key && (
        <>
          <QueryState q={q} what="Diagnostics">{(d) => <DataQualityPanel q={d.data} />}</QueryState>
          <Panel title="Corporate actions and their treatment" id="dq-ca" flush>
            <QueryState q={ca} what="Corporate actions">{(d) => <CorporateActionTable rows={d.data} />}</QueryState>
          </Panel>
        </>
      )}
    </div>
  );
}

export default function DataQuality() {
  const f = useFreshness();
  return (
    <div className="page">
      <PageHead title="Data quality" subtitle="Price basis, corporate-action treatment, vendor revisions, global finality, freshness and coverage — the evidence behind every number." />
      <div className="grid grid-2">
        <Panel title="Freshness by dataset" id="dq-fresh" flush>
          <QueryState q={f} what="Freshness">{(d) => <DataHealthTable rows={d.data} />}</QueryState>
        </Panel>
        <GlobalFinalitySummary />
      </div>
      <InstrumentDiagnostics />
    </div>
  );
}
