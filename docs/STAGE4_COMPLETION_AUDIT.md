# Stage 4 completion audit and E2 approval package (2026-10-14)

**Status:** STOPPED AT THE APPROVAL GATE.
- No E2 label, split, runner or test look exists.
- Nothing was written to the production database. All production checks below were read-only (`default_transaction_read_only=on`).
- **Stage 4 verdict today:** research infrastructure largely in place, **no candidate ACCEPTED**.
  - E1: P1 and P2 NOT ACCEPTED.
  - E2: BLOCKED (protocol decisions PC-1 to PC-3).
  - Stage 4 is **not COMPLETE**.

**Scope kept:**
- paper/research only;
- no orders;
- no change to cron, `.env`, schedules or the active registry (features-v4);
- no Stage 1 backfill;
- no shadow cron;
- no AutoTrade Pro access.

## 1. Repository state

| Item | Value |
|---|---|
| Branch / HEAD before this work | `main` @ `07b7a5c`, equal to `origin/main`, clean, no stash, single remote `origin` (github.com/abhishek-du/Prajna) |
| This work | `backend/app/training/e2.py`, `backend/tests/training/test_e2.py`, this file, `docs/STAGE4_E2_PROTOCOL_CHANGE_PROPOSAL.md`, Amendment 1 appended to `docs/STAGE4_E2_PREREGISTRATION.md`. Committed locally, **not pushed**. |
| Environment | Python 3.11.16, numpy 2.4.6 |

## 2. Stage 4 completion matrix

