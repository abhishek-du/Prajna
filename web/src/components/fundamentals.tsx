/* Renders vendor fundamentals exactly as delivered (shape-checked, never filled).
   Unknown shapes fall back to "unavailable" rather than guessing. */
import { Fragment } from "react";
import { Link } from "react-router";
import { fmtDate, fmtDateTimeIST, fmtPrice, humanize } from "../lib/format";
import type { CorporateAction, Fundamental } from "../types/api";
import { StatusBadge } from "./badges";
import { DataTable } from "./DataTable";
import { EmptyState, Unavailable } from "./states";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isArr = (v: unknown): v is unknown[] => Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : typeof v === "number" ? String(v) : null);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export const byType = (rows: Fundamental[], t: string) => rows.find((r) => r.statement_type === t) ?? null;

export function KnownAt({ f }: { f: Fundamental }) {
  return <span className="faint mono" style={{ fontSize: "var(--fs-2xs)" }}>snapshot known {fmtDateTimeIST(f.knowable_at)}</span>;
}

/** key_ratios: [{name, company_value, sector_value}] — values are the vendor's strings. */
export function KeyRatios({ f }: { f: Fundamental | null }) {
  if (!f || !isArr(f.payload)) return <Unavailable what="key ratios" capability="vendor key_ratios snapshot for this instrument" />;
  const rows = f.payload.filter(isObj).map((r) => ({ name: str(r.name) ?? "—", company: str(r.company_value), sector: str(r.sector_value) }));
  if (!rows.length) return <EmptyState title="The vendor returned no ratios." />;
  return (
    <DataTable rows={rows} rowKey={(r) => r.name} caption="Key ratios, company vs sector" columns={[
      { id: "name", header: "Ratio", sticky: true, cell: (r) => r.name },
      { id: "company", header: "Company", numeric: true, cell: (r) => <span className="num">{r.company ?? "—"}</span> },
      { id: "sector", header: "Sector", numeric: true, cell: (r) => <span className="num muted">{r.sector ?? "—"}</span> },
    ]} />
  );
}

/** Statement payload: { units_in, full_statement: [{particular, history: [{period, value}]}] } */
export function StatementTable({ f, title }: { f: Fundamental | null; title: string }) {
  if (!f || !isObj(f.payload)) return <Unavailable what={title} capability="vendor statement snapshot" />;
  const full = f.payload.full_statement;
  if (!isArr(full) || full.length === 0) return <EmptyState title={`${title}: no line items from the vendor.`} />;
  const lines = full.filter(isObj).map((l) => ({
    particular: str(l.particular) ?? "—",
    values: new Map((isArr(l.history) ? l.history.filter(isObj) : []).map((h) => [str(h.period) ?? "", numOrNull(h.value)])),
  }));
  const periods = [...new Set(lines.flatMap((l) => [...l.values.keys()]))].filter(Boolean);
  const units = str(f.payload.units_in);
  return (
    <div>
      <div className="toolbar" style={{ justifyContent: "space-between" }}>
        <span className="muted">{title}{units ? ` · ₹ ${units}` : ""}</span>
        <KnownAt f={f} />
      </div>
      <DataTable rows={lines} rowKey={(l) => l.particular} caption={title} columns={[
        { id: "particular", header: "Line item", sticky: true, cell: (l) => l.particular },
        ...periods.map((p) => ({ id: p, header: p, numeric: true,
          cell: (l: (typeof lines)[number]) => <span className="num">{fmtPrice(l.values.get(p) ?? null)}</span> })),
      ]} />
    </div>
  );
}

/** share_holdings: [{category, history: [{period, value(%)}]}] */
export function Shareholding({ f }: { f: Fundamental | null }) {
  if (!f || !isArr(f.payload)) return <Unavailable what="shareholding pattern" capability="vendor share_holdings snapshot" />;
  const cats = f.payload.filter(isObj).map((c) => ({
    category: humanize(str(c.category)),
    values: new Map((isArr(c.history) ? c.history.filter(isObj) : []).map((h) => [str(h.period) ?? "", numOrNull(h.value)])),
  }));
  const periods = [...new Set(cats.flatMap((c) => [...c.values.keys()]))].filter(Boolean);
  return (
    <DataTable rows={cats} rowKey={(c) => c.category} caption="Shareholding pattern (%)" columns={[
      { id: "category", header: "Holder", sticky: true, cell: (c) => c.category },
      ...periods.map((p) => ({ id: p, header: p, numeric: true,
        cell: (c: (typeof cats)[number]) => <span className="num">{c.values.get(p) !== undefined && c.values.get(p) !== null ? `${fmtPrice(c.values.get(p) ?? null)}%` : "—"}</span> })),
    ]} />
  );
}

