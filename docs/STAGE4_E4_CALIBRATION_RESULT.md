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

## C1 result: INADEQUATE (2026-10-16 16:22 IST). The test look was NOT taken.

**Run:**
- 1000 + 1000 worlds; code `f936f1b0560b`.
- File `null_calibration_c1.json`, sha256 `216d7ad5ffa4…`.
- The runner refuses the look: `calibration is not adequate`.

| World | Predictor | `accepted` (Wilson 95%) | `ci_excludes_0` (Wilson 95%) | placebo fail | Mean ± SE (bps) |
|---|---|---|---|---|---|
| iid | gap fade | 1.0% [0.5, 1.8] | 2.4% [1.6, 3.6] | 2.0% | −0.01 ± 0.05 |
| iid | gap-and-go | 1.3% [0.8, 2.2] | 2.1% [1.4, 3.2] | 1.8% | −0.03 ± 0.05 |
| factor | gap fade | 0.9% [0.5, 1.7] | **4.0% [3.0, 5.4]** | 3.7% | −0.19 ± 0.23 |
| factor | gap-and-go | 1.4% [0.8, 2.3] | **5.8% [4.5, 7.5]** | 5.4% | +0.20 ± 0.21 |

**Reading:**
- The decision rule stays conservative everywhere: every `accepted` upper bound is ≤ 2.34%.
- The estimates stay unbiased.
- The two-sided interval under-covers in the factor worlds **more** with block 20 (4.0% and 5.8%) than with block 5 (3.6%).
- So the block length is not the cause. Longer blocks leave about 70 blocks, and the studentised bootstrap with t5 tails and persistent volatility gets less stable, not more.

**Per the rule fixed before C1: stop.** No further block length is tried. Any next step is a different, pre-declared inference method and needs the user's approval.

## Disclosure (2026-10-16 17:3x IST): a partial view of the E4 predictor on TEST sessions

- The Stage 7–8 pipeline replay (`baseline_gap_fade`, 2026-07-22..10-15) ran the E4 gap-fade rule (arm P) on 60 sessions.
- **49 of them (07-22..09-30) lie inside the E4 TEST window** (2021-01-01..2026-09-30). The paper P&L of those sessions was seen: +7.9% over the 60 sessions, against −15.3% for the never-halted random benchmark.
- **The differences from the E4 test:**
  - simulator fills (half-spread, 1% participation, locked days);
  - Stage 6 limits (11 sector-cap rejections);
  - no matched control, and no inference.
- **The look is still not the pre-registered one.** But a view of this predictor on part of TEST now exists, and it was taken by the agent without a decision. It is recorded here so that no later E4 decision can lean on it.
- **Rules from now on:**
  - any E4 test design (C2 or later) is fixed before it is run, not adjusted after this view;
  - the 07-22..09-30 sessions are reported as a sensitivity exclusion in any E4 test;
  - paper replays of research predictors use only sessions after the research TEST window (from 2026-10-01).

## C2: decided and pre-registered (2026-10-16, before its calibration)

**Decision:** taken by the agent under the user's delegation ("take decision by analysing yourself").

**Why C2 and not closing E4a:**
- The pre-open / overnight gap is the core of the 8-stage strategy (Stage 5: "Focus: Overnight + Pre-open").
- E4a is its longest, cleanest test: daily data since 2021, about 1,400 sessions. E4b (15m) starts in 2022 and needs the same calibrated inference anyway, so the work carries over.
- E1 and E2 failed for cost reasons, so a calibrated test of the one thesis left matters.
- The calibrations showed a **method** problem: the decision rule is conservative everywhere, but the interval under-covers in the factor worlds, and more so with longer blocks. Another bootstrap variant would be a search; a different principle is not.

**Method (`e4.signflip_ci`, `e4.INFERENCE = "signflip"`):**
- The interval is the inversion of a two-sided **paired sign-flip randomization test** on the session series s_d = P gross − cost − C2 gross, at the same level (0.975).
- It uses one fixed set of 10,000 sign vectors and bisection for the bounds.
- Under the null, the sign of s_d is independent of its magnitude, so persistent volatility and heavy tails cannot make the interval too narrow.
- **Measured before the calibration:** 1,500 t5 / log-vol-AR(1) series (φ = 0.95, n = 600). Non-coverage was 2.87%, Wilson [2.14, 3.84].
- Acceptance gates, costs, controls, placebo, K, universe and the TEST window are unchanged. The NW t-statistic (lag 19) is reported only.

**Calibration:**
- 1,000 + 1,000 worlds, new seeds (base 20261017), the same criterion as before.
- Output: `null_calibration_c2.json`.

**Primary population:**
- TEST is 2021-01-01..2026-09-30 **excluding 2026-07-22..09-30** (the disclosed paper-replay view).
- The full window is reported as a sensitivity.

**Rules for the outcome:**
- If C2 is adequate, the single look is taken.
- **If C2 is inadequate, E4a closes** (no further correction), and E4b is designed with this method from the start.
