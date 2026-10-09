# Stage 1 F/S blocker: MOLDTECH and MOLDTKPAC (read-only investigation, 2026-10-09)

**Scope.** No code, migrations, database writes, ingestion, cron changes or recomputation were made. Evidence is in `audit/evidence/stage1_f_moldtek_investigation.json`.

**Context.** CA-OBSERVED (`8bad2f1`) and F3-PAYLOAD-BASIS (`b1bb105`) are untouched; the registry is `features-v4`.

## Findings

| # | Finding | Result | Evidence |
|---|---|---|---|
| 1 | Stage 1 F fails only because the latest 1D runs of MOLDTECH (`NSE_EQ|INE835B01035`, id 2849, tick 0.01) and MOLDTKPAC (`NSE_EQ|INE893J01029`, id 2975, tick 0.05) are FAILED. S fails only because F fails (G/I/J are DEFERRED). | **FAIL** (confirmed) | `app/acceptance/stage1.py:389-403`: F = depth covered AND no ACTIVE instrument whose latest COMMIT 1D run is FAILED with a FAIL anomaly. `:607-613`: S = PASS / DEFERRED only if F is PASS. Depth: 3,554 of 3,554 instruments covered. |
| 2 | Each failed run (2026-10-09 08:03 IST, window 10-01 → 10-08) was rolled back (0 rows written) after 4 UNEXPLAINED revisions: the stored bars of 10-01, 10-05, 10-06 and 10-07. | CONFIRMED | `ingest_run` FAILED, `rows_written` 0; 4 FAIL anomalies per instrument, "D3: UNEXPLAINED revisions fail". |
| 3 | The revisions are **exactly** a factor-2 corporate-action adjustment: prices / 2, rounded half-even to the tick; volume × 2. Example: MOLDTECH 10-07 close 220.99 → 110.50, volume 64,307 → 128,614. | CONFIRMED | `contracts/revision.classify` run as a pure function on the 8 anomalies with a hypothetical EXACT factor-2 event: **8 of 8 CA_ADJUSTMENT**, for ex-date 10-08 or 10-09. |
| 4 | **No SPLIT or BONUS is stored** for either instrument: only dividends (ex 2026-09-11; MOLDTKPAC also 2026-04-24), all fetched 2026-09-24. So the classifier has no event and the revision is UNEXPLAINED. Corporate actions are fetched only weekly (Saturday 10:00) or for new listings. | CONFIRMED | `corporate_action`, `ca_factor` (3 dividend rows, UNSUPPORTED / N/A); crontab; `ops/runbooks/daily.sh:111,120`. |
| 5 | **Every stored bar predates the vendor's adjustment.** One bulk payload per instrument (2020-01-01 → 09-22, fetched 2026-09-23 20:30 IST) plus one single-day payload per session (fetched the next morning at 08:03; the last one 2026-10-08 08:03, holding 10-07). The first adjusted payload is 2026-10-09 08:03. The adjustment is therefore between 10-08 08:03 and 10-09 08:03 IST. | CONFIRMED for the stored values; the adjustment instant is INFERRED within that window | `ohlcv_bar` payload / `fetched_at` history; archived responses `var/archive/UPSTOX_REST_V3/2026/10/09/1f9acf59….json.gz` (MOLDTECH) and `dc0ab8cb….json.gz` (MOLDTKPAC). |
| 6 | The vendor's 10-08 bar is already at the new level (MOLDTECH open 110.50, close 104.98; MOLDTKPAC open 335.00, close 326.05). | CONFIRMED (vendor data) | archived responses |
| 7 | Event type (bonus 1:1 or split 1:2) and the exact ex-date (10-08 or 10-09) | **UNPROVEN**: not in Prajna's data. Only a corporate-action fetch can establish them. | — |
| 8 | Do the past Stage 3 values for these two instruments need correcting? No. They describe sessions before the ex-date with unadjusted bars, which is correct for those `as_of`s. | **PASS** (INFERRED from 5 + 7: ex-date ≥ 10-08) | `feature_value`: 2026-09-29 and 10-08, 51–62 rows per snapshot each. |
| 9 | Stage 4 rows for these two instruments (v2-strict 1,200 each; v2-asif 14,848 each; labels 2,295 each, up to 2026-10-07): all for sessions before the ex-date, so unaffected. The 2026-10-08 label (not yet built) would show a false −50% `ret_cc` without the factor, if the ex-date is 10-08. | PASS for the stored rows; RISK for a future 10-08 label | `training_feature_value`, `training_label` counts |

