# News production investigation (Phase 0)

**Measured:** 2026-09-29, about 15:50–16:40 IST, read-only, at HEAD `6af7952`.

**Evidence (every figure below was reproduced now, not copied from an earlier audit):**

- **The database** `prajna`, alembic version `0014`.
- **The crontab.**
- **The DRY_RUN evidence files:** `backend/var/news/dryrun/<SOURCE>/events_2026-09-29.jsonl`, one full trading session (collector started 2026-09-28 evening, `--until 2026-09-29T15:45+05:30`).
- **The code:** `app/news/*`, `app/acceptance/news.py`, `app/canon/news_pit.py`, `app/features/news_features.py`.
- **The acceptance gate:** `prajna acceptance news` rerun at 16:34 IST.

The per-source measurements are in `docs/NEWS_SOURCE_MATRIX.md`.

## A. Current architecture

There are **two separate news paths**, and only the first writes to the database today.

| Path | What runs | Writes | Read by |
|---|---|---|---|
| **1. Upstox `/v2/news` (production)** | Cron every 30 minutes, 09:30–15:30 Mon–Fri, plus a weekend sweep at 11:00 and 19:00 (`ops/runbooks/news_poll.sh`, `flock -n var/run/news.lock`). It also runs inside the 07:00 morning job and the 16:05 close job | `news_article` (230 rows, 12 days, 2026-09-17 → 09-29) and `news_instrument` | Stage 2 `canon_news`; the Stage 3 v1 news features |
| **2. Multi-source collector (8 sources)** | `prajna news dry-run`, started by hand. It is **not scheduled** | **Files only**: `var/news/dryrun/<SRC>/` (`events_<day>.jsonl`, `state.json`, gzip raw payloads, a shared `stories.json`) | nothing in Stages 2 or 3 |

**Components of path 2:**

| Module | Role |
|---|---|
| `app/news/http.py` | a polite client: conditional GET (ETag / Last-Modified), feed `<ttl>`, jitter, exponential backoff, `Retry-After`; BLOCKED / AUTH_FAILED stop the source for good |
| `app/news/sources/*` | the adapters (below) |
| `app/news/enrich.py` | entity links (EXACT_SYMBOL / ISIN / COMPANY_NAME / ALIAS / UNRESOLVED), categories, mentions (index, sector, commodity, currency, central bank, …) |
| `app/news/stories.py` | story-v1 clustering: SAME_URL / SAME_TITLE / SIMILAR, with the reason recorded |
| `app/news/assess.py` | rule-based assessment: market scope (STOCK / SECTOR / INDEX / MARKET / MACRO / GLOBAL / UNKNOWN), impact, direction |
| `app/news/collector.py` | the DRY_RUN loop and recorder |
| `app/news/store.py` | `poll_shadow`: **one** locked poll written to the database (SHADOW or PRODUCTION); never run in production |
| `app/news/locks.py` | the write locks (section K) |
| `app/canon/news_pit.py` | the point-in-time reader over PRODUCTION rows |
| `app/features/news_features.py` | the `mnews_*` features, not in the Stage 3 registry |

## B. Current sources

| Key | Source | Type | Adapter status | Terms (NEWS-COMPLIANCE) |
|---|---|---|---|---|
| `NSE_ANNOUNCEMENTS` | NSE corporate announcements RSS | official exchange | PILOT | **APPROVED** (2026-09-29) |
| `SEBI_RSS` | SEBI press releases / orders RSS | official regulator | ADAPTER | **APPROVED** |
| `ET_STOCKS_RSS` | Economic Times, markets/stocks RSS | publisher | ADAPTER | **APPROVED** |
| `BS_MARKETS_RSS` | Business Standard, markets RSS | publisher | ADAPTER | **APPROVED** |
| `BL_MARKETS_RSS` | BusinessLine, markets RSS | publisher | ADAPTER | **APPROVED** |
| `MINT_MARKETS_RSS` | Mint, markets RSS | publisher | ADAPTER | **APPROVED** |
| `CNBCTV18_NEWS_SITEMAP` | CNBC-TV18 Google-News sitemap | publisher | ADAPTER | **APPROVED** |
| `INDIANEXPRESS_BUSINESS_RSS` | Indian Express, business RSS | publisher | ADAPTER | **APPROVED** |
| `MONEYCONTROL` | — | — | UNSUPPORTED | REJECTED: HTTP 403 on robots.txt and RSS; no bypass |
| `ZEE_BUSINESS` | — | — | UNSUPPORTED | REJECTED: HTTP 403; no bypass |
| `REUTERS` | — | — | UNSUPPORTED | REJECTED: robots.txt `Disallow: /`; only a licensed feed would do |
| Upstox `/v2/news` | vendor API (production path 1) | vendor | production | vendor contract |

