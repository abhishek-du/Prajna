# Stage 4 E1: pre-session stock selection, pre-registration

**Status:** DESIGN APPROVED 2026-10-12. Script written; **not run**: no validate look, no test look.
- **Research only:** no model is stored, no database writes, no orders, no profitability claim.
- **Code:**
  - `backend/app/training/e1.py`: pure computation;
  - `backend/ops/measure/stage4_e1_selection.py`: read-only loader and phases;
  - `backend/tests/training/test_e1.py`: tests.

This document fixes the design and the acceptance criteria **before any result exists**. A change to any item below is a new configuration with a new hash, and it is visible in the run ledger.

## Question

Do the top-ranked names of a liquid universe earn more from the official open to the official close than liquidity- and volatility-matched controls, by more than realistic costs?

## Why this experiment, and not more features

- Prajna's only measured signal, reversal (−`ret_1d`), already has gross predictive power on as-if-live v3: rank IC 0.034–0.072, t 3.0–10.4, in all 5 folds.
- It fails after costs: −0.16% to +0.08% per session net of 20 bps (`docs/STAGE4_DATASET_V3_REPORT.md`). The bottleneck is costs, execution and universe, which more features can't fix.
- Fundamentals, sector, news and pre-open data exist only from 2026-09-24 to 09-29. They can't be validated over the 257-session history.
- V1 (`auto-trade-pro/docs/2026-08-25_*`) showed that apparent selection edges vanish under matched controls. Its −0.297% timing figure was withdrawn as confounded. The V1 findings shape the method here; they are not Prajna conclusions.

## Data

| Item | Value |
|---|---|
| Dataset | `stage4-ds-v3-asif` (AS_IF_LIVE-v2: knowability **assumed** from measured live lags), PRE_SESSION |
| Target | `label-v2` `ret_oc`: official open to official close of session T, gross. A secondary run may use `label-tsl-long-v1-asif` `tsl_l_k1p5_gross_ret` (`--labels`). |
| Folds | The stored `wf-exp-120-20-20-e1` splits: 5 folds, 1-session embargo, 100 TEST sessions (2026-04-27 → 2026-09-17) |
| Quarantine | The script refuses a quarantined PRE_SESSION slice. None exists. |

## Selection (point-in-time only)

- **Universe:** the top 500 by `turnover_20` among the session's feature-eligible samples (all 24 core features VALID at as_of). Ties are broken by instrument key.
- **Picks:** the top quintile of the predictor score inside the universe. Long-only and equal weight, matching the TSL long-only contract.
- **Evaluation exclusions:** masks (`CA_WINDOW`, `EXTREME_UNEXPLAINED`), `PRICE_LEVEL_VENDOR_ADJUSTED` label flags, and a non-VALID target are applied **after** selection, to every arm alike, because they use information from after as_of. The tests prove that the selection never reads them.

## Predictors (2; Bonferroni)

| | Definition |
|---|---|
| P1 reversal | −`ret_1d` |
| P2 ridge24 | Ridge on the 24 core features, each ranked per session to [−0.5, 0.5]. The target is the session rank of y. It is fit on TRAIN only. The penalty comes from {1, 10, 100, 1,000, 10,000}, chosen per fold on VALID by mean rank IC, with ties going to the larger penalty. **Running P2 fits a model and needs the separate P2 approval.** |

## Controls

- **C0:** universe equal-weight.
- **C1:** permutation null. Random draws of the same size from each session's evaluable universe; 2,000 pooled draws; one-sided p.
- **C2 (primary):** per pick, the mean y of the non-picked evaluable names in the same (`turnover_20` decile, `atr_pct_14` decile) cell of the session universe. Picks with no match are counted and dropped.
- **Placebo:** random non-picked names against their own C2 controls.

## Primary metric and inference

- **Metric:** the mean per-session gross excess over C2, pooled over the 100 TEST sessions.
- **Inference:** a moving-block bootstrap over sessions (block 5, 10,000 draws, seed 20261012) gives a **97.5%** CI, i.e. Bonferroni over the 2 predictors.
- **Secondary:**
  - rank IC (mean, Newey-West t with lag 5);
  - session hit rate;
  - trades;
  - daily turnover (name overlap);
  - maximum drawdown of the daily excess series;
  - per-fold means;
  - C0 and C1.
- **Sensitivities** (reported, never acceptance inputs): unmasked; tier 1–200; tier 201–500; excluding the bottom 20% of the universe by `sma_20` (a survivorship check).
- **Cost sweep:** 0/10/20/30/40 bps per side. It is **illustrative** and asserts no fee schedule.

## Acceptance criteria (approved; applied per predictor)

| # | Criterion | Rationale |
|---|---|---|
| A1 | The lower bound of the 97.5% CI of gross C2-excess is above 0. PASS if lower > 0; FAIL if upper < 0; otherwise UNPROVEN. | Bonferroni over the 2 predictors |
| A2 | Net excess > 0 at the approved base cost, and ≥ 0 at 1.5× that cost | The edge must survive realistic and pessimistic costs. It is **NOT_EVALUATED until a cost model is approved**; `recost` applies one later without a database look. |
| A3 | Excess > 0 in at least ⌈0.8 × folds⌉ folds (4 of 5) | Stability; weak alone, so it is paired with A1 |
| A4 | The placebo CI includes 0 | The pipeline does not manufacture an effect |
| A5 (P2) | P2's primary mean is above P1's, otherwise P2 is dropped | Complexity has to earn its place |

**Sensitivity estimate:** with about 100 sessions and a daily excess standard deviation of roughly 0.3–0.5%, the minimum detectable effect is about 0.1% per session. Smaller true effects will read UNPROVEN, not FAIL.

## Discipline: one look at the TEST blocks

1. **`validate`** reads TRAIN and VALID only. It freezes the configuration (sha256 over every choice) and P2's penalties. It reports **no performance metric**, because each fold's VALID block overlaps the previous fold's TEST block, so a VALID result would be an early look at the test period.
2. **`test`** is the single look. It needs the matching validate file and refuses when a test file of that configuration exists. It refuses a dirty working tree.
3. **`recost`** applies an approved cost model (`name`, `per_side_bps`, `approved_by`, `source`) to the stored result. It needs no database.

Every run is appended to `backend/var/stage4/experiments/e1/ledger.jsonl`, so every look at every configuration is visible.

## Known limitations

- **Knowability is assumed (as-if-live).** Every E1 result is provisional until it is confirmed on at least the approved number of STRICT sessions. 60 is suggested, about 20 sessions a month.
- **Survivorship bias.** Only names in the current master exist. This biases long-only reversal upward. It cannot be repaired; the low-price sensitivity only probes it.
- **Execution prices.** Entry at the official open (a pre-open order filling at the equilibrium price) and exit at the official close (a closing-price auction, not a single print) are modelled proxies. There are no historical bid-ask spreads; spread and slippage enter only through the cost sweep.
- **Cross-sectional correlation.** Names within a session are correlated, so the session is the unit of inference. Labels are 1-session and do not overlap per instrument.

## Commands (not run)

```bash
cd backend
.venv/bin/python ops/measure/stage4_e1_selection.py validate --predictors reversal          # P1 only
.venv/bin/python ops/measure/stage4_e1_selection.py validate --predictors reversal,ridge24  # needs P2 approval
.venv/bin/python ops/measure/stage4_e1_selection.py test     --predictors <same as validate>
.venv/bin/python ops/measure/stage4_e1_selection.py recost --result var/stage4/experiments/e1/test_<sha12>.json --cost-model <approved.json>
```
