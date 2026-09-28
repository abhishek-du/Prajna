# News subsystem: inventory (Phase 1, 2026-09-28)

Written before any Phase 2+ change. The facts are taken from the code at commit `c557e68` and from the running system.

## Tables

| Table | Migration | Rows (prod, 28 Sep) | Writer | Knowable rule |
|---|---|---|---|---|
| `news_article` | 0001 | 196+ | `app/ingest/news.py` (Upstox) | `knowable_at` = vendor `published_time` (verified). **Not** first observation; see gap G1 |
| `news_instrument` | 0002 | 603+ | same | `knowable_at` = link `fetched_at` |
| `news_poll`, `news_item`, `news_item_observation`, `news_classification`, `news_entity_link`, `news_audit` | 0013 | 0 (locked) | `app/news/store.py` (SHADOW, locked) | `news_item.knowable_at` = `discovered_at` (check constraint); enrichments carry their own `knowable_at`; all append-only (trigger) |

- **Stage 2:** the `canon_news` view joins `news_article` to `news_instrument` with `knowable_at = GREATEST(article, link)`, which in practice is the fetch time.
- **Point-in-time reads:** `pit.news(as_of, key, since)`.
- **Not in Stage 2:** the `news_*` tables from 0013. No view reads them.

## Sources and adapters

| Source key | Adapter | Mode | Cadence (market/off/weekend) | Notes |
|---|---|---|---|---|
| Upstox `/v2/news` | `app/ingest/news.py` + `parsers/upstox_news.py` | **PRODUCTION** (Stage 1, criterion N) | cron: 09:30, then every 30 min 10:00–15:30; 07:00; 16:05 close; weekends 11:00/19:00 | vendor serves 7 days; no publisher field |
| `NSE_ANNOUNCEMENTS` | `sources/nse_announcements.py` | DRY_RUN | 300 / 900 / 1800 s, never below the feed ttl (5 min) | exchange filings; uploader symbol + filer name |
| `ET_STOCKS_RSS` | `sources/rss.py` | DRY_RUN | 120 / 600 / 1800 s | ETag |
| `BS_MARKETS_RSS` | `rss.py` | DRY_RUN | 180 / 900 / 1800 s | ETag, `lastModification` |
| `BL_MARKETS_RSS` | `rss.py` | DRY_RUN | effectively 3600 s (ttl 60) | |
| `MINT_MARKETS_RSS` | `rss.py` | DRY_RUN | 180 / 900 / 1800 s | no conditional GET |
| `CNBCTV18_NEWS_SITEMAP` | `rss.py` (sitemap) | DRY_RUN | 300 / 900 / 3600 s | ~270 KB per poll |
| `INDIANEXPRESS_BUSINESS_RSS` | `rss.py` | DRY_RUN | 180 / 900 / 1800 s | no description in the feed |
| `SEBI_RSS` | `rss.py` (`sebi_parser`) | DRY_RUN | 3600 s (ttl 60) | date-only `pubDate` |
| Moneycontrol, Zee Business | — | UNSUPPORTED | — | HTTP 403 (bot protection) |
| Reuters | — | UNSUPPORTED | — | robots.txt `Disallow: /` |

- **The collector:** one detached DRY_RUN process runs all 8 sources until 2026-09-29 15:45 IST. The PID is in `var/run/news_dryrun.pid`; evidence goes to `var/news/dryrun/<SOURCE>/`.
- **Scheduling:** there is **no cron entry** for the new sources.

## Behaviour today

