# Prajna read API: contract (v1)

- **Code:** `backend/app/readapi/` (FastAPI).
- **Machine-readable schema:** `GET /v1/openapi.json`; interactive docs at `/v1/docs`.
- **Tests:** `backend/tests/stage2/test_api.py`.
- **Status:** implemented, tested on the Stage 2 seed world, smoke-tested read-only against production on 2026-09-25. **Not deployed as a service** (no cron or systemd entry). Serving it is an explicit operational decision.

```bash
cd backend
.venv/bin/python -m app.readapi --host 127.0.0.1 --port 8090
# browser clients on another origin:
PRAJNA_API_CORS_ORIGINS=http://localhost:5173 .venv/bin/python -m app.readapi
```

## Principles

1. **Read-only.**
   - Every request runs in a `READ ONLY` transaction.
   - Every route is `GET`; there is no write endpoint.
2. **Point-in-time (PIT).**
   - Data reads take an optional `as_of` (ISO-8601 **with** offset; a naive timestamp is rejected with 422). The default is now.
   - Only rows with `knowable_at < as_of` are returned (`app.canon.pit`, re-checked per row).
   - `meta.point_in_time` says whether an answer is PIT or the current state.
3. **`knowable_at` is when Prajna knew a value**, its fetch, never the bar end or an assumed settlement time.
   - Timing finality (bar end + completion margin, decision TIMING-B2) is a separate concept and never moves `knowable_at`.
4. **Nothing is filled.** A missing bar is absent. `/quality` (coverage) and `/freshness` say why.
5. **Frontend-agnostic.**
   - Resources mirror the canonical data, not a particular screen.
   - No indicators, signals or decisions: Stage 3 is LOCKED.
6. **Honest labels:**
   - `/quote` is the latest *stored* bar, not a live tick (no live tick store in Stage 1; criterion L is OUT_OF_SCOPE);
   - global `label_date` is the vendor's label, not necessarily a trading date;
   - `instrument.sector` is today's sector, and `profile.sector_as_of` is the PIT one.
7. **Security.**
   - The server binds to `127.0.0.1` by default.
   - Exposing it beyond localhost needs an authenticating reverse proxy.
   - No endpoint returns a credential: `/pipeline/status` reports only the token's age.

## Envelope (every response)

```json
{"data": ...,
 "meta": {"as_of": "2026-09-25T10:00:00Z", "generated_at": "...", "point_in_time": true,
          "knowledge_rule": "knowable_at < as_of", "notes": ["..."]}}
```

**Types:**
- Timestamps are ISO-8601 UTC.
- Market dates are `YYYY-MM-DD` (IST session).
- Prices and volumes are JSON numbers.

**Instrument keys** contain `|` (for example `NSE_EQ|INE002A01018`, `NSE_INDEX|Nifty 50`) and must be URL-encoded in paths (`NSE_EQ%7CINE002A01018`).

**Errors:**
- `422`: bad parameter (for example timeframe `5m`, which is out of scope, or a naive `as_of`).
- `404`: unknown or excluded instrument.

## Endpoints (the 14 contract areas)

