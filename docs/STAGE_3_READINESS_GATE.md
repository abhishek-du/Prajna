# Stage 3 readiness gate (2026-09-26 00:15 IST)

**Stage 3 is LOCKED.** This document is a readiness report, not an unlock. Nothing of Stage 3 was implemented.

It is generated from read-only production queries, the acceptance gates and the test runs of 2026-09-25/26. It does not replace `docs/STAGE_3_READINESS_REPORT.md`, which another tool wrote and which is not reviewed here.

## 1. Gate checklist (the directive's unlock conditions)

| # | Condition | State | Evidence |
|---|---|---|---|
| 1 | Stage 1 acceptance COMPLETE | **NOT MET** | `docs/STAGE_1_FINAL_ACCEPTANCE.md`: overall NOT COMPLETE |
| 2 | no FAIL | met | the gate's `failing` list is empty |
| 3 | no BLOCKED | met | none |
| 4 | R resolved | **met** | PASS: sessions 2026-09-24/25 complete; `CLOSE_RERUN_CHECK idempotent=True` |
| 5 | X resolved | **NOT MET** (evidence pending) | WAITING_FOR_EVIDENCE: B1 and revised B2 have 2 of 3 required sessions; 0 violations; 0 late revisions |
| 6 | Stage 2 acceptance resolved | met | `acceptance stage2 --run-tests`: 16/16 PASS |
| 7 | security checks pass | met | `var/acceptance/secret_scan_20260925_final.json`: no secret outside its intended store; revoked token rejected; `old.token` deleted |
| 8 | migrations at the expected head | met | alembic `0010 (head)` |
| 9 | repository clean | **met for our work** | every change is committed; the untracked files are the external tool's (`frontend/`, `backend/app/api/`, one test, five docs) and are deliberately not committed or deleted |
| 10 | final Stage 1 report generated | met | `docs/STAGE_1_ARCHITECTURE_HARDENING_REPORT.md` |

- **Decisive gaps:** conditions 1 and 5, and they are the same gap. X needs one more real session for B1 (the 2026-09-25 daily bar, observed after it appears overnight) and one for B2 (the next trading session, 2026-09-28).
- **Where the evidence comes from:** the running poller and the scheduled timing monitor collect it without intervention.
- **What if a session disagrees:** if either contract is contradicted instead, X becomes BLOCKED and the TIMING-REVIEW decision is required.

## 2. Available datasets (production, ACTIVE canonical universe)

**Universe:** 3,532 canonical instruments.
- 3,155 STOCK
- 351 FUND_UNIT
- 21 OTHER (InvIT)
- 2 RIGHTS_ENTITLEMENT (1 ACTIVE, 1 REMOVED_FROM_MASTER)
- 3 indices (NIFTY, BANKNIFTY, INDIA VIX)

| Dataset | Instruments | From | To | Depth | Notes |
|---|---|---|---|---|---|
| 1D bars | 3,529 | 2020-01-01 | 2026-09-24 | 1,674 sessions, 3.65 M bars | vendor-adjusted as of fetch (basis recorded); before 2025-09-24 LOW confidence for adjustment |
| 1m bars | 3,456 | 2026-09-23 | 2026-09-25 | 3 sessions, 2.45 M bars | RAW_OBSERVED from the close; +1 session per close |
| 15m bars | 3,456 | 2026-09-24 | 2026-09-25 | 2 sessions | as above |
| 1h bars | 3,456 | 2026-09-24 | 2026-09-25 | 2 sessions | as above |
| 5m | — | — | — | — | OUT_OF_SCOPE (D2-5m) |
| Fundamentals | 3,529 (key ratios 3,133; shareholding 3,174) | statements from 2003/2012/2017 (by type) | 2026-06-30 | 12 statement types | snapshots with knowable_at; vendor payloads |
| Corporate actions | — | 2025-09-24 | 2026-09-24 | 2,320 events | ~1 year vendor depth; `ca_factor` v1 (139 EXACT split/bonus; rights / dividends UNSUPPORTED) |
| Global markets | 13 | 2020-03/04 | 2026-09-24 (N225 2026-09-22) | ~1,580–1,830 labels each | confirmed labels only; per-instrument label semantics |
| News | 167 articles, 509 links | published 2026-09-17 | 2026-09-25 | vendor keeps 7 days | publication vs receipt; 30-min market-hours polling since 2026-09-25 |
| FII/DII | 30+ series | 2026-04-01 | 2026-09-24 | 121 days each | |
| Pre-open | full universe | 2026-09-24 | 2026-09-25 | 2 sessions | |
| Trading calendar | — | 2020-01-01 | forward | | |

