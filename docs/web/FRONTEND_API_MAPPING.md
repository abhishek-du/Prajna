# Web client: API mapping

**Plumbing.**
- Client: `web/src/api/http.ts` (GET only; 15 s timeout; cancellation; typed `ApiError` with a human message plus technical detail shown only in developer mode).
- Domain clients: `web/src/api/clients.ts`. Query hooks: `web/src/api/hooks.ts`.
- Types: `web/src/types/api.ts`, mirroring `backend/app/readapi/schemas.py`.
- Contract test: `src/api/contract.test.ts` checks the fixtures (typed with those types) against `mocks/openapi.json`, which is dumped from the read API.

| Client · function | Endpoint | Hook | Cache (staleTime) | Polls with auto-refresh | Used by |
|---|---|---|---|---|---|
| `marketApi.session` | `GET /v1/market/session` | `useSession` | 60 s | yes | top bar, Overview, Markets |
| `marketApi.latest` (via `MarketDataProvider`) | `GET /v1/latest?keys=` (≤ 200) | `useLatest` | 60 s | yes | indices, screener page, sectors, watchlist, search, stock header |
| `marketApi.quote` | `GET /v1/instruments/{key}/quote` | `useQuote` | 60 s | yes | stock header (latest stored 1m bar) |
| `instrumentApi.list` | `GET /v1/instruments` | `useInstruments` | 10 min | no | screener, sector constituents, indices |
| `instrumentApi.search` | `GET /v1/search` | `useSearch` | 10 min | no | global search, screener text filter, news / data-quality symbol lookup |
| `instrumentApi.profile` | `GET /v1/instruments/{key}/profile` | `useProfile` | 10 min | no | stock workspace |
| `instrumentApi.quality` | `GET /v1/instruments/{key}/quality` | `useQuality` | 30 s | no | chart gap badge, data-quality tab, diagnostics |
| `chartApi.candles` (via `MarketDataProvider`) | `GET /v1/instruments/{key}/candles` | `useCandles` | 60 s | no | chart |
| `fundamentalApi.all` | `GET /v1/instruments/{key}/fundamentals` | `useFundamentals` | 10 min | no | overview / fundamentals / financials tabs |
| `fundamentalApi.corporateActions` | `GET /v1/instruments/{key}/corporate-actions` | `useCorporateActions` | 10 min | no | corporate-actions tab, diagnostics |
| `newsApi.list` | `GET /v1/news` | `useNews` | 60 s | yes | Overview, News, stock news tab |
| `sectorApi.list` | `GET /v1/sectors` | `useSectors` | 10 min | no | Overview, Sectors, screener filter, search |
| `globalApi.list` | `GET /v1/global` | `useGlobal` | 60 s | yes | global table, data quality |
| `globalApi.candles` | `GET /v1/global/{key}/candles` | `useQueries` (2 labels each) | 60 s | no | change between confirmed labels |
| `globalApi.finality` | `GET /v1/global/{key}/finality` | `useGlobalFinality` | 30 s | no | label history, finality summary |
| `operationsApi.freshness` | `GET /v1/freshness` | `useFreshness` | 30 s | yes | sidebar footer, data health, operations |
| `operationsApi.pipeline` | `GET /v1/pipeline/status` | `usePipeline` | 30 s | yes | operations, events menu |
| `acceptanceApi.get` | `GET /v1/acceptance` | `useAcceptance` | 30 s | no | acceptance, operations |

**Retry policy:** a 4xx is final; other failures retry twice. There is no refetch on window focus.

**Rate:** at most one request per endpoint per refresh interval (Off / 30 s / 1 min / 5 min). Reference data never polls.

## Missing backend capabilities (the UI shows "Data unavailable" and names these)

| # | Capability | Needed for | Suggested contract |
|---|---|---|---|
| 1 | universe-wide latest-price aggregate | market breadth, top movers, sector advance/decline or performance | `GET /v1/market/breadth?as_of=`, `GET /v1/market/movers?by=change_pct\|volume&limit=` |
| 2 | server-side sort / filter by price and fundamentals over the universe | screener price and fundamental columns beyond the visible page | `GET /v1/screener?sort=&filters=` over a materialised latest-price + ratios table |
| 3 | company market capitalisation | header, screener | not supplied by the vendor today (only a sector-level figure) |
| 4 | 52-week high/low | header, screener | derived endpoint over 1D bars, with the basis stated |
| 5 | live ticks | real-time quotes, intraday streaming | a canonical live tick store (Stage 1 criterion L is OUT_OF_SCOPE), exposed via SSE/WebSocket; `LiveTickProvider` plugs in |
| 6 | news publisher / category / market-wide news | news filters | vendor supplies neither; all news is instrument-linked |
| 7 | corporate-action payment date | corporate-actions table | not in the vendor feed |
| 8 | faster `/v1/global` | global table first paint | `/v1/global` takes about 1.1 s (the `global_bar_finality` view is evaluated over every global bar); materialise finality |
| 9 | 5m candles | chart | OUT_OF_SCOPE (decision D2-5m) |