| # | Requirement | Existing implementation | Evidence (verified 2026-10-14) | Missing work | Risk | Approval? | Proposed validation |
|---|---|---|---|---|---|---|---|
| 1 | Immutable, versioned datasets on the active registry | `policy.DATASETS` (v1/v2 frozen), `open_run` contract, `training_session_done.rows_sha256` | v3-asif: **257/257** snapshots, **47,480,669** rows (table count = run sum); v3-strict: **22/22** snapshots, 11 sessions, **4,655,286** rows. Both have one registry, `6f998a76…` (features-v4). | none | low | no | rerun fingerprint = stored |
| 2 | Point-in-time features | `ck_training_fv_pit` CHECK (`input_max_knowable_at < as_of`) | **0** violations on both v3 sets. 170,182 (asif) / 340,124 (strict) VALID rows have a NULL knowable_at: all zero-count news features (no input row exists); none are in CORE24. | none | low | no | CHECK + existing tests |
| 3 | No duplicates; value XOR reason | unique `uq_training_feature_value`, `uq_training_label`, `uq_training_sample`; `ck_*_value` | Enforced by constraints; status mismatch **0** | none | low | no | constraints |
| 4 | Labels without leakage | `ck_training_sample_no_leak` (`label_start_at > as_of`), `ck_training_label_window` | label-v2 (7,113,528 rows, sha `f277f36ce08c`) and TSL asif (2,453,145, `8b6ce2465570`) / strict (116,265, `462f5988baa2`). Each was built twice with an identical sha. | E2 `label-hold5-v1-asif` not built (gated) | — | **yes (gated)** | rebuild sha identical; synthetic CA tests |
| 5 | Corporate-action adjustment | `pit.bars_adjusted` (split/bonus EXACT factors knowable at the cutoff; dividends **not** adjusted) | Code read: `hold_label(dividends=…)` adds cash only in the total-return sensitivity, so no double count | none | low | no | `test_split_inside_the_window…`, `test_dividends…` |
| 6 | Survivorship | universe = current master | Known; documented in E1 and E2 | cannot be repaired from Upstox | **high (bias up for long-only)** | no | low-price sensitivity (E1) |
| 7 | Quarantine | `training_sample_quarantine`, migration 0020 | 1 slice: v3-strict × label-tsl-long-v1-strict × PRE_OPEN, 38,755 rows (the TSL contract is PRE_SESSION only); rows kept, append-only; the E1 runner refuses a quarantined slice | none | low | no | existing tests |
| 8 | Walk-forward splits | E1 `wf-exp-120-20-20-e1` stored (5 folds, 1-session embargo); E2 `make_folds` (5-session embargo, refuses embargo < H) | Stored splits listed: TRAIN 120–200, VALID 20, TEST 20, embargo 1 | E2 `wf-exp-120-20-20-e5` rows not written (gated) | — | **yes (gated)** | `test_embargo_purges_every_train_label_window` |
| 9 | Tuning on TRAIN/VALID only | E1: penalty chosen on VALID, `validate` reports no metric; ledger | E1 ledger: 4 entries (2 validate, 2 test), clean tree, code `cee164f` / `06fbf4e` | E2 runner not written | medium | **yes** | ledger refuses a second test look |
| 10 | Test set consulted once | E1 one-look discipline | Holds for E1. **E2 TEST overlaps E1 TEST in 92 of 100 sessions (PC-2).** | decision PC-2 | **high** | **yes** | — |
| 11 | Costs applied once, parts separated | `e2.Rates`, `order_cost_parts`, `CostModel.day_cost_parts`, `cost_summary` (new) | Rates reproduce the 6 charges-API totals within ₹0.03; parts sum to the total (new test) | — | low | no | `test_cost_parts_sum_to_the_total…` |
| 12 | Cost-adjusted primary metric | prereg §5/§7: C2 book with identical costs | **Defect PC-1:** costs cancel, and turnover differences are credited as excess (synthetic demo: +7.1 bps per day from zero edge) | decision PC-1 | **critical** | **yes** | `TestProtocolIssues` |
| 13 | Book accounting | `tranche_book` | **Defect fixed:** suspension-gap returns were lost; now booked on reopening | — | was medium | no | new regression test (fails on the old code) |
| 14 | Controls and placebo | `matched_controls`, `placebo_picks`, C1 permutation (E1) | Tests: same cell, no overlap, placebo excludes picks | C1 permutation for the tranche book is not implemented (runner) | low | runner approval | synthetic null test in the runner |
| 15 | Inference | `block_bootstrap_ci` (block ≥ 2H enforced), NW t lag 2H−1, 97.5% two-sided | Code read: quantiles 1.25% / 98.75%, seeded | power (§7) | **high** | no | `test_block_must_cover_the_overlap` |
| 16 | Acceptance A1–A6 | `e2.acceptance` | A1 CI rule, A2 ≥ 0 at 1.5×, A3 ⌈0.8·5⌉ = 4, A4 CI ∋ 0, A5 P2 > P1 net mean, A6 drawdown reported: **match the prereg** | A2's meaning depends on PC-1 | see 12 | **yes** | `test_acceptance_gates` |
| 17 | Reproducibility | config sha256, code sha, clean tree, ledger (E1) | E1 artifacts' sha256 match the results docs (`6804c03e…`, `19011bf3…`, `3b134335…`) | E2 runner: the same pattern plus a package-version record | low | runner approval | rerun = identical JSON |
| 18 | Model candidates | P1 reversal, P2 ridge24 | E1: both NOT ACCEPTED (A1 UNPROVEN, A2 NOT_EVALUATED) | E2 candidates the same; no new model justified | — | — | — |
| 19 | E1 A2 under the approved costs | `stage4_e1_selection.py recost` (no DB) | NOT_EVALUATED: no approved cost model existed | optional recost with C1–C4 (an open-to-close round trip at ₹10 L ≈ ₹10 k orders, about 93 bps + 10 bps spread; certain FAIL) | none | **yes** (it is a look at a spent result, but a new artifact) | ledgered recost |

## 3. Changes made in this preparation

1. **`tranche_book` suspension fix.** The drift ran open(d) → open(d+1) and skipped any leg with a missing open, so a held name's move across a suspension was lost. Example: 100 → suspended → 150 booked 0%. The drift now runs from the last valid open (`_last_px`); `missing_marks` is unchanged.
2. **Cost parts (C3/C4).** Additions:
   - `order_cost_parts` (brokerage, statutory, dp);
   - `CostModel.day_cost_parts` (+ spread, slippage);
   - `cost_summary` (gross, each part, net; net = gross − Σparts);
   - measured per-name half-spread with the 5 bps proxy as fallback (`half_spread_by_name`, `spread_coverage`).

   `order_cost_inr` and `day_cost` are unchanged in value: the existing API-reproduction tests still pass.
3. **Tests (+4, synthetic):**
   - the suspension regression;
   - parts sum and counted once (DP ₹23.60 per scrip);
   - measured spread with fallback and coverage;
   - the PC-1 demonstration.
4. **Docs:**
   - Amendment 1 to the prereg (approved C1–C4, C5 status, corrections), appended only;
   - `STAGE4_E2_PROTOCOL_CHANGE_PROPOSAL.md` (PC-1 to PC-4);
   - this file.

## 4. Tests and commands

