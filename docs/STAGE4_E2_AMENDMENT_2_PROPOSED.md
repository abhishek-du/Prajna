# Stage 4 E2: pre-registration Amendment 2 (PROPOSED, for review)

**Status:** PROPOSED 2026-10-14. Not adopted, and nothing run.
- It implements the decisions of 2026-10-14 on `docs/STAGE4_E2_PROTOCOL_CHANGE_PROPOSAL.md` (PC-1a, PC-2a, PC-3, PC-4), which were approved in principle.
- The original protocol (`docs/STAGE4_E2_PREREGISTRATION.md`, including Amendment 1) is preserved unchanged. This amendment takes effect only on your explicit adoption.
- No E2 label, split or test result exists. No number below comes from E2 TEST data.

**Code (written, not run against production):**
- `backend/app/training/e2.py`: experiment core. `Selection`, `K100`, `K20`, `choose`, `form_block`, `primary_series`, `evaluate`.
- `backend/ops/measure/stage4_e2_hold.py`: read-only runner. Configuration sha, one-look ledger, `--confirm-test-look`.
- `backend/ops/measure/e2_open_spread.py`: PC-4 measurement (run, read-only).
- `backend/ops/measure/e2_null_calibration.py`: synthetic calibration of the CI.
- `backend/tests/training/test_e2.py`: 35 synthetic tests.

## 1. Status of every E2 result (PC-2a)

- Every E2 result on the as-if-live history is **EXPLORATORY**. The runner writes `"status": "EXPLORATORY"`, `"independent_confirmation": false` and the E1 TEST overlap count into every result.
- **Why:** the E2 TEST sessions are 2026-05-08 → 2026-09-29, and 92 of the 100 were E1 TEST sessions. The E2 hypothesis came from the E1 look.
- **What a PASS means:** the candidate becomes **eligible** for the forward confirmatory test (§8). A PASS is never reported as confirmation.

## 2. Primary metric and acceptance (PC-1a), exact definitions

**The books:**
- **P book:** the predictor's staggered-tranche book (`tranche_book`, H = 5).
- **C2 book:** the matched-control book, formed per formation day.
- Both are valued open to open on adjusted opens.
- `cost_t(P)` is the P book's day-t cost under the approved model: brokerage, statutory, DP, half-spread and slippage, each once (`CostModel.day_cost_parts`), as a fraction of book value.

| Series (daily, TEST days only) | Definition | Role |
|---|---|---|
| **s_t (primary)** | `P_gross,t − cost_t(P) − C2_gross,t` | **A1, A2, A3, A5** |
| gross selection | `P_gross,t − C2_gross,t` | reported; A6 |
| both costed | `P_net,t − C2_net,t` | reported only (it credits turnover differences; PC-1) |
| absolute | `P_net,t` | reported |
| C0 | equal-weight universe book, gross | reported |
| placebo | `PL_gross,t − PLC_gross,t`: random non-picked names vs their own matched controls, **gross** | **A4** (costs would make any traded arm negative by construction) |

**Why this is cost-adjusted performance, not "beating a control":**
- The control is an **untraded** benchmark: it pays nothing.
- s_t > 0 only if the predictor's selection return exceeds the full cost of harvesting it.
- A control can never supply a cost advantage (tested: `test_no_edge_and_flat_prices_cannot_pass_through_a_control`, `test_costs_enter_once_on_the_predictor_book_only`).

**Not gated:**
- The absolute `P_net` includes the market's direction, so a long-only book can be positive in a rising market with no skill. It is reported, not gated.
- **Option for you:** add A7, "mean `P_net` > 0", if you want absolute profitability gated as well.

| # | Criterion (per predictor and configuration, fixed before the look) |
|---|---|
| A1 | The CI of mean(s_t) at the configuration's level: lower bound > 0 is **PASS**, upper bound < 0 is **FAIL**, otherwise **UNPROVEN**. Moving-block bootstrap, block 10 (= 2H), 10,000 draws, seeded. |
| A2 | mean(s_t) with every cost part × 1.5 is ≥ 0 (point estimate) |
| A3 | mean(s_t) > 0 in ≥ ⌈0.8 × folds⌉ = 4 of 5 TEST folds |
| A4 | The placebo series CI includes 0 |
| A5 (P2) | mean(s_t) of ridge24 > mean(s_t) of reversal, same configuration, otherwise P2 is dropped |
| A6 | Maximum drawdown of cumulative s_t and of the gross selection series. Reported, no threshold. |

