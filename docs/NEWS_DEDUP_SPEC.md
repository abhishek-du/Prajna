# News deduplication specification (dedup-v3, story-v2, scope-v1)

**Code:**

- `backend/app/news/dedup.py` (pure rules)
- `backend/app/news/stories.py` (story-v2)
- `backend/app/news/scope.py` (scope-v1)
- `backend/app/news/collector.py` (`process`: new vs edit)
- `backend/app/news/store.py` (where decisions are recorded)
- `backend/app/news/redecide.py` (append-only re-decision)

**Schema:** migration `0015` (`news_decision`), applied to production 2026-09-29 17:20 IST after a verified backup.

**Tests:** `tests/news/test_dedup.py`, `test_redecide.py`, `test_scope.py`, `test_store*.py`, `test_pit_replay.py`, `test_failures_security.py`.

## Principles

1. **Nothing is deleted or merged.** Every fetched article with a new (source, source_article_id) is stored as its own `news_item`. A duplicate is **marked** by a `news_decision` row pointing at its original. All news tables are append-only (DB trigger).
2. **Edits are observations, never overwrites.** Only a **new, different value** is an edit. A field *missing* from one response is not an edit.
   - Mint's feed alternates between variants with and without `pubDate`: 142 of 148 "edits" on 2026-09-29 were such flaps.
   - The known value is kept. This fix is in `9e8a94e`.
3. **Every decision is explainable and point in time.** It records the rule, rule version, original (for a duplicate), story, evidence and its own `knowable_at`.
   - A corrected rule adds a **new** decision row under a new version, knowable from the correction.
   - A snapshot before that time still sees what was decided then. `news_pit` takes the latest *knowable* decision.
4. **One decision per article (and per material edit) per rule version**, enforced by partial unique indexes.

## Identity levels

| Level | Key | Where enforced |
|---|---|---|
| Same article, same source | (source, source_article_id) | DB `uq_news_item_source_id` + `ON CONFLICT DO NOTHING`, with writers serialised by advisory locks |
| Same raw payload | payload SHA-256 | `raw_payload` primary key |
| Same-source duplicate under a new ID | canonical URL (tracking parameters, `/amp`, fragments and case removed); for media also title+summary or normalised title; 24 h window | dedup → `DUPLICATE_ARTICLE` |
| Same story, several articles / sources | story-v2 (below) | `news_story_member` → `STORY_RELATED` |

## Decisions (dedup-v3)

**For a newly stored article, the first rule that applies wins:**

| # | Decision | Rule | Condition |
|---|---|---|---|
| 1 | `DUPLICATE_ARTICLE` | `SAME_SOURCE_URL` | the same source stored an article with the same canonical URL in the 24 h before |
| 2 | `DUPLICATE_ARTICLE` | `SAME_SOURCE_CONTENT` | …same title and summary. **Media only** (v2) |
| 3 | `DUPLICATE_ARTICLE` | `SAME_SOURCE_TITLE` | …same normalised title. **Media only** |
| 4 | `STORY_CORRECTION` | `CORRECTION_OF_DOCUMENT` | **exchange / regulator** (v3): the title carries a correction marker and names the same "in the matter of" party as an earlier document of that source within 24 h |
| 5 | `STORY_CORRECTION` | `CORRECTION_MARKER` | joins an existing story, and the title carries a correction marker |
| 6 | `STORY_RELATED` | `STORY_SAME_URL` / `_SAME_TITLE` / `_SIMILAR` | joins an existing story |
| 7 | `NEW_ARTICLE` | `FIRST_SEEN` | otherwise, including a story's founder |

**Why rules 2 and 3 exclude exchange / regulator sources (v2):**

- An NSE title is only the filer's name.
- **Separate filings** (a different document link) can carry identical boilerplate text: for example several SAST disclosures from one company on the same day.
- dedup-v1 marked 38 such filings DUPLICATE on 2026-09-29. dedup-v2 decides them STORY_RELATED: one story, separate evidence, each counted.

**For an edit:**

| Decision | Condition |
|---|---|
| `STORY_CORRECTION` / `CORRECTION_MARKER` | the title changed and **gained** a correction marker |
| `STORY_UPDATE` / `MATERIAL_EDIT` | the title, summary or published time changed to a new value |
| none | only `source_updated_at` changed: stored as an observation, but not material |

