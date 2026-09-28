# Multi-source news: audit, feasibility and proposed design

**Status (2026-09-28, 16:00 IST):** decisions recorded (§9). The **pilot (NSE corporate announcements) is implemented and tested, and ran one real DRY_RUN poll** (evidence files only). SHADOW database writes are **LOCKED**. Nothing is scheduled. No other source is implemented. See §11 for the pilot's state.

---

## Part I: audit of the existing system (Phase 0)

### A. Architecture

**Pipeline:**
1. Upstox REST
2. raw archive (`raw_payload`, content-addressed)
3. pure parser
4. Stage 1 tables
5. Stage 2 canonical views and `app.canon.pit` (`knowable_at < as_of`)
6. Stage 3 features (locked) and the read API (`app/readapi`, read-only)

**Every write goes through `IngestRunner`:**
- a run ledger (`ingest_run`);
- the write token checked at the write path;
- anomalies recorded in `ingest_anomaly`;
- orphaned runs reaped.

**Constraint #1, "Upstox-only",** is recorded as non-negotiable in:
- `app/contracts/provenance.py` ("deliberately no" other sources);
- `app/contracts/identity.py`;
- `docs/STAGE_1_STATUS_REPORT.md` ("NSE crawlers and unapproved vendors are not allowed");
- `docs/STAGE_2_DESIGN.md` ("no NSE crawler").

**The multi-source news request conflicts with constraint #1.** It needs an explicit, recorded amendment (decision NEWS-SOURCES, §9) before any external source is added.

### B. News schema

**`news_article`** (196 rows, 187 distinct headlines, published 2026-09-17 … 2026-09-28):

| Column | Notes |
|---|---|
| `id` | |
| `headline`, `headline_sha256` | |
| `body` | the vendor summary |
| `url`, `vendor_article_id` | |
| `publisher` | **NULL for every row**: Upstox supplies none |
| `published_at` | |
| `vendor_payload` | |
| `source` | always `UPSTOX_REST_V2` |
| `run_id`, `payload_sha256` | provenance |
| `fetched_at` | |
| `knowable_at`, `knowable_at_verified`, `knowable_at_basis` | |

- The identity is (`headline_sha256`, `published_at`, `source`).
- It is append-only **by code**: a changed re-observation raises a WARN, and the stored row is kept. **No database trigger** enforces this, unlike `feature_value`.

**`news_instrument`** (603 links: 196 articles × 264 instruments) holds the vendor's grouping:
- `knowable_at` = the link's `fetched_at` (`for_snapshot_download`);
- `on conflict do nothing`.

### C. Timing semantics today

- **Article:** `news_article.knowable_at = published_time`. This is the vendor publication instant, marked `verified` (`for_announced_fact`). **That is exactly the rule the new contract forbids.**
- **Link:** `news_instrument.knowable_at = fetched_at`.
- **Measured Upstox lag,** publication to Prajna's fetch: median **1,558 min (≈ 26 h)**, p95 **≈ 7 days**. The cause is the polling schedule and the vendor's 7-day window: news collected on a later sweep is still published earlier.

### D. Point-in-time guarantees today

Stage 2's `canon_news` joins the article to its link:
- `knowable_at = GREATEST(article.knowable_at, link.knowable_at)`, which is effectively the **first fetch time**;
- every row in `canon_news` has a link.

So `pit.news()`, the Stage 3 news features and `GET /v1/news` are **already bounded by Prajna's observation time**, and no current consumer sees an article before Prajna fetched it.

The only place `published_at` acts as knowable is the raw `news_article.knowable_at` column. No PIT reader uses it on its own. The new design does **not** change or rewrite those rows (§3.3).

### E. Stage 1 criterion N

**"News": PASS if articles exist and the last COMPLETE sweep is less than 36 h old** (`app/acceptance/stage1.py:386`).

The collection schedule (`ops/cron/prajna.cron`):

| When | Job |
|---|---|
| 07:00 daily | sweep |
| 09:30, then every 30 min 10:00–15:30, Mon–Fri | poll |
| 16:05 | close sweep |
| 11:00 and 19:00, Sat–Sun | weekend sweep |