**Timestamps and provenance on every row:**
- `knowable_at` (strict `< as_of` reads), `fetched_at`, `run_id` and `payload_sha256`;
- the raw payload is archived first;
- the price basis is recorded per payload;
- vendor revisions are append-only observations;
- global finality and instrument lifecycle periods are recorded.

## 3. Data-quality limitations Stage 3 must respect

1. **Mixed price basis.** Pre-2025-09 1D history is vendor-adjusted and cannot be reconstructed as raw. `bars_adjusted` refuses LOW-confidence rows by default.
2. **Short intraday history.** It is 2–3 sessions deep (historical intraday backfill DEFERRED).
3. **Timing.** 1m/15m/1h bars are timing-final only after bar end + 120 s: an engineering threshold, not a vendor guarantee. The index 1m close is revised up to 95.6 s after the end. `knowable_at` is always the fetch time.
4. **Global labels** are vendor labels, not trading dates. Revised and placeholder labels are withheld.
5. **News** before 2026-09-24 is limited to the vendor's 7-day window. There is no publisher or category, and no market-wide feed.
6. **Corporate actions** only reach back about a year. Rights factors are unsupported.
7. **No live tick store** (criterion L OUT_OF_SCOPE).
8. **Survivorship-biased** equity history (policy accepted, criterion Y).

## 4. Remaining warm-up requirements

None can be stated until Stage 3 fixes its feature lookbacks.
- **Planning tool:** `prajna ops warmup-plan --sessions N --timeframe …` (read-only).
- **Example:** 20 sessions of 1m + 15m + 1h ≈ 17,655 requests ≈ 8.8 h at fraction 0.5.
- **Not run:** the full historical backfill (about 293k requests) stays DEFERRED.
- **Daily features** with ≤ 6-year lookbacks need no warm-up.

## 5. API contracts for the frontend

`docs/API_CONTRACT.md` (read-only `/v1`, point-in-time), implemented and tested. It covers the 14 areas plus market session, batched latest prices and global finality.

Missing capabilities, listed in `docs/web/FRONTEND_API_MAPPING.md` §"Missing backend capabilities":
- breadth and movers;
- universe-wide screener sort;
- company market cap and 52-week range;
- live ticks;
- news publisher and category;
- CA payment date;
- a faster `/v1/global`.

## 6. Recommended Stage 3 feature dependencies (inputs only; no features designed here)

| Feature family | Canonical input | PIT access | Constraint |
|---|---|---|---|
| daily price and volume | `canon_market_bar` 1D | `pit.bars` / `pit.bars_adjusted(as_of)` | refuse LOW confidence unless explicitly accepted; state the basis |
| intraday | 1m / 15m / 1h | `pit.bars` | start after bar_end + margin; history = sessions since 2026-09-23 or a planned warm-up |
| corporate-action-aware returns | `ca_factor` | `pit.bars_adjusted` | factors knowable before as_of only |
| fundamentals / valuation | `canon_fundamental` | `pit.fundamentals(as_of)` | the latest snapshot knowable at as_of |
| sector membership | profile snapshots | `pit.sector(as_of)` (never `canon_instrument.sector`) | |
| global context | `canon_global_bar` | `pit.global_bars` | confirmed labels only; label ≠ trading date |
| flows | `canon_macro_observation` (FII/DII) | `pit.macro` | publication lag |
| news / events | `canon_news` | `pit.news(as_of)` | the instrument link must be knowable |
| pre-open | `canon_preopen` | `pit.preopen` | |
| universe | lifecycle periods | `pit.coverage` / lifecycle | as-of membership, not today's master |
