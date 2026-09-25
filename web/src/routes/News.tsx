import { useMemo } from "react";
import { useSearchParams } from "react-router";
import { useNews, useSearch } from "../api/hooks";
import { PageHead, Panel } from "../components/layout";
import { NewsList } from "../components/news";
import { QueryState, TableSkeleton, Unavailable } from "../components/states";
import { fmtDate, fmtDuration } from "../lib/format";
import type { NewsItem } from "../types/api";

function Timeline({ items }: { items: NewsItem[] }) {
  const byDay = useMemo(() => {
    const m = new Map<string, NewsItem[]>();
    for (const n of items) {
      const d = (n.published_at ?? n.received_at).slice(0, 10);
      m.set(d, [...(m.get(d) ?? []), n]);
    }
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [items]);
  return (
    <div>
      {byDay.map(([day, list]) => (
        <section key={day} aria-label={fmtDate(day)}>
          <h3 style={{ padding: "var(--sp-4) var(--sp-5) 0" }}>{fmtDate(day)} · {list.length}</h3>
          <NewsList items={list} />
        </section>
      ))}
    </div>
  );
}

export default function News() {
  const [sp, setSp] = useSearchParams();
  const symbol = sp.get("symbol") ?? "";
  const since = sp.get("since") ?? "";
  const mode = sp.get("mode") === "timeline" ? "timeline" : "list";
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };
  const hit = useSearch(symbol);
  const key = symbol ? hit.data?.data.find((h) => h.trading_symbol.toUpperCase() === symbol.toUpperCase())?.instrument_key : undefined;
  const news = useNews({ instrument_key: key, since: since ? `${since}T00:00:00+05:30` : undefined, limit: 300 });
  const items = news.data?.data ?? [];
  const lat = items.filter((n) => n.published_at).map((n) => (Date.parse(n.received_at) - Date.parse(n.published_at as string)) / 1000).sort((a, b) => a - b);
  const median = lat.length ? (lat[Math.floor(lat.length / 2)] ?? null) : null;

  return (
    <div className="page">
      <PageHead title="News" subtitle="Published = vendor publication time. Received = when Prajna fetched it. Only news knowable now is shown." />
      <Panel title="News" id="news" flush
        aside={median !== null ? <span className="mono" title="median published → received over the shown items">median latency {fmtDuration(median)}</span> : undefined}
        note="Source and category filters: unavailable — the vendor supplies no publisher or category. All items are instrument-linked (no market-wide or global news feed).">
        <div className="toolbar">
          <input className="input" aria-label="Symbol" placeholder="Symbol (e.g. RELIANCE)" value={symbol} onChange={(e) => set("symbol", e.target.value.toUpperCase())} style={{ width: 180 }} />
          <label className="field">Published since
            <input className="input" type="date" value={since} onChange={(e) => set("since", e.target.value)} />
          </label>
          <select className="select" disabled aria-label="Source (unavailable)" title="the vendor supplies no publisher"><option>Source: unavailable</option></select>
          <select className="select" disabled aria-label="Category (unavailable)" title="the vendor supplies no category"><option>Category: unavailable</option></select>
          <span style={{ flex: 1 }} />
          <div className="segmented" role="group" aria-label="View">
            <button type="button" aria-pressed={mode === "list"} onClick={() => set("mode", "")}>List</button>
            <button type="button" aria-pressed={mode === "timeline"} onClick={() => set("mode", "timeline")}>Timeline</button>
          </div>
        </div>
        {symbol && !hit.isPending && !key ? (
          <Unavailable what={`news for “${symbol}”`} capability="no instrument with this exact symbol" />
        ) : (
          <QueryState q={news} what="News" skeleton={<TableSkeleton rows={8} cols={1} />}>
            {(d) => (mode === "timeline" ? <Timeline items={d.data} /> : <NewsList items={d.data} />)}
          </QueryState>
        )}
      </Panel>
    </div>
  );
}
