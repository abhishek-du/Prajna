# Stages 1–3: remaining work, quantified (2026-10-13; §3.3 updated 2026-10-14)

**Purpose:** what still separates Stages 1–3 from their full agreed scope.
- Each item lists its exact scope, cost, risk and the approval it needs.
- The acceptance gates are unchanged: Stage 1 COMPLETE (2026-10-12), Stage 2 PASS, Stage 3 COMPLETE (2026-10-13). "COMPLETE" there means the agreed criteria pass. It does not mean every diagram item exists.
- **Evidence:** read-only production queries on 2026-10-13. Nothing in this document was executed against production, except the Stage 3 gap backfill (§3.3), which was approved and run on 2026-10-13.

## Stage 1

### 1.1 Historical intraday backfill: checks G, I, J and S (DEFERRED by BACKFILL-DEFER, 2026-09-25)

| Stage | Depth | Instrument-sessions | Requests (upper bound) | New bars (about) | DB (about) |
|---|---|---|---|---|---|
| 1h (J) | from 2022-01 | 2,978,558 | 71,500 (20 quarter windows × 3,575) | 20.9 M | 10.6 GB |
| 1m (G) | last 6 months (from 2026-04-13) | 417,960 | 25,025 (7 month windows × 3,575) | 143 M | 73 GB |
| 15m (I) | from 2022-01 | 2,978,558 | 207,350 (58 month windows × 3,575) | 74.5 M | 37.8 GB |
| **Total** | | | **about 304 k** | **about 238 M** | **about 121 GB** + about 2.6 GB of archive |