/** competitors: [{instrument_key, sector, ...}] as listed by the vendor. */
export function Competitors({ f }: { f: Fundamental | null }) {
  if (!f || !isArr(f.payload)) return <Unavailable what="peers" capability="vendor competitors snapshot" />;
  const rows = f.payload.filter(isObj).map((c) => ({ key: str(c.instrument_key) ?? "", sector: str(c.sector),
    name: str(c.name) ?? str(c.company_name) ?? str(c.trading_symbol) })).filter((r) => r.key);
  if (!rows.length) return <EmptyState title="No peers listed by the vendor." />;
  return (
    <DataTable rows={rows} rowKey={(r) => r.key} caption="Peers (vendor list)" columns={[
      { id: "key", header: "Instrument", sticky: true,
        cell: (r) => <Link to={`/stocks/${encodeURIComponent(r.key)}`} className="symbol">{r.name ?? r.key}</Link> },
      { id: "sector", header: "Sector", cell: (r) => r.sector ?? "—" },
    ]} />
  );
}

export const FACTOR_HELP: Record<string, string> = {
  EXACT: "Adjustment factor proven from structured vendor fields (split: old/new face value; bonus a:b → (a+b)/b).",
  UNCERTAIN: "A factor exists but could not be proven exactly.",
  UNSUPPORTED: "No price factor: dividends never adjust prices; rights (premium not structured) and mergers are not modelled.",
  APPLIED: "The vendor's later history is already adjusted for this action (vendor-adjusted history detected).",
  NOT_APPLIED: "The vendor's later history shows the raw jump: not adjusted.",
  UNKNOWN: "Treatment could not be determined from the stored series.",
};

export function CorporateActionTable({ rows }: { rows: CorporateAction[] }) {
  if (!rows.length) return <EmptyState title="No corporate actions knowable for this instrument (the vendor feed is about 1 year deep)." />;
  const ratio = (r: CorporateAction) =>
    r.ratio_from !== null && r.ratio_to !== null ? `${r.ratio_from}:${r.ratio_to}`
      : r.face_value_before !== null && r.face_value_after !== null ? `FV ${r.face_value_before}→${r.face_value_after}` : "—";
  return (
    <DataTable rows={[...rows].sort((a, b) => (b.ex_date ?? "").localeCompare(a.ex_date ?? ""))} rowKey={(r) => String(r.id)}
      caption="Corporate actions" columns={[
        { id: "type", header: "Type", sticky: true, sortValue: (r) => r.action_type, cell: (r) => <span className="mono">{r.action_type}</span> },
        { id: "ex", header: "Ex-date", sortValue: (r) => r.ex_date, cell: (r) => <span className="mono">{fmtDate(r.ex_date)}</span> },
        { id: "record", header: "Record date", cell: (r) => <span className="mono faint">{fmtDate(r.record_date)}</span> },
        { id: "announced", header: "Announced", cell: (r) => <span className="mono faint">{fmtDate(r.announcement_date)}</span> },
        { id: "ratio", header: "Ratio / FV", cell: (r) => <span className="mono">{ratio(r)}</span> },
        { id: "amount", header: "Amount", numeric: true, cell: (r) => <span className="num">{r.amount !== null ? fmtPrice(r.amount) : "—"}</span> },
        { id: "status", header: "Factor status", cell: (r) => <StatusBadge status={r.factor_status} title={r.factor_status ? FACTOR_HELP[r.factor_status] : undefined} /> },
        { id: "factor", header: "Factor", numeric: true, cell: (r) => <span className="num">{r.factor_price !== null ? r.factor_price.toString() : "—"}</span> },
        { id: "vendor", header: "Vendor treatment", cell: (r) => <StatusBadge status={r.vendor_applied} title={r.vendor_applied ? FACTOR_HELP[r.vendor_applied] : undefined} /> },
        { id: "known", header: "Known", cell: (r) => <span className="mono faint">{fmtDateTimeIST(r.knowable_at)}</span> },
        { id: "payment", header: "Payment date", hiddenByDefault: true, cell: () => <span className="faint" title="not in the vendor feed">unavailable</span> },
      ]} />
  );
}

export function FactorLegend() {
  return (
    <dl className="kv" style={{ fontSize: "var(--fs-xs)" }}>
      {Object.entries(FACTOR_HELP).map(([k, v]) => (<Fragment key={k}><dt><StatusBadge status={k} /></dt><dd className="muted">{v}</dd></Fragment>))}
    </dl>
  );
}
