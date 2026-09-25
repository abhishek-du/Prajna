import { useParams } from "react-router";
import { useInstruments, useLatest } from "../api/hooks";
import { PageHead, Panel } from "../components/layout";
import { joinPrices, PricedInstrumentTable } from "../components/market";
import { EmptyState, QueryState, TableSkeleton } from "../components/states";

export default function SectorDetail() {
  const { sector = "" } = useParams();
  const list = useInstruments({ sector, security_class: "STOCK", lifecycle_status: "ACTIVE", limit: 200 });
  const keys = (list.data?.data ?? []).map((i) => i.instrument_key);
  const prices = useLatest(keys);
  const total = list.data?.meta.total ?? null;
  return (
    <div className="page">
      <PageHead title={sector} subtitle="Constituents (ACTIVE stocks, current vendor classification). Prices: latest stored daily close." />
      <Panel title="Constituents" id="constituents" flush
        aside={total !== null ? <span className="mono">{total} stocks{total > 200 ? " · first 200 shown" : ""}</span> : undefined}>
        <QueryState q={list} what="Constituents" skeleton={<TableSkeleton rows={12} cols={7} />}
          isEmpty={(d) => d.data.length === 0} empty={<EmptyState title={`No ACTIVE stock is classified in “${sector}”.`} />}>
          {(d) => <PricedInstrumentTable rows={joinPrices(d.data, prices.data?.data)} caption={`${sector} constituents`} />}
        </QueryState>
      </Panel>
    </div>
  );
}
