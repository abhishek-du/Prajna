# Corporate-action knowability (CA-OBSERVED) and payload basis (F3) fixes

**Implemented 2026-10-09** on your approval ("option 1 aur F3 fix dono implement karo"), following the review `docs/STAGE4_POST_BACKFILL_REVIEW.md` (F1, F2, F3).

There are two separate, auditable changes, each with its own commit, registry version and tests.

| | Fix 1: CA-OBSERVED | Fix 2: F3-PAYLOAD-BASIS |
|---|---|---|
| Commit | `8bad2f1` | `b1bb105` |
| Migration | **0018** `0018_ca_observed_knowability` (additive views) | none (code only) |
| Registry | `features-v3`, `362b2b106543a559770ea4588acb22b4f074c84b9cba349cc4ae7e5c2bfe637d` | **`features-v4`, `6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3` (active)** |
| Features re-versioned | 37 per-instrument features reading corporate actions or adjusted bars: +1 | 29 per-instrument features computed from adjusted bars: +1 |
| Decision | `CA-OBSERVED` (`app/features/decisions.py`) | `F3-PAYLOAD-BASIS` |
| Tests | `tests/stage2/test_ca_observed.py` (5) | `tests/stage2/test_payload_basis_f3.py` (4; the BLSE-pattern test fails without the fix) |

## Fix 1: corporate actions knowable when observed

**Migration 0018.** Views only; no stored row changes:
- `canon_corporate_action.knowable_at = greatest(KN-CA end of announcement day, fetched_at)`. `knowable_at_basis` says `OBSERVED (CA-OBSERVED)`.
- `canon_corporate_action_kn_ca` keeps the previous KN-CA definition, so the announcement metadata is preserved. `corporate_action.announcement_date` and `knowable_at` are untouched.
- `canon_ca_factor`: factors knowable when their action was fetched.
- Training shadows keep their semantics:
  - `train_strict.canon_ca_factor` and `train_asif2.canon_ca_factor` are added.
  - `train_asif2.canon_corporate_action` now reads the KN-CA view explicitly.
  - Verified: the output of all four training CA views is byte-identical before and after.

**`pit.bars_adjusted`** reads `canon_ca_factor`, and its horizon becomes `min(ex_date)` over actions knowable before `as_of`. If none is knowable, every vendor-adjusted bar is LOW confidence (F2).

**Regression cases:**
- An action announced before `as_of` but stored after it is invisible to `pit.corporate_actions`; its KN-CA value is still visible in the `_kn_ca` view.
- A factor fetched after `as_of` does not adjust bars.
- The horizon ignores actions stored after `as_of`.
- **Historical recompute:** a past snapshot recomputed after two late actions arrive is identical (values, reasons, `inputs_sha256`).
- The registry versions.

**Two existing Stage 2 tests encoded KN-CA.** They expected an action announced 2026-09-24 and stored 09-25 10:00 to be visible from 09-25 00:00, ten hours before Prajna had it. They were tightened, not relaxed: invisible at 00:00 and at 10:00:00; visible from 10:00:00.000001.

## Fix 2: per-payload vendor-adjustment provenance

**The rule.** A factor with `vendor_applied = APPLIED` counts as baked into a stored payload only if the vendor never later re-served a bar of that payload adjusted by that action. The evidence is a `CA_ADJUSTMENT` observation that names the action and was fetched after the bar.

**Why per payload, not per bar (VERIFIED on production during implementation):**
- BLSE's whole history (2026-01-01 → 10-05) is one payload, fetched on the ex-date morning.
- The vendor later re-served only the last 4 bars.
- A first per-bar version adjusted those 4 and simply moved the false −50% jump to 09-28 → 09-29.
- The per-payload rule adjusts all of them.

## Verification

**BLSE** (`ops/measure/ca_fix_verify.py`, read-only, evidence `audit/evidence/ca_fix_verify.json`):
- **2026-10-05 adjusted close = 159.575000** (= 319.15 / 2, ADJUSTED).
- Every pre-ex bar is adjusted. The ex-date change is +0.83%, where it was −49.6%.

