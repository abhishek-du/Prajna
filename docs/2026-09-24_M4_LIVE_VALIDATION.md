# M4 live validation: first real candle commit (2026-09-23 evening)

**Code under test:** `d72df15` (M4.3). HEAD at run time was `1e7446e`, which
changes docs only.
**When:** 2026-09-23, 18:55–19:05 IST, after the close.
**Where:** DB `prajna` (Docker `postgres:18`), Upstox account 2UB7PH.

## Verdict: **M4 live validation = PENDING**

**Passed:**
- **Phase 1:** first real 1D commit + provenance + idempotence + replay.
- **Phase 2:** 1m intraday commit, for the post-close case.
- **Phase 3:** evidence only; see below.

**Not yet satisfied:**
- (a) a **live** forming/settling bar kept out of the DB path, which needs
  market hours (scheduled for 2026-09-24);
- (b) B1/B2 over ≥ 3 sessions;
- (c) the real pre-open day (Phase 5, scheduled 2026-09-24 08:30 IST).

Stage 1 is **not** complete.

## 1. Commands executed

```bash
# Phase 1: 1D, explicit keys, --commit (no --all-instruments, no backfill)
prajna ingest candles --timeframe 1d --from 2026-09-08 --to 2026-09-23 \
  --key "NSE_EQ|INE002A01018" --key "NSE_EQ|INE040A01034" \
  --key "NSE_INDEX|Nifty 50" --key "NSE_INDEX|India VIX" --commit --token ***
# ... the same command again (idempotence)

# Phase 2: today's 1m bars, same keys
prajna ingest candles --timeframe 1m --intraday <same keys> --commit --token ***
# ... the same command again (idempotence)

# Phase 3: evidence only, DRY-RUN (vendor 5m/15m/1h NOT committed: that would pre-empt D2)
prajna ingest candles --timeframe 5m --timeframe 15m --timeframe 1h --intraday <same keys>

# Verification (read-only)
scratchpad verify_replay.py "ohlcv.1d." / "ohlcv.1m."   # archive -> re-parse -> compare with DB
prajna acceptance instruments --payload-sha256 bf4a5db8…  # FK dependency (M3.0)
```

## 2. Instruments and timeframes

| Instrument | Key | Why |
|---|---|---|
| RELIANCE | `NSE_EQ\|INE002A01018` | required |
| HDFCBANK | `NSE_EQ\|INE040A01034` | an additional liquid NSE_EQ name |
| NIFTY 50 | `NSE_INDEX\|Nifty 50` | required |
| India VIX | `NSE_INDEX\|India VIX` | required |

Timeframes:
- **committed:** 1D (09-08 → 09-23 request) and 1m (today, intraday endpoint);
- **dry-run only:** 5m, 15m, 1h.

## 3. Archive hashes (vendor bytes, sha256 prefix)

| Stream | Committed payload |
|---|---|
| 1d RELIANCE / HDFCBANK / India VIX / NIFTY 50 | `add44abbfc39` / `18b9ba175f2b` / `24d72dd2ad3b` / `67cc19466e77` |
| 1m RELIANCE / HDFCBANK / India VIX / NIFTY 50 | `988505f74b3e` / `b4fbf7e5afc4` / `b605c972dc7d` / `083aca712aa0` |
| dry-run 5m / 15m / 1h (RELIANCE) | `5ed7f3ece600` / `345610baf23f` / `1c2ba599189e` |

RELIANCE's 1D payload is byte-identical to the one fetched at 14:23 IST: the
same bytes, fetched 4.5 h apart, so no revision.

## 4. DB row counts