**Correction markers:** correction, corrected, corrigendum, erratum, clarification, clarifies, clarified, retract(s/ed), withdrawn, revised, rectification.

## Story identity (story-v2)

A new article joins an existing story only on explicit evidence, recorded with it. It is compared only with members knowable at its discovery.

- `SAME_URL` (score 1.0) or `SAME_TITLE` (0.95). For **exchange / regulator** documents the exact key is title **and** summary: a company's different filings are separate stories, and identical-text filings are one story.
- **`SIMILAR`** (media only), with J = title-word Jaccard over content words. The first condition that holds applies:

| Word overlap (J) | Time window | Also required |
|---|---|---|
| ≥ 0.25 | 2 h | a shared listed company and the same event category |
| ≥ 0.35 | 6 h | a shared listed company (v2; was 0.5) |
| ≥ 0.5 | 6 h | no company on either side, a shared entity and the same category |
| ≥ 0.45 | 3 h | no company on either side and a shared entity (v2) |
| ≥ 0.7 | 3 h | nothing else (near-identical wording) |

**Replay of the 2-day DRY_RUN data** (2026-09-28/29, 4,781 articles):

- **Cross-source stories went from 4 to 14.** All 14 were inspected and are the same story, for example:
  - Aegis Logistics' ₹6,000 cr fund raise (BS ×2, CNBC-TV18);
  - Honasa block deal (CNBC-TV18, ET, Mint);
  - "stocks breaking long-held supports" (BL, ET, Mint);
  - rupee at 96.03 (BL, CNBC-TV18).
- **A looser 0.25 / 6 h variant was rejected.** It added 6 more groups, but also merged two different "stocks in news" round-ups, and joined HDFC Bank's CEO transition to a separate Jefferies note.
- **Precision is preferred.** Recall of cross-source grouping stays modest, and that is a known limitation.

## Market scope (scope-v1)

Each article gets **one primary scope and every other applicable scope**:

- REGULATORY / CORPORATE / COMPANY / GEOPOLITICAL / CURRENCY / COMMODITY / MACRO / GLOBAL_MARKET / SECTOR / MARKET_WIDE;
- then low-confidence fallbacks: an exchange filing, or corporate / market vocabulary;
- else IRRELEVANT.

**IRRELEVANT items are stored, never dropped.** The scope is a separate classification row (method `SCOPE_RULES`).

## Production evidence (2026-09-29)

**First production day:**

- 2,002 backlog articles at 17:33 IST, then live polling. The per-source counts are in `docs/NEWS_DAILY_RECONCILIATION.md`.
- **Invariants (production, 20:1x IST):** duplicate source IDs 0; articles without a decision 0; decision / enrichment knowable before its article 0; anything knowable in the future 0.

**Append-only re-decisions applied in production:**

| Run | Time (IST) | Change |
|---|---|---|
| `c49a0f64` | 20:07:51 | NSE 38 DUPLICATE → STORY_RELATED (identical-text separate filings); 354 STORY_RELATED → NEW_ARTICLE (filings grouped only by the filer's name under story-v1) |
| dedup-v3 run | 20:14:40 | SEBI "Corrigendum to the final order in the matter of Adani Group Companies" NEW_ARTICLE → STORY_CORRECTION, correcting item 1973 ("Final order in the matter of Adani Group Companies…", stored 17:33) |

**Point in time, via the Stage 2 API on production:** before 20:07:51, NSE shows 354 RELATED and 38 DUPLICATE (item 145 is DUPLICATE of 142). After it, item 145 is STORY_RELATED. The v1 rows are kept.

## Concurrency

- **Serialisation:** the database part of a poll runs under `pg_advisory_xact_lock(news:source:<SRC>)`, then `(news:stories)`, always in that order.
- **Tests:** three overlapping writers insert each item once; an edit is recorded once; a writer killed mid-transaction leaves no rows.
- **In production:** a second collector started while one runs logs NEWS_COLLECT_SKIP (`flock -n`). Cron at 20:15 IST did exactly that while a collector was running.
