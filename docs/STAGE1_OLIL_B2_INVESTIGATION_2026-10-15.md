# Stage 1 gate failure 2026-10-15: OLIL (F/S) and B2 (X): read-only investigation

**Status:** INVESTIGATED, NOTHING CHANGED.
- No corporate-action record, bar, observation, decision, margin, criterion, configuration or backup/restore was written.
- 2 read-only vendor GETs were made and nothing was stored (the first response was misread, so the call was repeated once).
- The timing analysis wrote only a scratchpad file. The gate's input `var/acceptance/b1b2.json` is unchanged (sha256 prefix `fd8eb34e…` before and after).

**Impact today:** Stage 3 REFUSED both snapshots, and nothing was written.
- **PRE_SESSION**, 09:02: `stage1_complete` failing [F, S].
- **PRE_OPEN**, 09:34: failing [F, S, X].
- Every other scheduled job completed. The pre-open capture acceptance PASSed.

## 1. OLIL (OneClick Logistics India, `NSE_EQ|INE0OPS01011`, SME, lot 600): criterion F, hence S

**What failed:**
- The 07:03 IST 1D ingest stream `ohlcv.1d.NSE_EQ|INE0OPS01011` FAILED with 5 blocking `DUPLICATE_KEY` anomalies: "a different bar is already stored and no rule explains it (D3: UNEXPLAINED revisions fail)".
- The vendor re-served the stored history at a lower price level:

| Stored close | Re-served close | Ratio |
|---|---|---|
| 441.35 | 294.25 | 0.66670 |
| 440.65 | 293.80 | 0.66674 |
| 449.55 | 299.70 | 0.66667 |
| 455.00 | 303.35 | 0.66670 |
| 457.00 | 304.70 | 0.66674 |

- The ratio is a constant **2/3**, within tick rounding (tick ₹0.05).
- Latest stored bar: 2026-10-13. The 2026-10-14 bar was not stored, because the stream failed.

**Our stored corporate actions for OLIL:** only a RIGHTS issue (ex 2026-02-26, fetched 2026-09-24). There is no bonus or split.

**Our stored NSE announcements** (`news_item`, source NSE_ANNOUNCEMENTS, which covers 2026-09-28 onward only):

| Date | Announcement | Bonus wording? |
|---|---|---|
| 09-30 | AGM proceedings | no |
| 10-02 | AGM voting results | no |
| 10-10 | Postal-ballot voting results | subject not stated |
| 10-13 | SEBI DP certificate | no |

- No bonus or record-date announcement is in our store. The announcement on 2026-09-04 predates the store.

**Vendor corporate-action feed:**
- Call: `GET /v2/fundamentals/INE0OPS01011/corporate-actions`, 2026-10-15 07:58:49 UTC, HTTP 200, `cf-ray=a4ad47e46925d263-BOM`. Read only, not stored.

| Field | Value |
|---|---|
| Event | **Bonus**, ratio **1:2**: "Bonus issue of equity shares in the ratio of 1:2 of Rs. 10/-" |
| Announcement date | **2026-09-04** |
| Ex-bonus date / record date | **2026-10-15 / 2026-10-15** |
| Factor | BONUS_RATIO (a+b)/b = (1+2)/2 = **1.5**, so pre-ex prices × **0.6667** |

**Verdict: EXPLAINED.**
- The 0.6667 revision is the vendor's adjustment for a 1:2 bonus with ex-date today, applied to the history before ex.
- It is the same mechanism as MOLDTEK (2026-10-09).
- Root cause of the miss: the vendor lists actions only near the ex-date, and our corporate-action refresh is not daily. That gap is still open (MOLDTEK remediation, "Remaining").

### Exact remediation (MOLDTEK procedure; NEEDS YOUR APPROVAL; NOT DONE)

1. **Backup:**
   ```
   ops/runbooks/db_backup.sh --label olil_pre_ca_fix
   ```
   About 4.3 GB, about 15 min. Verify it.
2. **Vendor call 1:**
   ```
   prajna ingest corporate-actions --isin INE0OPS01011 --commit
   ```
   Inserts the BONUS (announcement 2026-09-04, ex 2026-10-15). It becomes knowable at the fetch time (CA-OBSERVED).
3. **Vendor call 2:** historical 1D for `NSE_EQ|INE0OPS01011`, 2026-10-01 → 2026-10-14:
   ```
   prajna ingest candles --timeframe 1d --from 2026-10-01 --to 2026-10-14 --key 'NSE_EQ|INE0OPS01011' --commit
   ```
   It needs the write token from the environment.
   - It should insert the 10-14 bar.
   - It records the re-served pre-ex bars as CA_ADJUSTMENT observations (factor 1.5).
   - The stored bars stay untouched.
