# News daily reconciliation: 2026-09-29 (PRODUCTION)

Generated 2026-09-29T14:38:47.110135+00:00 (as of 2026-09-29T14:38:47.110109+00:00), read-only, from the database. Produced by `prajna news reconcile`.

## Invariants (each must be 0)

| Check | Count |
|---|---|
| duplicate_source_ids | 0 |
| knowable_before_discovery | 0 |
| items_without_decision | 0 |
| decision_knowable_before_made | 0 |
| decision_knowable_before_item | 0 |
| enrichment_knowable_before_item | 0 |
| knowable_in_the_future | 0 |

**Invariants: OK**

## Per source

| Source | State | Polls | Failed | Fetched | Stored (live) | New | Duplicate | Related | Correction | Edits (material) | Refusals | Detection p50 / p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NSE_ANNOUNCEMENTS | COLLECTOR_DOWN | 2 | 1 | 1376 | 1376 (0) | 1338 | 0 | 38 | 0 | 0 (0) | 0 | None / None |
| ET_STOCKS_RSS | COLLECTOR_DOWN | 3 | 0 | 150 | 51 (1) | 51 | 0 | 0 | 0 | 0 (0) | 0 | 1605.2 / 1605.2 |
| BS_MARKETS_RSS | COLLECTOR_DOWN | 2 | 0 | 70 | 35 (0) | 35 | 0 | 0 | 0 | 1 (1) | 0 | None / None |
| BL_MARKETS_RSS | COLLECTOR_DOWN | 1 | 0 | 60 | 60 (0) | 60 | 0 | 0 | 0 | 0 (0) | 0 | None / None |
| MINT_MARKETS_RSS | COLLECTOR_DOWN | 2 | 0 | 70 | 36 (1) | 36 | 0 | 0 | 0 | 34 (34) | 0 | None / None |
| CNBCTV18_NEWS_SITEMAP | COLLECTOR_DOWN | 2 | 0 | 836 | 420 (4) | 420 | 0 | 0 | 0 | 1 (0) | 0 | 685.2 / 768.7 |
| INDIANEXPRESS_BUSINESS_RSS | COLLECTOR_DOWN | 0 | 0 | 0 | 0 (0) | 0 | 0 | 0 | 0 | 0 (0) | 0 | None / None |
| SEBI_RSS | HEALTHY | 1 | 0 | 30 | 30 (0) | 30 | 0 | 0 | 0 | 0 (0) | 0 | None / None |

Upstox `/v2/news` articles fetched the same day (production path 1): 27.

## Failures (first 50 per source)

- NSE_ANNOUNCEMENTS 2026-09-29T12:18:08.170730+00:00 MALFORMED 200 not XML: unclosed token: line 1, column 566019

## Scopes

- NSE_ANNOUNCEMENTS: COMPANY 764, CORPORATE 324, MARKET_WIDE 191, COMMODITY 42, SECTOR 34, MACRO 12, GLOBAL_MARKET 9
- ET_STOCKS_RSS: COMPANY 21, MARKET_WIDE 17, CORPORATE 7, SECTOR 3, IRRELEVANT 2, COMMODITY 1
- BS_MARKETS_RSS: CORPORATE 9, MARKET_WIDE 8, IRRELEVANT 5, COMPANY 5, SECTOR 2, REGULATORY 2, COMMODITY 2, MACRO 1, GEOPOLITICAL 1
- BL_MARKETS_RSS: COMMODITY 16, CORPORATE 13, MARKET_WIDE 8, REGULATORY 7, COMPANY 6, IRRELEVANT 5, CURRENCY 3, GEOPOLITICAL 1, GLOBAL_MARKET 1
- MINT_MARKETS_RSS: MARKET_WIDE 11, COMPANY 7, CORPORATE 7, COMMODITY 4, IRRELEVANT 3, SECTOR 1, CURRENCY 1, GLOBAL_MARKET 1, MACRO 1
- CNBCTV18_NEWS_SITEMAP: IRRELEVANT 168, CORPORATE 58, MARKET_WIDE 44, GEOPOLITICAL 37, COMPANY 29, REGULATORY 26, COMMODITY 20, MACRO 15, SECTOR 13, CURRENCY 7, GLOBAL_MARKET 3
- SEBI_RSS: REGULATORY 30
