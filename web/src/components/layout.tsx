import type { ReactNode } from "react";

export function Panel({ title, aside, children, note, flush, id }: {
  title: ReactNode; aside?: ReactNode; children: ReactNode; note?: ReactNode; flush?: boolean; id?: string;
}) {
  return (
    <section className="panel" aria-labelledby={id}>
      <div className="panel-head">
        <h3 id={id}>{title}</h3>
        {aside && <div className="aside">{aside}</div>}
      </div>
      <div className={`panel-body${flush ? " flush" : ""}`}>{children}</div>
      {note && <div className="panel-note">{note}</div>}
    </section>
  );
}

export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="inline">{actions}</div>}
    </div>
  );
}

export function Metric({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="metric-grid">{children}</div>;
}