## Why it fails, in one line

The vendor adjusted the history for a factor-2 event that Prajna has not stored yet. Because of D3, an unexplained revision fails the run and nothing is written.

## Smallest safe remediation (needs your approval: writes plus vendor calls)

**Both a fresh corporate-action fetch and a daily-bar re-ingestion are required, in this order:**

1. **Corporate actions, these 2 ISINs only** (2 vendor calls):
   ```
   prajna ingest corporate-actions --isin INE835B01035 --isin INE893J01029 --commit
   ```
   - **Check before going on:** a BONUS or SPLIT row per instrument, with an ex-date of 10-08 or 10-09 and `factor_for` = EXACT 2.
   - **If the vendor does not list it yet: STOP.** The blocker stays until it does. The data must never be patched by hand.
2. **Daily bars, these 2 keys** (2 vendor calls):
   ```
   prajna ingest candles --timeframe 1d --key NSE_EQ|INE835B01035 --key NSE_EQ|INE893J01029 --from 2026-10-01 --to 2026-10-08 --commit
   ```
   - Expected: run COMPLETE, 4 CA_ADJUSTMENT observations per instrument (the stored bars are never touched), and the 10-08 bar stored.
3. **Derived data** (no vendor call; it also runs daily at 06:40):
   ```
   prajna derive price-basis --commit
   prajna derive ca-factors --commit
   ```
   - It must run **after** step 2, so that `vendor_applied` becomes APPLIED from the observations (it is an upsert). Before step 2 it would be UNKNOWN, and those bars would be refused as LOW confidence.
   - With F3-PAYLOAD-BASIS:
     - payloads fetched before the ex-date (basis date < ex) are not baked → adjusted;
     - the payload fetched on the ex-date morning (if ex = 10-08) has re-served evidence → raw → adjusted.
4. **Gates** (expected results):
   ```
   prajna acceptance stage1                  # F PASS, S DEFERRED, overall COMPLETE
   prajna acceptance stage2 --run-tests      # PASS (always --run-tests: without it the report becomes NOT PASSED)
   prajna acceptance stage3 --run-tests      # M PASS (others unchanged)
   ```

**Not needed and not proposed:**
- changing D3;
- hand-editing data;
- any change to features, the registry or Stage 4;
- the separate daily corporate-action refresh (a cron change for its own approval; it would have prevented this).

## Tests and checks for the remediation

- **Point in time:**
  - After step 1, `pit.corporate_actions` shows the action only for `as_of > fetched_at` (CA-OBSERVED).
  - A recompute of the 2026-10-08 snapshot for both instruments is unchanged: the action was not observed before that `as_of`.
- **Adjustment:** `pit.bars_adjusted` (as of now):
  - all pre-ex bars ADJUSTED / 2;
  - no jump at the ex-date (|change| < 15%);
  - 0 RECONSTRUCTED;
  - 0 LOW confidence after the horizon.
- **Idempotency:**
  - rerunning step 2 inserts 0 bars and records no new FAIL;
  - rerunning step 3 changes nothing.
- **Determinism:** `feature_value` and Stage 4 fingerprints are unchanged (they are not written by any step).
- **Regression:** existing suites `tests/stage2/test_payload_basis_f3.py`, `tests/stage2/test_ca_observed.py`, `tests/integration/test_revision_ingest.py` and `tests/stage2/test_bars_adjusted.py`, plus the full suite before the gates.

## Risks

- **The vendor CA feed may not list the event yet.** It lists actions around the ex-date; for BLSE it was listed on the ex-date. Then the blocker persists, and scheduled Stage 3 stays refused.
- **The step 2 window must cover the stored bars the vendor revised.** 10-01 → 10-08 matches today's run.
- **A Monday 07:00 scheduled run without step 1 fails again.** With step 1 done on its own, Monday's scheduled 1D run would self-heal before 09:00. Step 2 is proposed now so the outcome is verified rather than assumed.

## Approval needed next

**"Run steps 1–4 for MOLDTECH and MOLDTKPAC only"** (4 vendor calls and production writes to `corporate_action`, `ohlcv_bar`, `ohlcv_observation`, `ohlcv_payload_basis` and `ca_factor`, through the normal ingest paths). This uses today's single-login allowance if a token login is needed. I stop and report if step 1 finds no SPLIT or BONUS.