Downstream features of the 2026-10-08 PRE_SESSION snapshot, recomputed under features-v4:

| Feature | Stored (features-v2, version 1) | Recomputed (version 3) | Independent |
|---|---|---|---|
| `ret_5d` | −0.5073 | −0.01464 | −0.01464 |
| `ret_20d` | −0.5048 | −0.00955 | −0.00955 |
| `sma_20` | 303.82 | 159.8875 | 159.8875 |
| `close_to_sma_20` | −0.4793 | −0.01055 | |
| `volatility_20` | 2.438 | 0.2247 | |
| `rsi_14` | 12.20 | 48.01 | |
| `breakdown_20` | 1 | 0 | |

**Whole 2026-10-08 PRE_SESSION snapshot recomputed** (206,281 rows):
- Values or reasons differ **only for BLSE** (23 features).
- `inputs_sha256` differs for the 8 `ca_days_*` of 1,555 instruments, because the observed `knowable_at` is now hashed. The values are identical.
- So fix 1 changes no value of the stored production snapshots.

**Old and new feature-version behaviour:**
- Stored rows keep `feature_version` and `registry_sha256` of features-v1 (2026-09-29) or features-v2 (2026-10-08). They are never re-labelled.
- New Stage 3 runs write features-v4 versions (bar features 3, CA features 2, others unchanged).
- A recompute of a pre-v4 session must not be committed. `persist` would fail closed with `DeterminismMismatch` rather than overwrite.

## Gates and tests

| Check | Result |
|---|---|
| Full suite after fix 1 | **1332 passed**, 0 failed (4 live tests deselected) |
| Full suite after fix 2 | **1336 passed**, 0 failed (4 live tests deselected) |
| Stage 2 acceptance (`--run-tests`) | **PASS**, A–P 16/16 |
| Stage 3 acceptance (`--run-tests`) | A–L, N, O **PASS**; **M BLOCKED** |

Stage 3 M is blocked by Stage 1 F/S failing, as it was before this patch: MOLDTECH / MOLDTKPAC bonus history revised before the action is stored. That is outside this patch and not authorised. Stage 3 level: DRY-RUN READY. **Scheduled Stage 3 runs stay refused until Stage 1 is COMPLETE.**

## Production safety

| Item | Before = after |
|---|---|
| `feature_value` | 801,434 rows; md5 `b45381f3…` (baseline format) and `fe2303f9…` (with version and hash columns) |
| Training datasets | v1 and v2 per-session fingerprints identical (e.g. v2-asif 47,274,794 rows `e7d3a893…`, v2-strict 4,229,340 `7161a1b4…`); labels 7,077,591 `15f0cb45…` |
| `corporate_action`, `ca_factor` | 2,336 each, unchanged |
| `stage3_event` | 36 |
| Crontab | sha `dbc5b41b…` |
| Flags | `PRAJNA_STAGE3_ENABLED=true`, `PRAJNA_STAGE3_BACKFILL_ENABLED=false` |

**Backup before 0018:** `var/backups/prajna_20261009T1252_ca_observed_pre_0018.dump` (sha256 `e27e72d9…`, verified).

**Not done (not authorised):**
- MOLDTECH / MOLDTKPAC ingestion;
- daily corporate-action refresh;
- rebuild of the Stage 4 datasets (v2 stays as built, under features-v2 and the pre-fix code; a v3 dataset would be a separate decision);
- models, orders.

## Remaining

1. Stage 1 F/S (MOLDTECH / MOLDTKPAC) blocks the scheduled Stage 3 runs. Separate authorisation is needed.
2. The stored production rows for BLSE on 2026-10-08 (features-v2) remain wrong by design: they are never re-labelled. Consumers must treat them as superseded by any features-v4 value.
3. Reproducing Stage 4 v2 exactly needs code before `8bad2f1`. The datasets themselves are unchanged.