4. **Derive:**
   ```
   prajna derive price-basis --commit
   prajna derive ca-factors --commit
   ```
   - `ca-factors` is a **global** upsert, as on 2026-10-09.
   - Compare row by row with the backup, and report other changed actions.
5. **Verify:**
   - point-in-time: the bonus is invisible before the fetch instant;
   - `pit.bars_adjusted` for OLIL: pre-ex bars ADJUSTED by 1.5, 0 RECONSTRUCTED;
   - targeted regression tests;
   - `prajna acceptance stage1`: expected F PASS, S DEFERRED;
   - `prajna stage3 locks`.
6. **Stage 3:** the next scheduled run (2026-10-16 09:00:30) evaluates the gate itself.
   - **Today's snapshots (2026-10-15) stay missing** unless separately approved for a bounded Stage 3 backfill, as for the 2026-10-13 gap.
   - INFERRED: the bonus is observed after today's `as_of`, so a backfill of 10-15 would not apply it, which is correct under CA-OBSERVED.
7. **Not fixed by this:** X is BLOCKED, so PRE_OPEN still refuses until §2 is decided.

## 2. B2 (criterion X, PRE_OPEN): 15m bars revised more than 300 s after the bar end

**Data:**
- `var/measure/candle_timing_*.jsonl`: 2026-09-23 → 2026-10-15, 15 full sessions.
- 3 sampled instruments: RELIANCE `INE002A01018`, HDFCBANK `INE040A01034`, `NSE_INDEX|Nifty 50`.
- Analyzer `ops/measure/analyze_timing.py --out <scratchpad>`. Medians were computed with the same extraction logic.

| Timeframe | Bars | Revisions after end | Median | P95 | P99 | Max | ≥ 300 s | ≥ 900 s |
|---|---|---|---|---|---|---|---|---|
| 1m (in scope) | 16,264 | 1,585 | 77.6 s | 93.6 | 128.7 | 200.4 | 0 | 0 |
| **15m (in scope)** | 1,101 | 1,382 | 36.7 s | 93.2 | 136.6 | **1,856.1** | **6** | **3** |
| 1h (in scope) | 309 | 345 | 31.7 s | 89.4 | 134.0 | 146.1 | 0 | 0 |
| 5m (out of scope) | 3,294 | 4,073 | 44.9 s | 96.5 | 137.0 | 666.9 | 4 | 0 |

**Every late event is on one session, 2026-10-14, across all 3 sampled instruments, in the same bar slots:**

| 15m bar (IST) | RELIANCE | HDFCBANK | Nifty 50 |
|---|---|---|---|
| 14:15–14:30 | 684.4 s | 684.6 s | 667.0 s |
| 14:30–14:45 | 1,855.7 s | 1,855.9 s | 1,856.1 s |

- The 5m late events are also on 2026-10-14, for bars of 14:15 and 14:25. That is about 500–667 s.

**Assessment:**
- **Isolated, vendor-side event:** 6 of 1,101 15m bars (0.54%), on 1 of 15 sessions (6.7%).
- The revisions are simultaneous across unrelated instruments: about 14:41 IST and about 15:16 IST corrections. That points to a single upstream data correction, not normal settling.
- On the other 14 sessions every in-scope timeframe stays below 201 s (1m), 137 s (15m) and 147 s (1h).
- Caveat: 3 instruments and 15 sessions are a small sample. "Isolated" is an observation, not a proven property.

**Consequences of a 900 s margin:**
- **It would not clear X.** The 14:30 bars were revised at about 1,856 s, beyond 900 s. B2 stays CONTRADICTED.
- To absorb this event the margin would need to be ≥ 1,860 s (31 min). The contract forbids enlarging the margin after observation without an explicit review.
- **PRE_OPEN readiness:** unaffected by any margin up to about 31 min.
  - The PRE_OPEN snapshot's intraday inputs come from the previous session, which ends at 15:30 IST, so its bars are final by about 16:01 at the latest.
  - The close ingest starts 16:05.
- **Intraday feature availability:** a later finality marks the last bars of the session final later. Features are computed the next morning, so the effect is none, with the same inference.
- **Risk:** a 31-min margin would also hide genuine late revisions in future. The contract's purpose is to surface them.

### Options (NEEDS YOUR DECISION; nothing changed)

