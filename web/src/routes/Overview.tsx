import { Link } from "react-router";
import { useFreshness, useInstruments, useLatest, useNews, useSectors, useSession } from "../api/hooks";
import { FreshnessBadge, StatusBadge } from "../components/badges";
import { GlobalTable } from "../components/global";
import { Metric, MetricGrid, PageHead, Panel } from "../components/layout";
import { joinPrices, PricedInstrumentTable } from "../components/market";
import { NewsList } from "../components/news";
import { QueryState, Skeleton, TableSkeleton, Unavailable } from "../components/states";
import { fmtDate } from "../lib/format";
import { DataTable } from "../components/DataTable";
import type { Freshness } from "../types/api";

export function SessionPanel() {
  const s = useSession();
  return (
    <Panel title="Market session" id="session" note="Calendar state from the NSE session calendar — not a data-feed status.">
      <QueryState q={s} what="Market session" skeleton={<Skeleton h={48} />}>
        {({ data: d }) => (
          <MetricGrid>
            <Metric label="State" value={<StatusBadge status={d.state} />} sub={d.session_type} />
            <Metric label="Session" value={fmtDate(d.date)} sub={d.is_trading_day ? `${d.open_ist?.slice(0, 5)}–${d.close_ist?.slice(0, 5)} IST` : "non-trading day"} />
            <Metric label="Previous session" value={fmtDate(d.previous_trading_day)} />
            <Metric label="Next session" value={fmtDate(d.next_trading_day)} />
          </MetricGrid>
        )}
      </QueryState>
    </Panel>
  );
}

export function IndicesPanel() {
  const idx = useInstruments({ segment: "NSE_INDEX", limit: 50 });
  const keys = (idx.data?.data ?? []).map((i) => i.instrument_key);
  const prices = useLatest(keys);
  return (
    <Panel title="Indian indices" id="indices" flush
      aside={<span>Latest stored daily close · no live feed in Stage 1</span>}>
      <QueryState q={idx} what="Indices" isEmpty={(d) => d.data.length === 0}>
        {(d) => prices.isPending ? <TableSkeleton rows={3} cols={6} /> :
          <PricedInstrumentTable rows={joinPrices(d.data, prices.data?.data)} caption="Indian indices" />}
      </QueryState>
    </Panel>
  );
}

function freshnessKind(dataset: string) {
  if (dataset.startsWith("candles_1") && dataset !== "candles_1d") return "intraday" as const;
  if (dataset === "news") return "news" as const;
  if (dataset === "global_1d") return "global" as const;
  return "ops" as const;
}

export function DataHealthTable({ rows }: { rows: Freshness[] }) {
  return (
    <DataTable rows={rows} rowKey={(r) => r.dataset} caption="Data freshness per dataset" columns={[
      { id: "dataset", header: "Dataset", sticky: true, sortValue: (r) => r.dataset, cell: (r) => <span className="mono">{r.dataset}</span> },
      { id: "status", header: "Last run", cell: (r) => <StatusBadge status={r.last_status} /> },
      { id: "fresh", header: "Last success", cell: (r) => <FreshnessBadge at={r.last_complete_run_finished} kind={freshnessKind(r.dataset)} /> },
      { id: "cadence", header: "Expected cadence", cell: (r) => <span className="faint">{r.expected_cadence}</span> },
    ]} />
  );
}

export default function Overview() {
  const sectors = useSectors();
  const news = useNews({ limit: 8 });
  const fresh = useFreshness();
  return (
    <div className="page">
      <PageHead title="Overview" subtitle="Market data foundation — stored observations with their knowledge time. No signals, no predictions." />
      <div className="grid grid-main-side">
        <div className="stack">
          <SessionPanel />
          <IndicesPanel />
          <div className="grid grid-2">
            <Panel title="Market breadth" id="breadth">
              <Unavailable what="advancing / declining / unchanged" capability="universe-wide latest-price aggregate (not in /v1)" />
            </Panel>
            <Panel title="Top movers" id="movers">
              <Unavailable what="gainers / losers / volume leaders" capability="universe-wide ranking over /v1/latest (per-key only, ≤ 200)" />
            </Panel>
          </div>
          <Panel title="Global markets" id="global" flush aside={<Link to="/global">All →</Link>}
            note="Confirmed vendor labels only; revised, placeholder and unconfirmed labels are withheld. Labels are not trading dates.">
            <GlobalTable compact />
          </Panel>
        </div>
        <div className="stack">
          <Panel title="Data health" id="health" flush aside={<Link to="/operations">Operations →</Link>}>
            <QueryState q={fresh} what="Data health" isEmpty={(d) => d.data.length === 0}>
              {(d) => <DataHealthTable rows={d.data} />}
            </QueryState>
          </Panel>
          <Panel title="Sectors" id="sectors" flush aside={<Link to="/sectors">All →</Link>}
            note="Stock counts per sector (ACTIVE stocks). Sector advance/decline: unavailable (no aggregate endpoint).">
            <QueryState q={sectors} what="Sectors" isEmpty={(d) => d.data.length === 0}>
              {(d) => (
                <DataTable rows={d.data.filter((s) => s.sector).slice(0, 12)} rowKey={(r) => r.sector ?? "-"} caption="Largest sectors"
                  columns={[
                    { id: "sector", header: "Sector", sticky: true, cell: (r) => <Link to={`/sectors/${encodeURIComponent(r.sector ?? "")}`}>{r.sector}</Link> },
                    { id: "stocks", header: "Stocks", numeric: true, cell: (r) => <span className="num">{r.stocks}</span> },
                  ]} />
              )}
            </QueryState>
          </Panel>
          <Panel title="Latest news" id="news" flush aside={<Link to="/news">All →</Link>}>
            <QueryState q={news} what="News">{(d) => <NewsList items={d.data} />}</QueryState>
          </Panel>
        </div>
      </div>
    </div>
  );
}
