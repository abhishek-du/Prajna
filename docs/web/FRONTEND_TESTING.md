# Web client: testing

```bash
cd web
npx tsc -b --noEmit        # strict type check (src, mocks, e2e)
npx vitest run             # unit, component, route, API-mocking, contract and boundary tests
npx vite build             # production build
# E2E against the real read API (read-only) through the production preview:
(cd ../backend && .venv/bin/python -m app.readapi --port 8090) &
npx vite preview --port 4173 &
npx playwright test        # uses the system Google Chrome (channel "chrome")
```

## Suites

| Suite | File | What it proves |
|---|---|---|
| Routes (26) | `src/app.routes.test.tsx` | every route loads its screen, including not-found; no route renders Stage 3 wording (BUY / SELL / LONG / SHORT / ENTRY / EXIT / TARGET / STOP LOSS / SIGNAL SCORE / AI SIGNAL / PREDICTION / PROBABILITY), a "LIVE" claim, or credential material |
| Shell (2) | `src/app.routes.test.tsx` | the top bar labels data "Latest stored"; navigation lists every section |
| Behaviour (15) | `src/app.behaviour.test.tsx` | see below |
| Freshness / Change (5) | `src/components/badges.test.tsx` | configurable per-kind thresholds; direction never by colour alone; withheld change renders "—" with its reason |
| Contract (18) | `src/api/contract.test.ts` | every fixture satisfies the read-API OpenAPI schema (field names and required fields); every endpoint the client calls exists |
| Boundaries (4) | `src/app.boundaries.test.ts` | application code never imports `mocks/`; only GET is issued; no credential material in the source; no `Math.random` |
| E2E (7) | `e2e/journey.spec.ts` | see below |

**Behaviour cases:**
- a 500 renders a human message and Retry, with no raw status;
- an unreachable API is reported as such;
- empty states render;
- missing capabilities render "unavailable" with the capability named;
- an empty watchlist explains itself;
- Ctrl+K search: RELIANCE shows its stored price, and Enter navigates;
- Escape closes search;
- the stock header shows "Latest stored" with session and freshness;
- chart: switching timeframe requests that timeframe; 5m is disabled with its reason;
- chart: a timeframe with no bars says why;
- a change the API flags as not comparable is withheld;
- revised and placeholder global labels render WITHHELD without values;
- global dates render as vendor labels;
- Stage 3 renders LOCKED with the gate's reason;
- operations show only the token age.

**E2E cases:**
- the 12-step journey on real data: overview → search RELIANCE → stock → chart (a canvas is rendered; 5m disabled) → 15m → fundamentals → corporate actions → news → data quality (CHAVDA CA_ADJUSTMENT) → operations → acceptance → Stage 3 locked;
- no page error;
- no data badge claims "Live";
- global label history (revised rows WITHHELD);
- responsive smoke at 1440 / 1280 / 1024 / 768 / 390 px over 5 screens: the page body never scrolls horizontally.

## Environment notes

- **E2E browser.** Playwright's own Chromium download failed TLS verification on this network ("self-signed certificate in certificate chain"). Verification was not disabled; the system Google Chrome is used instead (`channel: "chrome"`).
- **Chart testing.** jsdom has no canvas, so unit tests replace `CandlestickChart` with a marker that reports the bar count. The real chart is covered by the E2E test.
