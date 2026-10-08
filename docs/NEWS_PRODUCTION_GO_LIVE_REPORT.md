# News production go-live report

**Generated:** 2026-10-08, about 19:10 IST.

**Machine-readable evidence:** `audit/evidence/NEWS_PRODUCTION_GO_LIVE.json`.

All production figures below were queried directly from the production database (`prajna`, alembic `0015`).

## 1. Executive summary

- **Collection and storage:**
  - Multi-source news has been collected in production since 2026-09-29, by the cron-installed collector, from **7 sources**.
  - The production database holds **17,025 articles**, with 0 duplicate source IDs, 0 articles without a dedup decision, and 0 point-in-time violations.
- **Stage 3 (the 2026-10-08 runs):**
  - The 2026-10-08 production runs wrote the **news-v2 features into `feature_value`**: 24,903 news rows per snapshot.
  - The registry was `features-v2`: 104 features, `dd696ca6…`.
  - Point in time: 0 inputs knowable at or after as_of.
  - Values were verified against an independent recount and the canary.
  - The same-snapshot rerun was idempotent.
- **Why Stage 3 had written nothing since 2026-09-29:** Stage 1 criteria **D** and **X** failed its lock. Both were resolved **on evidence and by two explicit user decisions** (section 4). The lock was not bypassed.

The production Stage 3 runs of 2026-10-08 were **CRON-EQUIVALENT**: the exact cron command under cron's minimal environment, run late. They were not cron-triggered. The first **cron-triggered** Stage 3 run after the fix is due 2026-10-09 at 09:00:30 IST (section 16).

## 2. Before-state (baseline, 2026-10-08 17:55 IST)

| Item | Value |
|---|---|
| HEAD | `009445b` = `origin/main`, clean |
| Stage 1 | NOT COMPLETE, failing D and X |
| Stage 3 | 22 REFUSED events in `stage3_event`. The last runs that wrote anything were on 2026-09-29 |
| `feature_value` | 374,648 rows (features-v1, `9061d85b`); 0 news-v2 rows |
| Registry | `features-v2`, 104 features, `dd696ca6…` (activated in code at `009445b`, never used) |
| News | 7 sources enabled, Indian Express disabled; 16,839 articles; nightly reconciliation OK 09-29 → 10-07 |

## 3. Root cause of Stage 1 D and X

| Criterion | Expected | Actual | First failure | Cause | Legitimate? |
|---|---|---|---|---|---|
| **D** Instrument master | sector ≥ 90% of ACTIVE stocks; REVIEW = 0; UNCLASSIFIED only within a 7-day grace | coverage **100%** (3,175/3,175), but **REVIEW = 3** | 2026-09-30, recurring | Three **new listings** (BUILDPRO, ORIENTCABL, BLSE; first seen 10-02 → 10-08): the ISIN says company, but the vendor has **no financials yet**. The 7-day grace covered UNCLASSIFIED new listings, but not this REVIEW state | **Over-broad rule**: a normal new-listing state |
| **X** No look-ahead | 0 violations; B1 and B2 VERIFIED | **0 violations**; B1 VERIFIED; **B2 CONTRADICTED**: 23 late revisions, all `NSE_INDEX\|Nifty 50`, on 4 of 9 sessions, up to **200.4 s** (1m) / 146.1 s (15m, 1h) after the bar end, against the 120 s margin | 2026-10-01 | The vendor revises Nifty 50 intraday bars later than the TIMING-B2 margin set on 2026-09-25 (observed max then: 95.6 s) | **Legitimate**: the contract required an explicit review |

**Neither condition was a point-in-time risk:**

- `knowable_at` is always the fetch time, and X's look-ahead checks were all 0.
- Stage 3 consumes no intraday bars.

## 4. Fixes applied (`9df2999`)

**Decision TIMING-REVIEW** (user, 2026-10-08, "Margin 300 s"):

