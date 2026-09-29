# News daily reconciliation

**Status: no SHADOW or PRODUCTION collection day exists yet.**

- `news_item` and `news_poll` hold 0 rows in production (2026-09-29).
- Every source is still locked: flags off, and the acceptance MAPPING criterion waits for the user's review.
- **This file will be overwritten by the tool** on the first collection day:

```
cd backend
.venv/bin/prajna news reconcile --day <YYYY-MM-DD> --mode SHADOW|PRODUCTION \
    --md ../docs/NEWS_DAILY_RECONCILIATION.md \
    --json ../audit/evidence/news_reconcile_<YYYY-MM-DD>.json
```

The command is read-only. It writes the monitoring states to `var/status/news_health.json`, which `prajna ops status` shows, and **exits 1 if an invariant is violated**.

## What it reports (per source, for one IST day and one mode)

| Field | Meaning |
|---|---|
| state | the monitoring states (HEALTHY / COLLECTOR_DOWN / SOURCE_DOWN / RATE_LIMITED / FETCH_FAILURE / SOURCE_STALE / UNUSUAL_VOLUME / UNUSUAL_DUP_RATE) |
| polls, outcomes, failures | every poll by outcome; each failure with time, HTTP status and error |
| fetched | the sum of items presented by the feed in each poll (the same item counts once per poll) |
| stored (live / backlog) | new `news_item` rows; backlog = present in the source's first successful poll |
| decisions | NEW_ARTICLE / DUPLICATE_ARTICLE / STORY_RELATED / STORY_CORRECTION per stored article |
| edits | observations stored; how many were material (STORY_UPDATE / STORY_CORRECTION) and how many not (only `source_updated_at` changed) |
| scopes | the scope-v1 primary scope per stored article |
| unresolved company links | articles whose company mention could not be mapped |
| refusals | lock refusals recorded in `news_audit` |
| latency | detection (discovered − published), ingestion (processed − discovered), end-to-end; p50 / p90 / p95 / p99; live items only; clock-skew items counted separately |
| Upstox articles | Upstox `/v2/news` articles fetched the same day, for comparison |

**Invariants (each must be 0):**

- duplicate (source, source_article_id);
- an item knowable before it was discovered;
- a stored article without a dedup decision;
- a decision knowable before it was made.

## Reference: the DRY_RUN day 2026-09-29 (files, not the database)

Until a database day exists, the measured DRY_RUN session is the reference. See `docs/NEWS_SOURCE_MATRIX.md`:

- 1,365 live items;
- per-source polls, failures, latency and edits.