**Candidate status:**
- **ACCEPTED-EXPLORATORY:** A1 PASS and A2, A3 and A4 PASS (and A5 for P2). The candidate becomes eligible for §8.
- **FAIL:** A1 FAIL.
- **UNPROVEN:** otherwise.
- **BLOCKED:** a gate cannot be evaluated, e.g. a missing input.

## 3. Selection configurations (PC-3): two versions, neither replaces the other

| | `k100-top-quintile` (the 2026-10-13 pre-registration) | `k20` (new, PC-3) |
|---|---|---|
| Universe | top 500 by `turnover_20` among names with 24 VALID core features | same |
| Picks per tranche | top 20% (100) | **top 20** by the same score, same tie-break (`e2.choose`) |
| Controls / placebo | C2 per pick from the same cell; placebo the same count | same, at k = 20 |
| Capital and costs | C1–C4 as approved | same |
| Config sha (`--ci-level 0.975`) | `203b5ed55bbd…` | `1b22d5ee29a2…` |

**k20 changes the selection design.** It holds fewer, more concentrated names and has higher idiosyncratic variance. It is a separate configuration with its own sha, validate file and single test look.

**Order size and estimated cost** (approved rates, frozen half-spread proxy 3.63 bps per side; turnover is an assumption until measured):

| Capital | Selection | Order size | Round trip incl. 2× half-spread | Book cost per day at 10% / 20% one-sided turnover |
|---|---|---|---|---|
| ₹10,00,000 (primary) | K100 | ₹2,000 | 383.5 bps | 38.4 / 76.7 bps |
| ₹10,00,000 (primary) | **K20** | ₹10,000 | 100.3 bps | **10.0 / 20.1 bps** |
| ₹50,00,000 | K100 | ₹10,000 | 100.3 bps | 10.0 / 20.1 |
| ₹50,00,000 | K20 | ₹50,000 | 43.7 bps | 4.4 / 8.7 |
| ₹1,00,00,000 | K100 | ₹20,000 | 64.9 bps | 6.5 / 13.0 |
| ₹1,00,00,000 | K20 | ₹1,00,000 | 36.6 bps | 3.7 / 7.3 |
| ₹5,00,00,000 | K100 | ₹1,00,000 | 36.6 bps | 3.7 / 7.3 |
| ₹5,00,00,000 | K20 | ₹5,00,000 | 30.9 bps | 3.1 / 6.2 |

**Reading:**
- At ₹10 L, K20 cuts costs about 4× against K100. It is still above E1's gross matched excess of 5–8 bps per day, so E2 needs a 5-session effect of at least 2–4× E1's to pass even at K20.

**Multiplicity (decision needed):**
- If both configurations are looked at, there are 2 configurations × 2 predictors = 4 primary comparisons. Bonferroni then needs a **98.75%** CI.
- **Option 1:** declare one configuration primary before any look; it keeps 97.5%, and the other is secondary-exploratory.
- **Option 2:** look at both at 98.75% (`--ci-level 0.9875`, a different sha).
- **Recommendation:** Option 1 with **k20** primary. It is the only design whose costs at the approved capital are within reach of the E1 edge.

## 4. Opening half-spread (PC-4): measured and frozen

**Run:** `ops/measure/e2_open_spread.py --through 2026-10-14`, read-only, 30 s.

**Frozen file:** `backend/var/stage4/costs/open_spread_through_2026-10-14.json`
- sha256 `b1db9ed304a7639912221b352d98c199d4aec154d95afceb720bd32aa3834f82`;
- referenced by sha in both configurations;
- the script refuses to overwrite it.