| Area | Current state |
|---|---|
| Retry and backoff | `app/news/http.py`: conditional GET; interval floored at the feed ttl; ±20% jitter; ×2 backoff capped at 30 min; Retry-After honoured; 403 → BLOCKED and 401 → AUTH_FAILED, both stopping the source; no bypass. Upstox: the vendor client's own rate limiter |
| Deduplication | Level 1 only: exact source id / link within a source. `title_norm_hash` and `canonical_url` are stored but **not used for grouping**. There is **no cross-publisher story grouping** |
| Entity mapping, NSE (`nse-entity-v1`) | EXACT_SYMBOL only if the filer name agrees; COMPANY_NAME strict (filler words only); fund schemes never mapped by name; ALIAS learned from EXACT links; else UNRESOLVED with a reason |
| Entity mapping, media (`headline-entity-v1`) | whole-name phrase in the headline; generic names skipped; a one-word name that starts another company's name is skipped; multiple links per item. There are **no curated aliases**, and non-company entities (index, sector, commodity, currency, regulator, …) are **not** modelled |
| Classification | NSE `nse-subject-v1` (exchange subject → taxonomy); media `media-keywords-v1` (heuristic, 0.6); SEBI `regulator-source-v1` (REGULATORY by source). **No** impact, direction, scope, breaking flag or AI |
| `knowable_at` | new sources: first observation (`discovered_at`); backlog flag on the first response; edits → `news_item_observation`. Upstox raw column: publication time (G1) |
| Latency | `prajna news report`: p50/p95/p99/max publisher → discovery, backlog excluded, **per source for one day only**. No p90, no market/off-hours split, no processing, API or frontend timing |
| Content | no article bodies; feed descriptions only (≤ 500 characters); **no `content_fetch_status`**, robots or terms fields per item |
| AI | none. Bedrock was approved as enrichment (NEWS-CONTENT) but is not built |
| Locks | DRY_RUN: kill file + supported source. SHADOW: `PRAJNA_NEWS_CRAWLER_ENABLED` (**one global flag**; see G6) + source compliance APPROVED + token. PRODUCTION: not available. `PRAJNA_NEWS_MULTI_SOURCE_ENABLED` and `PRAJNA_NEWS_LIVE_STREAM_ENABLED` exist but are unused |
| Read API (`app/readapi`) | only `GET /v1/news` (Upstox via `pit.news`; `published_at` / `received_at` / `knowable_at`; `publisher` always null) |
| Stage 3 | `news_count_24h`, `news_count_7d`, `news_hours_since_last` (Upstox via `pit.news`); sentiment UNSUPPORTED |
| Stage 1 N | Upstox news swept within 36 h (unchanged) |
| Tests | news-specific: `tests/news` (77); Upstox: `tests/parsers/test_upstox_news.py`, `tests/integration/test_news_ingest.py`; Stage 2/3 news through PIT tests |

## Frontend assumptions (external worktree; read, not modified)

- `backend/app/api/news.py` (118 lines) reads `news_article` directly and reports sentiment as NOT_AVAILABLE.
- It does not use `pit.news`, so it has no `as_of`. It is outside the canonical read API, and conflicts with the rule that clients use `/v1`.
- The `web/` client uses `/v1/news`.

## Gaps against the requested programme

| # | Gap | Phase |
|---|---|---|
| G1 | The Upstox raw `news_article.knowable_at` is the publication time. Point-in-time readers are protected by the link join, but a canonical projection must use the first fetch time | 2, 10 |
| G2 | Missing fields: `content_fetch_status`, `robots_allowed`, `terms_status`, `source_priority`, raw metadata hash, content hash, `story_group_id` | 2 |
| G3 | No cross-publisher story grouping | 3 |
| G4 | No non-company entities, no curated aliases | 4 |
| G5 | No impact, scope, direction or breaking layer | 5–7 |
| G6 | One global crawler flag. **Per-source flags are required** | 17 |
| G7 | No Stage 2 views or `pit` functions for the new tables | 10 |
| G8 | No Stage 3 multi-source news features | 11 |
| G9 | Only `/v1/news` in the API | 12 |
| G10 | No content fetch, no AI | 8, 9 |
| G11 | Health comes from dry-run state files only; no rolling error rate or latency | 14 |
| G12 | No full-session dry-run evidence yet: the first market session is 2026-09-29 | 16 |
