import { useNavigate } from "react-router";
import { useSectors } from "../api/hooks";
import { DataTable } from "../components/DataTable";
import { PageHead, Panel } from "../components/layout";
import { QueryState, TableSkeleton, Unavailable } from "../components/states";

export default function Sectors() {
  const s = useSectors();
  const navigate = useNavigate();
  return (
    <div className="page">
      <PageHead title="Sectors" subtitle="Vendor sector classification of ACTIVE stocks (security class STOCK). Current classification, not point-in-time." />
      <div className="grid grid-main-side">
        <Panel title="Sectors" id="sectors" flush>
          <QueryState q={s} what="Sectors" skeleton={<TableSkeleton rows={14} cols={2} />} isEmpty={(d) => d.data.length === 0}>
            {(d) => {
              const total = d.data.reduce((a, r) => a + r.stocks, 0);
              return (
                <DataTable rows={d.data} rowKey={(r) => r.sector ?? "(unclassified)"} caption="Sectors"
                  initialSort={{ id: "stocks", dir: "desc" }}
                  onRowActivate={(r) => r.sector && navigate(`/sectors/${encodeURIComponent(r.sector)}`)}
                  columns={[
                    { id: "sector", header: "Sector", sticky: true, sortValue: (r) => r.sector ?? "",
                      cell: (r) => r.sector ?? <span className="faint">unclassified by the vendor</span> },
                    { id: "stocks", header: "Stocks", numeric: true, sortValue: (r) => r.stocks, cell: (r) => <span className="num">{r.stocks}</span> },
                    { id: "share", header: "Share", numeric: true, sortValue: (r) => r.stocks,
                      cell: (r) => <span className="num muted">{((r.stocks / total) * 100).toFixed(1)}%</span> },
                  ]} />
              );
            }}
          </QueryState>
        </Panel>
        <div className="stack">
          <Panel title="Sector performance" id="sec-perf">
            <Unavailable what="sector advance/decline and aggregate movement" capability="sector-level aggregate over latest prices (no endpoint)" />
          </Panel>
          <Panel title="Sector fundamentals" id="sec-fund">
            <Unavailable what="aggregate P/E, P/B, ROE per sector" capability="sector aggregates (per-instrument vendor ratios carry a sector comparison: see a stock's Fundamentals tab)" />
          </Panel>
        </div>
      </div>
    </div>
  );
}
