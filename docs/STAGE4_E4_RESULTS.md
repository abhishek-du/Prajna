# Stage 4 E4a: results of the single test look (2026-10-16)

**Label:** EXPLORATORY research result. **No profitability claim. PAPER ONLY.**

## Run

| Item | Value |
|---|---|
| Look | Single pre-registered look, 2026-10-16 21:21–21:24 IST |
| Config | sha `8725d023b76f…` (confirmation `E4-8725d023b76f`) |
| Output | `backend/var/stage4/experiments/e4/test_8725d023b76f.json` (git-ignored) |
| Calibration | C2 (paired sign-flip interval), `null_calibration_c2.json`, sha `d470bd97…`, code `4af51229b481` |
| Calibration result | ADEQUATE in every world type. `ci_excludes_0`: iid 2.1% / 2.9%, factor 2.5% / 2.6%, all Wilson intervals contain 2.5%. `accepted`: ≤ 1.1% everywhere |
| TEST window | 2021-01-01..2026-09-30, 1,425 sessions |
| Primary population | Excludes 2026-07-22..09-30 (the disclosed paper-replay view). The full window is reported as a sensitivity |
| Design | K = 10 at ₹10 L, open → close MIS, half-spread 5 bps, MIS charges, matched control C2, placebo, stress 1.5× |

## Results

**s_d = picks' gross − costs − matched control's gross, per session (bps).**

| Predictor | Status | Mean | 97.5% CI (sign-flip) | n | NW t | Placebo | Stress (1.5× costs) | Positive years |
|---|---|---|---|---|---|---|---|---|
| **gap fade** | **ACCEPTED-EXPLORATORY** (A1–A4 PASS) | **+27.2** | **[+19.1, +35.3]** | 1,367 | 6.6 | +1.4 [−4.0, +6.8] (passes) | +18.1 | 6/6 |
| gap-and-go | FAIL (A1–A3 FAIL) | −26.1 | [−34.0, −18.1] | 1,365 | −7.2 | −0.8 [−6.4, +4.8] | −35.2 | 1/6 |

**Gap fade by year (bps):** 2021 +52.8 · 2022 +20.6 · 2023 +18.2 · 2024 +38.7 · 2025 +14.7 · 2026 +12.4.

**Sensitivities for gap fade:**

| Case | Mean (bps) | 97.5% CI |
|---|---|---|
| E1 period excluded | +28.5 | [+20.0, +37.0] |
| Full window, including the paper-view sessions | +27.1 | [+19.2, +35.0] |
| K = 5 | +48.5 | [+35.8, +61.2] |
| **Slippage 5 bps per side** | **+17.2** | **[+9.1, +25.3]** |
| **Slippage 10 bps per side** | **+7.2** | **[−0.9, +15.3]: not significant** |
| **Slippage 20 bps per side** | **−12.9** | **[−21.0, −4.8]: loses** |

**Diagnostics (gap fade, mean per session):**
- picks' gross: +59.1 bps;
- matched-control gross: +13.7 bps;
- random universe (C0) gross: −14.8 bps;
- costs: 18.1 bps;
- 9.8 picks per session; 0.18 masked as locked days; universe of 497.

**Gap-and-go** is the mirror image: buying up-gaps loses.

## What this does and does not show

- **It does show** that inside the pre-registered design, buying the 10 largest down-gaps of the top-500 liquid NSE names at the official open and selling at the close beat matched controls. It did so after modelled MIS costs, in every year 2021–2026, with a calibrated interval excluding zero and a clean placebo.
- **The main risk is execution at the open.**
  - The rule reads the official open of the day (the pre-open auction price) and buys at that same price.
  - Live, orders for the auction close at 09:08 on the *indicative* price. After 09:15, the continuous market may already have moved away from the open.
  - The slippage sensitivity is the key number: the edge halves at 5 bps per side, is not significant at 10, and is negative at 20.
  - Realistic entry costs therefore decide whether this is tradable.
- **It does not show** a live, tradable profit. Nothing here changes the paper-only rule.

## Next steps (proposed; each needs the user's decision)

1. **Execution realism** (the first priority):
   - measure, on the stored pre-open data (since 2026-09-24) and the 1m bars (last 92 days), how far the IEP at 09:07 and the 09:15–09:16 prices sit from the official open for the names gap fade picks;
   - re-estimate the edge with that measured entry.
2. **Forward paper record:** `baseline_gap_fade` is arm P of this rule. The daily paper job (from 2026-10-16, after every TEST window) is its out-of-sample check. Its cron line is not yet installed.
3. **E4b** (15m data, ~22 Oct): a stop/target exit, with the inference fixed in advance using this C2 method.

## Execution realism, first measurement (2026-10-17)

**Run:**
- `backend/ops/measure/e4_execution_realism.py` (read-only); output `var/stage4/experiments/e4/execution_realism.json`.
- 15 sessions (2026-09-24..10-15) with pre-open and 1m data; the gap-fade picks are arm P, taken from the recorded paper target lists. That gives 150 picks.
- Distances are measured on all sessions, because they are a cost measurement. Returns are computed only for sessions on or after 2026-10-01, outside the TEST window.

**Distance from the official price, in bps. A positive value is worse for the trader.**

| Entry or exit | Mean | Median | p75 | p90 |
|---|---|---|---|---|
| IEP at 09:07 vs the official open (an auction order) | +0.5 | 0.0 | +18 | +74 |
| 09:15 1m close vs the open (a market order right after the open) | −3.0 | 0.0 | +61 | +117 |
| VWAP 09:15–09:19 vs the open | −4.0 | +1.7 | +54 | +125 |
| 15:15 1m close vs the official close (MIS square-off) | −2.9 | 0.0 | +14 | +40 |
| 15:20 1m close vs the official close | −1.3 | 0.0 | +15 | +39 |

**Reading:**
- **Entry through the pre-open auction fills at the official open by construction.** An auction trade crosses no bid-ask spread, so the 5 bps half-spread in E4 is conservative for this path.
- **A market order after 09:15 shows no systematic penalty on average** (mean −3 bps), but the dispersion is large: p90 is about +120 bps.
- **An exit at 15:15–15:20 sits about 0 on average** against the official close.
- **The real gap is the selection.** Live, the picks must come from the 09:07 IEP, not the official open. The IEP-based top 10 overlaps the open-based top 10 by only **7.3 of 10** names.
- On the 10 sessions after the TEST window, the open-based list grossed a mean of +13 bps and the IEP-based list about −1 bps. With a session SD of about 130 bps, **10 sessions cannot tell them apart**.
- **This sample is small:** 15 sessions, 150 picks, and a standard error of the mean of about 8–10 bps.

**Consequence:** a live-realistic version needs the selection on the 09:07 IEP, entry in the auction at the official open, and exit at the close or at 15:20. Its edge can only be learned **forward**, because IEP data exists only from 2026-09-24. The proposal is to add it as a forward paper strategy, `gap_fade_iep`, next to `baseline_gap_fade`.
