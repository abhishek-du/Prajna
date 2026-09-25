import { useParams, useSearchParams } from "react-router";
import { useCorporateActions, useFundamentals, useLatest, useNews, useProfile, useQuality, useQuote } from "../api/hooks";
import { Change, FreshnessBadge, StatusBadge } from "../components/badges";
import { ChartPanel } from "../components/charts/ChartPanel";
import { byType, Competitors, CorporateActionTable, FactorLegend, KeyRatios, KnownAt, Shareholding, StatementTable } from "../components/fundamentals";
import { Metric, MetricGrid, Panel } from "../components/layout";
import { NewsList } from "../components/news";
import { DataQualityPanel } from "../components/quality";
import { EmptyState, QueryState, Skeleton, TableSkeleton } from "../components/states";
import { fmtDate, fmtDateTimeIST, fmtPrice, fmtVolume } from "../lib/format";
import { useWatchlist } from "../lib/watchlist";
import type { Fundamental, Profile } from "../types/api";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "chart", label: "Chart" },
  { id: "fundamentals", label: "Fundamentals" },
  { id: "financials", label: "Financials" },
  { id: "corporate-actions", label: "Corporate actions" },
  { id: "news", label: "News" },
  { id: "data-quality", label: "Data quality" },
] as const;
type Tab = (typeof TABS)[number]["id"];

function InstrumentHeader({ keyId, p }: { keyId: string; p: Profile }) {
  const latest = useLatest([keyId]);
  const quote = useQuote(keyId);
  const wl = useWatchlist();
  const i = p.instrument;
  const px = latest.data?.data[0] ?? null;
  const m1 = quote.data?.data.last_1m ?? null;
  const watching = wl.has(keyId);
  return (
    <div className="header-instrument">
      <div>
        <div className="inline" style={{ gap: "var(--sp-4)" }}>
          <h1>{i.name ?? i.trading_symbol}</h1>
          <StatusBadge status={i.lifecycle_status} />
        </div>
        <div className="inline muted" style={{ marginTop: 4, fontSize: "var(--fs-sm)" }}>
          <span className="symbol" style={{ color: "var(--text)" }}>{i.trading_symbol}</span>
          <span>{i.exchange} · {i.segment}</span>
          {i.instrument_type && <span>· {i.instrument_type}</span>}
          {i.security_class && <span>· {i.security_class.replace(/_/g, " ")}</span>}
          {i.isin && <span className="mono">· {i.isin}</span>}
          <span>· {p.sector_as_of ?? i.sector ?? "sector unclassified"}</span>
        </div>
      </div>
      <div className="quote-block">
        {latest.isPending ? <Skeleton w={220} h={40} /> : px ? (
          <>
            <div className="inline">
              <span className="badge tone-info plain" title="Stage 1 has no live tick store">Latest stored · 1D close</span>
              <span className="price-big">{fmtPrice(px.close)}</span>
            </div>
            <div className="inline" style={{ marginTop: 4 }}>
              <Change value={px.change} pct={px.change_pct} unavailableReason={px.comparable_reason} />
              <span className="mono faint">session {fmtDate(px.market_date)}</span>
              <FreshnessBadge at={px.knowable_at} kind="daily" />
            </div>
            {!px.comparable && <div className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: 2 }}>Change withheld: {px.comparable_reason}</div>}
          </>
        ) : <span className="muted">No stored daily close.</span>}
        {m1 && (
          <div className="faint mono" style={{ fontSize: "var(--fs-xs)", marginTop: 4 }}>
            Latest stored 1m bar: {fmtPrice(m1.close)} at {fmtDateTimeIST(m1.bar_start)} (known {fmtDateTimeIST(m1.knowable_at)})
          </div>
        )}
        <button type="button" className="btn" style={{ marginTop: 6 }} aria-pressed={watching}
          onClick={() => watching ? wl.remove(keyId) : wl.add({ instrument_key: keyId, trading_symbol: i.trading_symbol, name: i.name, sector: i.sector })}>
          {watching ? "★ In watchlist" : "☆ Add to watchlist"}
        </button>
      </div>
    </div>
  );
}