It uses `flock var/run/news.lock`. **This proposal does not change N.**

### F. Stage 2

- `canon_news` is a view (above).
- `pit.news(s, as_of, key, since)` filters `knowable_at < as_of`.
- Stage 2 criterion O ("Stage 3 can consume safely") passes.
- There is no event clustering, classification or publisher.

### G. Stage 3 news capabilities

- `news_count_24h`, `news_count_7d` and `news_hours_since_last` are descriptive; they count Upstox news linked to the instrument.
- News **sentiment is UNSUPPORTED**, and pre-open-specific events are UNSUPPORTED.
- Stage 3 production is locked (DRY-RUN READY).

### H. API

- `GET /v1/news?instrument_key=&since=&as_of=&limit=` returns `published_at`, `received_at` (fetch), `knowable_at` and `publisher` (always null). It is point-in-time.
- `GET /v1/freshness` includes news.
- There are no source, health or latency endpoints.

### I. Frontend

- `web/` is Prajna's own client over the read API.
- **`frontend/` and `backend/app/api/` are an external worktree**, which, per standing instruction, I may not modify or commit. Any news UI therefore goes into `web/`, over read-API contracts.

### J. Production locks

- **Stage 3:** flags, kill switch, fresh Stage 1 gate, Stage 2 report, decisions, token and audit, all in `app/features/locks.py`.
- **Stage 2:** `STAGE2_LIVE_ENABLED=false`.
- **Ingestion:** the write token, and `flock` locks per job.
- **Rate limiting:** only the Upstox client (`app/vendor/upstox/rest.py`) has one. There is no generic HTTP client for third-party hosts.

### K. Tests

- 939 passed, 2 skipped.
- The network is blocked in tests by `conftest._network_guard`, and the test database is enforced.
- Fixtures under `tests/fixtures/`; seeds under `tests/support/`.

---

## Part II: source feasibility matrix (probed 2026-09-28, one request per URL)

For each source I checked robots.txt, fetched one feed with an identified research user agent, and noted HTTP headers. **No terms of use were reviewed legally.** That review is the user's (§9, NEWS-COMPLIANCE).

| Source | Access path | robots.txt (`*`) | Probe result | Timestamp | Conditional GET | Entity signal | Assessment |
|---|---|---|---|---|---|---|---|
| **NSE corporate announcements** (exchange filings) | official RSS `nsearchives.nseindia.com/content/RSS/Online_announcements.xml` | Allow `/` | 200, 1,162 items, 0.4 s | `28-Sep-2026 15:19:11` (IST, no zone: needs an explicit IST parse) | ETag + Last-Modified | **symbol in the item**, so EXACT_SYMBOL | **Best value: the primary source of company events.** Conflicts with constraint #1 ("no NSE crawler"): needs NEWS-SOURCES |
| **BSE notices** | RSS `bseindia.com/data/xml/notices.xml` | no `*` block | 200, only 9 items (exchange notices, not company filings) | RFC-822 GMT | none | none | Low value. BSE corporate announcements need its API, which is undocumented; not probed further |
| **Economic Times** | official RSS (`/markets/rssfeeds/1977021501.cms`, `/markets/stocks/news/rssfeeds/2146842.cms`) | Allow `/`; `rssarticleshow` disallowed | 200, 50 items per feed, 0.2 s | RFC-822 +0530 | ETag + Last-Modified | headline text only | **Feasible** (metadata only) |
| **Business Standard** | RSS `/rss/markets-106.rss` | `/api/` disallowed; RSS path allowed | 200, 35 items | RFC-822 +0530 | ETag + Last-Modified | headline | **Feasible** (metadata only; much content is paywalled) |
| **Livemint** | RSS `/rss/markets` | Allow `/` | 200, 35 items | pubDate present (format to verify) | none | headline | **Feasible**; polls cost a full download |
| **Hindu BusinessLine** | RSS `/markets/feeder/default.rss` | allowed; GPTBot/CCBot blocked by name | 200, 60 items | to verify | Last-Modified | headline | **Feasible** |
| **CNBC-TV18** | Google-News sitemap `/commonfeeds/v1/cne/sitemap/google-news.xml` | Allow `/` (results pages disallowed) | 200, 266 URLs, 261 KB | ISO-8601 +05:30 | none (full 261 KB per poll) | headline | **Feasible, but heavy**: slower cadence |
| **Moneycontrol** | RSS | robots.txt itself returns **403** (bot protection) | 403 | — | — | — | **UNSUPPORTED**: blocked; no bypass |
| **Zee Business** | RSS | robots.txt **403** | 403 | — | — | — | **UNSUPPORTED**: blocked; no bypass |
| **Reuters** | — | **`Disallow: /`** for `*` | not crawled | — | — | — | **UNSUPPORTED** without a licensed feed (Reuters/LSEG News API: commercial licence) |
| **Upstox** (existing) | REST V2 `/v2/news` | vendor API | as today | epoch ms | — | vendor grouping | unchanged; becomes one adapter over the existing tables |

