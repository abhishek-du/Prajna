# Stage 4 E2: pre-registration Amendment 2, revision 2 (PROPOSED, for review)

**Status:** PROPOSED, not adopted.

| Revision | Commit | Content |
|---|---|---|
| 1 | `3260926` | first proposal; its text is in git history |
| 2 | this one | your decisions of 2026-10-14 on revision 1 |

The original pre-registration (`docs/STAGE4_E2_PREREGISTRATION.md`, with Amendment 1) is unchanged.

**Nothing has run against E2 data:**
- no E2 labels or splits in production;
- no validate phase and no test look;
- `backend/var/stage4/experiments/e2/` holds only the synthetic calibration file.

> **Gate result:**
> - **Percentile CI (pre-registered):** INADEQUATE (§6). It is anti-conservative.
> - **Correction C-a** (studentized bootstrap, approved 2026-10-14): **false acceptance is now controlled**, but the result is formally **INADEQUATE** on the second pre-set criterion, **because the CI is too conservative** in iid worlds (§6.4).
>
> - **Waiver W** (approved by you 2026-10-14): recorded (§6.6). The calibration gate is now open.
> - The runner still refuses validate and test, because the E2 labels and splits are not built.
> - No E2 outcome was consulted.

## 1. Status of every E2 result

- **EXPLORATORY.** 92 of the 100 TEST sessions (2026-05-08 → 2026-09-29) were E1 TEST sessions.
- Every result file carries `"status": "EXPLORATORY"`, `"independent_confirmation": false` and the overlap count.
- A candidate that reaches ACCEPTED-EXPLORATORY only becomes **eligible** for the forward confirmatory test (§8).

## 2. Primary metric and acceptance

**Primary series:** s_t = `P_gross,t − cost_t(P) − C2_gross,t`
- `cost_t(P)` is brokerage, statutory, DP, half-spread and slippage, each once (`CostModel.day_cost_parts`). It is a fraction of book value.
- C2 is the untraded matched-control book.

**Reported, never gated:**
- `P_gross − C2_gross`;
- `P_net − C2_net`;
- absolute `P_net`;
- C0 gross;
- the placebo.

**No A7:** absolute net return is reported separately and not gated (your decision 4).

| # | Criterion (per predictor, k20 configuration) |
|---|---|
| A1 | The 97.5% two-sided **studentized** moving-block bootstrap-t CI of mean(s_t) (C-a, `e2.studentized_block_ci`): block 10 (= 2H), 10,000 draws, seeded. Lower bound > 0 is PASS, upper bound < 0 is FAIL, otherwise UNPROVEN. The same method is used for the A4 placebo CI. |
| A2 | mean(s_t) with every cost part × 1.5 is ≥ 0 |
| A3 | mean(s_t) > 0 in ≥ 4 of 5 TEST folds |
| A4 | The CI of the gross placebo series (random non-picked names minus their own matched controls) includes 0 |
| A5 (P2) | mean(s_t) of ridge24 > that of reversal, otherwise P2 is dropped |
| A6 | Maximum drawdown of cumulative s_t and of the gross selection series. Reported. |
| **NW** | **The Newey-West t of s_t (lag 2H − 1 = 9) agrees with A1:** t ≥ 2.2414 when A1 is PASS |

**Candidate status** (`e2.candidate_status`):
- **ACCEPTED-EXPLORATORY:** A1 PASS **and** NW agrees **and** A2, A3, A4 (and A5) PASS.
- **FAIL:** A1 FAIL.
- **BLOCKED:** an input is missing.
- **UNPROVEN:** otherwise, including A1 PASS with NW disagreeing.

## 3. Configurations

- **k20 is the SOLE PRIMARY acceptance configuration**, at a 97.5% CI.
- **k100** (the 2026-10-13 design) is a separately reported **SENSITIVITY**. It never decides the outcome and is never co-primary, so it needs no multiplicity correction.
- Shas are printed by `stage4_e2_hold.py config`, need no database, and are reproducible run to run:

| | Role | Picks per tranche | Config sha256 |
|---|---|---|---|
| `k20` | PRIMARY | 20 | `87eb85fae0dabbecb9393b306f98166d6852f6c0793f4868607e4df37a5189ce` |
| `k100-top-quintile` | SENSITIVITY | 100 (top 20% of 500) | `91778755b4c493524a7e193d02191eedecce6af86d487bc6705ecdf2112b47ed` |

