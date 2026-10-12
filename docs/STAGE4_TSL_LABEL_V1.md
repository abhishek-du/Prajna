# Stage 4: label-tsl-long-v1 (one-session long target/stop label)

**Status:** BUILT 2026-10-12 for both v3 datasets.
- **Research only:** no model training, no orders, gross returns only.
- **Open decision:** 38,755 out-of-contract STRICT sample rows. The cause is in §6.
- **Evidence:** `audit/evidence/stage4_tsl_label_v1.json`.
- **Code:**
  - `backend/app/training/tsl.py`;
  - integrity checks in `backend/app/training/integrity.py`;
  - tests in `backend/tests/training/test_tsl.py`.

## 1. Approved contract (2026-10-12: "k = 1.5, gross only, contract approved")

| Item | Rule |
|---|---|
| Versions | `label-tsl-long-v1-strict` (`stage4-ds-v3-strict`), `label-tsl-long-v1-asif` (`stage4-ds-v3-asif`). The label is dataset-specific because each dataset's own PRE_SESSION `atr_pct_14` row sets R. |
| Direction | Long only. |
| Signal instant | PRE_SESSION as_of (T 08:59:59 IST). PRE_OPEN is not used: its as_of falls after pre-open order entry. |
| Entry E | Session T's official open (vendor daily bar). This is a **modelled proxy**, not a guaranteed fill. |
| R | E × atr_pct_14 × 1.5 |
| Barriers | target = ceil_tick(E + 2R); stop = ceil_tick(E − R). Tick = `instrument.tick_size` / 100. If stop > E − tick, the row is `R_BELOW_TICK`. |
| Touch | Target hit when high ≥ target; stop hit when low ≤ stop. |
| Outcome | Target only: TARGET_HIT, +1, exit at the target. Stop only: STOP_HIT, −1, exit at the stop. Neither: HORIZON_EXIT, 0, exit at the official close. |
| Both touched | Resolved only by 1m bars, and only when the 1m max high equals the daily high, the 1m min low equals the daily low, and the first touches fall in different minutes. Otherwise the row is `AMBIGUOUS_ORDER`, with flag `RESOLUTION_NO_1M`, `_SAME_MINUTE` or `_INCONSISTENT`. |
| Values | `tsl_l_k1p5_outcome`, `tsl_l_k1p5_gross_ret` = exit/E − 1, `tsl_l_k1p5_r_multiple` = (exit − E)/(E − stop). |
| Costs | NOT APPLIED. Net returns are NOT IMPLEMENTED and are not claimed. |
| Exclusions | Status MISSING_INPUT; the value is null, never 0. Reasons: `ATR_NOT_VALID`, `BAR_REFUSED`, `MALFORMED_BAR`, `SPECIAL_SESSION`, `R_BELOW_TICK`, `AMBIGUOUS_ORDER`, `NO_TICK_SIZE`. |
| Flags | `CA_EX_T`, `UNSUPPORTED_CA_EX_T` and `DIVIDEND_EX_T`, as in label-v2. `PRICE_LEVEL_VENDOR_ADJUSTED:<F>` marks a stored bar that carries a vendor-applied factor; its prices are brought back to the traded level before tick rounding. |

## 2. Production build

- **Knowledge cutoff:** `2026-10-12T11:06:13+00:00`, shared by both builds and both reruns.
- **Backup:** `var/backups/prajna_20261012T1615_stage4_tsl_pre_build.dump`, sha256 `39029b99…98ce`, verified.
- **Code:** f39a6a0. The tree was clean at the start of every build.

| | strict (2026-09-24 → 10-09) | asif (2025-09-24 → 10-09) |
|---|---|---|
| Run (build / rerun) | b076e8dc / 96ca843b | 775251c8 / 1b9ac08f |
| Instruments | 3,553 | 3,569 |
| Label rows (3 per session × instrument) | 116,265 | 2,453,145 |
| rows_sha256 | 462f5988…faf | 8b6ce246…9bd |
| Rerun | 0 inserted, drift 0, same sha and fingerprints | 0 inserted, drift 0, same sha and fingerprints |
| TARGET_HIT | 183 | 4,106 |
| STOP_HIT | 1,503 | 24,236 |
| HORIZON_EXIT | 31,583 | 689,415 |
| ATR_NOT_VALID | 4,245 | 73,838 |
| BAR_REFUSED | 1,234 | 25,926 |
| AMBIGUOUS_ORDER | 4 | 111 |
| R_BELOW_TICK | 3 | 83 |
| Both touched, resolved by 1m | 2 | 3 |
| Label integrity (6 checks) | PASS (all 0) | PASS (all 0) |