| Table | Before | After |
|---|---|---|
| `ohlcv_bar` | 0 | **1,540** (1d 40 + 1m 1,500) |
| `ingest_run` | 13 | 42 (16 candle COMMIT, 18 candle DRY_RUN, 1 acceptance DRY_RUN; the rest earlier) |
| `raw_payload` | 74 | 82 (+8 candle payloads; the reruns added none) |
| `ingest_watermark` | 2 | 10 (4 × 1d at 2026-09-22; 4 × 1m with no date, since intraday never moves it) |
| `ingest_anomaly` | 1 | 1 (no new anomaly) |

## 5. Provenance verification

On all 1,540 rows, every column below is **0**:
- no run;
- run not COMPLETE/COMMIT;
- no payload;
- wrong source;
- `knowable_at > fetched_at`;
- `fetched_at` ≠ `raw_payload.fetched_at`;
- instrument FK key ≠ row key.

Traceable: `ohlcv_bar → ingest_run`, and `ohlcv_bar → raw_payload → archive
file`. Every row is `knowable_at_verified = false`, which is correct because
B1/B2 are unverified.

**Row checks:**
- **1D:** 09-08 → 09-22 (10 sessions per instrument). **09-23 is absent,
  correctly:** the daily bar was still unpublished at 19:03 IST (B1). Key =
  session_date 00:00 IST (D4); the label is kept verbatim.
- **1m:** 375 bars per instrument, 09:15 → 15:29 IST, all session 2026-09-23.
  No `knowable_at` earlier than its bar's end. `grid_unchecked` = 0 (the
  calendar row exists).

## 6. Duplicate / idempotency

Second run of each command:
- **1D:** inserted **0**, `already_present` 10 per instrument;
- **1m:** inserted **0**.

Rows stay 1,540, and `raw_payload` stays 82: identical bytes are
content-addressed once. **PASS.**

## 7. Replay (archive → parser → compare with DB)

| Stream | Runs | DB rows | Re-parsed COMPLETE rows | Mismatches |
|---|---|---|---|---|
| 1d | 4 | 40 | 40 | **0** |
| 1m | 4 | 1,500 | 1,500 | **0** |

Every field was compared: session_date, bar_start, OHLC, volume, OI,
vendor_ts_raw, knowable_at, verified and basis. **PASS.**
`acceptance instruments` (M3.0, the FK dependency): **PASS I1–I7**.

## 8. Phase 3: 5m/15m/1h vs 1m (evidence only; D2 NOT decided)

Vendor 5m (300 bars), 15m (100) and 1h (28) for the 4 instruments, against the
same bars aggregated from the **persisted** 1m bars: **428 / 428 identical**
in O, H, L, C and volume. It is one session, after the close. It does not
prove equality in general, and the contract is unchanged.

The forming-bar exclusion was **not observable tonight**: after the close
every bar is COMPLETE. It is proven offline (`test_forming_1h_bar_is_not_persisted`,
the settling cases). The live proof is scheduled for market hours on
2026-09-24.

## 9. B1 / B2 so far

| | Evidence | Sessions |
|---|---|---|
| B2, 1m | 153 bars bracketed: available 6–36 s after bar end (median ~19 s); never served forming; never changed after appearing | 1 (09-23) |
| B2, 5m/15m/1h | served while forming; 2/42 5m bars changed up to 30.9 s after end; 15m/1h unchanged after end | 1 |
| B1, availability | the daily bar was **not** on the historical endpoint the same evening (absent at 17:30 and 19:03 on 09-23) | 1 |
| B1, post-close volume | RELIANCE: the 1m volume sum equals the intraday daily bar at 15:30:02 (8,348,873); the daily reached 8,352,048 by 16:02 (**+3,175**). On 09-22 the daily exceeded the 5m sum by **+2,643**. **The pattern repeats** | 2 |

**The poller is running** (`backend/ops/measure/candle_timing.py`) until
2026-09-24 17:30 IST. It records when 09-23's daily bar first appears and the
full B2 distribution for 09-24. **B1 and B2 stay UNVERIFIED** until ≥ 3
sessions agree.

## 10. Pre-open (Phase 5)

