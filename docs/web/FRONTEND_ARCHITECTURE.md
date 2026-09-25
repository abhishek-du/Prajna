# Prajna web client: architecture

- **Code:** `web/`. It is a new application; `frontend/` is another tool's work and is not used or modified.
- **Backend:** the read API `backend/app/readapi` (`/v1`, contract `docs/API_CONTRACT.md`).
- **Audited 2026-09-25:**
  - read API: 17 endpoints;
  - data: 3,532 canonical instruments (3 indices); 1m/15m/1h/1d candles; 12 fundamentals statement types; corporate actions with versioned factors; 13 global instruments under the finality contract; news with published vs received time; freshness, pipeline and acceptance.

## 1. Non-negotiables (from the data contracts)

1. **No fabricated data.** Every financial value comes from `/v1`. What the API lacks is shown as **"Data unavailable"** together with the missing backend capability (see §9). Fixtures live only in `web/mocks/` and are imported only by tests.
2. **Stored is not live.** Stage 1 has no live tick store, so no screen says "LIVE". Prices are labelled **"Latest stored"** with their `knowable_at` / session date and a `FreshnessBadge`.
3. **Point-in-time.**
   - `knowable_at` is when Prajna knew a value (its fetch), never the bar end.
   - `as_of` is supported by the API client. The UI works "now" by default, and an `as_of` query parameter is carried by the chart and fundamentals routes for research.
4. **Vendor labels are not trading dates** (global). Global rows show the vendor label, the finality state, and the label-semantics note.
5. **Withheld is visible.** REVISED / PLACEHOLDER / UNCONFIRMED global labels are shown as **withheld**, with their reason and no values.
6. **Price basis and adjustment are visible.**
   - Candles carry `price_basis` (RAW_OBSERVED / VENDOR_ADJUSTED) and `basis_as_of`.
   - A daily change across a split/bonus is **not** shown as a move (`comparable=false` from `/v1/latest`).
7. **Stage 3 is locked.** No signal, target, prediction or indicator exists in this client. The only Stage 3 surface is a status line reading "Stage 3 Locked", taken from `/v1/acceptance`.
8. **Read-only and secret-free.** The client only issues `GET`s to `/v1`, never holds a credential, and only renders the token *age* reported by the API.

## 2. Stack

| Concern | Choice | Why |
|---|---|---|
| Build | Vite + React 19 + TypeScript (strict, no `any`) | fast, code-splittable |
| Routing | React Router (data-agnostic, lazy routes) | route-level code splitting |
| Server state | TanStack Query | caching, cancellation, refetch interval; server state kept out of UI state |
| UI state | React context (sidebar, refresh interval, theme); `localStorage` (watchlist, preferences); URL (filters, tab, timeframe) | no global store |
| Charts | TradingView Lightweight Charts v5 | canvas rendering for thousands of candles; no DOM per candle |
| Tables | own `DataTable` + `@tanstack/react-virtual` for long lists | sticky header and first column, density control |
| Styling | CSS custom-property tokens (`src/styles/tokens.css`) + plain CSS | no utility framework; one token source |
| Tests | Vitest + Testing Library + MSW (fixtures in `web/mocks/`); Playwright E2E against the real read API | |

## 3. Route map

| Route | Screen | Main endpoints |
|---|---|---|
| `/overview` | session, indices, sectors, global, news, data health | `/market/session`, `/instruments?segment=NSE_INDEX`, `/latest`, `/sectors`, `/global`, `/news`, `/freshness` |
| `/markets` | Indian indices + session + global snapshot | `/market/session`, `/latest`, `/global` |
| `/stocks` | screener table (server-paged) | `/instruments`, `/latest` (visible page) |
| `/stocks/:key` | equity workspace; tabs Overview · Chart · Fundamentals · Financials · Corporate actions · News · Data quality | `/profile`, `/latest`, `/quote`, `/candles`, `/fundamentals`, `/corporate-actions`, `/news`, `/quality` |
| `/sectors`, `/sectors/:sector` | sector list; constituents | `/sectors`, `/instruments?sector=`, `/latest` |
| `/global` | global instruments grouped Asia / Europe / US / FX & commodities; finality history | `/global`, `/global/{key}/candles`, `/global/{key}/finality` |
| `/news` | news research (date and symbol filters, timeline) | `/news` |
| `/watchlist` | locally persisted list | `/latest` |
| `/data-quality` | freshness, global finality, per-instrument diagnostics | `/freshness`, `/global/{key}/finality`, `/quality`, `/corporate-actions`, `/candles` |
| `/operations` | jobs, runs, lock, token age, disk, markers | `/pipeline/status`, `/freshness` |
| `/operations/acceptance` | Stage 1 / 2 criteria, Stage 3 LOCKED | `/acceptance` |

`:key` is the URL-encoded `instrument_key`, for example `/stocks/NSE_EQ%7CINE002A01018`.

