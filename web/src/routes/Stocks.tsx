import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useInstruments, useLatest, useSearch, useSectors } from "../api/hooks";
import { DensityControl } from "../components/DataTable";
import { PageHead, Panel } from "../components/layout";
import { joinPrices, PricedInstrumentTable } from "../components/market";
import { EmptyState, QueryState, TableSkeleton } from "../components/states";

const PAGE_SIZES = [50, 100, 200];
const VIEWS_KEY = "prajna.web.screener.views.v1";
const COLS_KEY = "prajna.web.screener.columns.v1";

function loadViews(): { name: string; query: string }[] {
  try { return JSON.parse(localStorage.getItem(VIEWS_KEY) ?? "[]") as { name: string; query: string }[]; } catch { return []; }
}

function usePersistentColumns(): [string[], (ids: string[]) => void] {
  const [ids, setIds] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(COLS_KEY);
      return raw ? (JSON.parse(raw) as string[]) : ["name", "sector", "close", "change", "change_pct", "volume", "session", "freshness"];
    } catch {
      return ["name", "sector", "close", "change", "change_pct", "volume", "session", "freshness"];
    }
  });
  useEffect(() => { try { localStorage.setItem(COLS_KEY, JSON.stringify(ids)); } catch { /* ignore */ } }, [ids]);
  return [ids, setIds];
}

export default function Stocks() {
  const [sp, setSp] = useSearchParams();
  const cls = sp.get("class") ?? "STOCK";
  const sector = sp.get("sector") ?? "";
  const life = sp.get("listing") ?? "ACTIVE";
  const q = sp.get("q") ?? "";
  const size = Number(sp.get("size") ?? 100);
  const page = Math.max(0, Number(sp.get("page") ?? 0));
  const set = (patch: Record<string, string | null>) => {
    const n = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) { if (v === null || v === "") n.delete(k); else n.set(k, v); }
    if (!("page" in patch)) n.delete("page");
    setSp(n, { replace: true });
  };

  const listing = useInstruments({ security_class: cls === "ANY" ? "" : cls, sector, lifecycle_status: life,
    limit: size, offset: page * size });
  const search = useSearch(q);
  const sectors = useSectors();
  const searching = q.trim().length > 0;
  const instruments = searching ? (search.data?.data ?? []) : (listing.data?.data ?? []);
  const prices = useLatest(instruments.map((i) => i.instrument_key));
  const total = listing.data?.meta.total ?? null;
  const columnsState = usePersistentColumns();
  const [views, setViews] = useState(loadViews);

  const saveView = () => {
    const name = `${cls}${sector ? ` · ${sector}` : ""}${life !== "ACTIVE" ? ` · ${life}` : ""}`;
    const next = [...views.filter((v) => v.name !== name), { name, query: sp.toString() }];
    setViews(next);
    try { localStorage.setItem(VIEWS_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };

  const toolbar = (
    <>
      <input className="input" aria-label="Filter by symbol, company or ISIN" placeholder="Symbol / company / ISIN" value={q}
        onChange={(e) => set({ q: e.target.value })} style={{ width: 220 }} />
      <label className="field">Class
        <select className="select" value={cls} onChange={(e) => set({ class: e.target.value })} disabled={searching}>
          {["STOCK", "FUND_UNIT", "RIGHTS_ENTITLEMENT", "OTHER", "ANY"].map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
        </select>
      </label>
      <label className="field">Sector
        <select className="select" value={sector} onChange={(e) => set({ sector: e.target.value })} disabled={searching} style={{ maxWidth: 200 }}>
          <option value="">All sectors</option>
          {(sectors.data?.data ?? []).filter((s) => s.sector).map((s) => <option key={s.sector} value={s.sector ?? ""}>{s.sector} ({s.stocks})</option>)}
        </select>
      </label>
      <label className="field">Listing
        <select className="select" value={life} onChange={(e) => set({ listing: e.target.value })} disabled={searching}>
          {["ACTIVE", "ANY", "REMOVED_FROM_MASTER", "VENDOR_REJECTED", "INELIGIBLE"].map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
        </select>
      </label>
      <DensityControl />
      <button type="button" className="btn" onClick={saveView}>Save view</button>
      {views.length > 0 && (
        <select className="select" aria-label="Saved views" value="" onChange={(e) => e.target.value && setSp(new URLSearchParams(e.target.value))}>
          <option value="">Saved views…</option>
          {views.map((v) => <option key={v.name} value={v.query}>{v.name}</option>)}
        </select>
      )}
    </>
  );

  const q_ = searching ? search : listing;
  return (
    <div className="page">
      <PageHead title="Stocks" subtitle={<>Canonical NSE universe. Prices are the latest <b>stored</b> daily close; columns sort the rows on this page.</>} />
      <Panel title={searching ? `Search results for “${q}”` : "Screener"} id="screener" flush
        aside={!searching && total !== null ? <span className="mono">{total.toLocaleString("en-IN")} instruments</span> : undefined}
        note={<>Not available as columns: market cap, P/E, P/B, ROE, ROCE, dividend yield, 52-week range — the list API carries no fundamentals and there is no universe-wide sort by price (missing backend capability). Fundamentals are on each stock's page.</>}>
        <QueryState q={q_} what="Instruments" skeleton={<TableSkeleton rows={12} cols={8} />}
          isEmpty={(d) => d.data.length === 0}
          empty={<><div className="toolbar">{toolbar}</div>
            <EmptyState title="No instrument matches these filters.">Clear a filter or search a different symbol.</EmptyState></>}>
          {() => (
            <>
              <PricedInstrumentTable rows={joinPrices(instruments, prices.data?.data)} caption="Stock screener"
                toolbar={toolbar} columnsState={columnsState} />
              {!searching && (
                <div className="pager">
                  <label className="field">Rows
                    <select className="select" value={size} onChange={(e) => set({ size: e.target.value })}>
                      {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </label>
                  <span className="mono">{total === null ? "" : `${page * size + 1}–${Math.min((page + 1) * size, total)} of ${total}`}</span>
                  <button type="button" className="btn" disabled={page === 0} onClick={() => set({ page: String(page - 1) })}>Previous</button>
                  <button type="button" className="btn" disabled={total === null || (page + 1) * size >= total} onClick={() => set({ page: String(page + 1) })}>Next</button>
                </div>
              )}
            </>
          )}
        </QueryState>
      </Panel>
    </div>
  );
}
