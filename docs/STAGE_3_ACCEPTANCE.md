# Stage 3 acceptance (feature engineering)

**Generated:** 2026-10-09T09:39:12.103216+00:00 by `prajna acceptance stage3` (read-only; regenerate, do not edit).

## Overall: **NOT COMPLETE (TESTED)**

Stage 3 is COMPLETE only when production execution is unlocked AND there is production evidence (O). Passing tests or a dry-run never makes it COMPLETE.

## Levels

| Level | Reached | Detail |
|---|---|---|
| IMPLEMENTED | **YES** | 104 features, 31 diagram items |
| TESTED | **YES** | K PASS |
| DRY-RUN READY | **no** | E PENDING |
| PRODUCTION READY | **no** | M PASS, N PASS |
| PRODUCTION UNLOCKED | **no** | PRAJNA_STAGE3_ENABLED=True, kill switch off |
| BACKFILL EXECUTED | **no** | 0 committed backfill runs (feature backfill deferred) |

## Criteria

| # | Question | Status | Evidence | Notes |
|---|---|---|---|---|
| A | Every item of the Stage 3 diagram is registered (IMPLEMENTED / PARTIAL / UNSUPPORTED / UNKNOWN, with the reason) | **PASS** | {"version": "features-v4", "registry_sha256": "6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3", "features": 104, "implemented": 104, "proposed_parameters": 68, "diagram_items": 31, "diagram_items_by_status": {"IMPLEMENTED": 19, "PARTIAL": 6, "UNSUPPORTED": 4, "UNKNOWN": 2}, "unexplained": [], "unknown_feature_ids": []} |  |
| B | Determinism: recomputing a snapshot gives identical values, reasons and input hashes | **PASS** | {"instruments": ["NSE_EQ\|INE024001021", "NSE_EQ\|INE095I01015", "NSE_EQ\|INF769K01KF8", "NSE_EQ\|INE0INJ01017", "NSE_EQ\|INE676A01027"], "identical": {"PRE_SESSION": true, "PRE_OPEN": true}} |  |
| C | Point in time: every input of every value was knowable strictly before the snapshot instant | **PASS** | {"dry_run_rows": 2874, "violations": 0, "stored_violations": 0, "db_check": "ck_feature_pit"} |  |
| D | Look-ahead probe: a past snapshot uses no bar of its own session or later although such bars now exist | **PASS** | {"session": "2026-10-01", "as_of": "2026-10-01T03:29:59+00:00", "bars_now_in_db_at_or_after_session": 25, "used": 0} | plus tests: TestPointInTime (injected facts at as_of change nothing) |
| E | Corporate actions and price basis: bars come from pit.bars_adjusted (factors knowable at as_of); LOW-confidence and RECONSTRUCTED bars are refused and never used | **PENDING** | {"adjusted_bars_in_sample": 0, "refused_bars_in_sample": 789, "refused_by_snapshot": {"PRE_SESSION": {"reconstructed": 0, "low_confidence": 789}, "PRE_OPEN": {"reconstructed": 0, "low_confidence": 789}}, "rule": "PASS needs >= 1 bar adjusted by a knowable action in the sample"} | plus tests: TestPriceBasis (bonus adjusted; action not yet knowable not applied; LOW refused) |
| F | Missing data is a null with a reason; nothing is filled | **PASS** | {"PRE_SESSION": {"DIVISION_UNDEFINED": 7, "INSUFFICIENT_HISTORY": 25, "MALFORMED_INPUT": 28, "MISSING_INPUT": 334}, "PRE_OPEN": {"DIVISION_UNDEFINED": 8, "INSUFFICIENT_HISTORY": 25, "MALFORMED_INPUT": 28, "MISSING_INPUT": 347}, "contract_violations": 0} |  |
| G | Idempotency: a rerun inserts nothing; a disagreeing recompute fails the run instead of overwriting | **PASS** | {"duplicate_keys_stored": 0, "constraint": "uq_feature_value", "tests": "TestRun (idempotent, determinism mismatch, restart)"} |  |
| H | Execution lock: a production write is refused unless every condition holds (checked in the engine itself, audited) | **PASS** | {"run_lock_now": [{"name": "stage3_enabled", "ok": true, "detail": "PRAJNA_STAGE3_ENABLED=true"}, {"name": "kill_switch_off", "ok": true, "detail": "not engaged"}, {"name": "stage1_complete", "ok": true, "detail": "overall COMPLETE"}, {"name": "stage2_pass", "ok": true, "detail": "PASS, generated 2026-10-09T09:26:18.995284+00:00"}, {"name": "decisions_approved", "ok": true, "detail": "all approved"}, {"name": "registry_consistent", "ok": true, "detail": "consistent"}, {"name": "write_token", "ok": false, "detail": "AuthorizationError"}]} | tests: TestLocks (each condition alone refuses; defaults refuse) |
| I | Backfill lock: a feature backfill additionally needs PRAJNA_STAGE3_BACKFILL_ENABLED; Stage 3 never starts the Stage 1 backfill | **PASS** | {"backfill_enabled": {"name": "backfill_enabled", "ok": false, "detail": "PRAJNA_STAGE3_BACKFILL_ENABLED is false (default; feature backfill not approved)"}, "backfill_lock_now": {"mode": "BACKFILL", "unlocked": false, "failing": ["backfill_enabled", "write_token"]}} |  |
| J | No vendor call: app.features imports no vendor, network or fetch module | **PASS** | {"forbidden": [], "from_app_ingest": ["app.ingest.runner"]} |  |
| K | The full test suite passes (Stage 1 + 2 + 3) | **PASS** | {"exit": 0, "summary": "1336 passed, 4 skipped in 400.58s (0:06:40)"} | run with --run-tests |
| L | Dry-run on real data: a sample of instruments at both snapshots of the latest session computes | **PASS** | {"session": "2026-10-09", "instruments": ["NSE_EQ\|INE024001021", "NSE_EQ\|INE095I01015", "NSE_EQ\|INF769K01KF8", "NSE_EQ\|INE0INJ01017", "NSE_EQ\|INE676A01027", "NSE_EQ\|INE671C01016", "NSE_EQ\|INE594H01019", "NSE_EQ\|INE036A01016", "NSE_EQ\|INE218I01013", "NSE_EQ\|INE598C01011", "NSE_EQ\|INE546C01010", "NSE_EQ\|INE743M01012", "NSE_EQ\|INE1FCO01014", "NSE_EQ\|INE761G01016", "NSE_EQ\|INE0PXD01014", "NSE_EQ\|INE497D01022", "NSE_EQ\|INE549H01021", "NSE_EQ\|INE586X01012", "NSE_EQ\|INE171A01029", "NSE_EQ\|INE488B01017", "NSE_EQ\|INE835B01035", "NSE_EQ\|INE893J01029", "NSE_EQ\|INE24OJ01029"], "errors": {}, "PRE_SESSION": {"rows": 1391, "values": 997, "nulls_by_reason": {"DIVISION_UNDEFINED": 7, "INSUFFICIENT_HISTORY": 25, "MALFORMED_INPUT": 28, "MISSING_INPUT": 334}, "refused_bars": {"reconstructed": 0, "low_confidence": 789}, "seconds": 51.67, "instruments": 23, "as_of": "2026-10-09T03:29:59 |  |
| M | Prerequisites: Stage 1 COMPLETE (evaluated now) and Stage 2 PASS | **PASS** | {"stage1": "overall COMPLETE", "stage2": "PASS, generated 2026-10-09T09:26:18.995284+00:00"} |  |
| N | Every Stage 3 decision is approved | **PASS** | {"pending": {}, "all": {"FEATURE-SCOPE": "APPROVED", "FEATURE-PARAMS": "APPROVED", "FII-DII-STALENESS": "APPROVED", "FEATURE-SNAPSHOTS": "APPROVED", "FEATURE-NO-SOURCE": "APPROVED", "CA-OBSERVED": "APPROVED", "F3-PAYLOAD-BASIS": "APPROVED"}} |  |
| O | Production evidence: at least one committed snapshot of features | **PASS** | {"complete_runs": 8, "backfill_runs": 0, "failed_runs": 2, "stored_values": 801434, "latest_session": "2026-10-08"} | stays PENDING while production execution is locked |

Registry: `6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3`

## What unlocks production

1. Stage 1 COMPLETE, evaluated fresh at execution time (criterion M).
2. Stage 2 report PASS, at most 7 days old, with its tests (M).
3. Every Stage 3 decision approved (N; FEATURE-PARAMS approved 2026-09-28).
4. `PRAJNA_STAGE3_ENABLED=true`, the kill switch released, and a write token. A feature backfill additionally needs `PRAJNA_STAGE3_BACKFILL_ENABLED=true`.

Until then `prajna stage3 run --commit` and `prajna stage3 backfill --commit` are refused, and the refusal is recorded in `stage3_event`.