**Not probed** (candidates for later): SEBI press releases (RSS), RBI press releases (RSS, for MARKET scope), PIB/Ministry of Finance.

### Content policy (default for every media source)

Store:
- title;
- URL (canonical);
- publisher timestamps;
- our timestamps;
- hashes;
- category, tags and author **only if present in the feed**.

**Do not store:**
- article bodies;
- RSS `<description>` text, unless NEWS-COMPLIANCE explicitly allows a short excerpt per source.

Exchange filings (NSE): subject, symbol and attachment URL, which is public regulatory disclosure.

---

## Part III: proposed design

### 1. Knowable-time contract (all new data)

| Timestamp | Meaning |
|---|---|
| `published_at` | the publisher's claimed time; informational only; can be edited by the publisher |
| `source_updated_at` | the publisher's update time, if any |
| `discovered_at` | the first poll in which Prajna saw the item: the fetch completion time of that poll |
| `fetched_at` | when the observation's response was received (per observation) |
| **`knowable_at`** | **= `discovered_at`** for every source, Upstox included in the new canonical layer. **Never** `published_at`. A stronger source contract (e.g. a push API with signed delivery times) could only be introduced by an explicit decision |

The database will enforce `knowable_at >= discovered_at` and `knowable_at <= now()` on insert.

**Every enrichment is its own append-only row** with `created_at = knowable_at`:
- classification;
- entity mapping;
- event cluster membership;
- scope;
- title edits.

A re-classification adds a row. A reader at as_of takes the latest row with `knowable_at < as_of`, so past snapshots never change.

### 2. Architecture

```
            ┌──────────────────── collector daemon (one process, per-source tasks) ─────────────┐
 feeds ───► │ SourceAdapter.discover()  ─ conditional GET (ETag/If-Modified-Since), jitter,     │
 (RSS,      │                              per-host token bucket, backoff, circuit breaker   │
 sitemap,   │   │ raw bytes → raw_payload (content-addressed archive, as today)                  │
 Upstox)    │   ▼                                                                                │
            │ parse (pure) → NewsItemObservation[]                                               │
            │   ▼                                                                                │
            │ news_poll (1 row / poll: status, http, latency, items, new)                       │
            │ news_item (1 row / source article; first seen = knowable)   ◄── dedup L1/L2       │
            │ news_item_observation (every sighting; title/time edits kept)                     │
            └──────────────┬─────────────────────────────────────────────────────────────────────┘
                           ▼ enrichment workers (idempotent, versioned, append-only)
                 dedup L3/L4 → news_event + news_event_member
                 classify (rules v1) → news_classification
                 entity resolution → news_entity_link (UNRESOLVED kept)
                 scope → news_scope (MARKET / INDEX / SECTOR / INSTRUMENT)
                           ▼
            Stage 2 views: canon_news_item, canon_news_event, ... (knowable_at < as_of)
            pit.news_items / pit.news_events (as_of)          ← Stage 3 features (new ids, locked)
            read API /v1/news*, /v1/news/sources|health|latency ← web/ news screens (SSE later)
```