| Option | Effect |
|---|---|
| **R1 (recommended)** | Record a TIMING-REVIEW incident decision: "2026-10-14 14:15–14:45 15m (and 5m) vendor correction, simultaneous across instruments", treated as a known vendor event. Keep 300 s. The analyzer and X exclude only that window, explicitly. This is a code/decision change with a test, and it is visible in X's evidence. |
| R2 | Raise the 15m margin to ≥ 1,860 s. It hides future late revisions, so it is not recommended. |
| R3 | Do nothing. X stays BLOCKED, and PRE_OPEN keeps refusing even after OLIL is fixed. |

## 3. Next approvals required

1. **OLIL remediation** steps 1–5: a backup, 2 vendor calls and 2 derives.
2. **B2:** R1, R2 or R3.
3. **Optional:** a bounded Stage 3 backfill of 2026-10-15 (both snapshots) after 1 and 2.
4. **Structural, recommended:** a daily corporate-action refresh. This is the third occurrence class (MOLDTEK, MOLDTKPAC, OLIL).

## 4. Incident record: B2 late vendor revisions on 2026-10-14 (R1, approved 2026-10-15)

**Decision R1:** the event is recorded as a known vendor incident. **Nothing else changes:**
- the 300 s completion margin for 1m, 15m and 1h stays (`app/contracts/timing.py`, `COMPLETION_MARGIN_S`);
- `ops/measure/analyze_timing.py` and the Stage 1 criterion X rules are unchanged;
- `var/acceptance/b1b2.json` is unchanged (sha256 prefix `fd8eb34e…`).

**This record does not make X PASS.**
- B2 stays CONTRADICTED and X stays BLOCKED under the existing rules.
- Any exclusion of this window from the gate would be a separate code/decision change, which is not approved.

| Field | Value |
|---|---|
| Incident | INC-B2-2026-10-14: simultaneous late vendor revisions of intraday bars |
| Session | 2026-10-14 (Wednesday) |
| Window | 15m bars 14:15–14:30 and 14:30–14:45 IST; 5m (out of scope) bars 14:15 and 14:25 |
| Instruments | every sampled instrument: RELIANCE `NSE_EQ|INE002A01018`, HDFCBANK `NSE_EQ|INE040A01034`, `NSE_INDEX|Nifty 50` |
| Measured delays after the bar end (15m) | 14:15 bar: 684.4 s, 684.6 s, 667.0 s; 14:30 bar: 1,855.7 s, 1,855.9 s, 1,856.1 s |
| Measured delays (5m, out of scope) | 507.1 s, 500.4 s, 500.6 s, 666.9 s |
| Correction instants (bar end + delay) | about 14:41 IST and about 15:16 IST |
| Baseline, the other 14 sessions | in-scope maxima 1m 200.4 s, 15m ≤ 137 s, 1h 146.1 s; 0 events ≥ 300 s |
| Frequency | 6 of 1,101 15m bars (0.54%), on 1 of 15 sessions |
| Classification | vendor-side data correction, simultaneous across unrelated instruments: an **observation**, not a proven cause |
| Source | `var/measure/candle_timing_20261014T0921.jsonl` (archived responses; sha per line), analysed 2026-10-15 |
| Gate effect | B2 CONTRADICTED, so X BLOCKED, so Stage 1 NOT COMPLETE. The PRE_OPEN lock failed [F, S, X] on 2026-10-15. |
| Stored production bars | **verified 2026-10-15:** the stored 15m bars of 14:15 and 14:30 for RELIANCE and Nifty 50 (fetched 16:05 and 18:35 IST) equal the last polled, corrected values of the timing log exactly (OHLCV) |
| Follow-up | a contract review is still required to clear X, under the existing rule "explicit contract review; the margin is never enlarged silently". Options R1-exclusion-in-code or R2 need a new decision. |

## 5. OLIL remediation execution, 2026-10-15: BLOCKED at step 2 (stopped as instructed)

**Preconditions (all passed before any write):**

