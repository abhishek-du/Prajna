import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router";
import { useFreshness, usePipeline, useSession } from "../../api/hooks";
import { APP_ENV, APP_VERSION, REFRESH_OPTIONS } from "../../config/data";
import { fmtDateTimeIST, fmtShortIST, fmtTimeIST } from "../../lib/format";
import { useMarketData } from "../../providers/marketData";
import { useSettings } from "../../providers/settings";
import { Badge, StatusBadge } from "../badges";
import {
  BrandMark, IconBell, IconGlobal, IconMarkets, IconNews, IconOps, IconOverview, IconQuality, IconSectors,
  IconSettings, IconStocks, IconWatch,
} from "../icons";
import { TableSkeleton } from "../states";
import { GlobalSearch } from "./GlobalSearch";

export const NAV = [
  { to: "/overview", label: "Overview", Icon: IconOverview },
  { to: "/markets", label: "Markets", Icon: IconMarkets },
  { to: "/stocks", label: "Stocks", Icon: IconStocks },
  { to: "/sectors", label: "Sectors", Icon: IconSectors },
  { to: "/global", label: "Global", Icon: IconGlobal },
  { to: "/news", label: "News", Icon: IconNews },
  { to: "/watchlist", label: "Watchlist", Icon: IconWatch },
  { to: "/data-quality", label: "Data Quality", Icon: IconQuality },
  { to: "/operations", label: "Operations", Icon: IconOps },
] as const;

function SidebarFooter() {
  const f = useFreshness();
  const latest = f.data?.data
    .map((x) => x.last_complete_run_finished)
    .filter((x): x is string => !!x)
    .sort()
    .at(-1);
  return (
    <div className="sidebar-footer">
      <dl>
        <dt>API</dt>
        <dd>{f.isPending ? "…" : f.isError ? <span style={{ color: "var(--negative)" }}>unreachable</span> : "reachable"}</dd>
        <dt>Last ingest</dt>
        <dd title={latest ? fmtDateTimeIST(latest) : undefined}>{fmtShortIST(latest)}</dd>
        <dt>Env</dt>
        <dd>{APP_ENV}</dd>
        <dt>Version</dt>
        <dd>{APP_VERSION}</dd>
      </dl>
    </div>
  );
}

function Sidebar() {
  const { settings, update } = useSettings();
  return (
    <nav className="sidebar" aria-label="Primary">
      <div className="brand"><BrandMark /><span className="brand-text">PRAJNA</span></div>
      <ul className="nav">
        {NAV.map(({ to, label, Icon }) => (
          <li key={to}>
            <NavLink to={to} title={label}><Icon /><span className="nav-label">{label}</span></NavLink>
          </li>
        ))}
      </ul>
      <SidebarFooter />
      <div style={{ padding: "0 var(--sp-5) var(--sp-4)" }}>
        <button type="button" className="collapse-btn" aria-pressed={settings.sidebarCollapsed}
          onClick={() => update({ sidebarCollapsed: !settings.sidebarCollapsed })}>
          {settings.sidebarCollapsed ? "»" : "« Collapse"}
          <span className="sr-only"> sidebar</span>
        </button>
      </div>
    </nav>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="mono muted hide-sm" style={{ fontSize: "var(--fs-xs)" }}>{fmtTimeIST(now)}</span>;
}

/** Calendar state only: never claims a live feed. */
export function MarketStatus() {
  const s = useSession();
  const md = useMarketData();
  if (s.isPending) return <span className="badge tone-neutral plain">Session …</span>;
  if (s.isError || !s.data) return <Badge tone="neutral" plain>Session unavailable</Badge>;
  const d = s.data.data;
  const label = d.state === "NON_TRADING_DAY" ? `${d.session_type.toLowerCase()} — market closed` : `NSE ${d.state.replace("_", "-").toLowerCase()}`;
  return (
    <span className="inline" title={`Calendar ${d.date}: ${d.open_ist ?? "—"}–${d.close_ist ?? "—"} IST. Calendar state, not a data-feed status.`}>
      <StatusBadge status={d.state === "OPEN" ? "OPEN" : d.state} />
      <span className="hide-sm muted" style={{ fontSize: "var(--fs-xs)" }}>{label}</span>
      <Badge tone="info" plain title="Stage 1 has no live tick store">{md.label}</Badge>
    </span>
  );
}

function RefreshControl() {
  const { settings, update, lastRefreshed } = useSettings();
  return (
    <label className="field hide-sm" title="Auto-refresh for prices, news and operations (reference data never polls)">
      Refresh
      <select className="select" value={settings.refreshSeconds} onChange={(e) => update({ refreshSeconds: Number(e.target.value) })}>
        {REFRESH_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <span className="mono faint" data-testid="last-refreshed">{lastRefreshed ? fmtTimeIST(lastRefreshed) : "—"}</span>
    </label>
  );
}

function EventsMenu() {
  const [open, setOpen] = useState(false);
  const p = usePipeline();
  const markers = p.data?.data.recent_markers ?? [];
  return (
    <div className="menu-wrap">
      <button type="button" className="btn ghost" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((o) => !o)} title="Pipeline events">
        <IconBell /><span className="sr-only">Pipeline events</span>
      </button>
      {open && (
        <div className="menu" role="dialog" aria-label="Pipeline events" style={{ width: 460, maxHeight: 360, overflow: "auto" }}
          onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>
          {p.isPending ? <TableSkeleton rows={4} cols={1} /> : markers.length === 0 ? <span className="muted">No recent runbook markers.</span> :
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 6 }}>
              {[...markers].reverse().map((m, i) => <li key={i} className="mono" style={{ fontSize: "var(--fs-2xs)", overflowWrap: "anywhere" }}>{m}</li>)}
            </ul>}
        </div>
      )}
    </div>
  );
}

function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const { settings, update } = useSettings();
  return (
    <div className="menu-wrap">
      <button type="button" className="btn ghost" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((o) => !o)} title="Settings">
        <IconSettings /><span className="sr-only">Settings</span>
      </button>
      {open && (
        <div className="menu" role="dialog" aria-label="Settings" onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>
          <div className="stack">
            <label className="field">Theme
              <select className="select" value={settings.theme} onChange={(e) => update({ theme: e.target.value as "dark" | "light" })}>
                <option value="dark">Dark</option><option value="light">Light</option>
              </select>
            </label>
            <label className="field">
              <input type="checkbox" checked={settings.developerMode} onChange={(e) => update({ developerMode: e.target.checked })} />
              Developer mode (technical error details)
            </label>
            <span className="faint" style={{ fontSize: "var(--fs-2xs)" }}>Read-only client. No credentials are stored or shown.</span>
          </div>
        </div>
      )}
    </div>
  );
}

export function AppShell() {
  const { settings } = useSettings();
  return (
    <div className="shell" data-collapsed={settings.sidebarCollapsed}>
      <Sidebar />
      <header className="topbar" aria-label="Top bar">
        <GlobalSearch />
        <span className="topbar-spacer" />
        <MarketStatus />
        <Clock />
        <RefreshControl />
        <EventsMenu />
        <SettingsMenu />
      </header>
      <main className="main" id="main">
        <Suspense fallback={<div className="page"><TableSkeleton rows={10} /></div>}>
          <Outlet />
        </Suspense>
      </main>
      <nav className="mobile-nav" aria-label="Primary (mobile)">
        {NAV.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to}><Icon /><span>{label}</span></NavLink>
        ))}
      </nav>
    </div>
  );
}
