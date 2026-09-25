import { useNavigate } from "react-router";
import { fmtDate, fmtPrice, fmtVolume } from "../lib/format";
import type { Instrument, LatestPrice } from "../types/api";
import { Change, FreshnessBadge, StatusBadge } from "./badges";
import { DataTable, type Column } from "./DataTable";

export type PricedRow = Instrument & { price: LatestPrice | null };

export function joinPrices(instruments: Instrument[], prices: LatestPrice[] | undefined): PricedRow[] {
  const m = new Map((prices ?? []).map((p) => [p.instrument_key, p]));
  return instruments.map((i) => ({ ...i, price: m.get(i.instrument_key) ?? null }));
}

/** Daily-close columns (from /v1/latest): the latest stored session, never "live". */
export function priceColumns<T extends { price: LatestPrice | null }>(): Column<T>[] {
  return [
    { id: "close", header: "Close (1D)", numeric: true, sortValue: (r) => r.price?.close ?? null,
      title: "latest stored daily close", cell: (r) => <span className="num">{fmtPrice(r.price?.close)}</span> },
    { id: "change", header: "Change", numeric: true, sortValue: (r) => r.price?.change ?? null,
      title: "vs the previous session; withheld across a split/bonus or basis change",
      cell: (r) => r.price ? <Change value={r.price.change} unavailableReason={r.price.comparable_reason} /> : "—" },
    { id: "change_pct", header: "Chg %", numeric: true, sortValue: (r) => r.price?.change_pct ?? null,
      cell: (r) => r.price?.change_pct !== null && r.price?.change_pct !== undefined
        ? <span className={`change ${r.price.change_pct > 0 ? "up" : r.price.change_pct < 0 ? "down" : "flat"}`}>
            {r.price.change_pct > 0 ? "▲ +" : r.price.change_pct < 0 ? "▼ " : ""}{r.price.change_pct.toFixed(2)}%</span>
        : <span className="faint" title={r.price?.comparable_reason ?? undefined}>—</span> },
    { id: "volume", header: "Volume", numeric: true, sortValue: (r) => r.price?.volume ?? null,
      cell: (r) => <span className="num">{fmtVolume(r.price?.volume)}</span> },
    { id: "session", header: "Session", sortValue: (r) => r.price?.market_date ?? null,
      cell: (r) => <span className="mono faint">{r.price ? fmtDate(r.price.market_date) : "—"}</span> },
    { id: "freshness", header: "Freshness", cell: (r) => <FreshnessBadge at={r.price?.knowable_at} kind="daily" /> },
    { id: "basis", header: "Basis", hiddenByDefault: true, sortValue: (r) => r.price?.price_basis ?? null,
      cell: (r) => <StatusBadge status={r.price?.price_basis ?? null} /> },
  ];
}

export function instrumentColumns<T extends Instrument>(): Column<T>[] {
  return [
    { id: "symbol", header: "Symbol", sticky: true, sortValue: (r) => r.trading_symbol,
      cell: (r) => <span className="symbol">{r.trading_symbol}</span> },
    { id: "name", header: "Company", sortValue: (r) => r.name ?? null, cell: (r) => r.name ?? "—" },
    { id: "sector", header: "Sector", sortValue: (r) => r.sector ?? null,
      title: "current sector (latest vendor profile)",
      cell: (r) => r.sector ?? <span className="faint">{r.segment === "NSE_INDEX" ? "—" : "unclassified"}</span> },
    { id: "class", header: "Class", hiddenByDefault: true, sortValue: (r) => r.security_class ?? null,
      cell: (r) => <span className="mono faint">{r.security_class ?? "—"}</span> },
    { id: "segment", header: "Segment", hiddenByDefault: true, cell: (r) => <span className="mono faint">{r.segment}</span> },
    { id: "lifecycle", header: "Listing", hiddenByDefault: true, sortValue: (r) => r.lifecycle_status ?? null,
      cell: (r) => <StatusBadge status={r.lifecycle_status} /> },
  ];
}

export function PricedInstrumentTable({ rows, caption, toolbar, extraColumns = [], columnsState }: {
  rows: PricedRow[];
  caption: string;
  toolbar?: React.ReactNode;
  extraColumns?: Column<PricedRow>[];
  columnsState?: [string[], (ids: string[]) => void];
}) {
  const navigate = useNavigate();
  const cols = [...instrumentColumns<PricedRow>(), ...priceColumns<PricedRow>(), ...extraColumns];
  return (
    <DataTable rows={rows} columns={cols} rowKey={(r) => r.instrument_key} caption={caption} toolbar={toolbar}
      columnsState={columnsState}
      onRowActivate={(r) => navigate(`/stocks/${encodeURIComponent(r.instrument_key)}`)} />
  );
}