| Check | Result |
|---|---|
| Command scope | `ingest corporate-actions --isin` touches one ISIN only. `ingest candles --key … --from … --to` takes exactly one key selector and a historical window. `derive price-basis` is a global, insert-only fill of missing payload bases (0 missing before). `derive ca-factors` is a global upsert of every factor: `derived_at` and `run_id` change for all rows, values change only with new evidence. Both are as described in the approval. |
| Backup | `var/backups/prajna_20261015T1344_olil_pre_ca_fix.dump`, 4.6 GB, 523 TOC entries, sha256 `71488ae719bcf2ba5687329dd0fc1c08c2547d85de6b2d808f6b941b1f6249ea` (recomputed: match). Started 13:44:46, verified 13:59:45 IST. |
| Rollback readiness | `pg_restore` 18.6 is available. Per-table extraction from the dump matches the live counts: `corporate_action` 2,344, `ca_factor` 2,344, `ohlcv_observation` 2,511. A full rollback is `pg_restore --clean` from this dump. A row-level rollback goes by `run_id`. **A trial restore was not possible:** `prajna_rw` has no CREATEDB (`db_backup.sh --trial-restore` needs it). |

**Pre-state fingerprints:**
- `corporate_action` 2,344, md5 `e081c9dc…`;
- `ca_factor` 2,344 rows (listing kept);
- OLIL 1D bars 711, md5 `88fdcfc4…`;
- other 1D bars 3,727,818, md5 `b28ad94e…`;
- observations 2,511;
- payload bases 195,898 (0 missing);
- `feature_value` 4,647,908, md5 `1f838536…`;
- `stage3_event` 72;
- crontab `dbc5b41b…`.

**Step 1 (PASS):** `prajna ingest corporate-actions --isin INE0OPS01011 --commit`.
- Result: run `5a1d70f8-d23d-4c35-bd42-a157ed61594d`; 2 events seen, **1 inserted, 1 already present** (the RIGHTS issue).
- New row **`corporate_action` 4109:**
  - BONUS, ratio_from 1 / ratio_to 2;
  - ex 2026-10-15, record 2026-10-15, announcement 2026-09-04;
  - fetched 14:00:59 IST; `knowable_at` 2026-09-04 23:59:59 IST (KN-CA). The canonical view takes greatest(knowable, fetched), so it is observed at 14:00:59 IST (CA-OBSERVED).
- It matches the vendor response field for field.

**Step 2 (FAIL):** `prajna ingest candles --timeframe 1d --from 2026-10-01 --to 2026-10-14 --key 'NSE_EQ|INE0OPS01011' --commit`.
- Result: run `ed2ac553-394e-4285-bf41-998653a3da64` FAILED.
  - 7 blocking `DUPLICATE_KEY` anomalies ("no rule explains the difference"); 1 revision would have been CA_ADJUSTMENT.
  - **Nothing was stored:** bars, observations and payload bases are unchanged. Only the FAILED run row and its 7 anomaly rows were written, plus the raw payload archive file.
- **Root cause:** the D3 contract (`app/contracts/revision.py`) explains a revision as CA_ADJUSTMENT only if every price equals **half-even(stored / F, tick)**. The vendor rounds the adjusted prices **up (ceiling) to the tick**:
  - F = 1.5, tick ₹0.05;
  - over the 20 revised prices of the 5 bars of the 07:03 run, ceiling matches **20/20** and half-even only **14/20**;
  - example: 423.10 / 1.5 = 282.0667, the vendor gives 282.10, half-even gives 282.05.
  - MOLDTEK's factor 2 never produced a third of a tick, which is why it passed.
- This is a contract mismatch, not a data error. Fixing it changes a D3 rule, which is not approved.

**Steps 3–4 (NOT RUN):** `derive price-basis` and `derive ca-factors`.
- They were stopped because step 2 failed.
- The scheduled 06:40 maintenance will derive factor 4109 tomorrow anyway, with the same global command.

**Post-state (verified):**
- every pre-state fingerprint above is unchanged;
- `corporate_action` = 2,345, with the 2,344 previous rows identical (md5 `e081c9dc…`).

**Acceptance (read-only evaluation, 14:0x IST):**
- Stage 1 **NOT COMPLETE**: F FAIL, S FAIL, X BLOCKED. Unchanged in verdict.
- Expect the 2026-10-16 07:00 morning ingest to fail OLIL the same way unless the contract is changed.

**Stage 3 backfill of 2026-10-15: NOT ELIGIBLE, NOT RUN.** Stage 1 is not PASS: F, S and X.

**Proposed fix (needs approval):**
- Extend CA_ADJUSTMENT in `app/contracts/revision.py` to accept the vendor's **ceiling-to-tick** rounding as well as half-even. Every price must equal ceil(stored / F, tick) or half-even(stored / F, tick), with volume = stored × F and OI unchanged.
- This stays exact, not a tolerance.
- Add tests for factor 1.5 thirds (the OLIL values) and keep the existing UNEXPLAINED tests failing closed.
- Then rerun steps 2–5.