```bash
cd backend
.venv/bin/python -m pytest tests/training -p no:randomly          # before: 87 passed; after: 91 passed (test DB)
.venv/bin/python -m pytest tests/training/test_e2.py -p no:randomly  # 25 passed
# regression proof: with the old drift line restored, test_a_move_across_a_suspension… FAILS (1 failed, 24 passed)
.venv/bin/ruff check app/training/e2.py tests/training/test_e2.py # clean (repo-wide ruff findings pre-exist, unchanged count)
```

- **Not run:** the full suite. `e2.py` is imported only by `tests/training/test_e2.py`.
- **Production checks:** read-only SQL via `PGOPTIONS=default_transaction_read_only=on` as `prajna_rw`:
  - row and snapshot counts;
  - PIT, status and NULL-knowable counts;
  - constraints;
  - splits;
  - label runs;
  - the earliest pre-open date.

## 5. Hashes

| Object | Hash |
|---|---|
| Active registry features-v4 | `6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3` |
| Prepared (inactive) features-v5 | `f415cebf11c5dc50599be4a885a904e96b0bc53bc044758527be16c9d29217f6` |
| label-v2 rows_sha256 | `f277f36ce08c…` (2 identical runs) |
| label-tsl-long-v1-asif / -strict | `8b6ce2465570…` / `462f5988baa2…` |
| E1 P1 config / test artifact | `e0e12d5bca77…` / `6804c03e43ddb28a…` |
| E1 P2 config / validate / test | `82e828c87e2a…` / `3b13433593b14b2f…` / `19011bf30e2606cb…` |

## 6. E2 protocol vs implementation

| Prereg item | Implementation | Consistent? |
|---|---|---|
| H = 5 primary, H = 3 sensitivity | `H = 5`; `hold_label(h=…)`, `make_folds(h=…)`, `tranche_book(h=…)` | yes (H = 3 by parameter) |
| Entry open T, exit open T+5; price-only primary; total return sensitivity | `hold_label` | yes |
| PIT cutoff | label from `pit.bars_adjusted` at a recorded cutoff | **builder not written** (gated) |
| Universe top 500 `turnover_20`, top quintile | `e1.universe`, `e1.picks` (reused) | yes (runner to wire) |
| Staggered 5 tranches, equal weight, drift, netting | `tranche_book` | yes, after the suspension fix |
| Folds 120/5/20/5/20, roll 20 | `make_folds` | yes. **Dates differ from the prereg header** (2026-05-08 → 09-29, not 04-27 → 09-17); recorded in Amendment 1 |
| C0 / C1 (200 draws) / C2 / placebo | C2 and placebo in `e2`; C0 trivial; **C1 for the tranche book not implemented** | partial (runner) |
| Primary: daily net excess vs C2 | `net_series` (caller-defined) | **PC-1 defect in the definition** |
| Block bootstrap, block ≥ 2H, 97.5% | `summarise` | yes |
| A1–A6 | `acceptance` | yes (A2 subject to PC-1) |
| Approved C1–C4 | `CostModel`, `Rates` (DP param), `cost_summary` | yes; C3 coverage ≥ 96% proxy |
| C5 primary legal texts | — | **gap open** (broker agreement ≠ statutory verification) |

## 7. Leakage, adjustment, split, cost and reproducibility audit

- **Leakage:**
  - The DB CHECKs enforce feature PIT and label-after-as_of. Violations: 0.
  - E2 purging is enforced in code: embargo ≥ H is refused otherwise, and TEST never needs data past the end.
  - The warm-up tranches use embargo-session features only.
  - **Residual:** VALID blocks overlap the previous fold's TEST, as in E1. `validate` therefore reports no metric.
- **Adjustment:**
  - Split/bonus factors apply only when knowable at the cutoff.
  - LOW-confidence vendor-adjusted bars are refused and become `SESSION_MISSING` in a hold label.
  - Dividends are never in the price series.
- **Splits:** chronological, disjoint, identical across instruments (one session index).
- **Costs:**
  - applied once per traded side;
  - brokerage per netted name per side, DP once per scrip per sell day;
  - spread and slippage are separate parts;
  - the multiplier scales every part (A2).
  - **Approximation:** costs are a fraction of a fixed `capital_inr`, not of the compounded book value. That is negligible over 20-session blocks; it is reported.
- **Execution realism:**
  - A suspended name is still "sold" at its last mark on exit, which is optimistic. The count is reported via `missing_marks`.
  - Entry and exit at the official open are proxies.