- **Failure isolation:** one asyncio task per source; an exception or timeout in one source changes only that source's health.
- **Separation from market data:** the collector is a separate process with its own lock file and its own database connection pool (size capped), and it is **never** called from the market-data runbooks. A collector failure cannot block them.
- **Modes**, set per source and globally:

| Mode | Behaviour |
|---|---|
| DISABLED | no requests |
| DRY_RUN | fetch and parse; writes only to a local JSONL evidence file; no database |
| SHADOW | writes the `news_*` tables with `source.production = false`; the Stage 2 views, Stage 3 and the API exclude non-production sources |
| PRODUCTION | visible to Stage 2, Stage 3 and the API |

  A source's promotion from SHADOW to PRODUCTION is recorded with a timestamp. Its SHADOW observations keep their real `discovered_at`, so they are PIT-correct.

### 3. Schema (proposed migrations 0013–0015; additive; backup first)

| Table | Purpose |
|---|---|
| `news_source` | registry: key, name, kind (API/RSS/SITEMAP), URL, tier, mode, `production`, cadence configured, compliance status, content policy, attribution text |
| `news_poll` | one row per poll: source, started/finished, HTTP status, bytes, `not_modified`, items seen/new, error, rate-limit flag, `payload_sha256` |
| `news_item` | one row per source article: source, `source_article_id`, url, canonical_url, title, `title_norm_hash`, `canonical_hash`, published_at, `discovered_at`, `knowable_at`, language, region, author/category/tags (if present), `content_available` (bool), `first_poll_id`. Unique (source, source_article_id), or (source, canonical_url) when there is no id. **Append-only trigger** |
| `news_item_observation` | every later sighting where title, published_at or `source_updated_at` changed (poll_id, observed values, `observed_at`); unchanged sightings only bump counters in `news_poll` |
| `news_event`, `news_event_member` | event cluster, and membership (item, event, level L1–L4, rule version, `knowable_at`). Re-clustering adds rows; a membership is superseded, never deleted |
| `news_classification` | item or event, category (the 35-value taxonomy from the request), confidence, method (`RULES_V1`, `EXCHANGE_SUBJECT`), version, `classified_at` = `knowable_at` |
| `news_entity_link` | item, instrument_key (nullable for UNRESOLVED), method (EXACT_SYMBOL / ISIN / COMPANY_NAME / ALIAS / MANUAL_RULE / UNRESOLVED), confidence, matched text, `mapped_at` = `knowable_at`, version |
| `news_scope` | item or event, scope_type (MARKET / INDEX / SECTOR / INSTRUMENT), scope_id, confidence, `knowable_at` |
| `news_entity_alias` | curated aliases (e.g. "RIL" → RELIANCE), with `valid_from` and `created_at` = `knowable_at`; used only from its creation time |

- **Existing tables are untouched.** `news_article` and `news_instrument` stay as they are.
- The Upstox adapter **projects** them into the canonical layer through a view that sets `knowable_at = news_article.fetched_at` (first fetch; rows are insert-once). So the raw column that uses publication time is never used as knowable.
- An append-only trigger on the existing `news_article` is proposed separately. It is additive and changes no behaviour.

### 4. Adapters

```python
class NewsSourceAdapter(Protocol):
    key: str                       # "ET_MARKETS_RSS"
    def capabilities(self) -> Capabilities       # conditional_get, has_ids, has_symbols, has_updated_at
    def request(self, state: PollState) -> Request      # URL + ETag/If-Modified-Since
    def parse(self, body: bytes, fetched_at) -> list[ItemObs]   # PURE (fixtures in tests)
    def health_policy(self) -> HealthPolicy      # stale_after, expected cadence
    def rate_limit(self) -> RateLimit            # min interval, max/min, backoff cap
    def attribution(self) -> str; content_policy(self) -> ContentPolicy
```

The generic HTTP client:
- has a per-host token bucket;
- applies ±20% jitter;
- backs off exponentially on 429/5xx (capped at 30 min) and honours Retry-After;
- has a circuit breaker (N failures → OPEN → half-open probe);
- identifies itself with a fixed User-Agent;
- makes no cookie or JavaScript challenges and no retries on 403.

