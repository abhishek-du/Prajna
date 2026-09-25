import { useQueries } from "@tanstack/react-query";
import { globalApi } from "../api/clients";
import { useGlobal } from "../api/hooks";
import { GLOBAL_REGIONS } from "../config/data";
import { fmtDate, fmtDateTimeIST, fmtPrice } from "../lib/format";
import type { GlobalBar, GlobalInstrument } from "../types/api";
import { Change, FreshnessBadge, StatusBadge } from "./badges";
import { DataTable, type Column } from "./DataTable";
import { QueryState, TableSkeleton } from "./states";

export interface GlobalRow {
  inst: GlobalInstrument;
  region: string;
  last: GlobalBar | null;
  prev: GlobalBar | null;
}

/** The latest two CONFIRMED labels per instrument; change only between them. */
export function useGlobalBoard() {
  const list = useGlobal();
  const insts = list.data?.data ?? [];
  const bars = useQueries({
    queries: insts.map((g) => ({
      queryKey: ["global-candles", g.instrument_key, 2],
      queryFn: ({ signal }: { signal: AbortSignal }) => globalApi.candles(g.instrument_key, 2, signal),
      staleTime: 60_000,
    })),
  });
  const rows: GlobalRow[] = insts.map((g, i) => {
    const b = bars[i]?.data?.data ?? [];
    return { inst: g, region: GLOBAL_REGIONS[g.instrument_key] ?? "Other",
      last: b.at(-1) ?? null, prev: b.length > 1 ? (b.at(-2) ?? null) : null };
  });
  return { list, rows, loadingBars: bars.some((b) => b.isPending) };
}

const shortSemantics = (s: string | null) =>
  !s ? "—" : s.startsWith("labels include weekend") ? "shifted calendar: label ≠ trading date" : "weekday labels";

export function globalColumns(): Column<GlobalRow>[] {
  return [
    { id: "name", header: "Instrument", sticky: true, sortValue: (r) => r.inst.name ?? r.inst.instrument_key,
      cell: (r) => <span><span className="symbol">{r.inst.instrument_key.split("|")[1]}</span> <span className="muted">{r.inst.name}</span></span> },
    { id: "region", header: "Region", sortValue: (r) => r.region, cell: (r) => r.region },
    { id: "label", header: "Vendor label", sortValue: (r) => r.last?.label_date ?? null,
      title: "the vendor's date label — not necessarily the instrument's trading date",
      cell: (r) => <span className="mono">{r.last ? fmtDate(r.last.label_date) : "—"}</span> },
    { id: "close", header: "Close", numeric: true, sortValue: (r) => r.last?.close ?? null,
      cell: (r) => <span className="num">{fmtPrice(r.last?.close)}</span> },
    { id: "change", header: "Change", numeric: true,
      sortValue: (r) => (r.last && r.prev ? (r.last.close - r.prev.close) / r.prev.close : null),
      title: "between the two latest confirmed labels",
      cell: (r) => r.last && r.prev
        ? <Change value={r.last.close - r.prev.close} pct={((r.last.close - r.prev.close) / r.prev.close) * 100} />
        : <span className="faint">—</span> },
    { id: "finality", header: "Finality", cell: (r) => <StatusBadge status={r.last?.finality ?? null} /> },
    { id: "known", header: "Known", cell: (r) => <FreshnessBadge at={r.last?.knowable_at} kind="global" /> },
    { id: "semantics", header: "Label semantics", hiddenByDefault: false,
      title: "measured per instrument (global_instrument_contract)",
      cell: (r) => <span className="faint" title={r.inst.label_semantics ?? undefined}>{shortSemantics(r.inst.label_semantics)}</span> },
    { id: "confirmed_at", header: "First fetched", hiddenByDefault: true,
      cell: (r) => <span className="mono faint">{fmtDateTimeIST(r.last?.first_fetched_at)}</span> },
  ];
}

export function GlobalTable({ compact = false }: { compact?: boolean }) {
  const { list, rows, loadingBars } = useGlobalBoard();
  const cols = globalColumns().filter((c) => !compact || ["name", "label", "close", "change", "finality"].includes(c.id));
  return (
    <QueryState q={list} what="Global markets" skeleton={<TableSkeleton rows={8} cols={5} />}
      isEmpty={(d) => d.data.length === 0}>
      {() => (loadingBars ? <TableSkeleton rows={8} cols={5} /> :
        <DataTable rows={[...rows].sort((a, b) => a.region.localeCompare(b.region))} columns={cols}
          rowKey={(r) => r.inst.instrument_key} caption="Global markets (confirmed labels only)" />)}
    </QueryState>
  );
}
