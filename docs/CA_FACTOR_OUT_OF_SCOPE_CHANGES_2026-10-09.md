# Out-of-scope `ca_factor` changes, 2026-10-09: documented, not reverted

**How it happened.** The approved MOLDTECH / MOLDTKPAC remediation ran `prajna derive ca-factors` (run `24575d9d-55fb-4072-9801-59c8c746b536`, 14:31:43 IST).
- That command is a **global upsert**: it re-derives every action with the data present at that moment.
- The previous values came from the scheduled maintenance derive at 06:40:05 IST (run `e8f6d377-06b7-49bd-a3fa-173937265a65`).
- Comparing row by row against the backup (`var/backups/prajna_20261009T1415_moldtek_pre_ca_fix.dump`, sha256 verified), the **values changed for exactly 2 actions outside the two approved instruments**. All other rows changed only `derived_at` / `run_id`, as every daily derive does.

| ca_id | Instrument / action | Before (06:40 derive) | After (14:31 derive) | Why (VERIFIED) | Impact |
|---|---|---|---|---|---|
| 4096 | BLSE `NSE_EQ|INE0NLT01028`, split ex 2026-10-06, factor 2 | APPLIED; `ca_adjustment_observations` 7 | APPLIED; `ca_adjustment_observations` **9** | 2 CA_ADJUSTMENT observations (bars 10-01, 10-05) fetched 2026-10-09 07:02:24 IST, after the 06:40 derive | none: `vendor_applied` unchanged; with F3-PAYLOAD-BASIS the BLSE payloads are raw either way |
| 4099 | `NSE_EQ|INE24OJ01029`, split ex 2026-10-08, face value 10 → 2, factor 5 | **UNKNOWN** ("no stored bar on one side of the ex-date") | **APPLIED** ("the stored series is smooth across the ex-date", ratio 1.0027) | the ex-day bar (10-08, open 259.70) was stored 2026-10-09 07:32:12 IST, after the 06:40 derive; prev close 260.40 | `pit.bars_adjusted`: the 183 pre-ex vendor-adjusted bars (one payload, basis = the ex-date) were LOW-refused under UNKNOWN; now all 184 bars are AS_STORED and usable |

**Correctness.** For 4099, an unadjusted series would step by about 5× at the ex-date; the observed step is 0.27%. The vendor history was therefore already adjusted when it was fetched on the ex-date morning. That is the opposite of BLSE, whose ex-date morning payload was raw. Evidence-based classification handles both cases.

**Not changed:** stored `feature_value` (INE24OJ01029: 120 rows) and Stage 4 rows (v1-strict 120, v2-strict 120, v2-asif 10,556). Future Stage 3 runs use the now-usable bars.

**INFERRED:** the next scheduled derive (2026-10-10 06:40) would compute the same values from the same data.

**Not reverted,** as instructed. A revert would restore the two rows from the backup: a manual write that needs explicit approval.

**Root cause for the future.** `derive ca-factors` has no per-instrument scope. A scoped option would be a code change (not proposed here).

Machine-readable record, including the full before rows from the backup: `audit/evidence/ca_factor_out_of_scope_2026-10-09.json`.