**A 403 marks the source BLOCKED and stops it.** There is no bypass.

### 5. Cadence (starting values; measured, then tuned)

| Tier | Sources | Market hours (09:00–15:45) | Off hours | Weekend |
|---|---|---|---|---|
| A | NSE announcements, ET stocks RSS | 60 s (conditional GET: mostly `304 Not Modified`) | 5 min | 15 min |
| B | Business Standard, BusinessLine, Livemint | 2 min | 10 min | 30 min |
| C | CNBC-TV18 sitemap (261 KB each) | 5 min | 15 min | 60 min |
| — | Upstox | unchanged (existing cron) | | |

The request asked for 15 s. Nothing in the probes justifies that: the feeds update every few minutes, and 15 s would multiply load for no latency gain. It is revisited after the dry-run latency measurement.

Budget at these values: about **1,000 requests per source per market day** for Tier A, mostly 304s.

### 6. Deduplication, clustering, classification, entities, scope

**Deduplication levels:**

| Level | Rule |
|---|---|
| L1 | exact URL, same item |
| L2 | canonical URL (strip query/utm/amp, lower-case host) |
| L3 | normalised title hash (Unicode NFKC, case-folded, punctuation and stopwords removed) |
| L4 | token Jaccard ≥ 0.8 (version 1) within ±3 h of `published_at`, same instrument |

- L3 and L4 group items **across publishers** into `news_event`.
- L5 (semantic) is **not built**, and correctness never depends on it.
- Every source item is kept.

**Classification:** `RULES_V1` is deterministic keyword and regex rules over the title, with rule-level confidence. NSE items use the exchange's own announcement subject (`EXCHANGE_SUBJECT`, high confidence). **No machine learning or LLM** is used, and there is no sentiment.

**Entities:**
- NSE items carry the symbol: EXACT_SYMBOL, confidence 1.0.
- Media items are matched against `canon_instrument` trading symbol, name and ISIN, plus the curated alias table.
- A candidate needs a unique match above the threshold. Otherwise the link is **UNRESOLVED** and nothing is guessed.
- Subsidiary and group mapping (e.g. "Jio" → RELIANCE) are MANUAL_RULE entries only.

**Scope:**
- INSTRUMENT from entity links;
- SECTOR from the point-in-time sector of the linked instruments, or rule keywords;
- INDEX and MARKET from rule keywords (RBI, repo rate, CPI, GDP, Fed, Nifty…), with confidence.

### 7. Monitoring, latency and health

- **`news_latency_metrics` view**, per source and day: p50, p95, p99 and max of (`discovered_at − published_at`); articles seen, new and failed; last success; last failure.
- Latency is computed only when `published_at` exists and is ≤ `discovered_at`. Negative values are recorded as CLOCK_SKEW.
- **Health:**

  | State | Rule |
  |---|---|
  | HEALTHY | none of the conditions below |
  | DEGRADED | error rate > 20% in the last 30 min |
  | STALE | no successful poll within 3 × cadence |
  | RATE_LIMITED | a 429 or Retry-After is in force |
  | BLOCKED | HTTP 403 |
  | AUTH_FAILED | authentication failure (Upstox) |
  | DISABLED / UNSUPPORTED | set by the registry |

- **Structured log events:** `news_poll_started` / `news_poll_completed`, `news_article_discovered`, `news_article_duplicate`, `news_event_clustered`, `news_mapping_created` / `news_mapping_unresolved`, `news_source_failed` / `news_source_rate_limited` / `news_source_stale`. Each carries the poll_id, item_id and event_id.

### 8. Contracts with other stages

- **Stage 1:** criterion N is **unchanged**. There is a separate gate, `prajna acceptance news`, with the criteria A–Q from the request, plus operational metrics NEWS-LATENCY, NEWS-SOURCE-COVERAGE and NEWS-PIPELINE-HEALTH. None of them feeds Stage 1 unless approved later.
- **Stage 2:** new views and `pit.news_items(as_of, …)` / `pit.news_events(as_of, …)`. Each enrichment is resolved "latest row with `knowable_at < as_of`". Required tests include:
  - an item published at 10:00 and discovered at 10:05 is invisible at as_of 10:04 and visible at 10:05;
  - a reclassification at 10:20: as_of 10:10 sees the original state, and as_of 10:20 the new one.