| Item | Value |
|---|---|
| Source dates | every session with pre-open capture: 2026-09-24 → 2026-10-14 (14). **13 used.** 2026-09-24 has no PRE_SESSION universe with 24 VALID core features (none in production, none in v3-strict), so it is recorded and unused. |
| Universe per date | top 500 by `turnover_20` with 24 VALID core features. Production `feature_value` where available (11 dates); else `stage4-ds-v3-strict` (09-25, 09-28). Source recorded per date. |
| Calculation | rung-0 quotes 09:15:00 ≤ t < 09:20:00 IST with 0 < bid ≤ ask; half-spread = (ask − bid) / (ask + bid) × 10⁴ bps; per (date, name) median; **reliable** if ≥ 3 quotes |
| Sample | **6,488** reliable name-days (497–500 per date) |
| **Proxy (fallback)** | **3.63 bps** per side (median). Quantiles p10 / p25 / p75 / p90: 1.89 / 2.56 / 5.66 / 7.94 |
| Pessimistic sensitivity | first-quote median **9.34 bps** |
| Measured coverage of TEST | measured (date, name) values exist for TEST sessions 2026-09-25, 09-28 and 09-29 only (3 of 100). **≥ 97% of TEST trades use the proxy.** The runner reports `spread_coverage`. |
| Fallback | a (session, name) with a reliable measurement uses it; anything else uses 3.63 bps |

**Decision needed:** the measured proxy (3.63) is **lower, i.e. less conservative**, than the 5 bps provisional proxy approved under C3.
- The proposal uses 3.63 as the fallback (PC-4: measured beats provisional).
- 5 bps and 9.34 bps are reported as sensitivities.
- If you prefer to keep 5 bps as the primary fallback, that is a different sha.

**Limitations:**
- The spreads were measured in Sep–Oct 2026 and are applied to May–Sep 2026, which assumes a stable regime.
- The official open is a call-auction price. Paying a half-spread at the auction is a conservative proxy, not a measured cost.

## 5. Data contract for the label and split build (needs the separate label/split approval)

