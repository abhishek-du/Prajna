# Stage 2 acceptance

**Generated:** 2026-10-09T09:26:18.995284+00:00 by `prajna acceptance stage2` (read-only; regenerate, do not edit).

## Overall: **PASS**

Stage 3 stays locked until this is PASS.

| # | Question | Status | Evidence | Notes |
|---|---|---|---|---|
| A | Can Stage 2 process Stage 1 data? | **PASS** | {"latest_commit_run": "0bad8bb5-393e-48f4-9864-c8c1786e23ce", "mode": "FULL", "seconds": 62.4, "instruments_current/decided/included": [3588, 3588, 3575], "coverage_pairs": 14300, "coverage_ranges": 117325} |  |
| B | Is data normalized consistently? | **PASS** | {"duplicate_bars": 0, "invalid_timeframe": 0, "null_required_bar_fields": 0, "coverage_contradicts_bars": 0, "non_session_bars_exposed": 0} |  |
| C | Are timestamps correct? | **PASS** | {"bar_knowable_before_event_end": 0, "daily_bar_fetched_same_session": 0, "daily_label_not_0000_ist": 0, "daily_event_not_session_hours": 0, "intraday_outside_session": 0, "market_date_not_label_date": 0} | D4: daily label 00:00 IST; event = the session's own hours (Muhurat sessions included); knowable after it |
| D | Is knowable_at preserved? | **PASS** | {"canonical_vs_stage1_mismatches": 0, "knowable_after_fetched": 0} |  |
| E | Is future leakage impossible? | **PASS** | {"real_db_probes": {"seed": 536607189, "instruments_probed": 40, "rows_returned_after_boundary": 47085, "boundary_behaviour_correct": 40, "coverage_point_in_time": 40}, "tests": ["TestPointInTime", "test_knowable_is_strictly_before"]} | every read requires as_of (coverage too); rows with knowable_at >= as_of are never returned |
| F | Is NSE filtering correct? | **PASS** | {"non_nse_included": 0, "eligible_equity_excluded": 0, "global_included": 0, "stale_rules": 0, "missing_reason": 0, "rules_sha256": "911fa7abf926ed38736e815cdfb69aac4cba63bf654e345b8ceb2392515df5f6"} |  |
| G | Is instrument mapping correct? | **PASS** | {"mapping_mismatches": 0, "orphans": 0, "missing_identifiers": 0} |  |
| H | Is data enrichment traceable? | **PASS** | {"instruments_with_sector": 3214, "sector_not_traceable_to_snapshot": 0} | sector coverage grows with the Stage 1 fundamentals sweep; PIT sector via pit.sector() |
| I | Is missing data represented correctly? | **PASS** | {"sessions_by_state": {"QUARANTINED": 2, "EMPTY": 2324178, "DATA": 3795224, "PENDING_BACKFILL": 8791670, "VENDOR_ERROR": 7}, "out_of_scope": "5m via pit.coverage/pit.bars (OutOfScope)"} | nothing is filled: no zero, no forward fill, no interpolation |
| J | Is bad data quarantined? | **PASS** | {"stage1_quarantined_bars_nse": 2, "coverage_quarantined_sessions": 2, "invalid_ohlc_visible": 0, "non_session_placeholder_bars_excluded": 69} |  |
| K | Is processing idempotent? | **PASS** | {"real_noop_reruns": ["d0d449e5-ab3b-4b07-90d4-cf9243c1aca1", "1a48ab3a-c905-4b1e-a612-988dd3a20249", "d9dfb6ac-429b-40ca-b379-058cb57e310d"], "tests": ["test_idempotent_three_runs", "test_stage1_ingest_is_processed_and_served_point_in_time"]} |  |
| L | Can processing resume after failure? | **PASS** | {"tests": ["test_crash_rolls_back_and_the_rerun_resumes"], "failed_canon_runs": 0, "note": "rows and checkpoint commit in one transaction"} |  |
| M | Can Stage 2 process incremental Stage 1 updates? | **PASS** | {"real_incremental_runs": ["3c60d7c9-8915-4c6b-94cc-61cfde058da6", "3bcb7bef-5c86-4fef-9550-141cd1c19db7", "0da30138-79a6-4701-939b-bf11b55d2034"], "tests": ["test_incremental_update_touches_only_the_new_pair"]} | real evidence needs a Stage 1 run finishing after a Stage 2 checkpoint |
| N | Are database constraints enforced? | **PASS** | {"missing_constraints": [], "tests": ["test_db_constraints"]} |  |
| O | Can Stage 3 consume the canonical data safely? | **PASS** | {"seed": 536614958, "probed": 10, "ok": 10, "probes": {"NSE_EQ\|INE002A01018": {"daily_bars": 250, "corporate_actions": 1, "news": 11, "fundamentals": 12, "sector": "Refineries", "coverage_ranges": 1}, "NSE_INDEX\|Nifty 50": {"daily_bars": 250, "corporate_actions": 0, "news": 0, "fundamentals": 0, "sector": null, "coverage_ranges": 1}, "NSE_EQ\|IN9175A01010": {"daily_bars": 250, "corporate_actions": 0, "news": 0, "fundamentals": 11, "sector": "Miscellaneous", "coverage_ranges": 1}, "NSE_EQ\|INE0LXA01019": {"daily_bars": 250, "corporate_actions": 1, "news": 0, "fundamentals": 12, "sector": "Medical Equipment", "coverage_ranges": 96}, "NSE_EQ\|INE813A01018": {"daily_bars": 250, "corporate_acti |  |
| P | Are all existing Stage 1 tests still passing? | **PASS** | {"exit": 0, "summary": "1336 passed, 4 skipped in 399.93s (0:06:39)"} |  |

## Quality gates

| gate | status | count |
|---|---|---|
| duplicate_bars | PASS | 0 |
| invalid_ohlc | PASS | 0 |
| negative_volume | PASS | 0 |
| null_required_bar_fields | PASS | 0 |
| knowable_after_fetched | PASS | 0 |
| bar_knowable_before_event_end | PASS | 0 |
| daily_bar_fetched_same_session | PASS | 0 |
| non_session_bars_exposed | PASS | 0 |
| orphan_instruments | PASS | 0 |
| invalid_exchange | PASS | 0 |
| invalid_timeframe | PASS | 0 |
| missing_identifiers | PASS | 0 |
| unexpected_gaps | PASS | 0 |
| duplicate_corporate_actions | PASS | 0 |
| duplicate_news_mappings | PASS | 0 |
| invalid_fundamentals | PASS | 0 |
| calendar_gaps_in_depth | PASS | 0 |
| coverage_contradicts_bars | PASS | 0 |

Informational: `{"sector_null_rate_nse_eq": 0.1002, "bars_excluded_non_session (canon_excluded_bar)": 69, "fundamentals_period_label_after_fetch": 49}`

## Dependence on Stage 1 (not yet complete)

- 15m PENDING_BACKFILL: 4,190,143 sessions pending
- 1d PENDING_BACKFILL: 20 sessions pending
- 1h PENDING_BACKFILL: 4,190,143 sessions pending
- 1m PENDING_BACKFILL: 411,364 sessions pending
- sector: grows with the fundamentals sweep (Stage 1 criterion D/O)

## Known limitations

- Market data is not copied. The canonical layer is views over the validated Stage 1 tables, plus two derived tables.
- `pit.coverage(key, tf, as_of)` is point-in-time. `pit.current_coverage` (the materialized table) is what Stage 1 holds **now**, for live use and operations only.
- `canon_instrument.sector` is the **current** sector. The historical sector comes from `pit.sector(key, as_of)`.
- A news-instrument association is knowable only when the vendor link was fetched (the Stage 1 contract), so historical news associations become visible from their fetch time.
- The daily convention is D4 (session_date label; knowable after the session). There is no 09:15 timestamp for daily bars.
- Upstox is the only vendor: there is no NSE HTTP connector, because NSE data arrives via Upstox.