**PENDING.** Scheduled: `ops/runbooks/preopen_day.sh --login 2026-09-24`
starts at 08:30 IST. Its output will be
`backend/var/acceptance/preopen_2026-09-24.json`.

## 11. Failures / anomalies

- None in the committed runs.
- The only `ingest_anomaly` row is the pre-existing COVERAGE_CAP from the old
  single-connection universe dry-run.

## 12. Decisions still requiring human approval

D1, D2, D3, D5, S1, S2, P1 and survivorship. See
[`2026-09-24_M4_DECISIONS.md`](2026-09-24_M4_DECISIONS.md), which includes the
new finding that Upstox provides corporate actions, fundamentals, news and
FII/DII.

## 13. FII/DII ingest: first live commit (2026-09-23, ~19:30 IST)

The user put FII/DII in Stage 1 scope on 2026-09-23, so it is ingested from
Upstox only. This does not change the verdict above.

- **Endpoints:** `GET /v2/market/fii` with `NSE_EQ|CASH`, `NSE_FO|INDEX_FUTURES`,
  `NSE_FO|INDEX_OPTIONS`, `NSE_FO|STOCK_FUTURES`, `NSE_FO|STOCK_OPTIONS`, and
  `GET /v2/market/dii` with `NSE_EQ|CASH`; `interval=1D`.
- **Measured semantics:**
  - `from=X` returns the 30 trading days **ending** at X;
  - with no `from`, the latest 30;
  - `time_stamp` = session date 00:00 IST;
  - before 2026-04-01 the response is an empty 200;
  - every record carries all 12 fields, and the non-applicable ones are 0.
- **Fixtures:** 8 real responses in `backend/tests/fixtures/upstox_institutional/`,
  with sha256 values in `manifest.json`.

```bash
prajna ingest institutional                           # dry run: 42 requests, 42 COMPLETE
prajna ingest institutional --commit --token ***      # commit
prajna ingest institutional --commit --token ***      # rerun (idempotence)
```

| Check | Result |
|---|---|
| Requests (commit) | 42 = 6 series × 7 windows (04-29, 05-27, …, 09-23), all COMPLETE, no GAP, no STALLED |
| Rows | **4,760** = 119 trading days × 40 series (cash 2 + index fut 8 + index opt 10 + stock fut 8 + stock opt 10 + DII cash 2) |
| Range | 2026-04-01 → 2026-09-22; 09-23 not yet published (and the fetch day is excluded anyway) |
| Window overlaps | 3,200 observations seen twice. **0 conflicting values** |
| Rerun | 6 requests, 0 inserted, 1,200 already present |
| Provenance (every row) | 0 without a COMPLETE/COMMIT run · 0 without a payload · 0 wrong source · 0 `knowable_at ≠ fetched_at` · 0 verified · 0 `fetched_at ≠ raw_payload.fetched_at` · 0 on/after the fetch day · 0 duplicate (series, date) |
| Replay (archive → parser → DB) | 42 runs, 4,760 rows, **0 mismatches** (value, unit, knowable_at, vendor record) |
| Watermarks | `macro.<side>.<type>.1D` = 2026-09-22 for all 6 |

**Tests:**
- parser: 30, on real responses plus mutations;
- integration: 12, covering walk, resume, earlier start, same-day exclusion,
  dry run, revision = FAIL, window gap = FAIL, calendar gap = FAIL, 429 = ABORT,
  error body archived, no token = refused.

Full suite: **480 passed**.

**Open (not decided here):**
- **Publication lag:** UNMEASURED; knowable_at stays `fetched_at`, unverified.
- **Same-day figures:** whether they are provisional and later revised is
  UNMEASURED. A revision would FAIL (D3).
- **Amount unit:** documented as INR, but the magnitude suggests INR crore;
  stored as `INR_vendor`.
- **Daily schedule:** the incremental needs a scheduler, the same open item as M4.4.
