# News deduplication specification (dedup-v1, with story-v1 and scope-v1)

**Code:**

- `backend/app/news/dedup.py` (pure rules)
- `backend/app/news/stories.py` (story-v1)
- `backend/app/news/scope.py` (scope-v1)
- `backend/app/news/store.py` (where they are recorded)

**Schema:** migration `0015` (`news_decision`).

**Tests:** `tests/news/test_dedup.py`, `test_scope.py`, `test_store.py`, `test_store_concurrency.py`.

## Principles

1. **Nothing is deleted or merged.** Every fetched article with a new (source, source_article_id) is stored as its own `news_item`. A duplicate is **marked** (a `news_decision` row), not dropped. Tables are append-only (DB trigger).
2. **Edits are observations, never overwrites.** A later change to a stored article's title, summary, published time or source-updated time is a `news_item_observation` row, with its own `observed_at`.
3. **Every decision is explainable.** It records the rule name, the rule version, the related article (for a duplicate), the story, the evidence (JSON) and its own `knowable_at`. A past `as_of` never sees a later decision.
4. **One decision per stored article and per material edit, per rule version.** This is enforced by two partial unique indexes.

## Identity levels

| Level | Key | Where enforced |
|---|---|---|
| Same article, same source | (source, source_article_id) | DB `uq_news_item_source_id` + `ON CONFLICT DO NOTHING`; poll writers are serialised by advisory locks, so "seen" is decided by one writer at a time |
| Same raw payload | payload SHA-256 | `raw_payload` primary key (content-addressed archive) |
| Same-source duplicate under a new ID | canonical URL / title+summary hash / normalised-title hash within 24 h | dedup-v1 → `DUPLICATE_ARTICLE` |
| Same story, several articles | story-v1 (SAME_URL / SAME_TITLE / SIMILAR, with score and evidence) | `news_story`, `news_story_member` → `STORY_RELATED` |

## Decisions (dedup-v1)

**For a newly stored article, the first rule that applies wins:**

| Order | Decision | Rule | Condition |
|---|---|---|---|
| 1 | `DUPLICATE_ARTICLE` | `SAME_SOURCE_URL` | the same source stored an article with the same **canonical URL** in the 24 h before it |
| 2 | `DUPLICATE_ARTICLE` | `SAME_SOURCE_CONTENT` | …with the same **title and summary** (SHA-256 of `title \x1f summary`) |
| 3 | `DUPLICATE_ARTICLE` | `SAME_SOURCE_TITLE` | …with the same **normalised title**. **Not for exchange / regulator sources:** an NSE title is the filer's name, and many different filings share it (213 same-title repeats on 2026-09-29, all distinct filings) |
| 4 | `STORY_CORRECTION` | `CORRECTION_MARKER` | it joins an existing story **and** its title carries a correction marker |
| 5 | `STORY_RELATED` | `STORY_SAME_URL` / `STORY_SAME_TITLE` / `STORY_SIMILAR` | it joins an existing story (the story-v1 evidence is copied) |
| 6 | `NEW_ARTICLE` | `FIRST_SEEN` | otherwise, including the founder of a new story |

- A duplicate names its original (`related_item_id`: the **earliest** match in the window). A DB check makes that mandatory.
- Only **earlier** articles can be originals.
- Articles outside the 24 h window are never duplicates.

**For an edit (an observation of a stored article):**

| Decision | Rule | Condition |
|---|---|---|
| `STORY_CORRECTION` | `CORRECTION_MARKER` | the title changed **and** gained a correction marker it did not have |
| `STORY_UPDATE` | `MATERIAL_EDIT` | the title, summary or published time changed |
| *(none)* | — | only `source_updated_at` changed: the observation is stored, but it is not a material change |

**Correction markers** (word-bounded, case-insensitive): correction, corrected, corrigendum, erratum, clarification, clarifies, clarified, retract(s/ed), withdrawn, revised, rectification.

## Cross-source stories (story-v1, unchanged)

- An article joins an existing story only on explicit evidence, recorded as `method`, `score` and `evidence`.
- **Point in time:** it is compared only with members knowable at its own discovery.
- Exchange and regulator items join **strictly** (the same company and category required), for the same reason as rule 3.
- **Story assignment is serialised across all sources** by one shared advisory lock, so two sources cannot both found a story for the same event.

## Market scope (scope-v1)

Each stored article gets **one primary scope and every other applicable scope**. They are stored as a second versioned `news_classification` row (method `SCOPE_RULES`); the secondary scopes go in the assessment evidence.

**Rule order:**

1. REGULATORY
2. CORPORATE
3. COMPANY
4. GEOPOLITICAL
5. CURRENCY
6. COMMODITY
7. MACRO
8. GLOBAL_MARKET
9. SECTOR
10. MARKET_WIDE
11. Low-confidence fallbacks (an exchange filing; corporate or market vocabulary)
12. IRRELEVANT

The exact rules are in the `scope.py` docstring. **IRRELEVANT items are stored and labelled, never dropped.** Readers that want the event category exclude `SCOPE_RULES` (story index, `news_pit`).

**Measured on the 1,365 live items of 2026-09-29** (DRY_RUN evidence, rules applied offline):

| Scope | Items |
|---|---|
| COMPANY | 565 |
| CORPORATE | 297 |
| MARKET_WIDE | 268 |
| COMMODITY | 70 |
| IRRELEVANT | 56 (4.1%: lifestyle, gadgets, crime, politics) |
| SECTOR | 36 |
| MACRO | 21 |
| GEOPOLITICAL | 17 |
| GLOBAL_MARKET | 15 |
| REGULATORY | 14 |
| CURRENCY | 6 |

**Known weakness:** the event classifier leaves 82% of items as category OTHER, so many scopes come from mentions or vocabulary (confidence 0.5–0.6), not from a category (0.8). **Scopes are routing aids, not labels to trade on.**

## Concurrency

- **Serialisation:** the database part of a poll runs under `pg_advisory_xact_lock(news:source:<SRC>)`, then `pg_advisory_xact_lock(news:stories)`. The locks are always taken in that order, so the two cannot deadlock, and they are released at commit or rollback.
- **Proved on the test database** with real commits on separate connections:
  - three overlapping polls insert each item once, and exactly one writer wins;
  - an edit seen by three overlapping polls is recorded once;
  - a writer that dies mid-transaction leaves no news rows, its run is FAILED, and a retry completes.
- **Without the locks, those tests fail:** the overlapping writers collide on the `raw_payload` key, and the edits would be double-recorded.

## Example evidence

| Case | Decision |
|---|---|
| Mint re-publishes a story with a new GUID but the same URL | `DUPLICATE_ARTICLE` / `SAME_SOURCE_URL`, `duplicate_of` = the first |
| BS and CNBC-TV18 both report "Brent near $107" | the second is `STORY_RELATED` / `STORY_SIMILAR` |
| An NSE filing's summary gains "has now informed" | observation + `STORY_UPDATE` / `MATERIAL_EDIT` (`changed: ["summary"]`) |
| "Correction: Rupee closes at 96.13" joining the rupee story | `STORY_CORRECTION` / `CORRECTION_MARKER` |
