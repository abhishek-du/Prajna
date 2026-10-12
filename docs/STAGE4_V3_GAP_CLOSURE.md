# Stage 4 v3: inventory and gap closure (2026-10-12)

## Phase A: read-only inventory (PASS / FAIL / UNPROVEN / NOT IMPLEMENTED)

| Item | State | Evidence |
|---|---|---|
| Git | **PASS** | `5a86e9f` = `origin/main`, clean before this work |
| Migration 0019 | **PASS** | alembic `0019` (production and test DB) |
| Builder v3 (contract, replay) | **PASS** | `app/training/{policy,replay}.py`; v1/v2 frozen |
| `stage4-ds-v3-strict` | **PASS**: complete | 5 runs COMPLETE; 22 of 22 snapshots (11 PRE_SESSION + 11 PRE_OPEN, 2026-09-24 → 10-09); 4,655,286 rows; one registry `6f998a76…` |
| `stage4-ds-v3-asif` | **PASS**: complete | 8 runs COMPLETE; 257 of 257 PRE_SESSION (2025-09-24 → 2026-10-09); 47,480,669 rows; one registry `6f998a76…` |
| Active or stale builds | **PASS**: none | no training process; no RUNNING run |
| label-v2 | **PASS** | 2 runs, one `rows_sha256` `f277f36c…`; 7,113,528 rows; flags and reasons as documented |
| Samples / splits / exports | **PASS** | strict 2 × 38,755 samples (27,978 eligible each), asif 817,715 (566,209); asif 5 folds; strict 0 folds (11 sessions) |
| Production `feature_value` features-v4 rows | **NOT PRESENT** | only 2026-09-29 (features-v1) and 2026-10-08 (features-v2). The v3 datasets do **not** need them: they replay the canonical Stage 1/2 data |
| Target/stop label | **NOT IMPLEMENTED** (undecided) | awaiting the decision listed in `STAGE4_DATASET_V3_REPORT.md` |

## Phase B: gaps found and closed (code and tests only; no build launched)

| # | Gap | Change |
|---|---|---|
| 1 | `samples.build` / `splits.build` accepted frozen datasets (v1/v2) and `label-v1` | `samples.check_versions` refuses them; `labels.FROZEN_LABELS` |
| 2 | Stored walk-forward splits were never re-verified against the dataset's sessions | `splits.violations` (pure) and `splits.verify`: boundaries, counts, overlap, embargo = 1, TRAIN from the first session and expanding |
| 3 | No consistency check of label-v2 flags or samples against their sources | new `app/training/integrity.py`: label checks (ambiguous / extreme flags vs values, reason ⇔ status, one flag set per session) and sample checks (NO_LABEL vs label rows, `core_valid` vs feature statuses, `feature_eligible`, masks vs flags, eligible has a label) |
| 4 | A killed worker leaves its run RUNNING forever; no completeness view | `replay.stale_runs` / `reap_runs` / `completeness`; CLI `prajna training status [--reap-older-than-hours N]` (read-only by default; reap marks FAILED and keeps done snapshots) |
| 5 | The manifest lacked run provenance | `stage4_v3_report.py --manifest-only`: registry, alembic, every run (code sha, build contract, policy params), label runs (cutoff, code sha, source fingerprints), samples, split verification, integrity, export files re-hashed from disk |

Already present, no change needed: PIT CHECKs and guards; missingness statuses (never 0); separate PRE_SESSION / PRE_OPEN identities (snapshot key, separate splits and exports); duplicate protection (unique keys plus validator); resume and idempotency.

## Verification

| Check | Result |
|---|---|
| `pytest tests/training/test_v3.py` | **18 passed** (4 new) |
| Full suite `pytest -m "not live"` | **1354 passed, 0 failed, 4 deselected** (live) |
| `prajna training status` (production, read-only) | stale RUNNING: none; strict 22/22, asif 257/257 complete |
| `stage4_v3_report.py --manifest-only` (production, read-only DB) | label integrity 0 violations; sample integrity 0 violations (both datasets); asif splits 0 violations (5 folds) |
| Frozen data before = after | v1/v2 per-session fingerprints, label-v1 `15f0cb45…`, `feature_value` 801,434 `b45381f3…`, 26 frozen runs — identical |
| v3 data unchanged | asif `acc65124…`, strict `62e70a81…`; label-v2 7,113,528 rows |
| Other instruments' classifications | `5630b099…` (3,589 rows), identical to the 2026-10-12 baseline |
| Stage 3 config | crontab sha `dbc5b41b…`; flags unchanged; `stage3_event` 38 (no new run). Watcher `b3ruk9b4k` untouched and alive |

`backend/var/stage4/exports/manifest.json` was rewritten with the richer provenance. The previous manifest is kept as `manifest.prev.json`. Export CSVs are unchanged.

## Remaining blockers (not code)

1. **Target/stop first-touch label:** needs your decision (horizon, entry, levels, both-touch rule, exit, costs).
2. **Production features-v4 rows** (needed for live and forward evaluation, not for the v3 builds): pending a successful scheduled Stage 3 run (2026-10-13 09:00:30 / 09:22).
3. **STRICT walk-forward:** needs ≥ 162 sessions. The STRICT dataset grows by 2 snapshots per session; extending it is a new build that needs your approval.
4. **Not authorised, unchanged:** the `share_holdings` classifier bug, the daily new-listing fundamentals refresh, the grace policy.