- **Reproducibility:** E1 has seeded RNGs, a config sha and a clean-tree ledger. The E2 runner must copy this and add package versions.

## 8. Statistical power and sample size

- **Sample:** 100 TEST sessions. With H = 5 overlap that is about 20 independent periods. The bootstrap draws 10 blocks of 10.
- **Minimum detectable mean daily excess** (80% power, from E1 dispersion): ridge24 **0.08–0.19% per day**, reversal **0.11–0.25% per day**.
- **Edge vs cost:** E1 gross matched excess was 0.05–0.08% per day, below what is detectable. **Expected E2 A1: UNPROVEN** on gross terms.
- **Costs at the approved primary ₹10 L:** 38.6–77.3 bps per day, against 5–8 bps per day of E1 edge. **Under PC-1a, A1 is expected FAIL.** Only the ₹5 Cr sensitivity has costs (3.9–7.9 bps per day) of the edge's order.
- **Multiplicity:** 2 predictors (Bonferroni 97.5%). The 4 capital books, 3 slippage levels, the H = 3 and total-return variants and the block-20 run are **sensitivities, not acceptance inputs**. They must be reported as uncorrected.

## 9. Estimated runtime, storage and vendor calls (if approved)

| Step | Estimate | Basis |
|---|---|---|
| Build `label-hold5-v1-asif` (+ H = 3 and total-return variants) | about 20–40 min; about 3 M rows, about 1.1 GB (training_label is 16.76 M rows / 6.1 GB today, about 365 B per row) | label-v2 took 27–37 min for 7.1 M rows |
| Write `wf-exp-120-20-20-e5` splits | seconds; 15 rows | — |
| E2 validate + test | minutes (in memory, 257 sessions × 500) | E1 runs took minutes |
| Backup first | about 4 GB, about 10 min | `db_backup.sh` of 2026-10-13 |
| **Vendor (Upstox) calls** | **none**: database only | — |
| Disk | 160 GB free | `df` 2026-10-14 |

## 10. Proposed commands: NOT RUN, NOT YET IMPLEMENTED

The label builder, the split writer and the runner do not exist yet. They should be written **after** PC-1 to PC-3 are decided, because the runner encodes the primary metric. The intended interface, following E1:

```bash
cd backend
ops/runbooks/db_backup.sh --label stage4_e2_labels
.venv/bin/python -m app.cli.main training labels --version label-hold5-v1-asif --cutoff <recorded> --commit     # to be written
.venv/bin/python -m app.cli.main training splits --scheme wf-exp-120-20-20-e5 --labels label-hold5-v1-asif --commit  # to be written
.venv/bin/python ops/measure/stage4_e2_hold.py validate --predictors reversal,ridge24 --capital 1000000            # to be written
.venv/bin/python ops/measure/stage4_e2_hold.py test     --predictors reversal,ridge24 --capital 1000000            # the single look
```

## 11. Remaining risks and approvals needed

| # | Item | Needed from you |
|---|---|---|
| 1 | **PC-1** primary metric (critical) | choose a / b / c (recommended: a, `P_net − C2_gross`) |
| 2 | **PC-2** E2 TEST overlaps E1 TEST (92/100) | choose a / b / c (recommended: a, EXPLORATORY with forward confirmation) |
| 3 | **PC-3** ₹10 L primary makes the book uneconomic | proceed knowingly, or pre-register a capital-appropriate selection size first |
| 4 | **PC-4** freeze the half-spread proxy from all captured sessions | yes / no |
| 5 | Prereg approval 1 (open-to-open, price-only, H = 5, A1–A6) | approve the protocol (with the PC decisions) |
| 6 | Writing the label builder, the split writer and the E2 runner (code + tests, no run) | approve the implementation |
| 7 | Building E2 labels and splits in production (backup first) | separate approval |
| 8 | The single E2 test look | separate approval |
| 9 | C5 primary legal texts | still open; reported as such |
| 10 | Optional: E1 `recost` with the approved costs (closes E1 A2) | optional approval |
| 11 | Survivorship and assumed knowability (as-if-live) | inherent; every result is provisional until STRICT forward sessions confirm |

**Recommendation:**
- Decide PC-1 to PC-3 first.
- Given the cost arithmetic at ₹10 L, the scientifically justified next experiment is a **forward, out-of-sample** test of a lower-turnover predictor at a capital-appropriate position count. It should not be a more complex model: no LSTM or ensemble, since linear baselines remain below cost.
