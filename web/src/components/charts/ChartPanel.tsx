import { useSearchParams } from "react-router";
import { useCandles, useQuality } from "../../api/hooks";
import { BARS_PER_TIMEFRAME, TIMEFRAMES, type AvailableTimeframe } from "../../config/data";
import { fmtDate, fmtDateTimeIST } from "../../lib/format";
import { useMarketData } from "../../providers/marketData";
import { useSettings } from "../../providers/settings";
import { Badge, FreshnessBadge, StatusBadge } from "../badges";
import { Panel } from "../layout";
import { EmptyState, ErrorState, Skeleton } from "../states";
import { CandlestickChart } from "./CandlestickChart";

const isTf = (v: string | null): v is AvailableTimeframe => v === "1m" || v === "15m" || v === "1h" || v === "1d";

export function TimeframeSelector({ value, onChange }: { value: AvailableTimeframe; onChange: (tf: AvailableTimeframe) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Timeframe">
      {TIMEFRAMES.map((t) => (
        <button key={t.tf} type="button" aria-pressed={value === t.tf} disabled={!t.available}
          title={t.reason ?? `${t.label} bars`} aria-label={t.available ? `${t.label} timeframe` : `${t.label} unavailable: ${t.reason}`}
          onClick={() => t.available && onChange(t.tf as AvailableTimeframe)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function ChartPanel({ keyId }: { keyId: string }) {
  const [sp, setSp] = useSearchParams();
  const tf: AvailableTimeframe = isTf(sp.get("tf")) ? (sp.get("tf") as AvailableTimeframe) : "1d";
  const adjusted = sp.get("adj") === "1";
  const set = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp);
    if (v === null) n.delete(k); else n.set(k, v);
    setSp(n, { replace: true });
  };
  const { settings } = useSettings();
  const md = useMarketData();
  const q = useCandles(keyId, { timeframe: tf, limit: BARS_PER_TIMEFRAME[tf], adjusted });
  const quality = useQuality(keyId);
  const series = q.data?.data;
  const candles = series?.candles ?? [];
  const last = candles.at(-1);
  const refused = series?.refused ? Object.values(series.refused).reduce((a, b) => a + b, 0) : 0;
  const gaps = (quality.data?.data.coverage[tf] ?? []).filter((r) => !["DATA", "EMPTY"].includes(r.state));

  return (
    <Panel title="Price chart" id="chart" flush
      aside={
        <>
          <TimeframeSelector value={tf} onChange={(v) => set("tf", v)} />
          <label className="field" title="Split/bonus-adjusted as knowable at the time (corporate-action factors)">
            <input type="checkbox" checked={adjusted} onChange={(e) => set("adj", e.target.checked ? "1" : null)} />
            Adjusted
          </label>
        </>
      }
      note={
        <span className="inline">
          <Badge tone="info" plain title="Stage 1 has no live tick store">{md.label}</Badge>
          {last && <>last bar {tf === "1d" ? fmtDate(last.market_date) : fmtDateTimeIST(last.bar_start)} · <FreshnessBadge at={last.knowable_at} kind={tf === "1d" ? "daily" : "intraday"} /></>}
          {last && <>basis <StatusBadge status={last.price_basis} /></>}
          {refused > 0 && <Badge tone="warning">{refused} bars withheld (low-confidence or reconstructed basis)</Badge>}
          {gaps.length > 0 && <Badge tone="warning" title={gaps.map((g) => `${g.state} ${g.from_date}..${g.to_date}`).join("; ")}>Partial: {gaps.length} coverage gap{gaps.length > 1 ? "s" : ""}</Badge>}
          <span className="faint">Values drawn exactly as stored; “known” is when Prajna fetched each bar.</span>
        </span>
      }>
      {q.isPending ? (
        <div className="chart-box"><Skeleton h="100%" /></div>
      ) : q.isError ? (
        <ErrorState error={q.error} what="Chart data" onRetry={() => void q.refetch()} />
      ) : candles.length === 0 ? (
        <EmptyState title={`No ${tf} bars stored for this instrument.`}>
          {tf === "1d" ? "Daily history may be missing for this listing." :
            "Intraday history starts 2026-09-23 and grows one session per close (historical intraday backfill: deferred)."}
          {refused > 0 && ` ${refused} bars were withheld by the adjustment rules; untick “Adjusted” to see stored values.`}
        </EmptyState>
      ) : (
        <CandlestickChart candles={candles} daily={tf === "1d"} theme={settings.theme} />
      )}
    </Panel>
  );
}
