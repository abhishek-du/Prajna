# Stage 4 E4a step 3: null calibration, INADEQUATE (2026-10-15)

**Result:** INADEQUATE under the criterion fixed before the run. **The E4a test look was NOT taken.** The runner refuses it (`REFUSED: calibration is not adequate`), checked at 20:55 IST. No E4 outcome has been computed.

**Run:**
- `ops/measure/e4_null_calibration.py --worlds 1000 --write`, 18:37 → 20:52 IST.
- Code sha `dc8230b63cf4…` (e4.py + script at `98bba60`); 10,000 bootstrap draws.
- File `backend/var/stage4/experiments/e4/null_calibration.json`, sha256 `95332d00b252…`.

**Criterion (fixed before the run):** for both predictors, in every world type:
- the Wilson 95% upper bound of `accepted` ≤ 2.5%; and
- the Wilson 95% interval of `ci_excludes_0` (two-sided 97.5% CI) contains 2.5%.

## Results (rates; Wilson 95% in brackets)

| World | Predictor | `accepted` | `ci_excludes_0` | `a1_pass` | placebo fail | Mean of means (bps) |
|---|---|---|---|---|---|---|
| iid | gap fade | 1.4% [0.8, 2.3] | 3.1% [2.2, 4.4] | 1.4% | 1.3% | −0.13 ± 0.06 |
| iid | gap-and-go | 1.3% [0.8, 2.2] | 2.8% [1.9, 4.0] | 1.5% | 2.4% | +0.03 ± 0.05 |
| factor | gap fade | 1.2% [0.7, 2.1] | **3.6% [2.6, 5.0]** | 1.7% | 4.3% | −0.30 ± 0.25 |
| factor | gap-and-go | 0.6% [0.3, 1.3] | **3.6% [2.6, 5.0]** | 1.8% | 4.4% | +0.28 ± 0.22 |

**What passes:**
- The decision rule itself is conservative everywhere. The `accepted` upper bounds (1.3–2.3%) are all ≤ 2.5%.
- The estimates are unbiased: every mean of means is within 1.3 SE of 0.

**What fails:**
- In the factor worlds (market and sector factors, t5 tails, persistent volatility regimes), the two-sided 97.5% interval excludes 0 in 3.6% of null worlds instead of 2.5%. The Wilson lower bound is 2.6% > 2.5%.
- So the confidence interval is **too narrow by a small margin** when volatility is persistent.
- The placebo-fail rate (4.3–4.4%) shows the same thing.

## Diagnosis

- The studentized moving-block bootstrap uses blocks of 5 sessions. The factor worlds have log-volatility AR(1) with φ = 0.95, i.e. a volatility half-life of about 14 sessions.
- Blocks of 5 sessions cut those regimes, so the bootstrap under-represents the variance of the session mean.
- The iid worlds, with no persistence, are within the criterion.

## Proposed correction (NOT applied; needs approval)

**C1:** set the bootstrap block length to **20 sessions**, about one trading month and longer than the volatility half-life, and the Newey-West lag to 19 (block − 1). Then run a **new** 1,000 + 1,000-world calibration:
- with new seeds;
- with the same criterion, unchanged;
- into a new file, `null_calibration_c1.json`. The current file stays as the record.

**Rule for the outcome:**
- If C1 is adequate, the single test look may run with C1.
- If C1 is inadequate, stop again and report. **No sequence of block lengths is searched.**

**Why 20 sessions, decided now and not by search:**
- It is the standard monthly block for daily returns.
- It exceeds the regime half-life.
- With about 1,400 test sessions, 70 blocks remain, so the bootstrap still has enough independent pieces.

**Cost:**
- The confidence interval will be somewhat wider, so the detectable edge rises a little (the MDE was about 7–9 bps before).
- The calibration rerun takes about 2.5 h of CPU.
- Nothing else in the design changes: predictors, universe, controls, costs, gates, TEST window.

**This is not tuning on E4 outcomes.**
- No E4 test number exists.
- The correction comes only from the synthetic null worlds, which is what the calibration step is for.
- It is fixed in advance, before its own calibration.

## C1 applied (2026-10-16)

- **Approval:** the user approved C1 on 2026-10-16 ("gap backfill aur C1 chala do").
- **Change:** `e4.BLOCK, NW_LAG = 20, 19`.
- **Calibration:** new seeds (base 20261016) and the same criterion. The output goes to `null_calibration_c1.json`; the block-5 file stays as the record.
- **Test look:** the runner now requires the C1 calibration. If C1 is inadequate, stop and report; no further block lengths will be tried.
