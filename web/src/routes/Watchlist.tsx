import { useLatest } from "../api/hooks";
import { DataTable } from "../components/DataTable";
import { PageHead, Panel } from "../components/layout";
import { priceColumns } from "../components/market";
import { EmptyState } from "../components/states";
import { useWatchlist, type WatchItem } from "../lib/watchlist";
import { useNavigate } from "react-router";
import type { LatestPrice } from "../types/api";

type Row = WatchItem & { price: LatestPrice | null };

export default function Watchlist() {
  const wl = useWatchlist();
  const prices = useLatest(wl.items.map((i) => i.instrument_key));
  const navigate = useNavigate();
  const m = new Map((prices.data?.data ?? []).map((p) => [p.instrument_key, p]));
  const rows: Row[] = wl.items.map((i) => ({ ...i, price: m.get(i.instrument_key) ?? null }));
  return (
    <div className="page">
      <PageHead title="Watchlist" subtitle="Saved in this browser only (no server-side watchlist exists). Prices: latest stored daily close." />
      <Panel title="Watchlist" id="wl" flush>
        {rows.length === 0 ? (
          <EmptyState title="Your watchlist is empty.">Open a stock and choose “Add to watchlist”, or search with Ctrl K.</EmptyState>
        ) : (
          <DataTable rows={rows} rowKey={(r) => r.instrument_key} caption="Watchlist"
            onRowActivate={(r) => navigate(`/stocks/${encodeURIComponent(r.instrument_key)}`)}
            columns={[
              { id: "symbol", header: "Symbol", sticky: true, sortValue: (r) => r.trading_symbol, cell: (r) => <span className="symbol">{r.trading_symbol}</span> },
              { id: "name", header: "Company", sortValue: (r) => r.name, cell: (r) => r.name ?? "—" },
              ...priceColumns<Row>(),
              { id: "sector", header: "Sector", sortValue: (r) => r.sector, cell: (r) => r.sector ?? "—" },
              { id: "remove", header: "", cell: (r) => (
                <button type="button" className="btn ghost" aria-label={`Remove ${r.trading_symbol}`}
                  onClick={(e) => { e.stopPropagation(); wl.remove(r.instrument_key); }}>Remove</button>
              ) },
            ]} />
        )}
      </Panel>
    </div>
  );
}
