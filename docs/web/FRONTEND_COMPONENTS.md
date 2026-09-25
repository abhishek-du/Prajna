# Web client: components

**Design tokens:** `web/src/styles/tokens.css`
- dark-first, with a light theme via `data-theme`;
- spacing on a 4 px grid;
- type scale; radius; border; surface; text / muted / faint;
- semantic tones: positive, negative, warning, info, accent;
- chart colours; motion durations, which go to 0 under `prefers-reduced-motion`.

**Styles:** `web/src/styles/app.css`. Components use only these tokens.

| Component | File | Purpose |
|---|---|---|
| `AppShell`, `Sidebar` (collapsible, footer: API · last ingest · env · version), `Topbar`, `MarketStatus`, `Clock`, `RefreshControl`, `EventsMenu`, `SettingsMenu`, mobile bottom navigation | `components/shell/AppShell.tsx` | application frame |
| `GlobalSearch` (Ctrl/Cmd+K, arrows, Enter, Escape; symbol / name / ISIN / sector; latest stored price + freshness) | `components/shell/GlobalSearch.tsx` | command search |
| `Panel`, `PageHead`, `Metric`, `MetricGrid` | `components/layout.tsx` | layout primitives |
| `DataTable` (sticky header and first column, sort of the loaded rows, column selector, density, keyboard row activation, virtualisation beyond 150 rows), `ColumnSelector`, `DensityControl` | `components/DataTable.tsx` | tables |
| `FreshnessBadge`, `StatusBadge`, `Badge`, `Change` (▲/▼ + sign + colour + screen-reader text) | `components/badges.tsx` | status and freshness |
| `Skeleton`, `TableSkeleton`, `EmptyState`, `ErrorState` (human message, Retry, developer details), `Unavailable` (names the missing capability), `QueryState` | `components/states.tsx` | data states |
| `CandlestickChart` (Lightweight Charts, price and volume panes, IST axis, crosshair legend) | `components/charts/CandlestickChart.tsx` | chart rendering |
| `ChartPanel`, `TimeframeSelector` | `components/charts/ChartPanel.tsx` | chart states, timeframe and adjustment |
| `KeyRatios`, `StatementTable`, `Shareholding`, `Competitors`, `CorporateActionTable`, `FactorLegend` | `components/fundamentals.tsx` | fundamentals and corporate actions (shape-checked vendor payloads) |
| `NewsList`, `NewsRow` (published / received / latency / source) | `components/news.tsx` | news |
| `PricedInstrumentTable`, `instrumentColumns`, `priceColumns`, `joinPrices` | `components/market.tsx` | instrument and price tables |
| `GlobalTable`, `useGlobalBoard`, `globalColumns` | `components/global.tsx` | global markets |
| `DataQualityPanel` | `components/quality.tsx` | coverage, basis, revisions, provenance |
| `MarketDataProvider` (`StoredBarProvider`; `LiveTickProvider` placeholder) | `providers/marketData.tsx` | the price / bars seam |
| `SettingsProvider`, `useRefetchInterval` | `providers/settings.tsx` | UI state (refresh, theme, sidebar, density, developer mode) |
| `useWatchlist` | `lib/watchlist.ts` | local watchlist (metadata only; prices always fetched) |

## Brief components mapped to the implementation

| Brief component | Implementation |
|---|---|
| `DataTableToolbar` | `DataTable` `toolbar` slot |
| `FilterBar` | screener and news toolbars |
| `DateRangePicker` | the news "published since" date input (the API supports `since` only) |
| `VolumeChart` | the volume pane of `CandlestickChart` |
| `NewsCard` | `NewsRow` |
| `FundamentalTable` | `KeyRatios` + `StatementTable` |
| `SectorTable` | the Sectors route table |
| `InstrumentHeader` | inside `routes/StockDetail.tsx` |
| `Timeline` | inside `routes/News.tsx` |
| `AcceptanceTable` | `StageTable` in `routes/Acceptance.tsx` |