| Object | Definition |
|---|---|
| `label-hold5-v1-asif` / `open_adj` | the official open of session T, split/bonus-adjusted by `pit.bars_adjusted` at one recorded knowledge cutoff for the whole window (a single basis, so the book's open-to-open path is consistent). Refused (LOW / RECONSTRUCTED) bars give no row. |
| `hold5_px`, `hold3_px` | `open[T+h] / open[T] − 1` on the same basis (`e2.hold_label`), with the flags of prereg §1. `hold5_px` is the ridge24 target. |
| total-return variant | **not implemented in the book** (`tranche_book` has no dividend cash). Reported at label level only, or deferred. Recorded as a gap. |
| eligibility | `training_sample.feature_eligible` of `label-v2` (it depends on features only) |
| splits | `wf-exp-120-20-20-e5`, 15 rows. The runner refuses unless the stored splits equal `e2.make_folds(257)`. |

## 6. Verification evidence (synthetic; no real data)

| Property | Test |
|---|---|
| Costs enter once, only on P | `test_costs_enter_once_on_the_predictor_book_only`: s_t = gross − cost_t(P) exactly, every day |
| A control cannot create a cost advantage | `test_no_edge_and_flat_prices_cannot_pass_through_a_control`: zero edge, so s < 0 and A1/A2 FAIL. Contrast with PC-1's "both costed" demo (+7.1 bps per day from nothing). |
| No look-ahead in selection | `test_selection_never_sees_later_sessions`: rewriting every later session leaves all earlier picks of every arm identical; `form_block` receives no labels or prices |
| Arms disjoint and sized | `test_arms_are_disjoint_and_sized_by_the_selection` (k = 100 / 20) |
| Order size | `test_k20_raises_the_order_size_fivefold_at_the_same_capital` (₹2,000 vs ₹10,000 at ₹10 L) |
| A real edge is found | `test_a_planted_edge_above_costs_passes` (A1–A4 PASS, C1 p = 1/21) |
| Noise is not a pass | `test_noise_world_is_not_a_pass` |
| One look | `test_one_look_is_enforced`: dirty tree, missing or foreign validate file, missing `--confirm-test-look E2-<sha12>` and an existing test file are all refused |
| Configuration identity | `test_each_selection_and_level_is_its_own_configuration` |
| Suspension accounting | `test_a_move_across_a_suspension_is_booked_when_the_name_reopens` (Amendment 1 fix) |

### CI calibration (`ops/measure/e2_null_calibration.py`, 100 noise worlds, 500 draws)

- The 97.5% block-10 CI excluded 0 in **4–5%** of zero-edge worlds, against the nominal 2.5% (95% band of 100 worlds: about 0–5.6%).
- Block 20 gave **9%**. Newey-West |t| > 2.24 gave 2–4%. The placebo mean was +0.08 bps (SE 0.09), so it is unbiased.
- **Reading:** with about 10 blocks in 100 sessions, the moving-block CI may be **anti-conservative by up to about 2×**. Block 20 is worse (fewer blocks).
- **Proposal, needing a decision:**
  - (a) run 1,000 worlds before the look and report the calibrated rate;
  - (b) additionally require the Newey-West t (lag 2H − 1) to agree with A1 for an ACCEPTED-EXPLORATORY status.
- **Not adopted silently.**

## 7. Statistical power and sample size

- **TEST:** 100 sessions, about 20 independent 5-session periods.
- **K100** (E1 dispersion: ridge24 sd 0.30% per session, reversal 0.40%): MDE at 80% power is 0.08–0.19% per day (ridge24) and 0.11–0.25% (reversal).
- **K20:** a fifth of the names. If the dispersion is idiosyncratic, the sd grows about √5 ≈ 2.2×: MDE is about **0.18–0.43% per day** (ridge24) and 0.25–0.56% (reversal). This is an approximation; the factor is between 1 and 2.2.
- **Against costs:** K20 at ₹10 L costs about 10–20 bps per day. A real 5-session edge would need s_t of about 0.2–0.4% per day to be detectable. **Expected verdict for both configurations: UNPROVEN or FAIL.** E2 can only find a large effect.
- **Further limits:**
  - knowability is assumed (as-if-live);
  - survivorship bias (current master), worse over multi-day holds;
  - the calibration above.

## 8. Forward confirmatory design (for a candidate that reaches ACCEPTED-EXPLORATORY)

- **Freeze:** the configuration sha, the P2 refit rule (expanding TRAIN, refit every 20 sessions, penalty from the frozen validate file), costs, the metric s_t and the gates. These are fixed **before the first forward session**.
- **Data:** formation sessions strictly after the freeze date, never used by E1 or E2. A pick is recorded before 09:15 IST of its session by a paper-only shadow log; the E2 shadow variant is not written, and its install needs approval. Evaluation is open to open.
- **Knowability:** STRICT where the pipeline has it (production features since 2026-09-29), else as-if-live, reported separately.
- **Test:** one-sided, mean s_t > 0, the moving-block CI as in A1 plus a Newey-West cross-check. A fixed horizon N is chosen now, with **no peeking**; or a group-sequential design with pre-set alpha spending, if you prefer interim looks.
- **Required N** = (1.96 + 0.84)² σ² / δ² × an overlap inflation of 1–5× (80% power, one-sided 2.5%; per-day sd σ):

| True s_t (per day) | σ = 0.30% (K100 ridge) | σ = 0.67% (K20, approx.) |
|---|---|---|
| 0.10% | 71–353 sessions | 352–1,760 sessions |
| 0.20% | 18–88 | 88–440 |
| 0.30% | 8–39 | 39–196 |

- **Reading:** about 250 sessions a year. A forward confirmation is feasible within months only for an effect of at least about 0.3% per day. Smaller effects cannot be confirmed in a reasonable time. That is a reason not to begin unless E2 shows a large effect.

## 9. Approval checklist

| # | Item | Status |
|---|---|---|
| 1 | Adopt this amendment (metric s_t, A1–A6 as defined, candidate statuses) | **your decision** |
| 2 | Primary configuration: k20 at 97.5% (recommended), or both at 98.75% | **your decision** |
| 3 | Fallback half-spread: 3.63 bps measured (proposed), or 5 bps C3 | **your decision** |
| 4 | A7 absolute `P_net` > 0 gate: add or not | **your decision** |
| 5 | CI calibration: 1,000 worlds pre-look, and/or a Newey-West agreement requirement | **your decision** |
| 6 | Total-return sensitivity: implement in the book, or report at label level only | **your decision** |
| 7 | Write the label/split builders (code + tests, no production run) | needs approval |
| 8 | Build `label-hold5-v1-asif` and `wf-exp-120-20-20-e5` in production (backup first) | separate approval |
| 9 | Validate, then the single test look per configuration | separate approval |
| 10 | E2 shadow logger + forward design freeze (only after an ACCEPTED-EXPLORATORY) | later approval |
| 11 | C5 primary legal texts | open |
