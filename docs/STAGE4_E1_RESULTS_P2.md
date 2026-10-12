# Stage 4 E1: P2 ridge24, test look results

**Verdict:** **NOT ACCEPTED, P2 dropped.** A1 UNPROVEN, A2 NOT_EVALUATED (no approved cost model), A3 FAIL (3 of 5 folds), A4 PASS, A5 FAIL.

**Status:**
- Run 2026-10-12, approved by the user. As-if-live data with **assumed** knowability: provisional, research only, no profitability claim.
- The ridge was fit in memory only; no model was stored.

**Provenance:**
- configuration sha256 `82e828c87e2a581048bac4a140c0e69c7e15056bd57ec4dd8324becfad2ad472` (predictors `reversal,ridge24`);
- code 06fbf4e, clean tree;
- design: `docs/STAGE4_E1_PREREGISTRATION.md`;
- artifacts: `backend/var/stage4/experiments/e1/validate_82e828c87e2a.json` (sha256 `3b134335…`) and `test_82e828c87e2a.json` (`19011bf3…`);
- the ledger now has 4 entries;
- no database writes (the `training_*` write counters were identical before and after).

**Why the configuration includes P1:**
- A5 compares P2 against P1 within one result.
- P1's numbers here are **identical** to its first look (`test_e0e12d5bca77.json`: same data, same seeds), so the repeat carries no new information about P1.
- Its verdict is unchanged: `docs/STAGE4_E1_RESULTS_P1.md`.

**Penalties** (validate, chosen per fold on VALID by mean rank IC; no metric reported): 10000 / 1000 / 1000 / 100 / 100.

## Primary (top 500 by turnover, long-only top quintile, 100 TEST sessions 2026-04-27 → 09-17)

| Metric | P2 ridge24 | P1 reversal |
|---|---|---|
| Gross excess over matched controls (C2), mean per session | **+0.051%** | +0.076% |
| 97.5% CI | **[−0.019%, +0.134%]**: A1 UNPROVEN | [−0.023, +0.158] |
| Per fold | −0.026 / −0.046 / +0.183 / +0.121 / +0.022%: **3 of 5**, A3 FAIL | 4 of 5 |
| Placebo | +0.021%, CI [−0.033, +0.086]: A4 PASS | PASS |
| Rank IC (Newey-West t) | **0.069 (7.04)** | 0.044 (4.27) |
| Session hit rate | 0.54 | 0.57 |
| Picks, absolute gross (C0 −0.111%) | −0.052% | −0.056% |
| C1 one-sided p | 0.0015 | 0.0015 |
| Trades (evaluable; unmatched) | 10,000 (9,992; 803) | 10,000 (9,981; 306) |
| Daily name turnover | **14.5%** | 78% |
| Maximum drawdown of cumulative excess | 2.2% | 3.0% |

**Illustrative costs** (per side; net excess): 0 bps +0.051%, 10 bps −0.149%, 20 bps −0.349%. Any cost above about 2.6 bps per side makes net excess negative.

## Sensitivities (reported, never acceptance inputs)

| Variant | C2 excess | 97.5% CI | Rank IC (t) |
|---|---|---|---|
| Unmasked | +0.051% | [−0.019, +0.134] | 0.069 (7.01) |
| Tier 1–200 | +0.025% | [−0.047, +0.120] | 0.061 (4.34) |
| Tier 201–500 | +0.090% | [+0.005, +0.179] | 0.062 (6.88) |
| Excluding the bottom 20% by `sma_20` | +0.082% | [+0.009, +0.160] | 0.062 (6.14) |

Two of the four uncorrected sensitivities have a CI above 0. That is not evidence of an edge: they are not acceptance inputs, and they are not corrected for multiple comparisons.

## Reading (no decision taken)

- **A stronger ranking, but a smaller matched excess.** The ridge orders the cross-section better than reversal (IC 0.069 vs 0.044). Its picks still don't beat liquidity- and volatility-matched controls significantly, and it is less stable across folds. Per the pre-registration, P2 is dropped (A5).
- **Low name turnover doesn't cut costs here.** Ridge picks persist (14.5% daily turnover vs 78%), but the label is open-to-close, so every session is a full round trip whatever the overlap. The persistence only matters to a **multi-session holding** design. That would be a new pre-registered experiment, and nothing here supports it yet.
- **Costs still dominate.** The gross matched excess (about 5 bps a session) is below any plausible round-trip cost. A2 will be FAIL for any realistic cost model; it is not declared until one is approved.
- **Provisional.** The data is as-if-live with assumed knowability, carries survivorship bias, and uses modelled open and close prices.
- **E1 is finished:** neither predictor is accepted, and both configurations are spent.