**Approved scope:** headline, summary, URL and timestamps only. `body_allowed=False` for every source, so article bodies stay TERMS_BLOCKED.

### What the 8 sources cover (Phase 1 news universe)

Measured on the **1,365 live items of 2026-09-29** (backlog excluded). The counts are keyword hits on title + summary + category, so they are indicative only.

- NSE counts are inflated by filing boilerplate: "SEBI (LODR)", "Nifty" in index-inclusion notices, "global" in names.
- IE and SEBI had 0 live items that day, so they have no column.

| Topic | BL | BS | CNBC | ET | Mint | NSE | Total |
|---|---|---|---|---|---|---|---|
| Indices (Nifty / Sensex / Bank Nifty) | 3 | 12 | 5 | 17 | 12 | 229 | 278 |
| RBI | 2 | 1 | 4 | 1 | | | 8 |
| SEBI | 3 | 1 | 1 | 2 | 3 | 137 | 147 |
| Government policy / ministry | | 2 | 12 | 1 | | | 15 |
| Budget / tax / GST | | | 2 | 1 | 1 | 2 | 6 |
| Rates / inflation (CPI / WPI) | 2 | | 7 | 2 | 3 | | 14 |
| GDP / IIP / PMI | | | | | 1 | | 1 |
| FII / FPI / DII flows | | 1 | | 3 | 2 | 3 | 9 |
| Rupee / USD-INR | 3 | 1 | 3 | 1 | 2 | | 10 |
| Crude oil | 3 | 5 | 11 | 4 | 7 | | 30 |
| Gold / commodities | 9 | 3 | 13 | | 1 | 49 | 75 |
| Global equities | 4 | 6 | 7 | 7 | 5 | 275 | 304 |
| US Fed / Treasury yields | 1 | 2 | 12 | 4 | 8 | | 27 |
| China | | | 4 | 1 | | 1 | 6 |
| Middle East / geopolitics | | | 11 | 1 | 2 | 5 | 19 |
| Tariffs / trade / sanctions | | 2 | 9 | 2 | | | 13 |
| Earnings / results | 2 | 5 | 11 | 7 | 5 | 39 | 69 |
| M&A | 1 | 1 | 3 | 1 | 1 | 5 | 12 |
| Fundraising (QIP / NCD / rights) | | 6 | 2 | | 1 | 9 | 18 |
| IPO / listing | 5 | 7 | 13 | 4 | 7 | 19 | 55 |
| Block / bulk deals | | 1 | 3 | 1 | 2 | | 7 |
| Ratings / defaults | 1 | 3 | 6 | 4 | 3 | 6 | 23 |
| Courts / tribunals (NCLT, SAT) | | | 5 | | | | 5 |
| Promoters / management | 1 | 1 | 9 | 3 | 1 | 14 | 29 |
| Dividends / buybacks / splits | | 3 | 2 | 1 | 2 | 9 | 17 |
| **Live items** | 31 | 74 | 129 | 91 | 53 | 987 | 1,365 |

**Coverage gaps** (topics with no dedicated source):

- **Official macro releases:** MoSPI (CPI, WPI, GDP, IIP), PIB / ministries, RBI press releases. These reach Prajna only through publisher stories. RBI publishes RSS feeds; they are **not yet audited** and are a candidate adapter.
- **Weather / disasters and cyber incidents:** only incidental publisher coverage.
- **Court decisions:** only CNBC-TV18 carried any on the day measured.

The same-day check (`docs/NEWS_COVERAGE_CHECK_2026-09-29.md`) found 11 of the 12 market stories of 2026-09-29 in these files.

## C. Current polling frequency

| Source | Configured market / off-hours interval (s) | Feed `<ttl>` | Effective | Polls on 09-29 | Median gap (s) |
|---|---|---|---|---|---|
| NSE | 300 / 900 | 5 min | 300 | 115 | 317 |
| ET | 120 / 600 | — | 120 | 253 | 125 |
| BS | 180 / 900 | — | 180 | 170 | 192 |
| BL | 180 / 900 | **60 min** | **3,600** | 16 | 3,864 |
| Mint | 180 / 900 | — | 180 | 168 | 192 |
| CNBC-TV18 | 300 / 900 | — | 300 | 116 | 327 |
| IE | 180 / 900 | — | 180 | 170 | 191 |
| SEBI | 3,600 / 3,600 | 60 min | 3,600 | 16 | 3,603 |

**How intervals are applied:**

