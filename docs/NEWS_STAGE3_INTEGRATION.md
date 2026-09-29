# News in Stage 3: integration (FEATURE-NEWS-V2)

**Decision FEATURE-NEWS-V2:** APPROVED by the user on 2026-09-29, with activation only after a canary on a **real scheduled snapshot**.

**State (2026-09-29 21:30 IST): built, tested, rehearsed on production data; NOT active.**

- `app/features/registry.py`: `NEWS_V2_ACTIVE = False`. The active registry is `features-v1`, 65 features, `REGISTRY_SHA256 9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188`.
- The engine's news step (`engine.news_rows`) emits rows only for news specs present in the active registry, so today it emits none.

## How it works

1. **One point-in-time read per snapshot:** `news_features.snapshot_inputs` reads `app.canon.news_pit` for PRODUCTION rows with `knowable_at < as_of` over 3 days, plus the coverage state at `as_of`.
2. **Market-wide:** 32 features, CONTEXT, stored under the instrument key `MARKET`.
3. **Per company:** 7 features, INSTRUMENT, computed from the same rows grouped by the company links knowable at `as_of`. There are no per-instrument queries.
4. **Provenance:** `inputs_sha256` = SHA-256 of the coverage state and every input row's (id, `knowable_at`, current dedup decision, scope, edited). `input_max_knowable_at` = the latest `knowable_at` among them. The engine refuses any input knowable at or after `as_of` (LookAhead).

**Counting rules (all features):**

| Rule | Detail |
|---|---|
| Windows | by `knowable_at` (Prajna's first observation), **never** publication time |
| Duplicates | DUPLICATE_ARTICLE articles are never counted (reported once as `mnews_duplicate_count_24h`) |
| Backlog | articles in a source's first successful poll (arrival time unknown) are never counted as arrivals. Found in the rehearsal: the 2,002 go-live backlog articles created a one-time spike |
| Edits | only real edits count (a changed title or summary, or a new non-null time); a feed flapping a field is not an edit |
| Corrections | dedup STORY_CORRECTION, including regulator corrigenda (dedup-v3) |

**Quality state per snapshot:**

| State | Condition | Values |
|---|---|---|
| NORMAL | a PRODUCTION poll succeeded within 2 h before `as_of` | 0 is a real zero |
| MISSING | no PRODUCTION poll before `as_of` at all | every feature MISSING_INPUT |
| STALE | polls exist, but none succeeded within 2 h | every feature MISSING_INPUT |
| INVALID | an input knowable at or after `as_of`, or the 50,000-row reader limit hit | every feature MALFORMED_INPUT |

**A missing input is never converted to 0.**

## Features

**Market-wide (CONTEXT, key `MARKET`; exact definitions in `registry._MNEWS_CONTEXT`):**

- `mnews_news_count_1h` / `_4h` / `_24h` / `_3d`, `mnews_unique_publishers_1h` / `_24h`, `mnews_unique_sources_24h`, `mnews_publisher_diversity_24h`;
- `mnews_news_velocity_1h` / `_24h`;
- `mnews_breaking_news_count_24h`, `mnews_high_relevance_news_count_24h`, `mnews_negative` / `positive` / `mixed_news_count_24h` (assess-v1: observable rules and headline words, not predictions);
- `mnews_regulatory` / `corporate` / `macro_news_count_24h` (event group);
- `mnews_market_wide` / `macro_scope` / `geopolitical` / `commodity` / `currency` / `global_market_news_count_24h` (scope-v1);
- `mnews_story_group_count_24h`, `mnews_new_story_count_24h`, `mnews_updated_story_count_24h` (story-v2);
- `mnews_correction_count_24h`, `mnews_edited_news_count_24h`, `mnews_duplicate_count_24h`;
- `mnews_time_since_last_news_s`, `mnews_time_since_last_high_relevance_news_s`.

**Per company (INSTRUMENT; `registry._MNEWS_COMPANY`):**

- `mnews_company_count_1h` / `_4h` / `_24h` / `_3d`;
- `mnews_company_story_count_24h`, `mnews_company_correction_count_24h`;
- `mnews_company_time_since_last_s`.

With coverage, a company without linked news has counts of 0 and time-since MISSING_INPUT. Sector-level news is available through scope-v1 and mentions, but it has **no per-sector feature** in v2; that is a limitation.

## Evidence

| Test / tool | What it proves |
|---|---|
| `tests/news/test_news_features.py` | pure definitions: windows, dedup, backlog, scopes, corrections, edits, quality states, the truncation guard, not in the active registry |
| `tests/news/test_pit_replay.py` | a PRODUCTION day replayed through the store and `news_pit` at 8 instants, and the engine news step with the specs enabled in the test only: 32 + 7 rows, duplicate and backlog excluded, real zero vs MISSING, deterministic, STALE → MISSING_INPUT, nothing while inactive |
| `ops/measure/news_canary.py` (read-only) | on production data: coverage, point in time, **market-wide and per-company counts equal an independent raw-SQL recount**, real zeros, determinism, **non-news features identical with and without the news specs** |

**Rehearsal of the canary tool on production data** (as_of 2026-09-29 21:20 IST, not a scheduled snapshot):

| Check | Result |
|---|---|
| Coverage | NORMAL |
| Point in time | 0 of 24,749 rows with an input knowable at or after as_of |
| Market-wide vs SQL | 1h 66 = 66; 24h 859 = 859; duplicates 0 = 0; corrections 1 = 1 |
| Top 25 companies vs SQL | all equal at 1h / 24h / 3d |
| Companies without news | 2,644, all with a real 0 and time-since MISSING |
| Determinism | identical |
| Non-news features | 525 rows identical |

## Activation plan (steps with a timestamp are not done yet)

1. **Canary** on the real scheduled snapshot: `python ops/measure/news_canary.py --session 2026-09-30 --kind PRE_SESSION` (as_of 08:59:59 IST), after the collector has run from 06:00. Evidence goes to `audit/evidence/news_stage3_canary_2026-09-30_PRE_SESSION.json`. Every check must PASS, and the values are inspected.
2. **Activation at a session boundary:** after the 2026-09-30 PRE_OPEN run completes, never between the two snapshots of one session.
   - Set `NEWS_V2_ACTIVE = True`. That gives registry `features-v2`, 104 features and a new hash.
   - Record FEATURE-NEWS-V2 as ACTIVATED, with the canary evidence.
   - Regenerate the feature audit.
   - Run the Stage 3 tests and gate.
3. **Verification** on the next scheduled runs (2026-10-01 PRE_SESSION 09:00:30 and PRE_OPEN 09:22):
   - `mnews_*` rows persisted under the new hash;
   - the determinism compare passes;
   - the non-news values have the same definitions (v1 specs unchanged).
