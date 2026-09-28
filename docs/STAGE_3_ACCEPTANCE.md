# Stage 3 acceptance (feature engineering)

**Generated:** 2026-09-28T17:03:00.534759+00:00 by `prajna acceptance stage3` (read-only; regenerate, do not edit).

## Overall: **NOT COMPLETE (PRODUCTION READY)**

Stage 3 is COMPLETE only when production execution is unlocked AND there is production evidence (O). Passing tests or a dry-run never makes it COMPLETE.

## Levels

| Level | Reached | Detail |
|---|---|---|
| IMPLEMENTED | **YES** | 65 features, 31 diagram items |
| TESTED | **YES** | K PASS |
| DRY-RUN READY | **YES** | A-L PASS |
| PRODUCTION READY | **YES** | M PASS, N PASS |
| PRODUCTION UNLOCKED | **no** | PRAJNA_STAGE3_ENABLED=False, kill switch off |
| BACKFILL EXECUTED | **no** | 0 committed backfill runs (feature backfill deferred) |

## Criteria

| # | Question | Status | Evidence | Notes |
|---|---|---|---|---|
| A | Every item of the Stage 3 diagram is registered (IMPLEMENTED / PARTIAL / UNSUPPORTED / UNKNOWN, with the reason) | **PASS** | {"version": "features-v1", "registry_sha256": "9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188", "features": 65, "implemented": 65, "proposed_parameters": 29, "diagram_items": 31, "diagram_items_by_status": {"IMPLEMENTED": 19, "PARTIAL": 6, "UNSUPPORTED": 4, "UNKNOWN": 2}, "unexplained": [], "unknown_feature_ids": []} |  |
| B | Determinism: recomputing a snapshot gives identical values, reasons and input hashes | **PASS** | {"instruments": ["NSE_EQ\|INE697V01011", "NSE_EQ\|INF200KB1AK8", "NSE_EQ\|INF205KA1BP1", "NSE_EQ\|INE0QBU01012", "NSE_EQ\|INE07K301024"], "identical": {"PRE_SESSION": true, "PRE_OPEN": true}} |  |
| C | Point in time: every input of every value was knowable strictly before the snapshot instant | **PASS** | {"dry_run_rows": 2488, "violations": 0, "stored_violations": 0, "db_check": "ck_feature_pit"} |  |
| D | Look-ahead probe: a past snapshot uses no bar of its own session or later although such bars now exist | **PASS** | {"session": "2026-09-21", "as_of": "2026-09-21T03:29:59+00:00", "bars_now_in_db_at_or_after_session": 21, "used": 0} | plus tests: TestPointInTime (injected facts at as_of change nothing) |
| E | Corporate actions and price basis: bars come from pit.bars_adjusted (factors knowable at as_of); LOW-confidence and RECONSTRUCTED bars are refused and never used | **PASS** | {"adjusted_bars_in_sample": 302, "refused_bars_in_sample": 898, "refused_by_snapshot": {"PRE_SESSION": {"reconstructed": 0, "low_confidence": 898}, "PRE_OPEN": {"reconstructed": 0, "low_confidence": 898}}, "rule": "PASS needs >= 1 bar adjusted by a knowable action in the sample"} | plus tests: TestPriceBasis (bonus adjusted; action not yet knowable not applied; LOW refused) |
| F | Missing data is a null with a reason; nothing is filled | **PASS** | {"PRE_SESSION": {"DIVISION_UNDEFINED": 6, "INSUFFICIENT_HISTORY": 16, "MALFORMED_INPUT": 26, "MISSING_INPUT": 352}, "PRE_OPEN": {"DIVISION_UNDEFINED": 9, "INSUFFICIENT_HISTORY": 16, "MALFORMED_INPUT": 26, "MISSING_INPUT": 367}, "contract_violations": 0} |  |
| G | Idempotency: a rerun inserts nothing; a disagreeing recompute fails the run instead of overwriting | **PASS** | {"duplicate_keys_stored": 0, "constraint": "uq_feature_value", "tests": "TestRun (idempotent, determinism mismatch, restart)"} |  |
| H | Execution lock: a production write is refused unless every condition holds (checked in the engine itself, audited) | **PASS** | {"run_lock_now": [{"name": "stage3_enabled", "ok": false, "detail": "PRAJNA_STAGE3_ENABLED is false (default; production execution not approved)"}, {"name": "kill_switch_off", "ok": true, "detail": "not engaged"}, {"name": "stage1_complete", "ok": true, "detail": "overall COMPLETE"}, {"name": "stage2_pass", "ok": true, "detail": "PASS, generated 2026-09-28T16:51:11.575744+00:00"}, {"name": "decisions_approved", "ok": true, "detail": "all approved"}, {"name": "registry_consistent", "ok": true, "detail": "consistent"}, {"name": "write_token", "ok": false, "detail": "AuthorizationError"}]} | tests: TestLocks (each condition alone refuses; defaults refuse) |
| I | Backfill lock: a feature backfill additionally needs PRAJNA_STAGE3_BACKFILL_ENABLED; Stage 3 never starts the Stage 1 backfill | **PASS** | {"backfill_enabled": {"name": "backfill_enabled", "ok": false, "detail": "PRAJNA_STAGE3_BACKFILL_ENABLED is false (default; feature backfill not approved)"}, "backfill_lock_now": {"mode": "BACKFILL", "unlocked": false, "failing": ["stage3_enabled", "backfill_enabled", "write_token"]}} |  |
| J | No vendor call: app.features imports no vendor, network or fetch module | **PASS** | {"forbidden": [], "from_app_ingest": ["app.ingest.runner"]} |  |
| K | The full test suite passes (Stage 1 + 2 + 3) | **PASS** | {"exit": 0, "summary": "1122 passed, 4 skipped in 327.91s (0:05:27)"} | run with --run-tests |
| L | Dry-run on real data: a sample of instruments at both snapshots of the latest session computes | **PASS** | {"session": "2026-09-28", "instruments": ["NSE_EQ\|INE697V01011", "NSE_EQ\|INF200KB1AK8", "NSE_EQ\|INF205KA1BP1", "NSE_EQ\|INE0QBU01012", "NSE_EQ\|INE07K301024", "NSE_EQ\|INE268L01046", "NSE_EQ\|INE0WO601020", "NSE_EQ\|INE158A01026", "NSE_EQ\|INE540H01012", "NSE_EQ\|INE075Z01011", "NSE_EQ\|INE09EO01013", "NSE_EQ\|INE767C01012", "NSE_EQ\|INE277B01014", "NSE_EQ\|INF754K01VW2", "NSE_EQ\|INE500L01026", "NSE_EQ\|INE933X01016", "NSE_EQ\|INE12E301017", "NSE_EQ\|INF247L01HG7", "NSE_EQ\|INE855B01025", "NSE_EQ\|INE732A01036", "NSE_EQ\|INE2FMX01012", "NSE_EQ\|INE0PT101017", "NSE_EQ\|INE524T01029"], "errors": {}, "PRE_SESSION": {"rows": 1198, "values": 798, "nulls_by_reason": {"DIVISION_UNDEFINED": 6, "INSUFFICIENT_HISTORY": 16, "MALFORMED_INPUT": 26, "MISSING_INPUT": 352}, "refused_bars": {"reconstructed": 0, "low_confidence": 898}, "seconds": 37.87, "instruments": 23, "as_of": "2026-09-28T03:29:59 |  |
| M | Prerequisites: Stage 1 COMPLETE (evaluated now) and Stage 2 PASS | **PASS** | {"stage1": "overall COMPLETE", "stage2": "PASS, generated 2026-09-28T16:51:11.575744+00:00"} |  |
| N | Every Stage 3 decision is approved | **PASS** | {"pending": {}, "all": {"FEATURE-SCOPE": "APPROVED", "FEATURE-PARAMS": "APPROVED", "FII-DII-STALENESS": "APPROVED", "FEATURE-SNAPSHOTS": "APPROVED", "FEATURE-NO-SOURCE": "APPROVED"}} |  |
| O | Production evidence: at least one committed snapshot of features | **PENDING** | {"complete_runs": 0, "backfill_runs": 0, "failed_runs": 0, "stored_values": 0, "latest_session": null} | stays PENDING while production execution is locked |

Registry: `9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188`

## What unlocks production

1. Stage 1 COMPLETE, evaluated fresh at execution time (criterion M).
2. Stage 2 report PASS, at most 7 days old, with its tests (M).
3. Every Stage 3 decision approved (N; FEATURE-PARAMS approved 2026-09-28).
4. `PRAJNA_STAGE3_ENABLED=true`, the kill switch released, and a write token. A feature backfill additionally needs `PRAJNA_STAGE3_BACKFILL_ENABLED=true`.

Until then `prajna stage3 run --commit` and `prajna stage3 backfill --commit` are refused, and the refusal is recorded in `stage3_event`.