**How these were measured:**
- Requests come from `contracts.candles.plan_windows` (Upstox's earliest date is 2022-01-01).
- Instrument-sessions are bounded by each instrument's first daily bar.
- Bytes come from production `ohlcv_bar`: 508 B per row including indexes, and about 11 B per bar of gzip archive.

**Disk:** 176 GB free now, so the full backfill would leave about 55 GB.
- That is **below the runbook's 60 GB guard**, so the run would stop itself near the end of 15m.
- Running 1h and 1m only leaves about 92 GB.

**Rate limit and runtime:** Upstox allows 2,000 requests per 30 minutes per user.
- At fraction 0.5: about 1,000 per 30 minutes, i.e. about 2,000 per hour.
- 1h: about 36 h. 1m: about 12.5 h. 15m: about 104 h. Total about 150 h of eligible windows.
- `backfill.sh` refuses 06:50–16:00 on trading days, which leaves about 6.5 h per weeknight plus weekends.
- So the full backfill takes **about 3–4 weeks of nights**, and 1h + 1m alone about 1 week.

**Machinery (exists and is tested):**
- `ops/runbooks/backfill.sh`: resumable stream checkpoints, idempotent inserts, the candles lock, the overrun guard, one re-login, 429 and auth stops.
- **Fixed today** (`9293f04`): the 60 GB disk guard used to be checked only *between* stages. It now also stops a running stage, resumably.

**Rollback:** the inserts only add rows. Rows can be identified by `run_id` per stage, and existing bars are never touched (duplicates are no-ops).

**Proposed first approval:** the 1h stage only, then 1m. Review disk and quota after each. Leave 15m until a storage plan exists.

### 1.2 `share_holdings` classifier defect: FIXED (`dc4b925`)

- **Defect:** the query looked for `'shareholding'`, but the parser stores `'share_holdings'`.
- **Impact:** 0 of 3,593 classifications change. It was latent.
- **Deployed by the next 06:30 refresh:** classes unchanged, `method_version` becomes `secclass-v2`.
- **Regression test:** fails on the old query, passes now.

### 1.3 Fundamentals cadence (monthly by decision; not changed)

- **Now:** cron `0 11 1 * *` runs `daily.sh monthly`, i.e. `ingest fundamentals` for about 3,560 ISINs × 12 endpoints, **about 42.7 k requests**.
  - New listings get one fetch on their first day.
  - The 2026-10-12 one-off re-fetch covered 4 new listings.
- **Daily full refresh:** about 42.7 k requests per day, about 21 h at fraction 0.5, which is not feasible beside the daily jobs.
- **Smallest useful change (proposed, not implemented):** an event-driven refresh.
  - The trigger: NSE announcements already ingested in category *Outcome of Board Meeting*. There were 240 in the last 30 days, about 11 per trading day off-season and several hundred per day in results season.
  - The refresh: re-fetch only those ISINs the next morning, at about 12 requests each.
  - Cost: about 130 requests per day off-season, about 3–6 k in season.
  - It needs your approval (a cadence change) and a mapping test from announcement symbol to ISIN.

### 1.4 Other Stage 1 items

| Item | Status | Decision |
|---|---|---|
| H: 5m candles | OUT_OF_SCOPE (D2-5m) | user 2026-09-24 |
| L: all-day WebSocket persistence | OUT_OF_SCOPE (D5, Stage 7) | user |
| 12 Oct 1m for 2 ETFs | **Retried today:** 750 bars, 0 duplicates | done |

## Stage 2

All 16 criteria PASS (daily with tests). Nothing remains in scope.

## Stage 3

### 3.1 Feature coverage

- **Registry:** 104 features registered and implemented; 31 diagram items (19 IMPLEMENTED, 6 PARTIAL, 4 UNSUPPORTED, 2 UNKNOWN). The reasons are in `app/features/registry.py` `DIAGRAM`.
- **Measured:** the value coverage of the 2026-10-13 production rows.

| Class | Features or items | Evidence and realistic source |
|---|---|---|
| IMPLEMENTED_AND_VALIDATED | 98 features: values present, reasons valid, PIT 0 violations | Acceptance A–O |
| **FAILED_VALIDATION (source never supplies it)** | `ca_days_to_any`, `ca_days_to_dividend`, `ca_days_to_bonus`, `ca_days_to_split`: **0 values ever** (all MISSING_INPUT) | Across all 2,344 corporate-action events, the vendor never listed one before its ex-date (max ex-date minus first fetch = 0). A "days to the next action" feature cannot be computed from Upstox. A realistic source is NSE announcements (board-meeting and record-date intimations, already ingested), but that needs a parser and point-in-time tests. Proposal: mark these UNSUPPORTED_SOURCE in the registry. That is a registry change, so it needs approval. |
| **UNSUPPORTED_SOURCE (vendor data malformed)** | `revenue_yoy_q`, `pat_yoy_q`: 2–3 values of 3,561 | The vendor's "quarterly" income statement returns **annual** periods (e.g. RELIANCE: Mar 2023–Mar 2026). The code correctly refuses them as MALFORMED_INPUT. No other approved source exists. |
| PARTIAL | Support/resistance; bid-ask spread (all-day); debt levels; news sentiment; pre-open gap; pre-open events | As registered |
| UNSUPPORTED_SOURCE | Earnings surprises, analyst upgrades and downgrades: no source. Earnings dates: see the NSE-announcement route above. All-day order book: Stage 7. | Never fabricated |
| UNKNOWN (definition needed) | Market regime; sector/market events | A modelling decision, needs approval |

### 3.2 PRE_OPEN timing

- **Today:** finished 09:51:33.
- **Cause:** stale planner statistics. They were refreshed on 12 Oct, before 13 Oct's 410 k new rows, so the per-instrument query used an index that scans the whole session: 842 s against about 260 s.
- **Fix:** `97fe58e` runs ANALYZE after the replay. It is deployed via `main` from 14 Oct and not yet verified in production.
- **Design limit, not changed:** option B waits for the full capture (to 09:20) and its replay (about 12 minutes), so PRE_OPEN cannot be ready before about 09:36. A pre-09:15 PRE_OPEN would need a different capture/replay design, which needs a decision.

### 3.3 Feature backfill: DONE 2026-10-13 (approved; `.env` flag still `false`)

- **Production gap closed:** the 7 trading sessions without features since go-live now have both snapshots.
  - 2026-09-30, 10-01, 10-05, 10-06, 10-07, 10-09 and 10-12: 206,571 PRE_SESSION + 220,815 PRE_OPEN rows each, all under features-v4 (`6f998a76`).
  - 2026-09-29 (`9061d85b`) and 2026-10-08 (`dd696ca6`) keep their original registries. 10-08 was outside both ranges and would have been refused anyway (`ac3cbb2`, RegistryConflict).
  - `feature_value` now holds **4,220,522 rows over 10 sessions** (2026-09-29 to 10-13, 20 snapshots).
- **Run:** `ops/runbooks/stage3_gap_backfill.sh --execute --confirm GAP-2026-09-30..2026-10-12` (`f1fb35e`), 17:05–20:29 IST.
  - Two bounded commands; `PRAJNA_STAGE3_BACKFILL_ENABLED=true` was set only in their process environment. **No vendor calls** (criterion J).
  ```
  PRAJNA_STAGE3_BACKFILL_ENABLED=true prajna stage3 backfill --from 2026-09-30 --to 2026-10-07 --commit
  PRAJNA_STAGE3_BACKFILL_ENABLED=true prajna stage3 backfill --from 2026-10-09 --to 2026-10-12 --commit
  ```
- **Backup first:** `backend/var/backups/prajna_20261013T1705_stage3_gap_backfill.dump` (4.0 GB, sha256 `62a6388e…`, verified).
- **Checks, all PASS:**

| # | Check | Result |
|---|---|---|
| 1 | Existing sessions unchanged (`feature_fingerprint.py --compare`, md5 per snapshot) | 6 of 6 identical; the only new snapshots are the 14 expected |
| 2 | Inserted rows | 2,991,702 (7 × 427,386); `already_present` 0 |
| 3 | Point in time (`ck_feature_pit`, `as_of` vs inputs) | 0 violations |
| 4 | One registry per snapshot | every new snapshot features-v4 only |
| 5 | Duplicates / null contract (value XOR reason) | 0 / 0 |
| 6 | Determinism: full rerun of both ranges | 0 inserted, 2,991,702 values matched, all 20 snapshots byte-identical |

- **Evidence:** `backend/var/logs/stage3_gap/20261013T1705/` (`before.json`, `after.json`, `compare.json`, per-range `backfill_*.json`, `rerun_*`). Not in git (`backend/var/` is ignored).
- **Not changed:** the `.env` backfill flag (still `false`), the registry (features-v4 active, v5 prepared only), Stage 3 code, cron.
- **Purpose:** live/production feature continuity only. Stage 4 research uses the separate replayed training datasets (`training_feature_value`, 257 sessions), which this does not touch.