- **Stage 3:**
  - The existing news features keep their definitions and ids.
  - New descriptive features are added as new ids under a new decision **FEATURE-NEWS-V2**:
    - counts over 5 m / 15 m / 1 h / 4 h / 1 d;
    - source and publisher counts;
    - counts by category and scope;
    - recency;
    - event confirmation count.
  - Sentiment stays **UNSUPPORTED**.
  - The Stage 3 locks are unchanged.
- **Read API:** `/v1/news` (source, publisher, category and scope filters), `/v1/news/{id}`, `/v1/news/events`, `/v1/news/sources`, `/v1/news/health`, `/v1/news/latency`, `/v1/market/news`, `/v1/sectors/{sector}/news`. Every response carries `meta.as_of`, the knowable rule and a freshness mode (LIVE only if the collector is running and HEALTHY, otherwise LATEST_STORED or HISTORICAL). An SSE stream (`NEWS_DISCOVERED`, `NEWS_CLUSTERED`, `NEWS_MAPPED`) comes only after the collector is stable, behind `PRAJNA_NEWS_LIVE_STREAM_ENABLED`.
- **UI:** in `web/` (not `frontend/`):
  - news stream, event clusters, source confirmation;
  - per-instrument, sector and market views;
  - per item: publisher time, discovery time, knowable_at and latency;
  - source health and latency pages.

### 9. Decisions (recorded in `app/news/decisions.py`)

| ID | Status | Decision |
|---|---|---|
| **NEWS-SOURCES** | **APPROVED** (user, 2026-09-28: "All feasible") | Constraint #1 (Upstox-only) is **amended for news only**. Allowed: NSE announcements, ET, Business Standard, BusinessLine, Livemint, CNBC-TV18. Moneycontrol, Zee Business and Reuters are UNSUPPORTED (blocked or disallowed; no bypass) |
| **NEWS-CONTENT** | **APPROVED** (user) | Store metadata, URL and the feed's short description. Store the article **body where a source's pages are publicly accessible and allowed by robots.txt** (never behind a paywall, login or bot protection). An **AI description via AWS Bedrock** is a versioned enrichment (knowable when generated), never fact and never a Stage 3 feature without its own spec. The Bedrock credentials are to be read from `auto-trade-pro/.env` (V1) at the time that step is built: never printed, and V1 never modified. **Body collection and AI descriptions are not built yet** |
| **NEWS-PILOT** | **APPROVED** (user) | NSE corporate announcements RSS first |
| NEWS-KNOWABLE | APPROVED (your Phase 1 rule) | `knowable_at = discovered_at`; existing Upstox rows untouched |
| NEWS-CADENCE | PROPOSED | The NSE feed declares `<ttl>5</ttl>`, so the pilot polls every 5 min in market hours (15 min off-hours, 30 min at weekends) and never faster than the ttl, instead of the 60 s proposed earlier |
| NEWS-COMPLIANCE | **PENDING** | Per-source terms-of-use review, by the user. Until APPROVED for a source, only DRY_RUN is possible for it: the SHADOW lock checks this |
| NEWS-RUNTIME | PROPOSED | A long-running collector daemon; not yet decided or built |

**Flags, all default false:**
- `PRAJNA_NEWS_MULTI_SOURCE_ENABLED` (enrichment and visibility);
- `PRAJNA_NEWS_CRAWLER_ENABLED` (any external request outside DRY_RUN);
- `PRAJNA_NEWS_LIVE_STREAM_ENABLED`.

There is also a kill file `var/run/news.kill`. **PRODUCTION requires** Stage 1 COMPLETE, Stage 2 PASS, dry-run evidence, NEWS-COMPLIANCE approved for the source, and the flags.

### 10. Delivery order (after approval)

