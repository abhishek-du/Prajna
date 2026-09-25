/* Candles + volume on TradingView Lightweight Charts (canvas; no DOM node per
   candle). Values are drawn exactly as the API returned them. The legend
   follows the crosshair and shows OHLCV, the bar time (IST), when Prajna
   knew the bar (knowable_at) and its price basis. */
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { fmtDate, fmtDateTimeIST, fmtPrice, fmtVolume } from "../../lib/format";
import type { Candle } from "../../types/api";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || undefined;
const IST_OFFSET_S = 5.5 * 3600;

/** Daily bars are keyed by their market date (a calendar label); intraday bars
 * by their start instant, shifted so the axis reads IST wall-clock time. */
function timeOf(c: Candle, daily: boolean): Time {
  return daily ? c.market_date : ((Date.parse(c.bar_start) / 1000 + IST_OFFSET_S) as UTCTimestamp);
}

function Legend({ c, daily }: { c: Candle | null; daily: boolean }) {
  if (!c) return null;
  return (
    <div className="chart-legend" aria-live="off">
      <span>{daily ? fmtDate(c.market_date) : fmtDateTimeIST(c.bar_start)}</span>
      <span>O <b>{fmtPrice(c.open)}</b></span>
      <span>H <b>{fmtPrice(c.high)}</b></span>
      <span>L <b>{fmtPrice(c.low)}</b></span>
      <span>C <b>{fmtPrice(c.close)}</b></span>
      <span>V <b>{fmtVolume(c.volume)}</b></span>
      <span title="the earliest instant Prajna knew this bar">known {fmtDateTimeIST(c.knowable_at)}</span>
      <span>basis <b>{c.price_basis ?? "unrecorded"}{c.basis_as_of ? ` @ ${c.basis_as_of}` : ""}</b></span>
      {c.adjustment_status && <span>adj <b>{c.adjustment_status}</b></span>}
    </div>
  );
}

export const CandlestickChart = memo(function CandlestickChart({ candles, daily, theme }: {
  candles: Candle[]; daily: boolean; theme: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{ c: ISeriesApi<"Candlestick">; v: ISeriesApi<"Histogram"> } | null>(null);
  const byTime = useMemo(() => new Map(candles.map((c) => [String(timeOf(c, daily)), c])), [candles, daily]);
  const last = candles.length ? (candles[candles.length - 1] as Candle) : null;
  const [hover, setHover] = useState<Candle | null>(null);

  // create once per theme (colours come from the design tokens)
  useEffect(() => {
    if (!box.current) return;
    const up = css("--positive") ?? "#3fb68b";
    const down = css("--negative") ?? "#e5575b";
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--chart-text"),
        fontFamily: css("--font-mono"), fontSize: 11, panes: { separatorColor: css("--border") } },
      grid: { vertLines: { color: css("--chart-grid") }, horzLines: { color: css("--chart-grid") } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: css("--chart-crosshair") }, horzLine: { color: css("--chart-crosshair") } },
      rightPriceScale: { borderColor: css("--border") },
      timeScale: { borderColor: css("--border"), timeVisible: !daily, secondsVisible: false, rightOffset: 4 },
      localization: { locale: "en-IN" },
    });
    const cs = c.addSeries(CandlestickSeries, { upColor: up, downColor: down, wickUpColor: up, wickDownColor: down,
      borderVisible: false, priceLineVisible: false });
    const vs = c.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false,
      lastValueVisible: false }, 1);
    c.panes()[1]?.setHeight(90);
    chart.current = c;
    series.current = { c: cs, v: vs };
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, [theme, daily]);

  // data
  useEffect(() => {
    const s = series.current;
    if (!s) return;
    const up = css("--positive-muted") ?? "rgba(63,182,139,.4)";
    const down = css("--negative-muted") ?? "rgba(229,87,91,.4)";
    s.c.setData(candles.map((k) => ({ time: timeOf(k, daily), open: k.open, high: k.high, low: k.low, close: k.close })));
    s.v.setData(candles.map((k) => ({ time: timeOf(k, daily), value: k.volume, color: k.close >= k.open ? up : down })));
    chart.current?.timeScale().fitContent();
  }, [candles, daily, theme]);

  // legend follows the crosshair; falls back to the latest bar
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const h = (p: { time?: Time }) => setHover(p.time === undefined ? null : byTime.get(String(p.time)) ?? null);
    c.subscribeCrosshairMove(h);
    return () => c.unsubscribeCrosshairMove(h);
  }, [byTime, theme, daily]);

  return (
    <div className="chart-box" role="img" aria-label={`Candlestick chart, ${candles.length} bars`} data-testid="candle-chart">
      <Legend c={hover ?? last} daily={daily} />
      <div ref={box} style={{ position: "absolute", inset: 0 }} />
    </div>
  );
});