- **Shared by both:**
  - universe: top 500 by `turnover_20` with 24 VALID core features;
  - controls as before;
  - capital ₹10 L primary; ₹50 L, ₹1 Cr and ₹5 Cr as sensitivities;
  - slippage 0, with 5 / 10 / 20 bps as sensitivities;
  - stress 1.5×, block 10 (block 20 as a sensitivity), H = 3 as a sensitivity;
  - 200 C1 permutations, seed 20261014.
- **Void shas:**
  - revision 1: `1b22d5ee…` and `203b5ed5…` (3.63 bps fallback);
  - revision 2 before C-a: `56adca95…` and `093f4908…` (percentile CI).
- **Order size and cost** at ₹10 L (approved rates):

| Selection | Order size | Round trip | Book cost per day at 10–20% turnover |
|---|---|---|---|
| k20 | ₹10,000 | 103.0 bps | 10.3–20.6 bps |
| k100 | ₹2,000 | 386.2 bps | 38.6–77.2 bps |

  These use the 5 bps fallback (revision 1 showed the 3.63 bps figures). Turnover is an assumption until measured.

## 4. Half-spread

| Item | Value |
|---|---|
| Primary | a **reliable measured** (session, name) value where one exists, otherwise **5 bps** (C3 as approved) |
| Sensitivities | flat **3.63 bps** (the measured median) and flat **9.34 bps** (the first-quote median) |
| Source | `backend/var/stage4/costs/open_spread_through_2026-10-14.json`, sha256 `b1db9ed304a7639912221b352d98c199d4aec154d95afceb720bd32aa3834f82`. It is referenced by sha in both configurations. |
| Method | rung-0 quotes 09:15–09:20 IST; half-spread = (ask − bid)/(ask + bid); per-name median; reliable = ≥ 3 quotes; top-500 universe per date |
| Dates | 13 of 14 captured sessions (2026-09-25 → 10-14), 6,488 name-days; 2026-09-24 has no qualifying universe |
| Coverage | measured values exist for 3 of 100 TEST sessions (09-25, 09-28, 09-29), so **≥ 97% of TEST trades use 5 bps**. The runner reports `spread_coverage`. |

## 5. Labels and splits: builder code written, NOT run in production

### `app/training/hold.py` (`label-hold5-v1-asif`)

**Basis and windows:**
- **One price basis:** `pit.bars_adjusted` at one recorded cutoff.
- **Holding periods count calendar trading sessions:** a session without a bar is a gap, not skipped.
- **Rows:** emitted on canonical-bar days only, as label-v2 does.

| Label | Definition |
|---|---|
| `open_adj` | the adjusted official open of T |
| `hold5_px`, `hold3_px` | `open[T+h]/open[T] − 1` |
| `hold5_tr`, `hold3_tr` | plus every dividend with ex-date in (T, T+h], divided by every later EXACT split/bonus factor up to the cutoff date (the same factors `bars_adjusted` applies) |

**Rows are explicit, never 0.** Reasons:
- `BAR_REFUSED`
- `MALFORMED_BAR`
- `SESSION_MISSING`
- `NO_EXIT_SESSION`
- `DIVIDEND_NO_AMOUNT`

Flags (never used to select):
- `CA_IN_WINDOW:<id>`
- `UNSUPPORTED_CA_IN_WINDOW:<type>`
- `DIVIDEND_IN_WINDOW`

**Build properties:**
- one transaction, append-only;
- a run row with the cutoff, registry, code sha, source fingerprints and `rows_sha256`;
- **drift against stored rows aborts the build** (rollback).

**Total return is at LABEL level only** (your decision 6):
- the runner reports, per TEST fold, the mean `hold5_tr` and `hold5_px` excess of the picks over their controls (`e2.label_level_excess`);
- **book-level dividend cash accounting is NOT implemented**: `tranche_book` ignores dividends.

### `app/training/splits.py`

- **New scheme `wf-exp-120-20-20-e5`:** embargo 5 and tail 5.
- `build(..., scheme=)` refuses any other label version for e5, and e5 for any other label.
- **Proven equal to `e2.make_folds(257)`.** E1's `wf-exp-120-20-20-e1` is unchanged (tested).
- `samples.label_snapshots`: label-hold versions are PRE_SESSION only.