1. Migration 0013 (registry, poll, item, observation) with the append-only triggers.
2. The HTTP client (rate limit, backoff, circuit breaker) and the adapter protocol.
3. **The pilot adapter** and its fixtures and tests.
4. `prajna news dry-run` over a full market session, producing `docs/NEWS_MULTI_SOURCE_DRY_RUN.md` with latency and counts.
5. Deduplication, entity mapping and clustering: migration 0014, with tests.
6. The remaining adapters, one commit each.
7. Stage 2 views and `pit` functions, with PIT tests.
8. Stage 3 FEATURE-NEWS-V2 (locked).
9. Read API.
10. `web/` screens.
11. Observability.
12. `prajna acceptance news`.
13. SHADOW run, then the production-readiness report.

At each step: tests, `git diff --check`, and a commit. Nothing reaches PRODUCTION without the §9 decisions and the flags.

---

## 11. Pilot state (NSE corporate announcements)

**Built:**
- `app/news/`:
  - `sources/nse_announcements.py`: pure parser;
  - `http.py`: conditional GET, ttl floor, jitter, backoff, 403 stops the source, and no bypass;
  - `enrich.py`: `EXCHANGE_SUBJECT` classification and entity links;
  - `collector.py`: timing, backlog, and the DRY_RUN recorder;
  - `store.py`: locked SHADOW writes;
  - `locks.py`;
  - `report.py`.
- Migration **0013**: `news_poll`, `news_item`, `news_item_observation`, `news_classification`, `news_entity_link` and `news_audit`, all append-only (trigger), with `knowable_at >= discovered_at` checked. It was applied to production after backup `prajna_20260928T1543_news_pre_0013.dump` (verified). The tables are empty.
- CLI: `prajna news sources | health | dry-run | report | poll --commit (LOCKED) | kill on|off`.
- Flags, all false: `PRAJNA_NEWS_CRAWLER_ENABLED`, `PRAJNA_NEWS_MULTI_SOURCE_ENABLED`, `PRAJNA_NEWS_LIVE_STREAM_ENABLED`.
- Tests: `tests/news/`, 47 tests covering parsing, malformed and hostile XML, timing and backlog, knowable = discovery, edits as observations, entity links, classification, 304/403/429/5xx, backoff, ttl, the kill switch, database-down isolation, restart, the SHADOW lock, idempotency, append-only storage and the PIT check.

**Entity links: the file-name symbol is the uploader's code.**
- A debenture trustee files for its issuer; a filing agent files under its own code. So `EXACT_SYMBOL` requires the filer name to agree with the instrument name.
- Name-only matches (`COMPANY_NAME`) are strict: an unmatched filer word must be a filler, parenthesised, or trail a truncated vendor name.
- Fund and ETF scheme filings are never mapped by name.
- Measured false positives, now prevented and covered by tests:
  - "Kotak Mahindra Mutual Fund - Kotak Nifty MNC ETF" was matched to "KOTAK NIFTY ETF";
  - "SUNDARAM HOME FINANCE" was matched to "SUNDARAM FINANCE LTD".

**First real DRY_RUN poll (2026-09-28 15:45 IST), one request:**

| Measure | Result |
|---|---|
| Response | HTTP 200, 506 KB |
| Items | 1,228, all backlog (the first response), so no latency is claimed |
| Same link repeated in the feed | 62 |
| Mapping, final rules (re-evaluated offline on the archived response) | 335 EXACT_SYMBOL, 578 COMPANY_NAME, 1 ALIAS, 314 UNRESOLVED (**74.4%**); most unresolved filers are unlisted debt issuers (NABARD, NIIF…) or fund schemes |
| Classification | 1,133 OTHER (trading-window, NAV and routine filings), then MANAGEMENT_CHANGE 38, DEBT 24, ORDER_CONTRACT 12, … |

**Not yet done:**
1. A **full market-session DRY_RUN** to measure latency; the first response is backlog by definition.
2. `docs/NEWS_MULTI_SOURCE_DRY_RUN.md`.
3. Event clustering (L3/L4).
4. The other adapters.
5. Body fetching and Bedrock descriptions.
6. The Stage 2 views and `pit` functions, Stage 3 FEATURE-NEWS-V2, the read API and the `web/` screens.
7. The news acceptance gate.
8. The runtime daemon.