- The market interval applies 09:00–15:45 IST on weekdays.
- The effective interval is max(configured, feed `<ttl>`), with jitter between 0.8× and 1.2×.
- Conditional GET is used, so most polls return 304.

**Upstox (path 1):** every 30 minutes, 09:30–15:30. That is about 118 requests per run: 3,5xx keys in batches of 30.

## D. Current production vs dry-run behaviour

| | Upstox path | Multi-source DRY_RUN | Multi-source SHADOW | Multi-source PRODUCTION |
|---|---|---|---|---|
| Scheduled | yes (cron) | **no** (started by hand) | no | no |
| Writes | `news_article` | files only | `news_*` tables, `mode='SHADOW'`, invisible to readers | `news_*` tables, `mode='PRODUCTION'` |
| Rows today | 230 | — | 0 | 0 |
| Read by Stages 2 and 3 | yes | no | no (by design) | `canon/news_pit.py` and `mnews_*` (not in the registry) |

- `store.poll_shadow` performs **one** poll per call. **No long-running collector writes to the database.**
- The collector overshot `--until`: started with 15:45 IST, it was still alive at 16:34. **Fixed in `6af7952`** (the deadline is checked before every poll, and no sleep crosses it); regression tests added. The already-running process still uses the old code until it exits.

## E. Current DB schema

Migrations **0013 and 0014** (applied) created the news tables below. All have 0 rows.

| Table | Purpose | Key constraints |
|---|---|---|
| `news_poll` | one row per fetch | `mode` ∈ {SHADOW, PRODUCTION}; `outcome` ∈ {OK, NOT_MODIFIED, RATE_LIMITED, BLOCKED, AUTH_FAILED, ERROR, MALFORMED}; `finished_at >= started_at` |
| `news_item` | one row per source article | **`uq_news_item_source_id` UNIQUE (source, source_article_id)**; `knowable_at >= discovered_at`; `processed_at >= discovered_at`; `content_fetch_status` enum. Columns include `canonical_url`, `title_norm_hash`, `published_at`, `source_updated_at` |
| `news_item_observation` | later edits of an item (title, summary or time changed) | append-only |
| `news_story`, `news_story_member` | story clusters | member `method` ∈ {FOUNDER, SAME_URL, SAME_TITLE, SIMILAR}; score between 0 and 1; UNIQUE (item_id, rule_version) |
| `news_classification` | category | UNIQUE (item_id, method, version); confidence between 0 and 1 |
| `news_entity_link` | instrument link | `method` enum; UNRESOLVED ⇔ `instrument_key IS NULL`; UNIQUE (item_id, version, instrument_key) |
| `news_entity_mention` | index, sector, commodity, currency, central bank, macro indicator, exchange, court | UNIQUE (item_id, entity_type, entity_id, version) |
| `news_assessment` | rule/AI assessment | `market_scope` ∈ {STOCK, SECTOR, INDEX, MARKET, MACRO, GLOBAL, UNKNOWN}; `basis` ∈ {RULES, AI} |
| `news_content` | a body, when allowed | `status='AVAILABLE'` ⇔ `body IS NOT NULL` |
| `news_ai_enrichment` | AI output (never treated as fact) | UNIQUE (item_id, model_id, prompt_version, input_sha256) |
| `news_audit` | REFUSED / KILL_ON / KILL_OFF / BLOCKED | |

- **Every table has an append-only trigger** (`tr_<table>_append_only`), so rows are never updated or deleted.
- Every derived row carries its own `knowable_at`, which is never before the time it was derived.
- Upstox has its own tables: `news_article`, with UNIQUE (headline_sha256, published_at, source) and `knowable_at <= fetched_at`; and `news_instrument`.

## F. Current deduplication behaviour

| Level | Where | Rule |
|---|---|---|
| Same article across polls | collector `seen` map (state) and DB `uq_news_item_source_id` | the same (source, source_article_id) is never a new item |
| Edit of a known article | `process` → `changed` | title, summary or published time changed → an observation (`change` event / `news_item_observation`); **never overwrites** |
| Same link repeated inside one feed | report `duplicates.same_link_repeated_in_feed` | counted, stored once |
| Across sources / same story | story-v1 | SAME_URL (canonical URL), SAME_TITLE (normalised-title hash), SIMILAR (token similarity within a window), with the score and reason stored |

**Missing:**

- **No explicit per-item dedup decision** (NEW / DUPLICATE / UPDATE / RELATED / CORRECTION) is recorded. It has to be inferred from events.
- **No correction detection.**
- **A concurrent insert of the same (source, id)** would raise on the unique key and fail the whole poll transaction. There is no `ON CONFLICT` and no advisory lock.
- **Story assignment is not serialised** across concurrent writers.