## 6. CI calibration (1,000 null worlds per world type): INADEQUATE

**Run:** `ops/measure/e2_null_calibration.py --worlds 1000 --jobs 24 --write`, about 10 minutes.

**What it exercises:** the full pre-registered machinery on synthetic null worlds:
- zero costs and an uninformative score, so the true mean of s_t is 0;
- k20 and k100;
- 10,000 bootstrap draws, block 10;
- NW;
- A1–A4 and `candidate_status`.

**World types:**
- **iid:** independent returns.
- **factor:** market factor with t5 tails and volatility regimes, 20 sector factors, t5 idiosyncratic noise, and AR(0.9) persistent scores.

**Result file:** `backend/var/stage4/experiments/e2/null_calibration.json`
- sha256 `5a0008f7b203b5e6c6214591d00f6d7ea421c50c782a587ddc339222bb483833`;
- code sha (`e2.py` + script) `64ce3821f284…`;
- **`"adequate": false`**.

**Criterion, fixed in the script before the run:** for k20, in every world type, the Wilson 95% upper bound of the ACCEPTED-EXPLORATORY rate must be ≤ 2.5% (twice the nominal one-sided 1.25%).

| Rate (count / 1,000; Wilson 95%) | nominal | iid k20 | factor k20 | iid k100 | factor k100 |
|---|---|---|---|---|---|
| **ACCEPTED-EXPLORATORY** (the decision rule) | ≤ 1.25% | **16 (0.99–2.58%)** ✗ | 11 (0.62–1.96%) | 13 (0.76–2.21%) | 8 (0.41–1.57%) |
| A1 PASS alone | 1.25% | 23 (1.54–3.43%) | 25 (1.70–3.66%) | 23 (1.54–3.43%) | 26 (1.78–3.78%) |
| CI excludes 0 (two-sided) | 2.5% | 54 (4.16–6.98%) | 49 (3.73–6.42%) | 56 (4.34–7.20%) | 56 (4.34–7.20%) |
| A4 placebo FAIL | 2.5% | 64 (5.04–8.09%) | 65 (5.13–8.20%) | 54 (4.16–6.98%) | 59 (4.60–7.54%) |
| Mean of s_t (bps; SE) | 0 | +0.014 (0.044) | −0.015 (0.229) | −0.020 (0.021) | −0.022 (0.120) |

### 6.1 Findings

1. **The construction is unbiased.** The mean of s_t is within 1 SE of 0 in every cell, so controls, placebo and costs do not create an effect.
2. **The 97.5% moving-block CI is anti-conservative.** It excludes 0 in about 5–6% of null worlds instead of 2.5%, and A1 PASS fires about 2× too often.
   - **Likely cause:** a percentile moving-block bootstrap with only about 10 blocks over 100 sessions (5 non-contiguous 20-session TEST blocks) underestimates the variance of the mean.
3. **The Newey-West agreement roughly halves the false-acceptance rate** (2.3% → 1.6% for iid k20), but not enough. The iid k20 upper bound of 2.58% exceeds the pre-set 2.5%, so the criterion fails.
4. **The placebo gate A4 false-FAILs about 5–8% of the time.** That is the same undercoverage seen from the other side: in a real run it would wrongly reject about 1 in 15 genuine candidates.

### 6.2 What this means

With the pre-registered inference, the realised false-acceptance rate of an E2 PASS could be about 1.6%, not ≤ 1.25%, and the CIs are too narrow. The gate is behaving as designed: it stops the test look.

### 6.3 Proposed correction (needs your decision; NOT implemented, NOT run)

Every option is validated only on new synthetic null worlds: a new calibration file, a new code sha, no E2 data.

