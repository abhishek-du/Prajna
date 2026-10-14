# Stage 4 E2: proposed protocol changes (FOR REVIEW, nothing adopted)

**Status:** PROPOSED 2026-10-14 by the Stage 4 audit (`docs/STAGE4_COMPLETION_AUDIT.md`).
- **Decisions (user, 2026-10-14, in principle):** PC-1 **a**; PC-2 **a** (EXPLORATORY + forward confirmation design); PC-3 keep ₹10 L primary and ₹50 L / ₹1 Cr / ₹5 Cr sensitivities, and prepare a separately versioned **k20** configuration (20 picks per tranche) without replacing the original; PC-4 **approved** (recompute and freeze).
- **Implementation:** `docs/STAGE4_E2_AMENDMENT_2_PROPOSED.md`, which is proposed and not adopted. Neither configuration has been run.
- `docs/STAGE4_E2_PREREGISTRATION.md` is **not** changed by this document. Each item needs an explicit decision before E2 labels, splits or the runner are built.
- No E2 result exists, so none of these proposals is informed by an outcome.

## PC-1 (critical): the primary "net excess vs C2" cancels the costs it is meant to test

**Current text:**
- §5: the C2 tranche book uses "identical accounting and **identical costs**".
- §7: the primary series is "the daily net excess of the P-book over the C2-book".
- A1 and A2 apply to that series.

**Problem:**
- Both books pay costs, so the primary metric is approximately `gross excess − (cost_P − cost_C2)`. The question "does the edge survive realistic costs" is never asked: a book can pass A1 and A2 while losing money net of costs.
- **Worse, it rewards turnover differences, not prediction.** C2 is re-drawn at random every formation day, so it rarely nets trades. A persistent predictor (P2's daily name turnover was 14.5% in E1) nets many trades. The cost difference then **adds** to the excess.
- **A2 at 1.5× costs** can then *raise* the metric instead of stressing it.
- **Demonstrated** (`TestProtocolIssues::test_identical_costs_on_c2_credit_lower_turnover_not_an_edge`, synthetic):
  - zero gross edge at ₹1 Cr;
  - "net excess vs C2, both costed" = **+7.1 bps per day** with the API rates, and **+8.6** with the approved DP charge added;
  - the P book itself loses 0.3 bps per day net.
- **E1 did not have this problem:** its A2 was `gross excess − round-trip cost` (`e1.acceptance`), i.e. the control was **not** charged.

**Options:**

| | Primary series | Comment |
|---|---|---|
| **a (recommended)** | `P_net − C2_gross`: the P book pays the approved costs, the control is an untraded benchmark | Same logic as E1's A2: the selection edge must exceed the cost of harvesting it. Conservative. |
| b | Keep "both costed" as the primary, and add a gate A7: `P_net` absolute mean CI lower bound > 0 | Keeps the matched comparison, adds an absolute profitability gate. Two primaries need a multiplicity decision. |
| c | Keep as written | Not recommended: A1 and A2 would not test costs. |

**Under every option, report:**
- `P_gross − C2_gross`;
- `P_net − C2_gross`;
- `P_net − C2_net`;
- `P_net` absolute;
- `C0`.

**Code impact:**
- The runner is not written yet.
- `e2.net_series`, `cost_summary` and `acceptance` already support every option, because the caller decides which series to pass.

## PC-2 (major): 92 of the 100 E2 TEST sessions were already looked at in E1

- **Overlap:** the E2 folds (`wf-exp-120-20-20-e5` on the 257 as-if-live sessions) put TEST at **2026-05-08 → 2026-09-29**. The E1 TEST look covered 2026-04-27 → 09-17, so **92 of the 100 E2 TEST sessions** overlap.
- **The hypothesis came from that look:** E2 itself was motivated by an E1 observation, "P2 picks persist, which only matters to a multi-session design" (`docs/STAGE4_E1_RESULTS_P2.md`).
- **Consequence:** an E2 PASS on those sessions would be a second look at data that suggested the hypothesis. That is a garden-of-forking-paths risk, and it is not an independent confirmation.

**Options:**

| | Treatment | Comment |
|---|---|---|
| **a (recommended)** | Run E2 as written, but label it **EXPLORATORY**. A PASS only makes the candidate eligible for a confirmatory test on sessions after 2026-10-09: forward, as-if-live then STRICT, from the daily pipeline. | Honest. It costs time, not data. |
| b | Restrict the E2 TEST to sessions after 2026-09-17 | Only about 12 labelled sessions today (the last needs T+5 ≤ 2026-10-09). Far too few for A1. |
| c | Treat E2 as confirmatory | Not recommended |

## PC-3 (decision support): at the approved primary capital, the design is uneconomic by construction

- **C1 primary ₹10 L:** 100 names × 5 tranches gives orders of about **₹2,000**.
  - Flat brokerage and DP make that **376 bps per round trip**, or **38.6–77.3 bps per day** of book cost (prereg §6).
  - E1's best gross matched excess was **5–8 bps per day**.
- **Expected verdict:** under PC-1a, A1 is FAIL at ₹10 L unless the 5-session effect is about 5–10× E1's. The ₹5 Cr sensitivity (3.9–7.9 bps per day) is the only book where costs are comparable to the E1 edge.
- **The fix would be a design change:** a smaller pick count, e.g. the top 20 names per tranche, gives ₹10 k orders at ₹10 L. That would be a **new preregistered configuration** (universe and selection change); it is not proposed here as a silent change.
- **Decision requested:** proceed with the approved C1 knowing the likely outcome, or pre-register a capital-appropriate selection size **before** any look.

## PC-4 (minor, recorded): C3 measured spreads barely cover the TEST period

- The pre-open capture starts 2026-09-24, so at most 4 of the 100 TEST sessions have a measured opening spread.
- The approved fallback (5 bps proxy, coverage reported) applies to ≥ 96% of TEST trades. The proxy comes from **one** measured day (2026-10-12) of the top 500.
- **Proposal:** before the run, recompute the proxy from every captured session to date, and freeze it with its date range in the configuration. A 13.9 bps first-quote sensitivity is already reported.

## Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| PC-1 | Primary series and cost treatment of C2 | a: `P_net − C2_gross` |
| PC-2 | Status of an E2 result on the E1-overlapping period | a: EXPLORATORY; confirm forward |
| PC-3 | Proceed at ₹10 L, or pre-register a capital-appropriate selection size first | Your decision; no silent change |
| PC-4 | Re-measure and freeze the half-spread proxy before the run | Yes |
