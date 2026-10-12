# Stage 4 E1: P1 reversal, test look results

**Verdict:** **NOT ACCEPTED.** A1 UNPROVEN, A2 NOT_EVALUATED (no approved cost model), A3 PASS, A4 PASS.
- **Status:** the single TEST look was taken 2026-10-12 20:44 IST, approved by the user. As-if-live data with **assumed** knowability: provisional, research only, no profitability claim.

**Provenance:**
- configuration sha256 `e0e12d5bca77409caa7319b367f3846088f86eb44e8f57cfb6a96bc606baead2`;
- code cee164f, clean tree;
- design: `docs/STAGE4_E1_PREREGISTRATION.md`;
- artifacts: `backend/var/stage4/experiments/e1/validate_e0e12d5bca77.json` and `test_e0e12d5bca77.json` (sha256 `6804c03e…`);
- 2 entries in `ledger.jsonl`;
- no database writes (the `training_*` write counters were identical before and after).

## Primary (top 500 by turnover, long-only top quintile, 100 TEST sessions 2026-04-27 → 09-17)

| Metric | Value |
|---|---|
| Gross excess over matched controls (C2), mean per session | **+0.076%** |
| 97.5% CI (block bootstrap) | **[−0.023%, +0.158%]**: includes 0, so A1 is UNPROVEN |
| Per fold | +0.042 / −0.057 / +0.027 / +0.218 / +0.149%: 4 of 5 > 0, so A3 PASS |
| Placebo | +0.029%, CI [−0.030, +0.096]: A4 PASS |
| Rank IC | 0.044, Newey-West t 4.27 |
| Session hit rate | 0.57 |
| Picks, absolute gross (C0 universe −0.111%) | **−0.056% per session** |
| C1 (random same-size picks, unmatched) | null −0.111%, one-sided p 0.0015 |
| Trades | 10,000 (9,981 evaluable; 306 without a matched cell) |
| Daily name turnover | 78% |
| Maximum drawdown of cumulative excess | 3.0% |

**Illustrative cost sweep** (not acceptance; no fee schedule asserted):

| Per side | Net excess | Net long, absolute |
|---|---|---|
| 0 bps | +0.076% | −0.056% |
| 10 bps | −0.124% | −0.256% |
| 20 bps | −0.324% | −0.456% |

At the measured gross excess, any cost above about 3.8 bps per side makes net excess negative.

## Sensitivities (reported, never acceptance inputs)

| Variant | C2 excess | 97.5% CI | Rank IC (t) |
|---|---|---|---|
| Unmasked | +0.076% | [−0.022, +0.158] | 0.044 (4.27) |
| Tier 1–200 | +0.027% | [−0.109, +0.148] | 0.049 (4.02) |
| Tier 201–500 | +0.043% | [−0.080, +0.150] | 0.041 (3.89) |
| Excluding the bottom 20% by `sma_20` | +0.098% | [+0.006, +0.179] | 0.052 (4.78) |

The low-price exclusion is the only variant whose CI excludes 0. It is one of four unadjusted sensitivities, so it is not evidence of an edge.

## Reading (no decision taken)

- **The ranking carries information but not a matched excess.** Rank IC is consistently positive (t ≈ 4), and the picks beat random draws (C1 p 0.0015). Against liquidity- and volatility-matched controls, though, the excess is not significant. Part of the apparent edge is turnover and ATR exposure, which the matched controls absorb.
- **Long-only lost money even gross:** −0.056% per session, in a test window where the universe averaged −0.111% from open to close. The excess is relative, not absolute.
- **Costs dominate.** With 78% daily turnover, the excess (about 7.6 bps per round trip) is below any plausible round-trip cost. A2 will be FAIL for any realistic cost model, but it is not declared until a cost model is approved (`recost`).
- **Provisional.** The data is as-if-live with assumed knowability, carries survivorship bias, and uses modelled open and close prices.
- **This configuration is spent.** A re-test of it is refused. Any variation is a new configuration and a new look, visible in the ledger.