| Option | Change | Expected effect | Cost |
|---|---|---|---|
| **C-a (recommended)** | **Studentized** moving-block bootstrap (bootstrap-t: each draw's mean divided by its NW standard error), block 10, the same 97.5% level | The standard remedy for percentile-interval undercoverage with few blocks; keeps the stated level | Small code change; A1 semantics unchanged |
| C-b | Keep the percentile bootstrap, widen to the level that calibrates (e.g. 99.5%), chosen on synthetic worlds from a pre-declared grid {98.75, 99, 99.5, 99.75} | Restores the false-positive rate | Lower power; the level is chosen by calibration, not stated a priori |
| C-c | Make the primary test a NW t against the t-distribution with ≈ 20 effective degrees of freedom; the bootstrap CI is reported only | Simple, conservative | Changes A1's definition |
| C-d | Fold-level test: 5 fold means, one-sided t with 4 df | Very conservative, transparent | Very low power |

**Recommended sequence:**
1. Adopt C-a.
2. Rerun 1,000 + 1,000 null worlds with the **same pre-set criterion**, and also require the two-sided rate's Wilson interval to include 2.5%.
3. If it is still inadequate, C-b with the grid declared before the run.
4. Report back before any E2 data is touched.

### 6.4 Recalibration with correction C-a (approved 2026-10-14)

**C-a, the studentized moving-block bootstrap-t:**
- **Original:** mean m, with SE s from the overlapping block means (Künsch).
- **Per draw:** a mean m* of k = ⌈n/10⌉ blocks, with its own block SE s*.
- **Pivot:** t* = (m* − m̃)/s*, centred at the mean of all block means.
- **CI:** [m − q₀.₉₈₇₅·s, m − q₀.₀₁₂₅·s].
- **Tests:** location/scale equivariance; a constant series gives a point interval; wider than the percentile CI on a short series; the default of `summarise`.

**Run:**
- `e2_null_calibration.py --worlds 1000 --jobs 24 --write`, the same worlds and seeds as §6.
- File: `backend/var/stage4/experiments/e2/null_calibration_studentized.json`, sha256 `7bff0ad484ec9de8ba72a12813b239a2952edf3716e06c5d766f4bf4d61fb5da`.
- Code sha `283fa95ac8ad…`.
- `"adequate": false`.
- The percentile file is kept unchanged.

**Pre-set criteria (§6.3, step 2; fixed in the script before the run):**
1. The k20 ACCEPTED-EXPLORATORY Wilson upper bound is ≤ 2.5% in every world type.
2. The k20 two-sided Wilson interval contains 2.5%.

| Rate (count / 1,000; Wilson 95%) | nominal | iid k20 | factor k20 | iid k100 | factor k100 |
|---|---|---|---|---|---|
| **ACCEPTED-EXPLORATORY** | ≤ 1.25% | **6 (0.28–1.30%)** ✓ | **10 (0.54–1.83%)** ✓ | 9 (0.47–1.70%) | 5 (0.21–1.17%) |
| A1 PASS alone | 1.25% | 6 (0.28–1.30%) | 14 (0.84–2.34%) | 9 (0.47–1.70%) | 11 (0.62–1.96%) |
| CI excludes 0 (two-sided) | 2.5% | **14 (0.84–2.34%)** ✗ (conservative) | 27 (1.86–3.90%) ✓ | 20 (1.30–3.07%) | 27 (1.86–3.90%) |
| A4 placebo FAIL | 2.5% | 16 (0.99–2.58%) | 40 (2.95–5.40%) | 16 (0.99–2.58%) | 34 (2.44–4.71%) |
| Before C-a (percentile), for comparison: accepted / two-sided | | 16 / 54 | 11 / 49 | 13 / 56 | 8 / 56 |

**Reading:**
- **Criterion 1 PASSES in both world types.** C-a brings false acceptance to the nominal level, or below it: iid 0.6%, factor 1.0%. This was the purpose of the correction.
- **Criterion 2 FAILS in iid worlds, on the conservative side.** The CI is too wide: it excludes 0 in 1.4% of worlds instead of 2.5%. In factor worlds, which are closer to real data, it is on target (2.7%).
- **Cost of the conservatism:** some power. It is not a false-positive risk.
- **A4 placebo:** it still over-rejects in factor worlds (4.0% vs 2.5%). That would wrongly reject about 1 in 25 genuine candidates. The direction is again conservative for acceptance.
- **The construction remains unbiased:** mean s_t within 1 SE of 0.

### 6.5 Decision needed (nothing adopted; the gate stays closed)

| Option | Meaning |
|---|---|
| **W (recommended)** | Accept C-a with a **recorded waiver** of criterion 2 for the conservative direction only. Criterion 2 was meant to catch mis-calibration; failing it by being too conservative does not threaten the false-positive control the gate protects. The waiver is post-calibration, so it is recorded as such, and **E2 data is still untouched**. On approval only, a `--waive-conservative-coverage` flag (**not implemented yet**) would write a new calibration file stating the reason; the existing files are never edited. |
| X | Keep the gate closed, and pre-register a different method (e.g. C-c: NW t against t with about 20 df) with its own criteria and a new 1,000 + 1,000 calibration |
| Y | Stop E2 here and record Stage 4 E2 as **BLOCKED (inference not calibrated)** |

### 6.6 Waiver W (approved 2026-10-14), recorded

**Tool:** `ops/measure/e2_calibration_waiver.py`. It writes a waiver only when:
1. the source has ≥ 1,000 worlds, `ci_method` studentized, and criterion 1 holds in every world type;
2. every criterion-2 failure is **below** 2.5% (conservative).

An anti-conservative result, or a false-acceptance bound above 2.5%, is never waivable (tested).

**File:** `backend/var/stage4/experiments/e2/null_calibration_studentized_waiver.json`, sha256 `be7e6f7805d4f40e1424eba6d0a1e20d935c825a96b17c8415469f65065f02a4`.
- It records:
  - the source file and its sha (`7bff0ad4…`);
  - the calibrated code sha (`283fa95a…`);
  - the conservative failure (iid 1.4%, Wilson 0.84–2.34%);
  - the reason, the approver and the time.
- It is never overwritten, and its source is never edited.

**Runner gate (`calibration_ok`):**
- requires ≥ 1,000 worlds, `adequate`, and the calibrated code sha = the current `e2.py` + calibration script;
- for a waiver, also requires the source file unchanged;
- today it returns `(True, "adequate")`.

**Any change to `e2.py` or the calibration script invalidates it.** A recalibration is then needed, into a new file.

## 6.7 Amendment 3: evaluation mask (decided 2026-10-14, before any E2 look)

**Decided by:** Claude, under the authority you gave on 2026-10-14 ("take decisions by analysing all scenarios").

**Why it is needed (from the QA of the built labels, before any E2 metric existed):**
- `label-hold5-v1-asif` has 153 VALID `hold5_px` values below −40% that carry no corporate-action flag. Examples:

| Symbol | Session | label-v2 gap |
|---|---|---|
| BHAGYANGR | 2026-10-08 | −91% |
| VERANDA | 2026-10-06 | −87% |
| INDIAGLYCO | 2026-09-02 | −80% |

- label-v2 marks each of these sessions `EXTREME_UNEXPLAINED`: |ret_cc| or |gap| > 25% with no EXACT factor. These are corporate actions the vendor never recorded. A tranche holding one books a fake crash, or a fake jump.

**Rule:**
- **Suspect session:** a session x of instrument k where label-v2 has `EXTREME_UNEXPLAINED` or `UNSUPPORTED_CA_EX_T:*` (an action with no price factor).
- **What is dropped:** a name formed on day d is masked when a suspect session lies in [d, d + H]. It is dropped **after selection**, identically from every arm: P, C2, placebo, placebo-C2, C0 and every C1 permutation. It is also dropped from the ridge TRAIN/VALID rows.
- **Selection never sees the mask.** This mirrors E1, which applied `EXTREME_UNEXPLAINED` and `CA_WINDOW` as evaluation exclusions to every arm alike.
- **Reported, not gated:** the unmasked result is a sensitivity.
- **Code:** `stage4_e2_hold.py` (`suspect_days`, `masked`, `apply_mask`). It is not in `e2.py`, so the C-a calibration and the waiver W stay valid for the unchanged core.
- **Tests:** `TestEvaluationMask` (window, symmetry across arms, no mutation, ridge rows).

**Config shas** (they replace §3's):

| | Role | Config sha256 |
|---|---|---|
| k20 | PRIMARY | `c9ca0b51c607ef6f2c9f96aa550b51228189ac71110cd4bb553bbb736210b3fc` |
| k100 | SENSITIVITY | `a4ffbdd760fb09a8b8d45ff1e3a94bbeae5be2282aff3a6fc175e2e694274b2b` |

## 7. Power and sample-size limits (k20)

- **TEST size:** 100 TEST sessions, about 20 independent 5-session periods. The calibration shows the effective information is lower than the bootstrap assumed.
- **Variance:** k20 holds a fifth of k100's names, so idiosyncratic sd is up to √5 ≈ 2.2× higher.
  - In the factor null worlds, the spread of mean(s_t) across worlds is **1.9× larger for k20** than for k100 (SE 0.229 vs 0.120 bps, measured).
  - Minimum detectable mean s_t at 80% power: about **0.18–0.43% per day** (ridge24) and 0.25–0.56% (reversal). This is extrapolated from E1's dispersion × 2.2.
- **Costs to beat at ₹10 L:** 10.3–20.6 bps per day; E1's gross matched excess was 5–8 bps per day.
- **Expected verdict: UNPROVEN or FAIL.** E2 can only detect a 5-session effect roughly 3–8× larger than E1's 1-session effect.
- **Other limits:**
  - assumed knowability (as-if-live);
  - survivorship bias (current master, worse over multi-day holds);
  - spreads measured in Sep–Oct applied to May–Sep;
  - the auction open is priced with a half-spread (conservative);
  - no book-level dividend cash.

## 8. Forward confirmatory design (unchanged from revision 1)

- **Freeze before the first forward session:**
  - the configuration sha;
  - the P2 refit rule;
  - costs, s_t and the gates;
  - the corrected inference of §6.3.
- **Data:** sessions after the freeze only. Picks are recorded before 09:15 IST by a paper-only shadow log; the E2 variant is not written, and installing it needs approval.
- **Test:** one-sided, at a fixed horizon N or with pre-set alpha spending.
- **Required N** = (1.96 + 0.84)² σ² / δ² × an overlap inflation of 1–5×. At k20 (σ ≈ 0.67% per day):

| True effect δ | Sessions needed |
|---|---|
| 0.3% per day | 39–196 |
| 0.2% per day | 88–440 |
| 0.1% per day | 352–1,760 |

  The calibration result suggests the upper end.

## 9. Verification evidence

| Property | Evidence |
|---|---|
| Costs once, on P only | `test_costs_enter_once_on_the_predictor_book_only`; `test_cost_parts_sum_to_the_total_and_are_counted_once` |
| No control cost advantage | `test_no_edge_and_flat_prices_cannot_pass_through_a_control`; calibration: mean s_t = 0 within 1 SE |
| No selection leakage | `test_selection_never_sees_later_sessions`; `form_block` gets features only; the runner's `load_session` selects no label column |
| Configuration identity | `test_each_selection_and_level_is_its_own_configuration`; shas reproducible run to run |
| One look | `test_one_look_is_enforced`: dirty tree; missing or foreign validate; no confirm token; missing, < 1,000-world or inadequate calibration; an existing test file. Plus `test_calibration_must_be_of_the_current_code`. |
| Candidate rule | `TestCandidateStatus` (NW disagreement gives UNPROVEN; missing A5 gives BLOCKED) |
| Labels | `tests/training/test_hold.py`: 8 pure tests (definitions, calendar windows, reasons, dividend holder of record, rescaling by later splits, split flags, determinism) and 4 tests on the TEST database seed world (values, bonus basis, refusals, idempotency, label after as_of, scheme guard) |
| Splits | e5 = `make_folds(257)`, no violations, E1 unchanged; tail purge |
| Suspension fix | `test_a_move_across_a_suspension_is_booked_when_the_name_reopens` |

## 10. Approval checklist

| # | Item | Status |
|---|---|---|
| 1 | Adopt revision 2 (§1–§5) | **your decision** |
| 2 | Inference correction C-a: **approved and recalibrated** (§6.4): false acceptance controlled; criterion 2 failed on the conservative side | done |
| 2b | §6.5 waiver W | **approved and recorded** (§6.6) |
| 3 | Build `label-hold5-v1-asif` and `wf-exp-120-20-20-e5` in production (backup first; about 20–40 min, about 1–1.5 GB, no vendor calls) | **next: separate approval needed** |
| 4 | validate, then the single k20 test look (k100 reported as a sensitivity) | separate approval |
| 5 | E2 shadow logger and forward freeze (only after ACCEPTED-EXPLORATORY) | later |
| 6 | C5 primary legal texts | open |