- The completion margin for 1m / 15m / 1h goes from **120 s to 300 s**, about 1.5× the observed maximum, effective 2026-10-08 18:30 IST.
- It remains an engineering threshold. A revision after 300 s blocks X again.
- **A fetch is judged by the margin in force at its time**, so X's look-ahead SQL no longer hard-codes 120 s. 16 bars from a manual test on 2026-09-24 (before any timing contract existed, never revised) stay valid, and nothing was deleted.
- The B1/B2 evidence was regenerated from the same archived responses: **B1 VERIFIED, B2 VERIFIED**, 10 agreeing sessions, 0 late revisions.

**Decision D-NEW-LISTING-GRACE** (user, 2026-10-08):

- A **new** listing in REVIEW **only** because the vendor has no financials yet gets the existing 7-day grace.
- Any other REVIEW, or this one after 7 days, still fails D.

**Result, evaluated live as Stage 3's lock does it:** **Stage 1 COMPLETE**.

- D PASS: review 0, with 3 in the grace.
- X PASS.
- The previously approved DEFERRED items (G, I, J, S) are unchanged.

**Earlier fixes in this programme** (all committed): the duplicate-row engine bug found at activation (`009445b`), the bare-ampersand feed repair (`a492fbe`), and the monitoring false alarms (`463b7a2`).

## 5. Test results

**Targeted tests:**

- the reviewed timing contract and its history;
- the D grace: in grace, after 7 days, and with another disagreeing signal;
- the timing analyzer cases, restated against the contract margin;
- the real-response fixtures, which now settle 4 bars (was 1);
- the Stage 3 lock, registry and persistence;
- news PIT, dedup and news-v2 features.

All pass.

## 6. Full suite (after the news-v2 activation and the Stage 1 fix)

| Measure | Value |
|---|---|
| Collected | **1,320** |
| Exit code | **0** (0 failed, 0 errors) |
| Duration | 381 s |
| Skipped | the 4 live crontab tests (opt-in), then run with `-m live`: **4 passed** |

## 7. Registry

`features-v2`: **104 features** = 65 v1 + 32 market-wide `mnews_*` + 7 per-company `mnews_company_*`.

`REGISTRY_SHA256 dd696ca66b022392877d6cf10bf752601de417931165c93b03bacb9ae3d3fa1a`, carried by every 2026-10-08 row.

## 8. Production news

**17,025 articles by source:**

| Source | Articles |
|---|---|
| NSE | 13,016 |
| CNBC-TV18 | 2,033 |
| ET | 742 |
| Mint | 523 |
| BL | 338 |
| BS | 282 |
| SEBI | 91 |

**Current decisions:**

| Decision | Count |
|---|---|
| NEW_ARTICLE | 16,477 |
| STORY_RELATED | 535 |
| DUPLICATE_ARTICLE | 12 |
| STORY_CORRECTION | 1 |
| STORY_UPDATE (edits) | 1,290 |

**Invariants:** duplicate source IDs 0; missing decisions 0; point-in-time violations 0.

**Indian Express** stays **disabled**: there is no fresh validation sample, and its feed is stale.

## 9. Stage 2

- Production news reaches Stage 2 through `app.canon.news_pit` (PRODUCTION rows, `knowable_at < as_of`) and `/v1/news/articles`.
- Real records were traced from payload → article → `news_pit` → API on 2026-09-29.
- The Stage 3 runs below read the news **only** through `news_pit`.

## 10. Real production Stage 3 runs (2026-10-08, CRON-EQUIVALENT)

