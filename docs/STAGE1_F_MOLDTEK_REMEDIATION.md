# Stage 1 F/S remediation: MOLDTECH and MOLDTKPAC (executed 2026-10-09)

**Approval:** "steps 1-4 MOLDTECH aur MOLDTKPAC ke liye chalao", following `docs/STAGE1_F_MOLDTEK_INVESTIGATION.md`.

**Backup before any write:** `var/backups/prajna_20261009T1415_moldtek_pre_ca_fix.dump` (sha256 `53d4a07c…`, verified).

No code, migration, D3 rule, feature, registry, Stage 4, cron, model or trading change was made.

## Vendor calls (4, as approved)

| # | Call | Run | Result |
|---|---|---|---|
| 1, 2 | `GET /v2/fundamentals/{INE835B01035, INE893J01029}/corporate-actions` | `25ffb100-88ba-47cf-8578-0412edec138f` (14:30:59 IST) | 5 events seen; 2 inserted, 3 already present (the dividends) |
| 3, 4 | historical 1D, 2026-10-01 → 10-08, `NSE_EQ|INE835B01035` / `NSE_EQ|INE893J01029` | `f7eb21e4-1eeb-4352-9f70-fa53767ddf37` / `6f6ef131-6cf8-42d9-99c3-c86422d83a8d` (14:31:29 IST) | COMPLETE, 0 anomalies; 1 bar inserted each (10-08); 8 CA_ADJUSTMENT observations |

No new TOTP login was needed; the token was valid.

## The event (from vendor evidence)

| | MOLDTECH (ca 4101) | MOLDTKPAC (ca 4102) |
|---|---|---|
| Type | **BONUS 1:1** ("Bonus issue of equity shares in the ratio of 1:1 of Rs. 2/-") | **BONUS 1:1** ("… of Rs. 5/-") |
| Announcement | 2026-08-26 | 2026-08-26 |
| Ex-date / record date | **2026-10-09** / 2026-10-09 | **2026-10-09** / 2026-10-09 |
| Factor (`factor_for`) | **EXACT 2** (BONUS_RATIO (a+b)/b) | **EXACT 2** |
| Knowability | KN-CA 2026-08-26 23:59:59 IST kept; observed (CA-OBSERVED) **2026-10-09 14:30:59 IST** | same; observed 14:30:59 IST |

This matches the investigation's assumption (ex-date 10-08 or 10-09). The vendor's 10-08 bar is therefore vendor-adjusted. It was stored from a payload dated 2026-10-09 (`VENDOR_ADJUSTED`).

## Records written

**`corporate_action`:** +2 rows (4101, 4102). The other 2,333 rows are identical (md5 `d2ccd195…` before and after).

**`ohlcv_bar` (per instrument):**
- +1 row (2026-10-08): MOLDTECH O 110.50 / C 104.98 / V 85,060; MOLDTKPAC O 335.00 / C 326.05 / V 147,900.
- The 1,681 existing rows are byte-identical (md5 `62aee57f…` and `f7c2cd78…`).

**`ohlcv_observation`:** +8 CA_ADJUSTMENT rows. They cover the stored bars of 10-01, 10-05, 10-06 and 10-07, explained by factor 2 (`ca_ids` [4101] / [4102], half-even to tick 0.01 / 0.05). The stored bars are untouched.

**`ohlcv_payload_basis`:** +2 rows (the 2026-10-09 payloads, VENDOR_ADJUSTED, basis 2026-10-09), written by the ingest itself. `derive price-basis`: 0 missing, 0 inserted (run twice: idempotent).

**`ca_factor`:**
- `derive ca-factors` processed 2,338 events.
- New rows 4101 and 4102: EXACT 2, **APPLIED** (4 CA_ADJUSTMENT observations each).

**Outside the two instruments (reported, not reverted).** `derive ca-factors` is a global upsert. It rewrites `derived_at` / `run_id` of every row, as the 06:40 daily maintenance does. Compared row by row with the backup, the **values changed for exactly 2 other actions**:

| Action | Change | Cause |
|---|---|---|
| 4096 BLSE split | `vendor_evidence.ca_adjustment_observations` 7 → 9; `vendor_applied` stays APPLIED | 2 observations recorded by this morning's ingest, after today's 06:40 derive |
| 4099 `NSE_EQ|INE24OJ01029` split 1:5 (ex 2026-10-08) | `vendor_applied` UNKNOWN → **APPLIED** ("the stored series is smooth across the ex-date", ratio 1.0027) | its ex-day bar was stored by the 08:03 ingest, after the 06:40 derive |