## 3. Samples and splits

| | strict | asif |
|---|---|---|
| Samples | 77,510 (38,755 PRE_SESSION + **38,755 PRE_OPEN**, see §6) | 817,715 (PRE_SESSION) |
| Eligible | 62,154 | 569,151 |
| Sample integrity | **FAIL** `snapshot_allowed` = 38,755; the other checks are 0 | PASS (all 0) |
| Splits `wf-exp-120-20-20-e1` | 0 folds: 11 sessions, fewer than the 162 needed | 5 folds; verify PASS |
| Manifest | `manifest.label-tsl-long-v1-strict.json` (integrity false) | `manifest.label-tsl-long-v1-asif.json` (pass) |

The label-v2 `manifest.json` was not modified; its md5 `1c7bae24…` is the same before and after.

## 4. Descriptive outcome summary (gross, no costs; not a performance claim)

| Outcome | strict n | strict mean gross | asif n | asif mean gross | asif mean R |
|---|---|---|---|---|---|
| TARGET_HIT | 183 | +11.0% | 4,106 | +11.3% | 2.01 |
| STOP_HIT | 1,503 | −5.3% | 24,236 | −5.6% | −1.00 |
| HORIZON_EXIT | 31,583 | −0.41% | 689,415 | −0.16% | −0.03 |

**Observation (no decision taken):**
- With k = 1.5 and a one-session horizon, the barriers sit about 5.5% below and 11% above the open.
- About 95% of the valid labels are therefore HORIZON_EXIT.
- The outcome classes are heavily imbalanced: in asif, TARGET_HIT is 0.6% of the valid labels and STOP_HIT 3.4%.
- Changing k or the horizon would be a new label version and needs your approval.

## 5. Immutability

These are identical before and after the build:
- label-v1 (7,077,591 rows) and label-v2 (7,113,528 rows);
- production `feature_value` (801,434 rows);
- the 26 frozen v1/v2 runs and the 13 v3 runs;
- the `training_feature_value` fingerprints of every dataset version (v1, v2 and v3);
- the label-v2 samples and splits, and the non-TSL label runs;
- `instrument_security_class` (3,593 rows);
- `stage3_event` (38);
- the crontab (sha `dbc5b41b…`);
- the Stage 3 flags.

The only differences are the new TSL label rows and sample rows.

## 6. Deviation: STRICT PRE_OPEN samples (decision needed)

- **What happened:** the samples builder joined a label version to every done snapshot of a dataset.
- **Effect:** `stage4-ds-v3-strict` has PRE_SESSION and PRE_OPEN snapshots, so 38,755 PRE_OPEN `training_sample` rows were built with `label-tsl-long-v1-strict`. That breaks the PRE_SESSION-only contract.
  - The label rows themselves are correct.
  - The asif dataset (PRE_SESSION only) is unaffected.
- **Fix (69d752e):** `samples.label_snapshots()` restricts target/stop samples and splits to PRE_SESSION. A new integrity check, `snapshot_allowed`, counts out-of-contract rows. A test replays PRE_OPEN and fails without the fix.
- **Not done:** the 38,755 rows are still stored. `training_sample` is append-only, enforced by a trigger, and removing rows needs your decision. Until then:
  - the strict TSL sample integrity reports FAIL;
  - a strict samples rerun refuses, because the stored rows differ from the recompute.

  Consumers must filter `snapshot = 'PRE_SESSION'`.

## 7. Not done / open

- Cost model and net returns (needs approval).
- k sensitivity and multi-session horizons (new versions only).
- The STRICT window is too short for splits.
- Removing the STRICT PRE_OPEN sample rows (§6).