## 4. Component hierarchy

```
AppShell
├─ Sidebar (collapsible; compact on tablet; drawer on mobile) + footer
│  (API status · data timestamp · env · version)
├─ Topbar: GlobalSearch (Ctrl/Cmd+K) · MarketStatus · clock (IST) ·
│  RefreshControl · EventsMenu (runbook markers) · SettingsMenu
└─ <Outlet/> (lazy route)
   Shared: DataTable(+Toolbar, ColumnSelector) · FilterBar · Metric/MetricGrid ·
   FreshnessBadge · StatusBadge · Change (▲/▼ + sign + colour) · EmptyState ·
   ErrorState · Unavailable (names the missing capability) · Skeleton ·
   ChartContainer · CandlestickChart (price + volume panes) · NewsList/NewsItem ·
   FundamentalTable · StatementTable · CorporateActionTable · SectorTable ·
   InstrumentHeader · Timeline · DataQualityPanel · AcceptanceTable
```

## 5. Data layer

- **`src/api/http.ts`:** one `request()`.
  - Base URL from `VITE_API_BASE` (default `/v1`, proxied in development).
  - Timeout 15 s; `AbortSignal` from TanStack Query.
  - The envelope is unwrapped.
  - Errors are typed (`ApiError` with status, human message and technical detail).
- **Domain clients:** `marketApi`, `instrumentApi`, `chartApi`, `fundamentalApi`, `newsApi`, `sectorApi`, `globalApi`, `operationsApi`, `acceptanceApi`.
- **Types:** `src/types/api.ts` mirrors `backend/app/readapi/schemas.py` field for field, and is checked by a contract test against the served OpenAPI document.
- **`MarketDataProvider`:**
  - interface `{ mode, latest(keys), candles(...) }`;
  - `StoredBarProvider` (today; mode `STORED`);
  - `LiveTickProvider`, a placeholder that reports "not available in Stage 1" and is never selected.
  - A future live source plugs in without touching screens.

## 6. Caching, refresh, freshness

| Kind | staleTime |
|---|---|
| reference data (instrument lists, sectors, profile, fundamentals, corporate actions) | 10 min |
| prices and candles | 60 s |
| operations | 30 s |

- **Auto-refresh:** Off / 30 s / 1 min / 5 min, chosen globally. It applies only to price, operations and news queries; reference data never polls. The last refresh is shown in IST.
- **`FreshnessBadge(timestamp, kind)`** thresholds live in `src/config/freshness.ts`, per data kind (intraday / daily / global / news / ops). They are never hard-coded in components.

## 7. States

Every data component renders one of:
- **skeleton**, with the same geometry as the real component;
- **empty**, which says why;
- **error**, with a human sentence, a Retry button, and technical details in developer mode;
- **stale**, the data plus a stale badge;
- **unavailable**, naming the missing capability.

Chart-specific states: loading, no data, partial (coverage gap), withheld / revised (global), "latest stored".

## 8. Responsive, accessibility, motion

- **Breakpoints:**
  - ≥ 1280 full sidebar;
  - 1024–1279 icon sidebar;
  - 768–1023 icon sidebar with stacked panels;
  - < 768 bottom navigation plus a drawer.
- **Tables** scroll horizontally with a sticky first column. Charts resize via `ResizeObserver`.
- **Accessibility:** keyboard-reachable everything, visible focus rings, ARIA on navigation, dialogs, tabs and tables. Direction is conveyed by ▲/▼ and sign as well as colour.
- **Motion:** subtle transitions only (sidebar, panel appearance); `prefers-reduced-motion` disables them.
- **Theme:** dark-first tokens, with a light theme via `data-theme`.

## 9. Missing backend capabilities (rendered as "Data unavailable")

| UI need | Status |
|---|---|
| live ticks / real-time quote | no live tick store (Stage 1 L OUT_OF_SCOPE) |
| market breadth, top movers, sector advance/decline or performance | no universe-wide latest-price aggregate |
| screener price columns beyond the visible page, sorting by price or fundamentals | `/latest` is per-key (≤ 200); `/instruments` sorts by symbol only |
| screener fundamentals columns (P/E, P/B, ROE, ROCE; market cap) | fundamentals are per instrument only; market cap is not provided |
| 52-week high/low | not derived (computable client-side from 1d candles on the stock page only) |
| news source / category / Indian-vs-global filters | `publisher` is empty from the vendor; no category; all news is instrument-linked |
| 5m candles | OUT_OF_SCOPE (decision D2-5m); shown disabled |
| corporate-action payment date | not in the vendor feed |

## 10. Stage 3 boundary

The client contains no BUY/SELL/LONG/SHORT/entry/exit/target/stop-loss/score/signal/prediction/probability wording or fields. A test asserts that none of these words appear in any rendered route. `/operations/acceptance` shows Stage 3 **LOCKED** with the reason supplied by the API.