**NSE:** 213 same-title repeats on 09-29. NSE filing titles are the company name, so these are separate filings, not duplicates. Story-v1 must not treat them as SAME_TITLE for NSE (to be verified in the dedup test matrix).

## G. Current provenance

**Every item event carries:**

- `source`, `id` (the source's article ID), `url`, `canonical_url`;
- `published_at` **and** `published_at_raw` (the exact source string);
- `discovered_at`, `knowable_at`;
- `backlog` (present in the first successful poll, so its time of first appearance is unknown);
- `latency_s` and `latency_class`;
- `terms_status`, `content_fetch_status`, `source_priority`, `processed_at`.

**Every poll event carries:**

- `started_at` / `finished_at`, `outcome`, `http_status`, `bytes`;
- `payload_sha256` (the raw payload is archived under `raw/`, gzip);
- `error`, `retry_after_s`, `issues`;
- since `6040d85`, `ttl_s`.

`news_item` has the same fields, plus a foreign key to its `news_poll` row.

## H. Current PIT behaviour

- **`knowable_at` = Prajna's first observation**, the `discovered_at` of the poll that first saw the item. It is **never the publisher time**.
  - Enforced by the DB check `knowable_at >= discovered_at`.
  - Tested: `test_pilot` asserts `knowable_at != published_at`.
- **Backlog items** (in the first successful poll of a source) have `knowable_at` = that poll, and are excluded from latency.
- **Edits** become observations with their own `observed_at`. A reader at time T sees the version known at T.
- **`app/canon/news_pit.py`:**
  - reads **PRODUCTION** rows only, strictly `knowable_at < as_of`;
  - every derived row (link, class, story member, assessment) is filtered by its **own** `knowable_at`.
- **Missing vs zero:** `mnews_*` return MISSING_INPUT when no PRODUCTION poll succeeded within `COVERAGE_WINDOW` = 2 h before as_of. **A missing input is never a 0.**
- **SEBI publishes a date only** (no time), so its latency is NOT_MEASURABLE. Its `knowable_at` is still Prajna's first observation.

## I. Current Stage 3 integration

- **Stage 3 registry `features-v1`** (65 features, hash `9061d85b…`) includes the **Upstox** news features only (from `canon_news` / `news_article`).
- The **multi-source `mnews_*` features** exist in `app/features/news_features.py` but are **not registered**.
- **FEATURE-NEWS-V2 is APPROVED** (2026-09-29), activation only after a production canary day.
- With 0 PRODUCTION rows, every `mnews_*` would be MISSING_INPUT. The Stage 3 locks are unchanged.

## J. Current failures / gaps

| # | Finding | Evidence | State |
|---|---|---|---|
| J1 | No scheduled multi-source collector writes to the DB | `store.poll_shadow` is one poll per call; no cron line | open (Step 2.2) |
| J2 | `--until` overshoot | polled 15:46–15:48, alive 16:34 | **fixed `6af7952`** |
| J3 | Acceptance ignored the feed `<ttl>` (BL: EVIDENCE and POLITENESS PENDING despite 16 healthy hourly polls) | gate gap rule 3 × 180 s | **fixed `6040d85`**; now BL EVIDENCE and POLITENESS PASS |
| J4 | **NSE: 8 MALFORMED polls, HTTP 200 with truncated XML** | payload sizes 112–375 KB, growing through the day ("no element found" at the last byte). The feed is the whole day's announcements, so it grows past a size at which transfers are cut. Plus 3 connection errors / timeouts. 9.6% failed polls in total (below the 20% HEALTH limit) | open. A truncated payload is rejected whole, with nothing half-parsed; the next poll recovers. Monitor the rate |
| J5 | **ET detection latency is high** (p50 3,566 s, p95 10,508 s) | 50 of 91 live ET items are **"Share Price Live Updates" pages**. Their `pubDate` is the live blog's creation time (08:00–09:05), and they enter the feed hours later (p50 5,840 s). The other 41 items: p50 1,251 s, p95 2,050 s. Polling is every ~125 s, so the lag is the feed's, not Prajna's | explained; report ET latency split by live-blog vs article |
| J6 | Indian Express published nothing new on 09-29 (newest item 28 Sep 19:27; `lastBuildDate` 07:36) | 49 × HTTP 200 with the same 200 items | a source-staleness case: needs the SOURCE_STALE monitoring state |
| J7 | No DB concurrency guard: unique-key conflict fails the poll; story assignment can race | code | open (Step 2.3) |
| J8 | No explicit dedup decision record; no correction detection | schema | open (Step 2.4, migration 0015) |
| J9 | Classifier leaves most items OTHER | category OTHER 1,124 of 1,365 live items (82%); market scope UNKNOWN 369 (27%) | open (scope-v1 taxonomy, Step 2.5) |
| J10 | No reconciliation report, no monitoring states, **no alert channel anywhere** | — | open (Steps 2.7 and 2.8); alert delivery is a later decision |
| J11 | Mapping review never judged | `var/news/review/*.json`: 254 rows, all `correct: null` | **blocked on the user** (REVIEW_SHEET.md) |
| J12 | No official macro source (MoSPI, PIB, RBI) | section B | candidate adapters; not audited |

## K. Current compliance gates

**A multi-source DB write requires every item below** (`app/news/locks.py` `require`). Each refusal is audited in `news_audit`.

| Lock | Current state |
|---|---|
| per-source flag `PRAJNA_NEWS_<SRC>_ENABLED` | **false** for all 8 (not set in `.env`) |
| kill switch `var/run/news.kill` | off |
| terms `compliance == APPROVED` | **APPROVED** for all 8 (`c0b98a7`) |
| source acceptance, `var/acceptance/news.json` = PASS for the source | **PENDING** for all 8 |
| Stage 2 PASS | PASS |
| write token | not supplied |
| PRODUCTION only: `PRAJNA_NEWS_MULTI_SOURCE_ENABLED` | **false** |

**Acceptance on 2026-09-29 (16:34 IST, after the TTL fix):**

| Criterion | Result |
|---|---|
| EVIDENCE, HEALTH, POLITENESS, TERMS | **PASS for all 8** |
| LATENCY | PASS for 6; SEBI NOT_MEASURABLE (date only, does not block); IE PENDING (no new items that day) |
| MAPPING | **PENDING for all 8** (the human review) |
| PIT | needs `--run-tests` (PASS on the 10:59 run: the news suite passes) |

**So no source can write yet, not even SHADOW.** The next blocker is the mapping review.

## L. Recommended architecture

```
cron (flock, one instance)
  └─ ops/runbooks/news_collect.sh  --mode SHADOW|PRODUCTION --until <close+>
       └─ prajna news collect: one asyncio task per source (isolated failures)
            ├─ polite fetch (ttl / ETag / backoff / Retry-After)       [exists]
            ├─ parse → enrich → classify (scope-v1) → assess            [exists + scope-v1]
            └─ one transaction per poll:
                 pg_advisory_xact_lock(hash(source))                    [new]
                 insert news_poll; insert news_item ON CONFLICT DO NOTHING [new]
                 news_decision (NEW / DUPLICATE / UPDATE / RELATED / CORRECTION) [new, 0015]
                 pg_advisory_xact_lock(stories) → story assignment      [new]
                 observations / links / classes / assessments           [exists]
news_pit (PRODUCTION, knowable_at < as_of) ──> Stage 3 mnews_* (registry v2, at activation)
news health  → var/status + ops status + log markers
news reconcile --day → docs/NEWS_DAILY_RECONCILIATION.md + JSON
```

**Principles:**

- Reuse the tested DRY_RUN pipeline, so the SHADOW and PRODUCTION writers see exactly what DRY_RUN saw.
- Keep the locks as they are.
- Nothing is deleted.
- Irrelevant items are stored and classified IRRELEVANT, not dropped.

## M. Exact implementation plan

This follows the approved plan (`/home/cis/.claude/plans/…cryptic-falcon.md`). Each step is committed separately.

1. **Done:**
   - decisions: NEWS-COMPLIANCE APPROVED, FEATURE-NEWS-V2 APPROVED after canary (`c0b98a7`);
   - acceptance TTL rule (`6040d85`);
   - `--until` fix (`6af7952`);
   - these investigation docs.
2. **Engineering, test database only:**
   - `news collect` loop and runbook;
   - advisory locks and `ON CONFLICT`;
   - migration 0015 `news_decision` (backup first);
   - scope-v1;
   - latency metrics in DB mode;
   - monitoring states;
   - `news reconcile`;
   - test matrices: dedup, PIT replay at 8 instants, failures, concurrency, security.
3. **Stage 3 v2 features:** built and tested now; registered only at activation.
4. **Rollout, each step gated by evidence:**
   1. the user judges the mapping review → acceptance PASS;
   2. SHADOW for at least 1 trading day, compared with Upstox;
   3. canary PRODUCTION (NSE, SEBI, ET, BS) for 1 day;
   4. full PRODUCTION plus cron (**new cron lines need the user's approval**);
   5. Stage 3 v2 activation.
5. **Final documents** and NEWS-GATE-A…M.
