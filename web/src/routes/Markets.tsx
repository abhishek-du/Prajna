import { GlobalTable } from "../components/global";
import { PageHead, Panel } from "../components/layout";
import { Unavailable } from "../components/states";
import { IndicesPanel, SessionPanel } from "./Overview";

export default function Markets() {
  return (
    <div className="page">
      <PageHead title="Markets" subtitle="Indian session and indices beside global markets. Indian sessions and global vendor labels are different calendars." />
      <SessionPanel />
      <IndicesPanel />
      <div className="grid grid-2">
        <Panel title="Market breadth" id="m-breadth">
          <Unavailable what="advancing / declining" capability="universe-wide latest-price aggregate" />
        </Panel>
        <Panel title="Intraday index view" id="m-intraday">
          <Unavailable what="live index ticks" capability="live tick store (Stage 1: OUT_OF_SCOPE); open an index for its stored 1m / 15m / 1h bars" />
        </Panel>
      </div>
      <Panel title="Global markets" id="m-global" flush
        note="Change is between the two latest confirmed vendor labels of each instrument.">
        <GlobalTable />
      </Panel>
    </div>
  );
}