| # | Area | Endpoint | PIT | Notes |
|---|---|---|---|---|
| 1 | Instruments | `GET /v1/instruments?segment=&security_class=&lifecycle_status=ACTIVE&limit=&offset=` | no (current universe) | `security_class`: STOCK / FUND_UNIT / RIGHTS_ENTITLEMENT / OTHER; lifecycle: ACTIVE / INELIGIBLE / REMOVED_FROM_MASTER / VENDOR_REJECTED |
| 2 | Stock search | `GET /v1/search?q=&limit=` | no | ranked SYMBOL_EXACT > SYMBOL_PREFIX > ISIN > NAME; ACTIVE first |
| 3 | Stock profile | `GET /v1/instruments/{key}/profile?as_of=` | yes | security-class signals, lifecycle periods (knowable before as_of), latest vendor profile payload |
| 4 | OHLCV | `GET /v1/instruments/{key}/candles?timeframe=1m\|15m\|1h\|1d&start=&end=&limit=&as_of=&adjusted=false&allow_low_confidence=false` | yes | each candle carries `knowable_at`, `fetched_at`, `price_basis` (RAW_OBSERVED / VENDOR_ADJUSTED), `basis_as_of`. `adjusted=true`: split/bonus-adjusted as known at as_of; low-confidence or reconstructed rows withheld and counted in `refused` |
| 5 | Latest quote | `GET /v1/instruments/{key}/quote?as_of=` | yes | last 1m and 1d stored bars + `age_seconds`; **not real-time** |
| 6 | Fundamentals | `GET /v1/instruments/{key}/fundamentals?statement_type=&as_of=` | yes | latest snapshot per statement type (vendor payload verbatim) |
| 7 | Corporate actions | `GET /v1/instruments/{key}/corporate-actions?as_of=` | yes | with the versioned factor (`factor_status` EXACT / UNCERTAIN / UNSUPPORTED, `factor_price`, `vendor_applied`) |
| 8 | Sector classification | `GET /v1/sectors`; `sector` on instruments; `sector_as_of` on the profile | current / PIT | sector counts over ACTIVE STOCKs |
| 9 | Global markets | `GET /v1/global?as_of=`, `GET /v1/global/{key}/candles?as_of=&limit=` | yes | only CONFIRMED / CONFIRMED_BY_AGE bars; revised, placeholder and unconfirmed bars are never exposed; per-instrument `label_semantics` |
| 10 | News | `GET /v1/news?instrument_key=&since=&as_of=&limit=` | yes | `published_at` (vendor) vs `received_at` (Prajna's fetch); an instrument's news needs its link to be knowable |
| 11 | Data freshness | `GET /v1/freshness` | no | per dataset: last COMPLETE run, age, last status, expected cadence |
| 12 | Data quality / provenance | `GET /v1/instruments/{key}/quality` | no | current coverage per timeframe, vendor-revision observations by class, price basis mix, quarantined bars, provenance |
| 13 | Pipeline / job status | `GET /v1/pipeline/status` | no | last run per job family, running runs, candles lock, token age, disk, recent runbook markers |
| 14 | Acceptance status | `GET /v1/acceptance` | no | the latest Stage 1 / Stage 2 gate reports (never re-evaluated by the API) |

### Supporting read contracts (added for the web client, generic)

| Endpoint | PIT | Notes |
|---|---|---|
| `GET /v1/market/session?date=&as_of=` | no (calendar) | the NSE calendar entry and, for today, `state` PRE_OPEN / OPEN / CLOSED / NON_TRADING_DAY; **calendar state, not a data-feed status**; previous and next trading day |
| `GET /v1/latest?keys=k1,k2,...&as_of=` (≤ 200 keys) | yes | the latest daily close + the previous one; `change` / `change_pct` are **withheld** (`comparable=false`, with a reason) across a split/bonus ex-date or a price-basis difference, because a raw difference would not be a market move |
| `GET /v1/global/{key}/finality?limit=` | no | every recent vendor label with its finality: REVISED / PLACEHOLDER / UNCONFIRMED labels carry **no values**; CONFIRMED / CONFIRMED_BY_AGE carry the close |

Other changes:
- `GET /v1/instruments` accepts `sector=` and returns `meta.total`. An empty filter value, or `ANY` for `lifecycle_status`, means no filter.
- News items carry `publisher`, which is null on every article so far: the vendor supplies none.
- `GET /v1/acceptance` includes `stage3: {status: "LOCKED", reason}`.

### Not available (backend capabilities a client must show as unavailable)

| Capability | Why |
|---|---|
| live ticks / real-time quotes | no canonical live tick store (L OUT_OF_SCOPE) |
| market breadth, top movers, sector performance | no universe-wide latest-price aggregate endpoint (per-instrument `/latest` only, ≤ 200 keys) |
| 52-week high/low, market capitalisation | not derived; market cap not in the vendor profile |
| news source / category filters | `publisher` empty from the vendor; no category field |
| 5m candles | OUT_OF_SCOPE (decision D2-5m) |
| intraday history before 2026-09-23 | backfill DEFERRED |

## Known limits (data, not API)

- **Intraday history** starts 2026-09-23 and grows one session per close. The historical intraday backfill is DEFERRED.
- **1D history before 2025-09-24** (the corporate-action horizon) is vendor-adjusted as of its fetch; `adjusted=true` withholds it unless `allow_low_confidence=true`.
- **News** history starts 2026-09-24 (the vendor serves 7 days).
- **No live tick store** (L OUT_OF_SCOPE): `/quote` is the latest stored bar.

## Relation to `backend/app/api/`

A separate dashboard-oriented API (`backend/app/api/`, `/api/v1/...`) and a `frontend/` directory were being written by another tool in the same working tree on 2026-09-25, during this hardening. They are **not part of this contract, not reviewed and not committed here**.