function OverviewTab({ keyId, p }: { keyId: string; p: Profile }) {
  const f = useFundamentals(keyId);
  const latest = useLatest([keyId]);
  const px = latest.data?.data[0] ?? null;
  const desc = typeof p.profile?.company_profile === "string" ? p.profile.company_profile : null;
  // vendor shape: { unit, value, formatted } (sector-level, not the company's)
  const cap = p.profile?.sector_market_cap_inr;
  const secCap = cap && typeof cap === "object" && "value" in cap && typeof (cap as { value: unknown }).value === "number"
    ? (cap as { value: number; unit?: string }) : null;
  return (
    <div className="grid grid-main-side">
      <div className="stack">
        <Panel title="Latest stored session" id="ov-session">
          {px ? (
            <MetricGrid>
              <Metric label="Close (1D)" value={fmtPrice(px.close)} sub={fmtDate(px.market_date)} />
              <Metric label="Previous close" value={fmtPrice(px.previous_close)} sub={fmtDate(px.previous_market_date)} />
              <Metric label="Change" value={<Change value={px.change} pct={px.change_pct} unavailableReason={px.comparable_reason} />} />
              <Metric label="Volume" value={fmtVolume(px.volume)} />
              <Metric label="Price basis" value={<StatusBadge status={px.price_basis} />} sub="of the latest bar" />
            </MetricGrid>
          ) : <EmptyState title="No stored daily bar." />}
        </Panel>
        <Panel title="Company" id="ov-company">
          {desc ? <p style={{ margin: 0, color: "var(--text-muted)", lineHeight: 1.6 }}>{desc}</p> : <EmptyState title="The vendor supplies no company description." />}
        </Panel>
        <Panel title="Key ratios" id="ov-ratios" flush aside={f.data && byType(f.data.data, "key_ratios") ? <KnownAt f={byType(f.data.data, "key_ratios") as Fundamental} /> : undefined}>
          <QueryState q={f} what="Key ratios">{(d) => <KeyRatios f={byType(d.data, "key_ratios")} />}</QueryState>
        </Panel>
      </div>
      <div className="stack">
        <Panel title="Classification" id="ov-class">
          <dl className="kv">
            <dt>Sector (as of now)</dt><dd>{p.sector_as_of ?? "unclassified"}</dd>
            <dt>Sector market cap</dt><dd className="mono">{secCap ? `₹ ${fmtPrice(secCap.value)} ${secCap.unit === "crore" ? "Cr" : secCap.unit ?? ""} (vendor, whole sector)` : "unavailable"}</dd>
            <dt>Company market cap</dt><dd className="faint">unavailable (not provided by the vendor)</dd>
            <dt>Security class</dt><dd>{p.instrument.security_class ?? "—"}</dd>
            <dt>Class signals</dt><dd className="mono faint" style={{ fontSize: "var(--fs-2xs)" }}>{p.security_class_signals ? Object.keys(p.security_class_signals).join(", ") : "—"}</dd>
          </dl>
        </Panel>
        <Panel title="Listing lifecycle" id="ov-life" flush>
          {p.lifecycle_periods.length === 0 ? <EmptyState title="No lifecycle period knowable." /> : (
            <table className="dt" data-density="compact">
              <caption className="sr-only">Listing lifecycle</caption>
              <thead><tr><th>Status</th><th>From</th><th>To</th></tr></thead>
              <tbody>{p.lifecycle_periods.map((l, n) => (
                <tr key={n}><td><StatusBadge status={l.status} /></td><td className="mono">{fmtDateTimeIST(l.valid_from)}</td>
                  <td className="mono">{l.valid_to && !l.valid_to.startsWith("9999") ? fmtDateTimeIST(l.valid_to) : "open"}</td></tr>
              ))}</tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  );
}

function FundamentalsTab({ keyId }: { keyId: string }) {
  const f = useFundamentals(keyId);
  return (
    <QueryState q={f} what="Fundamentals" skeleton={<TableSkeleton rows={10} cols={3} />}
      isEmpty={(d) => d.data.length === 0} empty={<EmptyState title="No fundamentals snapshot is knowable for this instrument." />}>
      {(d) => (
        <div className="grid grid-2">
          <Panel title="Valuation & profitability (vendor ratios)" id="f-ratios" flush
            note="Growth, margins, debt and cash ratios not listed here are not supplied by the vendor for this instrument.">
            <KeyRatios f={byType(d.data, "key_ratios")} />
          </Panel>
          <Panel title="Shareholding pattern" id="f-share" flush><Shareholding f={byType(d.data, "share_holdings")} /></Panel>
          <Panel title="Peers (vendor list)" id="f-peers" flush><Competitors f={byType(d.data, "competitors")} /></Panel>
        </div>
      )}
    </QueryState>
  );
}

function FinancialsTab({ keyId }: { keyId: string }) {
  const f = useFundamentals(keyId);
  const [sp, setSp] = useSearchParams();
  const basis = sp.get("basis") === "standalone" ? "standalone" : "consolidated";
  const period = sp.get("period") === "quarterly" ? "quarterly" : "yearly";
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); n.set(k, v); setSp(n, { replace: true }); };
  return (
    <div className="stack">
      <div className="inline">
        <div className="segmented" role="group" aria-label="Statement basis">
          {["consolidated", "standalone"].map((b) => <button key={b} type="button" aria-pressed={basis === b} onClick={() => set("basis", b)}>{b}</button>)}
        </div>
        <div className="segmented" role="group" aria-label="Income statement period">
          {["yearly", "quarterly"].map((b) => <button key={b} type="button" aria-pressed={period === b} onClick={() => set("period", b)}>{b}</button>)}
        </div>
      </div>
      <QueryState q={f} what="Financial statements" skeleton={<TableSkeleton rows={12} cols={5} />}>
        {(d) => (
          <div className="stack">
            <Panel title={`Income statement · ${period}`} id="s-income" flush><StatementTable f={byType(d.data, `income:${basis}:${period}`)} title="Income statement" /></Panel>
            <Panel title="Balance sheet · yearly" id="s-bs" flush><StatementTable f={byType(d.data, `balance_sheet:${basis}`)} title="Balance sheet" /></Panel>
            <Panel title="Cash flow · yearly" id="s-cf" flush><StatementTable f={byType(d.data, `cash_flow:${basis}`)} title="Cash flow" /></Panel>
          </div>
        )}
      </QueryState>
    </div>
  );
}

