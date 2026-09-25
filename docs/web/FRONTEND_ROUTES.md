# Web client: routes

All routes are lazy-loaded chunks under the `AppShell`. `:key` is the URL-encoded `instrument_key`.

| Route | Screen | What it shows (all from `/v1`) | URL state | Shown as unavailable |
|---|---|---|---|---|
| `/` | redirect to `/overview` | | | |
| `/overview` | Overview | market session (calendar state); Indian indices (latest stored 1D close, change withheld when not comparable); global snapshot (confirmed labels only); data health (freshness per dataset); sectors (counts); latest news | | market breadth; top movers |
| `/markets` | Markets | session; indices; full global table | | breadth; live index ticks |
| `/stocks` | Screener | server-paged instrument list (class / sector / listing filters, text search), latest stored close / change / volume / session / freshness / basis for the visible page; column selector; density; saved views | `q`, `class`, `sector`, `listing`, `size`, `page` | market cap, P/E, P/B, ROE, ROCE, dividend yield, 52-week range as columns; universe-wide sort by price |
| `/stocks/:key` | Equity workspace | header: name, symbol, exchange, segment, type, class, ISIN, sector, lifecycle, latest stored 1D close + change + session + freshness, latest stored 1m bar with its knowable time, watchlist toggle | `tab` | |
| `…?tab=overview` | | latest stored session metrics, price basis, company description, key ratios, classification (sector market cap is the vendor's *sector* value), lifecycle periods | | company market cap |
| `…?tab=chart` | Chart | candles + volume (1m / 15m / 1h / 1D; 5m disabled: OUT_OF_SCOPE), adjusted toggle (withheld rows counted), crosshair legend with OHLCV, time, knowable_at and basis, coverage-gap badge | `tf`, `adj` | live bars |
| `…?tab=fundamentals` | | vendor key ratios vs sector, shareholding pattern, peers (vendor list) | | growth, margin, debt and cash ratios the vendor does not list |
| `…?tab=financials` | | income (yearly / quarterly), balance sheet, cash flow; consolidated / standalone | `basis`, `period` | |
| `…?tab=corporate-actions` | | actions with ex / record / announced dates, ratio / face value, amount, factor status, factor, vendor treatment, knowable time; status legend | | payment date |
| `…?tab=news` | | instrument news with published vs received | | |
| `…?tab=data-quality` | | coverage per timeframe, price basis mix, vendor revisions by class, quarantine, provenance | | |
| `/sectors` | Sectors | sector list with counts and share | | sector performance, sector fundamentals aggregates |
| `/sectors/:sector` | Sector | constituents (ACTIVE stocks) with latest stored prices | | |
| `/global` | Global markets | grouped Asia / Europe / US / FX & commodities / India offshore; vendor label, close, change between confirmed labels, finality, known, label semantics; per-instrument label history with REVISED / PLACEHOLDER / UNCONFIRMED shown as WITHHELD | | |
| `/news` | News research | list or timeline; symbol and "published since" filters; median latency | `symbol`, `since`, `mode` | source / category filters |
| `/watchlist` | Watchlist | locally saved instruments with latest stored prices | | server-side watchlists |
| `/data-quality` | Data quality | freshness per dataset, global finality summary, instrument diagnostics (default CHAVDA: the real CA_ADJUSTMENT case) with corporate-action treatment | `symbol` | |
| `/operations` | Operations | snapshot, running runs, candles lock, token **age**, disk, Stage 1/2 overall + Stage 3 status, jobs (24 h), runbook markers, freshness | | |
| `/operations/acceptance` | Acceptance | Stage 1 and Stage 2 criteria with gate statuses; Stage 3 **LOCKED** with the reason | | |
| `*` | Not found | | | |
