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
