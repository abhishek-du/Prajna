# Stage 4 E2: multi-session holding, test-look results

**Verdict:** **NOT ACCEPTED.** Both candidates are **UNPROVEN** on the sole primary configuration (k20). Neither reaches ACCEPTED-EXPLORATORY, so no forward confirmation is triggered.

**Status:**
- EXPLORATORY: 92 of the 100 TEST sessions were E1 TEST sessions.
- As-if-live data with assumed knowability.
- Research only: no model stored, no profitability claim, paper only.

## Provenance

| Item | Value |
|---|---|
| Protocol | `docs/STAGE4_E2_PREREGISTRATION.md` (+ Amendment 1); `docs/STAGE4_E2_AMENDMENT_2_PROPOSED.md`, revision 2 (decisions of 2026-10-14) + §6.6 waiver W + §6.7 Amendment 3 |
| Primary config (k20) | sha256 `c9ca0b51c607ef6f2c9f96aa550b51228189ac71110cd4bb553bbb736210b3fc` |
| Code | `5622cd2`, clean tree (ledger) |
| Validate | `backend/var/stage4/experiments/e2/validate_c9ca0b51c607.json`. Ridge penalties per fold: 1 / 1000 / 100 / 10000 / 1. No metric. |
| Test | `backend/var/stage4/experiments/e2/test_c9ca0b51c607.json`, sha256 `fb033a779ad39687ca31b6c3652eafc87e242d74682c65c81aac576b9a10d411`. This was the single look. |
| Calibration gate | `null_calibration_studentized_waiver.json`, sha256 `be7e6f78…`. Its source `7bff0ad4…` is unchanged, and its code sha matches `e2.py`. |
| Labels | `label-hold5-v1-asif`: cutoff 2026-10-14T18:30+05:30; 3,965,195 rows, 3,573 instruments; `rows_sha256` `0b4f5e7becb5…`. A rerun produced the same sha, inserted 0 rows, drift 0. |
| Splits | `wf-exp-120-20-20-e5`: 15 rows; equal to `e2.make_folds(257)`; rerun inserted 0 |
| Backup before the build | `backend/var/backups/prajna_20261014T1900_stage4_e2_labels.dump`, sha256 `db1669d2…` |
| Existing data | label-v1, label-v2, the TSL labels and both E1 split sets have byte-identical fingerprints before and after |
| TEST | 2026-05-08 → 2026-09-29, 100 sessions, 5 folds. 72 instruments masked (Amendment 3). |

## Primary results (k20, ₹10 L capital, 5 bps fallback half-spread, 0 slippage)

- **Daily series, in bps per day.**
- **CI:** 97.5% studentized moving-block bootstrap, block 10, 10,000 draws.
- **NW:** Newey-West t with lag 9.

| Series | reversal (P1) | ridge24 (P2) |
|---|---|---|
| **s_t = P_gross − cost(P) − C2_gross (primary)** | **−13.97 [−25.05, +5.32]**, NW −2.91 | **−9.77 [−21.11, +2.36]**, NW −2.42 |
| Fold means of s_t | −14.0 / −8.1 / −4.6 / −26.4 / −16.8 | −12.1 / −13.8 / −10.8 / +2.8 / −15.0 |
| Gross selection: P_gross − C2_gross | +5.18 [−5.95, +24.55] | +5.22 [−5.39, +16.50] |
| Both costed: P_net − C2_net (reported only) | +4.79 | +8.62 |
| Absolute P_net | −11.40 | −9.75 |
| C0 universe (gross) | +1.23 | +1.23 |
| Placebo (gross vs its C2) | −0.59 [−10.27, +6.51] | +2.76 [−7.50, +9.78] |
| C1 permutation (gross, 200 draws), one-sided p | **0.005** | **0.030** |
| Cost per day: brokerage / statutory / DP / spread | 8.93 / 4.11 / 4.26 / 1.86 = **19.2** | 7.45 / 2.71 / 3.62 / 1.21 = **15.0** |
| One-sided turnover per day (P / C2) | 18.9% / 18.7% | 12.6% / 18.3% |
| Mean positions; masked picks; unmatched | 85.0; 1; 62 | 41.1; 0; 77 |
| Spread coverage (measured / proxy) | 115 / 3,668 | 99 / 3,059 |
| Max drawdown of cumulative s_t (gross) | 15.3% (4.1%) | 11.5% (2.4%) |

