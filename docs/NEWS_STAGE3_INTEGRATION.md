# News in Stage 3: integration (FEATURE-NEWS-V2)

**Decision FEATURE-NEWS-V2:** APPROVED by the user on 2026-09-29, with **activation only after a production canary day**, meaning PIT, de-duplication and coverage are evidenced on real PRODUCTION rows.

**Current state: built and tested; NOT registered.**

- The Stage 3 registry is still `features-v1` (65 features, `REGISTRY_SHA256 9061d85b…`), and the Stage 3 locks are unchanged.
- The test `tests/news/test_news_features.py::test_not_in_the_approved_stage3_registry` asserts that no `mnews_*` id is registered.

## What Stage 3 has today

`features-v1` includes **Upstox** news only:

- `news_count_24h`, `news_count_7d`, `news_hours_since_last`;
- stock-tagged articles, about 27 a day.

The multi-source layer is not read by Stage 3 until activation.

## The v2 candidate (`app/features/news_features.py`, `news-features-v2-candidate`)

**How they are computed:**

- **Market-wide:** instrument_key None.
- **Per company:** an instrument's own news, via the resolved entity links knowable at `as_of`.
- **Inputs:** `app.canon.news_pit` only, PRODUCTION rows with `knowable_at < as_of` (see `docs/NEWS_PIT_SPEC.md`).
- **Windows** are measured back from `as_of` by `knowable_at`, never by publisher time.
- **Duplicates** (dedup-v1 DUPLICATE_ARTICLE) are never counted.

| Feature | Definition (window by `knowable_at`) | Missing / undefined |
|---|---|---|
| `mnews_news_count_1h` / `_4h` / `_24h` / `_3d` | de-duplicated articles | quality ≠ NORMAL → MISSING_INPUT |
| `mnews_unique_publishers_1h` / `_24h`, `mnews_unique_sources_24h` | distinct publishers / Prajna sources | ″ |
| `mnews_breaking_news_count_24h` | assess-v1 `is_breaking` (observable rules only) | ″ |
| `mnews_high_relevance_news_count_24h` | assess-v1 `potential_impact = HIGH` | ″ |
| `mnews_negative` / `positive` / `mixed_news_count_24h` | explicit direction words in the headline (assess-v1) | ″ |
| `mnews_regulatory` / `corporate` / `macro_news_count_24h` | assess-v1 event group | ″ |
| `mnews_market_wide` / `macro_scope` / `geopolitical` / `commodity` / `currency` / `global_market_news_count_24h` | scope-v1 primary scope | ″ |
| `mnews_news_velocity_1h` | last hour ÷ the mean hourly count of the prior 23 h | no prior news → DIVISION_UNDEFINED |
| `mnews_news_velocity_24h` | last 24 h ÷ the mean daily count of the prior 48 h | ″ |
| `mnews_publisher_diversity_24h` | distinct publishers ÷ articles | no articles → DIVISION_UNDEFINED |
| `mnews_story_group_count_24h`, `mnews_new_story_count_24h`, `mnews_updated_story_count_24h` | story-v1 stories, founders, stories joined by a later article | ″ |
| `mnews_correction_count_24h` | dedup-v1 STORY_CORRECTION articles | ″ |
| `mnews_edited_news_count_24h` | articles with an edit observed before `as_of` | ″ |
| `mnews_duplicate_count_24h` | articles marked DUPLICATE_ARTICLE (information only) | ″ |
| `mnews_time_since_last_news_s` | `as_of` − the latest `knowable_at` (3-day lookback) | none → MISSING_INPUT |
| `mnews_time_since_last_high_relevance_news_s` | ″ for HIGH | ″ |

**Quality state per snapshot:**

| State | Condition | Values |
|---|---|---|
| NORMAL | a PRODUCTION poll succeeded within 2 h before `as_of` | 0 is a real zero |
| MISSING | no PRODUCTION poll before `as_of` at all | MISSING_INPUT |
| STALE | PRODUCTION polls exist, but none succeeded within 2 h | MISSING_INPUT |
| INVALID | a row not knowable before `as_of`, or the reader's 50,000-row limit reached | MALFORMED_INPUT (fail closed) |

**A missing input is never 0.**

**Snapshot timing** (PRE_SESSION 08:59:59, PRE_OPEN 09:08:00):

- The 2 h coverage window requires the collector to run **before 07:00 IST**. The proposed schedule starts at 06:00.
- The overnight gap means items published overnight are knowable only from the first morning poll, never back-dated.

## Tests

| Test | What it proves |
|---|---|
| `tests/news/test_news_features.py` | the pure definitions: windows, dedup exclusion, scopes, corrections, edits, quality states, the truncation guard, not registered |
| `tests/news/test_pit_replay.py` | the features on a replayed PRODUCTION day (5 counted + 1 duplicate at 12:00, STALE at 15:00, MISSING before the first poll), and the reader at 8 instants |

## Activation checklist (all needed; none done yet)

1. The user's mapping review → `prajna acceptance news` PASS per source.
2. SHADOW for at least 1 full trading day; reconciliation invariants OK; compared with Upstox.
3. Canary PRODUCTION (NSE, SEBI, ET, BS) for 1 trading day:
   - invariants OK;
   - 0 PIT violations (a recompute of the canary day's `mnews_*` at 08:59:59 / 09:08:00 matches);
   - STALE / MISSING behaviour observed.
4. **Registry change as a new version:**
   - add the `mnews_*` definitions to `app/features/registry.py` (a new registry id and hash);
   - update the Stage 3 decisions (FEATURE-NEWS-V2: ACTIVATED, with the canary evidence);
   - update the feature audit document;
   - the Stage 3 gate (tests K) must stay PASS.
5. The first scheduled Stage 3 run after activation is verified: rows, reasons, determinism.

**No step may use a weakened lock.** Stage 3 production stays governed by its own locks and schedule.
