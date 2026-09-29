# Stage 3 acceptance (feature engineering)

**Generated:** 2026-09-29T05:29:10.470177+00:00 by `prajna acceptance stage3` (read-only; regenerate, do not edit).

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
| B | Determinism: recomputing a snapshot gives identical values, reasons and input hashes | **PASS** | {"instruments": ["NSE_EQ\|INE0URU01010", "NSE_EQ\|INE094A01015", "NSE_EQ\|INF174KA1YO3", "NSE_EQ\|INE245A01021", "NSE_EQ\|INE0PLQ01011"], "identical": {"PRE_SESSION": true, "PRE_OPEN": true}} |  |
| C | Point in time: every input of every value was knowable strictly before the snapshot instant | **PASS** | {"dry_run_rows": 2488, "violations": 0, "stored_violations": 0, "db_check": "ck_feature_pit"} |  |
| D | Look-ahead probe: a past snapshot uses no bar of its own session or later although such bars now exist | **PASS** | {"session": "2026-09-22", "as_of": "2026-09-22T03:29:59+00:00", "bars_now_in_db_at_or_after_session": 25, "used": 0} | plus tests: TestPointInTime (injected facts at as_of change nothing) |
| E | Corporate actions and price basis: bars come from pit.bars_adjusted (factors knowable at as_of); LOW-confidence and RECONSTRUCTED bars are refused and never used | **PASS** | {"adjusted_bars_in_sample": 302, "refused_bars_in_sample": 988, "refused_by_snapshot": {"PRE_SESSION": {"reconstructed": 0, "low_confidence": 988}, "PRE_OPEN": {"reconstructed": 0, "low_confidence": 988}}, "rule": "PASS needs >= 1 bar adjusted by a knowable action in the sample"} | plus tests: TestPriceBasis (bonus adjusted; action not yet knowable not applied; LOW refused) |
| F | Missing data is a null with a reason; nothing is filled | **PASS** | {"PRE_SESSION": {"DIVISION_UNDEFINED": 2, "INSUFFICIENT_HISTORY": 9, "MALFORMED_INPUT": 29, "MISSING_INPUT": 250}, "PRE_OPEN": {"DIVISION_UNDEFINED": 3, "INSUFFICIENT_HISTORY": 9, "MALFORMED_INPUT": 29, "MISSING_INPUT": 252}, "contract_violations": 0} |  |
| G | Idempotency: a rerun inserts nothing; a disagreeing recompute fails the run instead of overwriting | **PASS** | {"duplicate_keys_stored": 0, "constraint": "uq_feature_value", "tests": "TestRun (idempotent, determinism mismatch, restart)"} |  |
| H | Execution lock: a production write is refused unless every condition holds (checked in the engine itself, audited) | **PASS** | {"run_lock_now": [{"name": "stage3_enabled", "ok": false, "detail": "PRAJNA_STAGE3_ENABLED is false (default; production execution not approved)"}, {"name": "kill_switch_off", "ok": true, "detail": "not engaged"}, {"name": "stage1_complete", "ok": true, "detail": "overall COMPLETE"}, {"name": "stage2_pass", "ok": true, "detail": "PASS, generated 2026-09-28T17:48:51.443631+00:00"}, {"name": "decisions_approved", "ok": true, "detail": "all approved"}, {"name": "registry_consistent", "ok": true, "detail": "consistent"}, {"name": "write_token", "ok": false, "detail": "AuthorizationError"}]} | tests: TestLocks (each condition alone refuses; defaults refuse) |
| I | Backfill lock: a feature backfill additionally needs PRAJNA_STAGE3_BACKFILL_ENABLED; Stage 3 never starts the Stage 1 backfill | **PASS** | {"backfill_enabled": {"name": "backfill_enabled", "ok": false, "detail": "PRAJNA_STAGE3_BACKFILL_ENABLED is false (default; feature backfill not approved)"}, "backfill_lock_now": {"mode": "BACKFILL", "unlocked": false, "failing": ["stage3_enabled", "backfill_enabled", "write_token"]}} |  |
| J | No vendor call: app.features imports no vendor, network or fetch module | **PASS** | {"forbidden": [], "from_app_ingest": ["app.ingest.runner"]} |  |
| K | The full test suite passes (Stage 1 + 2 + 3) | **PASS** | {"exit": 0, "summary": "1122 passed, 4 skipped in 337.75s (0:05:37)"} | run with --run-tests |
| L | Dry-run on real data: a sample of instruments at both snapshots of the latest session computes | **PASS** | {"session": "2026-09-29", "instruments": ["NSE_EQ\|INE0URU01010", "NSE_EQ\|INE094A01015", "NSE_EQ\|INF174KA1YO3", "NSE_EQ\|INE245A01021", "NSE_EQ\|INE0PLQ01011", "NSE_EQ\|INE321T01012", "NSE_EQ\|INE0PSC01024", "NSE_EQ\|INE0LOJ01019", "NSE_EQ\|INE842C01021", "NSE_EQ\|INE280B01018", "NSE_EQ\|INE454P01035", "NSE_EQ\|INE0Q7P01013", "NSE_EQ\|INE784W01015", "NSE_EQ\|INE528A01020", "NSE_EQ\|INE716B01029", "NSE_EQ\|INE022C01012", "NSE_EQ\|INE764D01017", "NSE_EQ\|INE906O01029", "NSE_EQ\|INE242C01024", "NSE_EQ\|INE553C01016", "NSE_EQ\|INE2FMX01012", "NSE_EQ\|INE0PT101017", "NSE_EQ\|INE524T01029"], "errors": {}, "PRE_SESSION": {"rows": 1198, "values": 908, "nulls_by_reason": {"DIVISION_UNDEFINED": 2, "INSUFFICIENT_HISTORY": 9, "MALFORMED_INPUT": 29, "MISSING_INPUT": 250}, "refused_bars": {"reconstructed": 0, "low_confidence": 988}, "seconds": 49.21, "instruments": 23, "as_of": "2026-09-29T03:29:59+ |  |
| M | Prerequisites: Stage 1 COMPLETE (evaluated now) and Stage 2 PASS | **PASS** | {"stage1": "overall COMPLETE", "stage2": "PASS, generated 2026-09-28T17:48:51.443631+00:00"} |  |
| N | Every Stage 3 decision is approved | **PASS** | {"pending": {}, "all": {"FEATURE-SCOPE": "APPROVED", "FEATURE-PARAMS": "APPROVED", "FII-DII-STALENESS": "APPROVED", "FEATURE-SNAPSHOTS": "APPROVED", "FEATURE-NO-SOURCE": "APPROVED"}} |  |
| O | Production evidence: at least one committed snapshot of features | **PASS** | {"complete_runs": 3, "backfill_runs": 0, "failed_runs": 0, "stored_values": 374648, "latest_session": "2026-09-29"} | stays PENDING while production execution is locked |

Registry: `9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188`

## What unlocks production

1. Stage 1 COMPLETE, evaluated fresh at execution time (criterion M).
2. Stage 2 report PASS, at most 7 days old, with its tests (M).
3. Every Stage 3 decision approved (N; FEATURE-PARAMS approved 2026-09-28).
4. `PRAJNA_STAGE3_ENABLED=true`, the kill switch released, and a write token. A feature backfill additionally needs `PRAJNA_STAGE3_BACKFILL_ENABLED=true`.

Until then `prajna stage3 run --commit` and `prajna stage3 backfill --commit` are refused, and the refusal is recorded in `stage3_event`.
