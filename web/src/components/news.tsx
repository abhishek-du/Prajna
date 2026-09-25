import { Link } from "react-router";
import { fmtDateTimeIST, fmtLatency } from "../lib/format";
import type { NewsItem } from "../types/api";
import { EmptyState } from "./states";

/** A news item: publication (vendor) and receipt (Prajna) are different instants
 * and are always shown separately, with the ingestion latency between them. */
export function NewsRow({ n, symbol }: { n: NewsItem; symbol?: string | null }) {
  return (
    <article className="news-item">
      <div style={{ minWidth: 0 }}>
        {n.url ? <a href={n.url} target="_blank" rel="noreferrer noopener">{n.headline}</a> : <span>{n.headline}</span>}
        <div className="news-times" style={{ marginTop: 4 }}>
          <span title="publication time reported by the vendor">Published {fmtDateTimeIST(n.published_at)}</span>
          <span title="when Prajna fetched it">Received {fmtDateTimeIST(n.received_at)}</span>
          <span title="published → received">Latency {fmtLatency(n.published_at, n.received_at)}</span>
          <span>Source {n.publisher ?? "not supplied by the vendor"}</span>
        </div>
      </div>
      <div>
        {n.instrument_key && (
          <Link className="symbol" to={`/stocks/${encodeURIComponent(n.instrument_key)}`} style={{ fontSize: "var(--fs-xs)" }}>
            {symbol ?? n.instrument_key.split("|")[1]}
          </Link>
        )}
      </div>
    </article>
  );
}

export function NewsList({ items, symbols }: { items: NewsItem[]; symbols?: Map<string, string> }) {
  if (items.length === 0) return <EmptyState title="No news knowable for this selection." />;
  return <div>{items.map((n) => <NewsRow key={`${n.news_id}:${n.instrument_key}`} n={n} symbol={n.instrument_key ? symbols?.get(n.instrument_key) : null} />)}</div>;
}