All runs used `ops/runbooks/stage3_snapshot.sh <KIND> [--after-replay] --token-from-dotenv` under `env -i` (cron's environment).

| Run | Snapshot (as_of IST) | Start → end (IST) | Status | Inserted | Already present |
|---|---|---|---|---|---|
| `0ea32099-7de7-482f-a641-38de445e5c12` | PRE_SESSION 08:59:59 | 18:38:46 → 18:42:35 | COMPLETE | **206,281** | 0 |
| `520c8783-e7f3-4498-b305-acb0b55b93f4` | PRE_OPEN 09:08:00 | 18:53:09 → 18:57:28 | COMPLETE | **220,505** | 0 |
| `77fc9f5c-4d80-406a-bf90-f10203256aff` | PRE_SESSION (idempotency rerun) | 18:46:42 → 18:50:38 | COMPLETE | 0 | 206,281 |
| `90649cb1-f5c0-416a-bf4b-bc9fa9193648` | PRE_SESSION (lock-test rerun) | 19:00:12 → 19:04:10 | COMPLETE | 0 | 206,281 |

`stage3_event` records RUN_COMPLETE for each run. Both runs are marked STAGE3_LATE (completed after 09:15), and their values remain point-in-time.

## 11. News feature rows in production

| Snapshot | All rows | `mnews_*` market-wide | `mnews_company_*` | of which MISSING_INPUT | Inputs knowable ≥ as_of | Registry hashes |
|---|---|---|---|---|---|---|
| PRE_SESSION | 206,281 | 32 | 24,871 | 2,128 | **0** | 1 |
| PRE_OPEN | 220,505 | 32 | 24,871 | 2,129 | **0** | 1 |

- **Duplicate feature rows** (same session, snapshot, instrument, feature and registry): **0**.
- `feature_value` total is 801,434: 374,648 from v1 plus 426,786 from 2026-10-08.
- **MISSING_INPUT is never a false zero.** Those rows are `mnews_company_time_since_last_s` for companies with no news in 3 days. Their counts are real zeros, because coverage was proven (a successful poll within 2 h of as_of).

## 12. Point-in-time evidence

- Every news input of every 2026-10-08 row was knowable **before** as_of: 0 exceptions, checked on `input_max_knowable_at`.
- **Production values equal two independent references:**
  - all 32 market-wide values equal the read-only canary for the same snapshot;
  - the top 25 companies equal a raw-SQL recount at 1h / 24h / 3d.

## 13. Duplicate evidence

- In the 24 h window there were 1,990 non-backlog articles knowable before as_of. One is a duplicate: #13758, ET "Hindalco Share Price Live Updates", a duplicate of #11852.
- So `mnews_news_count_24h = 1,989` and `mnews_duplicate_count_24h = 1`.
- Backlog (a source's first poll, arrival time unknown) is never counted as an arrival.

## 14. Feature-level traces (PRE_SESSION, as_of 2026-10-08 08:59:59 IST)

Each value was re-derived from the underlying articles, and every article's `knowable_at` is before as_of. The full article lists are in the JSON.

| Feature | Instrument | Value | Recount | Example article (source, published → discovered = knowable, IST) |
|---|---|---|---|---|
| `mnews_company_count_24h` | ADANIENT | 11 | 11 | #15576 ET, 08:04 → 08:22 |
| `mnews_company_count_24h` | TCS | 11 | 11 | #15596 Mint, 08:41 → 08:53 ("TCS Q2 preview") |
| `mnews_company_count_24h` | TATAPOWER | 10 | 10 | #15586 BS, 08:08 → 08:33 |
| `mnews_company_count_24h` | TITAN | 10 | 10 | #14855 ET, 10-07 17:21 → 17:46 |
| `mnews_company_count_24h` | TATASTEEL | 9 | 9 | #15586 BS, 08:08 → 08:33 |
| `mnews_company_count_1h` | ADANIENT | 1 | 1 | #15576 ET, 08:22 |
| `mnews_company_count_3d` | TCS | 20 | 20 | #15596 Mint |
| `mnews_news_count_1h` | MARKET | 32 | 32 | #15597 CNBC-TV18, 08:37 → 08:54 |

## 15. Idempotency

- Fingerprint of the PRE_SESSION snapshot (count + md5 over instrument, feature, value, reason, inputs hash):
  - before the rerun: `206,281 / 2abc83c5e85f7bc00a64fb58a1e2a317`;
  - after it: **identical**.
- The rerun inserted 0 rows; 206,281 were already present.

## 16. Scheduling

**Crontab** (identical to `ops/cron/prajna.cron`; 0 duplicate entries; no Prajna systemd timer):

| Job | Schedule (IST) |
|---|---|
| News collector supervisor | `*/15 6-22` and `0,15 23` |
| News reconciliation | `45 23` |
| Stage 2 refresh | `30 5` |
| Stage 3 PRE_SESSION | `0 9` + 30 s |
| Stage 3 PRE_OPEN | `22 9` with `--after-replay` |

**Scheduler evidence:**

- The **news collector** has been cron-triggered daily since 2026-09-29 20:45:01; the latest start was 2026-10-08 06:00:01.
- The **nightly reconciliation** has been cron-triggered every day, all OK.
- **Stage 3:** every cron-triggered run from 09-30 to 10-08 was REFUSED (the Stage 1 lock). **The first cron-triggered Stage 3 run after the fix is due 2026-10-09 at 09:00:30 IST, and is PENDING** at the time of writing.

## 17. Failure and recovery

| Case | Result | Evidence |
|---|---|---|
| Stage 3 lock collision | PASS | in production: the second run SKIPped and wrote nothing |
| Stage 3 retry / idempotency | PASS | in production: rerun inserted 0, fingerprint identical |
| Collector overlap | PASS | in production: SKIP markers every 15 min while running |
| Collector kill and restart | PASS | in production, 2026-09-29 |
| Malformed feed | PASS | in production: BS on 10-06; fixed by repair, `a492fbe` |
| Stale feed | PASS | monitoring state; Indian Express |
| HTTP 500 / 429 / timeout / truncated / empty / duplicate / hostile HTML / unsafe URL / oversized payload | PASS | test suite |
| Real database outage | **UNTESTED** | deliberately not induced in production |
| Stage 3 process killed mid-run | **UNTESTED in production** | persistence atomicity is covered by tests |

## 18. Known limitations

- **Indian Express is disabled.**
- **Cross-source story grouping is conservative.** story-v2 prefers precision.
- **"Breaking"** follows observable rules (fast detection of a HIGH item), so NSE results filings qualify.
- **Sentiment is still unsupported**; the news features are volume, recency, scope and direction-word counts.
- **The timing margin is an engineering threshold.** A vendor revision after 300 s will block Stage 1 X again, by design.
- **The D grace expires after 7 days.** If those three listings are still in REVIEW then, D fails again.
- **The 2026-10-08 Stage 3 runs were cron-equivalent and late**; the cron-triggered run is still pending.

## 19. Commits

| Commit | Change |
|---|---|
| `9df2999` | Stage 1 D/X fix and decisions |
| `009445b` | news-v2 activation and duplicate-row engine fix |
| `463b7a2` | monitoring |
| `a492fbe` | XML repair |
| `b384a9e` | canary tool and the backlog rule |
| `8701460` | engine wiring |

Earlier news commits are listed in `docs/NEWS_DEDUP_SPEC.md` and `docs/NEWS_STAGE3_INTEGRATION.md`.

## 20. Final A–R acceptance

| Gate | Status | Evidence |
|---|---|---|
| A Sources | PASS | 7 sources in production; Indian Express disabled by design |
| B Production DB | PASS | 17,025 articles; invariants 0 |
| C Dedup | PASS | 0 duplicate IDs; duplicate excluded from the features (section 13) |
| D Story identity | PASS | story-v2, inspected (conservative) |
| E Updates / corrections | PASS | 1,290 updates; 1 regulator correction |
| F Scope | PASS | scope-v1 on every article |
| G PIT | PASS | 0 violations in the news DB and in `feature_value` inputs |
| H Stage 2 | PASS | `news_pit` → Stage 3 |
| I Stage 3 | PASS | 24,903 news rows per snapshot in production, verified |
| J Scheduling | PASS | collector and reconciliation cron-triggered daily |
| K Failure recovery | PARTIAL | a real DB outage is UNTESTED |
| L Security | PASS | hostile-input tests |
| M Monitoring | PASS | states and nightly reconciliation |
| N Reconciliation | PASS | OK every night since 2026-09-29 |
| O Performance | PASS | Stage 3 ~135–160 s of compute per snapshot; news tables 55 MB after 9 days |
| P Real scheduled production run | **PENDING** | collection is cron-triggered (PASS); Stage 3 cron-triggered with news is due 2026-10-09 09:00:30 |
| Q Restart recovery | PASS | collector kill and restart (2026-09-29) |
| R Evidence | PASS | this report and the JSON |
