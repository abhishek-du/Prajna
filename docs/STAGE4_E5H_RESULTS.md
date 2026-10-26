# Stage 4 E5-H results: the frozen E5 model on 2020 (single look, 2026-10-26)

**Verdict: NOT_ACCEPTED.** Gates A1 and A2 fail; A3 and A4 pass. PAPER RESEARCH ONLY.

The look was taken once, by `ops/measure/e5h_look.py --look`, at 2026-10-26 11:24 IST.

| Item | Value |
|---|---|
| Model | `4db89a708a128001…` (e5-recipe-v2), sha verified at load |
| Pre-registration | `docs/STAGE4_E5H_PREREGISTRATION.md`, sha256 `203f001f7c9b…` |
| Code | `52dc694` |
| Ledger | `backend/var/stage4/experiments/e5h/look.json` and `ledger.json`. A second look is refused |
| Dataset | `stage4-ds-h2020`: 260 PRE_SESSION snapshots (2019-12-17..2020-12-31), 28.8 M rows, 3 runs COMPLETE, no duplicate session, every `as_of` before 09:15 IST |
| Labels | `label-h2020` run `90c0f872`: 3,474,423 rows, 1,697 instruments, rows sha `38f07db6…`, drift 0 |

## 1. Data steps (2026-10-23..26)

**Warm-up backfill.**
- 2019-09-01..12-31 Upstox 1d: 3,574 jobs, 120,019 bars, 1,618 instruments, 0 failed.

**Calendar.**
- `trading_session` started at 2020-01-01, and `canon_market_bar` joins it, so the 2019 bars were invisible at first.
- The standard `ingest calendar --from 2019-09-03 --to 2019-12-31 --commit` added 120 days:
  - 79 NORMAL, 1 SPECIAL (muhurat 2019-10-27), 7 HOLIDAY;
  - 2019-09-01/02 have no NIFTY 50 evidence and were refused.

**Basis.**
- Median |first 2020 open / last 2019 close − 1| = 0.6 %.
- The look's pre-registered rule excluded 10 basis-break names to 2020-03-31, and 16 names with a price-factor action between the two fetches.

**Not evaluable.**
- 2020-02-01 (budget day) and 2020-11-14 (muhurat) have no PRE_SESSION values.
- 250 of 252 sessions were evaluated.

**Interruption (disclosed).**
- The build paused while the host was suspended, from 2026-10-23 22:24 to 2026-10-26 09:41.
- The first `--look` run crashed before writing any ledger and before any output was shown.
  - Cause: a SPECIAL previous session has no recorded close.
  - Fix (`52dc694`): those sessions use the standard 15:30 close in the results-day window. This is exact for the budget day and conservative for the evening muhurat.
  - The second run is the look.

## 2. Primary result (s_d = picks − MIS cost − matched controls)

| | E5 picks | Placebo (random, same count) |
|---|---|---|
| Sessions / cash sessions | 250 / 137 | 250 / 138 |
| Mean picks per session | 3.86 | 3.86 |
| **Mean s_d** | **+3.3 bps** | −8.2 bps |
| Sign-flip CI (0.975) | [−17.1, +23.9] bps | [−21.8, +5.6] bps |
| Mean s_d at 1.5 × costs | −0.6 bps | |
| Minimum detectable effect (realised) | 25.7 bps | |
| Net book (picks − cost, not relative) | −18.6 bps / session, Sharpe −1.43, max drawdown 54.7 % | −24.9 bps, Sharpe −2.56 |

| Gate | Rule | Result |
|---|---|---|
| A1 | CI of mean s_d above 0 | **FAIL** (−17.1 bps lower bound) |
| A2 | mean s_d at 1.5 × costs ≥ 0 | **FAIL** (−0.6 bps) |
| A3 | mean s_d > 0 in both halves | PASS |
| A4 | placebo CI contains 0 | PASS (the controls are fair) |

## 3. Secondary (reported, not decisive)

**Ranking.**
- IC 0.020 (t 3.2); the development IC was 0.056.
- AUC 0.508, accuracy 0.582, Brier 0.242.
- Hit rate 0.496, precision 0.406, recall 0.008.

**Range and volatility.**
- Range coverage 63.5 %; development was 78 %.
- Volatility rank IC 0.51; development was 0.66.

**Reading.**
- The model ranks 2020 open-to-close returns slightly better than chance.
- Its volatility forecast still works.
- Its picks did not beat the matched controls by enough to cover costs.
- The realised MDE (26 bps) is above the planned 17 bps because 2020 (COVID) was more volatile than the development window. The test could only detect a large edge.

## 4. What this means (pre-registered §6)

**NOT_ACCEPTED: Stage 4 is complete with a negative answer.**
- E5 is **not** used by Stage 5 before its forward look. Paper trading keeps the baseline strategies (`baseline_gap_fade`, `bench_c0`).
- The E5 forward test continues **unchanged**: the same model, 40 sessions and a single look.
  - 2026-10-26 was missed: the host was suspended through the 09:06 prediction, and a prediction after the 09:15 open is not allowed.
  - The look moves by one session, to about 2026-12-18.
- A forward ACCEPTED would conflict with this result. It would be read as weak evidence that needs a further confirmation period, not as permission for production use.
- E5.1 (refit) stays locked. E6 continues as a paper monitor (look about mid-April 2027).

## 5. Stage 4 completion summary (model card)

| Item | State |
|---|---|
| Data, features, labels, datasets | Built, versioned, PIT-checked (Stages 1–3; datasets v3/v4b/h2020; label-v2, label-h2020) |
| Models | E5 ensemble (LightGBM, random forest, ridge, LSTM, stacked): 7 outputs, frozen 2026-10-21 |
| Out-of-sample evaluation | E5-H on 2020: NOT_ACCEPTED (this file). Forward test: running, look ~2026-12-18 |
| Other candidates | E1 NOT ACCEPTED; E2 closed; E4 gap fade ACCEPTED-EXPLORATORY (slippage-fragile); E4b STOPPED; E6 paper monitor |
| Usable strategy for Stage 5 | **None proven.** Baselines only |
| Clean historical windows left | None for open-to-close. Every new candidate is tested forward (about 40 sessions, roughly 2 months) |

**Next candidates, each a new pre-registration and forward test:**
- E6 post-results drift (running);
- E5.1-style models with results, news and fundamentals features, once those have 120 sessions of history;
- a multi-day holding horizon instead of open-to-close.