**Reading the "both costed" row:** it is the PC-1 artefact. Ridge's lower turnover makes it look positive (+8.62) only because the randomly re-drawn control pays more costs. Under the adopted metric it is −9.77.

## Acceptance

| Gate | reversal | ridge24 |
|---|---|---|
| A1 (s_t CI) | UNPROVEN | UNPROVEN |
| NW agreement with A1 | no (t = −2.91: the evidence leans negative) | no (t = −2.42) |
| A2 (s_t ≥ 0 at 1.5× costs) | FAIL (−23.55) | FAIL (−17.27) |
| A3 (≥ 4 of 5 folds > 0) | FAIL (0/5) | FAIL (1/5) |
| A4 (placebo CI ∋ 0) | PASS | PASS |
| A5 (P2 > P1) | — | PASS (−9.77 > −13.97) |
| **Candidate status** | **UNPROVEN** | **UNPROVEN** |

## Sensitivities (reported, never acceptance inputs; uncorrected)

| Variant | reversal s_t [CI] | ridge24 s_t [CI] |
|---|---|---|
| Capital ₹50 L | −3.42 [−14.47, +15.77] | −0.92 [−11.82, +10.72] |
| Capital ₹1 Cr | −2.10 [−13.16, +17.10] | +0.19 [−10.67, +11.77] |
| Capital ₹5 Cr | −1.05 [−12.12, +18.26] | +1.08 [−9.76, +12.58] |
| Slippage 5 / 10 / 20 bps | −15.82 / −17.66 / −21.35 [−32.47, −2.07] | −10.99 / −12.20 / −14.63 [−26.37, −2.14] |
| Half-spread 3.63 / 9.34 bps (flat) | −13.46 / −15.56 | −9.44 / −10.83 |
| Unmasked | −14.42 | −9.77 |
| Block 20 | −13.97 [−33.37, +5.00] | −9.77 [−26.44, +7.82] |
| H = 3 | −20.61 [−37.52, −1.71] | −8.16 [−20.92, +3.34] |
| Total return (label level, per fold; hold5_tr − hold5_px excess shift) | within ±3 bps of price-only in every fold | within ±2.5 bps |

## Interpretation (no decision beyond the pre-registered gates)

1. **There is a gross selection signal; the costs overwhelm it.**
   - Both predictors' picks beat random same-size picks of the universe (C1 p = 0.005 and 0.030).
   - They also beat their matched controls by about +5 bps per day gross.
   - But at ₹10 L with 20 names per tranche, costs are 15–19 bps per day, dominated by flat brokerage and DP. The cost-adjusted primary is about −10 to −14 bps per day, negative in 4–5 of 5 folds.
2. **Capital is the binding constraint, not the model.** At ₹1–5 Cr (reported, uncorrected) the cost-adjusted mean is about 0 with wide CIs. Even there, nothing approaches a detectable positive edge.
3. **Multi-day holding did not rescue E1.** The 5-session gross matched excess (about 5 bps per day) is about the size of E1's 1-session excess (5–8 bps per day). The holding period did not amplify it.
4. **Limitations:**
   - EXPLORATORY: the period overlaps E1;
   - assumed knowability;
   - survivorship bias;
   - modelled open prices;
   - book-level dividends not implemented (the label-level total-return shift is small).

## Consequences

- **E2 is finished:** both configurations' looks are spent; k100 is reported in its own section once run.
- **Stage 4 status:** research infrastructure complete; **no candidate ACCEPTED**: E1 P1/P2 NOT ACCEPTED, E2 P1/P2 UNPROVEN.
- **Stage 5 must not start** on these predictors.
- **Next scientifically justified step** (not started; each would need a new pre-registration):
  - **Wait for data, not a new model.** Fundamentals, news and pre-open features have about 3 weeks of history. A predictor using them can only be tested once roughly 120 or more sessions accumulate.
  - **Fewer, cheaper trades at the approved capital.** The flat-fee arithmetic says any design at ₹10 L needs orders of ₹50 k or more, i.e. about 4–5 names per tranche, or a weekly rather than daily formation. That is a new configuration, and it would be pre-registered and tested on **forward** sessions only. The E1/E2 period is now spent.
  - No LSTM, XGBoost or ensemble while the linear baselines show about 5 bps of gross edge against 15+ bps of cost.