Both are what the next scheduled derive (2026-10-10 06:40) would have produced from the same data. They exceed the "two instruments only" safeguard because the approved command has no per-instrument scope. They were not reverted: a revert would be a manual edit, which is not approved. The backup holds the previous rows if you want them restored.

**Everything else is unchanged:**
- 1D bars of all other instruments up to 10-08: 3,711,450 rows, same hash.
- Their observations: 1,792.
- `feature_value`: 801,434 rows, `b45381f3…`.
- Labels: 7,077,591 rows, `15f0cb45…`.
- All Stage 4 training datasets: per-session fingerprints identical.
- `stage3_event`: 36.
- Crontab sha `dbc5b41b…`; flags unchanged.

## Checks

| Check | Result |
|---|---|
| PIT: `pit.corporate_actions` BONUS before vs after the fetch instant | invisible at 14:30:00 IST; visible from 14:31:00 (both) — **PASS** |
| Adjustment as of now (`pit.bars_adjusted`, since 2026-09-01) | 25 ADJUSTED (all pre-ex bars, factor 2) + 1 AS_STORED (10-08, vendor-adjusted payload); 0 RECONSTRUCTED; 0 LOW after the horizon; largest daily change 5.0% / 6.3% (no jump) — **PASS** |
| Adjusted closes at the ex boundary | MOLDTECH 10-07 110.495 → 10-08 104.98; MOLDTKPAC 333.60 → 326.05 |
| Full history | 1,425 LOW bars each, before the 2025-09-24 corporate-action horizon, as for every instrument — expected |
| Determinism: 2026-10-08 PRE_SESSION / PRE_OPEN recomputed for both | 114 / 122 values compared, **0 differences** (the bonus was not observable at those `as_of`s) — **PASS** |
| Idempotency, derived | `derive price-basis` rerun: 0 inserted — **PASS** |
| Idempotency, ingestion | **NOT RUN**: a rerun of step 2 needs 2 more vendor calls than approved. The structural guard (identical bars are a no-op; revisions become observations) is covered by `tests/integration/test_revision_ingest.py` |
| Regression (targeted) | `test_payload_basis_f3`, `test_ca_observed`, `test_revision_ingest`, `test_bars_adjusted`, `test_corporate_action_ingest`, `test_price_basis_revision`: **45 passed** |
| Full suite | **1336 passed, 0 failed** (4 live tests deselected) |

## Gates (actual verdicts)

| Gate | Verdict |
|---|---|
| `prajna acceptance stage1` | **COMPLETE**: F PASS, S DEFERRED (BACKFILL-DEFER), failing [] |
| `prajna acceptance stage2 --run-tests` | **PASS** (A–P 16/16) |
| `prajna acceptance stage3 --run-tests` | **M PASS** (Stage 1 COMPLETE and Stage 2 PASS, evaluated now); A–D, F–O PASS; **E PENDING**; level **TESTED** (it was DRY-RUN READY this morning, with E PASS) |
| `prajna stage3 locks` (read-only) | **RUN: UNLOCKED** (7/7) |

**Why E is PENDING.** E needs at least one bar adjusted by a knowable action in its sample. The gate picks the instruments with the newest factors (now MOLDTECH, MOLDTKPAC, `NSE_EQ|INE24OJ01029`) and evaluates the latest session's snapshot (2026-10-09, `as_of` 08:59:59 IST).
- The two bonuses were observed at 14:30:59, so under CA-OBSERVED they are correctly **not** knowable at that `as_of`.
- INE24OJ01029's split is vendor-baked, so nothing is adjusted.
- The gate was not changed.
- INFERRED: at the next session (2026-10-12) the bonus is observable before `as_of`, the pre-ex bars adjust (verified as of now: 25 bars each), and E should return to PASS. Not verified until that gate run.

## Remaining

- **The next scheduled Stage 3 runs:** 2026-10-12 09:00:30 and 09:22. The lock is unlocked now. Stage 1 is re-evaluated at run time.
- **Daily corporate-action refresh: out of scope.** Without it, the next split or bonus can block Stage 1 the same way.
- **The 2026-10-08 label (not built yet):** the bonus has ex-date 10-09, so the 10-08 label is unaffected. A 10-09 label must use the factor, and `bars_adjusted` now provides it.
