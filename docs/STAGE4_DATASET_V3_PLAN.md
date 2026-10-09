# Stage 4 dataset builder v3: plan (Phase 0)

**Research only.** No model is trained, no order placed, no Stage 1/2/3 logic or feature definition changed, no vendor call made.

## 1. Current schema and entry points (inspected)

**Tables:**

| Table | Holds | Mode |
|---|---|---|
| `training_dataset_run` | run metadata | updatable status |
| `training_feature_value` | one row per (version, session, snapshot, instrument, feature); `status`, `reason`, `inputs_sha256`, `input_max_knowable_at < as_of` CHECK | append-only |
| `training_session_done` | resume marker | append-only |
| `training_label` | labels | append-only |
| `training_policy_param` | frozen policy parameters | append-only |

**Shadow schemas:**
- `train_strict`: corporate actions as observed (0017; `canon_ca_factor` added in 0018).
- `train_asif2`: AS_IF_LIVE-v2 measured lags (0017/0018).
- `train_asif`: v1, superseded.

**Code:**
- `app/training/replay.py`: `replay_snapshot` calls `engine.compute_snapshot`, the production engine, unchanged.
- `policy.py`: datasets and policies.
- `availability.py`: the missingness contract.
- `labels.py`: label-v1.
- CLI `prajna training build | labels | policy`.

**Gaps found:**
- `DATASETS` still points at the **v2** versions. A `training build` run today would append features-v4 rows to `stage4-ds-v2-*`: a silent recompute under new semantics.
- No sample, split or export layer.

## 2. Invariants kept and components reused

**Kept:**
- v1/v2 feature and label rows are immutable (append-only triggers, plus new code guards).
- `input_max_knowable_at < as_of`; one registry hash per dataset version.
- NOT_AVAILABLE_HISTORICALLY / MISSING_INPUT / STALE_INPUT are never 0.
- Bounded inserts (≤ 30,000 binds); one REPEATABLE READ snapshot per replay.

**Reused unchanged:** the replay, the universe rule, the missingness contract, the AS_IF_LIVE-v2 frozen parameters and the shadow views.

## 3. Changes for `stage4-ds-v3`

**Versions:**
- `stage4-ds-v3-strict`: STRICT_PIT-v2 knowability, PRE_SESSION and PRE_OPEN.
- `stage4-ds-v3-asif`: AS_IF_LIVE-v2, PRE_SESSION.
- Both built with **features-v4** (`6f998a76…`): CA-OBSERVED and F3 code.
- PRE_SESSION and PRE_OPEN rows stay separate (snapshot key).

**Build contract (code):**
- Every dataset version declares the registry it must be built with.
- A build is refused when:
  - the active registry differs;
  - an existing run of that version carries another hash;
  - the version is frozen (v1, v2);
  - the working tree is dirty (unless `--allow-dirty`, which is recorded).

**Migration 0019 (additive):**
- `training_dataset_run`: `label_version`, `code_git_sha`, `source_fingerprints` jsonb, `build_contract` jsonb (nullable).
- `training_label`: `flags text[]`, `reason`, `run_id` (nullable, so label-v1 rows are untouched).
- New `training_label_run` (cutoff, registry, code sha, fingerprints).
- New `training_sample` and `training_split` (append-only).

**Samples (`training_sample`):**
- One row per (dataset, label version, session, snapshot, instrument).
- Feature eligibility, from the 30 baseline features of the review: VALID count and the missing ids.
- Label validity: VALID label ids and label flags.
- Masks and exclusion reasons, recorded, never deleted.

**Splits (`training_split`):** chronological expanding walk-forward, train ≥ 120 sessions, validation 20, test 20, roll 20, **1-session embargo** between the blocks. Every instrument shares the boundaries.

**Report and export:** baselines (zero, reversal, momentum: no ML), coverage, exclusions, masked vs unmasked sensitivity, cost sensitivity at 0/10/20/40 bps round trip, and a calibration interface (Brier, reliability). CSV.gz export plus a manifest with independent fingerprints.

## 4. Labels: defined vs unresolved

**`label-v1` (inspected).** Nine labels per (session T, instrument): `ret_cc`, `gap`, `ret_oc`, `high_exc`, `low_exc`, `hit_up_1/2`, `hit_dn_1/2`.
- Prices come from `bars_adjusted` as of the build instant, 2026-10-08, under the **pre-fix** code: KN-CA, no F3.
- Its BLSE 2026-10-06 `ret_cc` is the known −49.6% artefact (F3).
- Bars refused as LOW/RECONSTRUCTED produce **no row at all** (silent).
- The `hit_*` flags are independent threshold reaches, not an exit rule.
- It is immutable, and it is not used by v3.

**`label-v2` (fully specified, implemented):**
- The same nine definitions and the same session window (T open → T close).
- The fixed price basis: features-v4 code, a recorded knowledge cutoff, factors as observed.
- Explicit validity:
  - `BAR_REFUSED`, `MALFORMED_BAR` and `PREV_SESSION_MISSING` rows instead of silence;
  - flags `CA_EX_T` (with the factor), `UNSUPPORTED_CA_EX_T`, `DIVIDEND_EX_T`, `EXTREME_UNEXPLAINED` (|ret_cc| or |gap| > 25% without an EXACT factor at T), `AMBIGUOUS_ORDER_1` / `_2` (both thresholds touched the same day).

**Unresolved: not implemented, needs your decision.** A target/stop ("first touch") label needs all of the following, which no document defines:
- horizon;
- entry price (open, PRE_OPEN IEP, or VWAP);
- exit rule;
- target and stop levels (fixed % or ATR multiples);
- tie and ambiguity handling;
- cost model.

The alternatives are listed in the final report. Daily OHLC cannot order the touches. 1-minute bars exist only from 2026-09-23, so resolving the order is possible only for about 12 sessions.

## 5. Risks, migration and rollback

**Risks:**
- About 3–4 h build time for AS_IF_LIVE v3, and about 30 GB more storage.
- Stage 3 E is still PENDING: v3 does not claim Stage 3 readiness.
- Survivorship is unchanged.

**Migration 0019:**
- Additive; backup first.
- Downgrade drops only the new tables and columns. v1/v2 rows are never touched.
- Rollback of data: v3 rows are separate versions. If needed, mark their runs SUPERSEDED, as was done for v1.