function CorporateActionsTab({ keyId }: { keyId: string }) {
  const ca = useCorporateActions(keyId);
  return (
    <div className="grid grid-main-side">
      <Panel title="Corporate actions" id="ca" flush note="Factors are versioned (cafactor-v1). Adjusted charts apply only factors knowable at the chosen time.">
        <QueryState q={ca} what="Corporate actions">{(d) => <CorporateActionTable rows={d.data} />}</QueryState>
      </Panel>
      <Panel title="What the statuses mean" id="ca-legend"><FactorLegend /></Panel>
    </div>
  );
}

function NewsTab({ keyId }: { keyId: string }) {
  const n = useNews({ instrument_key: keyId, limit: 100 });
  return (
    <Panel title="News linked to this instrument" id="n" flush note="Published = vendor time; Received = when Prajna fetched it. They differ.">
      <QueryState q={n} what="News">{(d) => <NewsList items={d.data} />}</QueryState>
    </Panel>
  );
}

export default function StockDetail() {
  const { key = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const tab = (TABS.some((t) => t.id === sp.get("tab")) ? sp.get("tab") : "overview") as Tab;
  const profile = useProfile(key);
  const quality = useQuality(tab === "data-quality" ? key : null);
  const setTab = (t: Tab) => { const n = new URLSearchParams(sp); n.set("tab", t); setSp(n, { replace: true }); };
  return (
    <div className="page">
      <QueryState q={profile} what="Instrument" skeleton={<Skeleton h={64} />}>
        {({ data: p }) => (
          <>
            <InstrumentHeader keyId={key} p={p} />
            <div className="tabs" role="tablist" aria-label="Instrument sections">
              {TABS.map((t) => (
                <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id}
                  aria-controls={`panel-${t.id}`} onClick={() => setTab(t.id)}
                  onKeyDown={(e) => {
                    const i = TABS.findIndex((x) => x.id === tab);
                    if (e.key === "ArrowRight") setTab(TABS[(i + 1) % TABS.length]?.id ?? "overview");
                    if (e.key === "ArrowLeft") setTab(TABS[(i - 1 + TABS.length) % TABS.length]?.id ?? "overview");
                  }}>
                  {t.label}
                </button>
              ))}
            </div>
            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
              {tab === "overview" && <OverviewTab keyId={key} p={p} />}
              {tab === "chart" && <ChartPanel keyId={key} />}
              {tab === "fundamentals" && <FundamentalsTab keyId={key} />}
              {tab === "financials" && <FinancialsTab keyId={key} />}
              {tab === "corporate-actions" && <CorporateActionsTab keyId={key} />}
              {tab === "news" && <NewsTab keyId={key} />}
              {tab === "data-quality" && (
                <QueryState q={quality} what="Data quality">{(d) => <DataQualityPanel q={d.data} />}</QueryState>
              )}
            </div>
          </>
        )}
      </QueryState>
    </div>
  );
}
