# M4 live validation: first real candle commit (2026-09-23 evening)

**Code under test:** `d72df15` (M4.3). HEAD at run time was `1e7446e`, which
changes docs only.
**When:** 2026-09-23, 18:55–19:05 IST, after the close.
**Where:** DB `prajna` (Docker `postgres:18`), Upstox account 2UB7PH.

## Verdict: **M4 live validation = PENDING, and only B1/B2 over ≥ 3 sessions remain** (updated 2026-09-24 09:40 IST)

Items (a) and (c) below were satisfied on 2026-09-24; see §9a, §10 and §15.

**Original verdict (2026-09-23): PENDING**

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

### 9a. B1, second observation (2026-09-24 morning)

The poller's 1D historical requests show when 09-23's daily bar first appeared:

| Instrument | Last absent (IST) | First present (IST) | Changed afterwards? |
|---|---|---|---|
| RELIANCE | 09-24 06:51:32 | 09-24 07:01:33 | no (identical to 09:32) |
| HDFCBANK | 09-24 06:51:32 | 09-24 07:01:33 | no |
| NIFTY 50 | 09-24 06:51:32 | 09-24 07:01:33 | no |

- RELIANCE's historical 09-23 volume is **8,352,048**. That exactly equals the
  intraday daily bar at 16:02 on 09-23: the historical bar carries the settled
  post-close value.
- **Session 1 of B1:** the daily bar is published between ~06:51 and 07:01 IST
  on the next day, and was not revised through 09:32.
- The current rule (knowable_at = fetched_at; never persisted on the fetch
  day) is consistent with this. B1 stays UNVERIFIED until ≥ 3 sessions agree.

**Open observation:** the poller's historical-candle requests kept returning
200 between 03:30 and 08:30 IST on 09-24, with the token from 09-23. Either
the token outlived ~03:30, or that endpoint does not check the token. This is
UNVERIFIED and changes nothing: the pre-open runbook logs in before 08:30 in
any case.

## 10. Pre-open (Phase 5): **DONE, verdict WARN, real market data**

**Command:** `ops/runbooks/preopen_day.sh --login 2026-09-24`.

| Step | Timing and result |
|---|---|
| Start | 08:30 IST |
| TOTP login | OK at 08:30:28 |
| Universe | 3,527 committed |
| Capture | 08:55:15 → 09:20:00 |
| Replay | 2 archives, COMPLETE |
| Acceptance | 09:31 |

**Output:** `backend/var/acceptance/preopen_2026-09-24.json`.

| Group | Result |
|---|---|
| A1–A8 (transport) | all PASS. 2 connections (2,000 + 1,527 keys), 3,527 / 3,527 subscribed keys produced frames, archives sha-verified (`d7240647…` 6,048 frames, `d11cb5d0…` 5,829 frames) |
| B1–B5 (DB) | all PASS: 392,371 `preopen_tick` rows, 1,961,780 `preopen_book` rungs, 18 status rows. knowable_at > fetched_at: 0. Timestamps 08:55:15 → 09:19:59 IST |
| C1 transitions | PASS: PRE_OPEN_START 09:00:00.013, PRE_OPEN_M_END 09:05:00.110, PRE_OPEN_END 09:09:13.010 |
| C2 IEP | PASS: 3,119 of the 3,123 ticking instruments had an IEP; 2,280 had an IEQ |
| C3 IIQ | PASS: iiq_total for 2,245 instruments, iiq_m for 1,908 |
| C4 depth | PASS: 194,638 ticks with 4 quoted rungs; 851 with 5 |
| C5 tbq/tsq | PASS: 3,123 instruments |
| C6 completeness | **WARN**: 3,123 / 3,527 (88.6 %) had an in-window tick. The missing ones are spread across all series (EQ 308, SM 42, ST 26, BE 22, IV 5, BZ 1). The feed only sends on change, so these are most likely instruments without pre-open order activity. A3 proves every key delivered frames |
| **B7** | **OBSERVED**. iiq_m is non-zero for 1,908 instruments; 103,559 ticks have a negative iiq_total and 84,070 a negative iiq_m; in 76,667 ticks \|iiq_m\| > \|iiq_total\| |
| **B8** | **RESOLVED**. IEP is populated for CAS-eligible (211 / 211) and non-CAS (2,908) instruments |

**Reconnects:** 12 in total, all caused by the 60 s stale watchdog. **All of
them fell outside the pre-open window**:
- 08:56–08:59, before PRE_OPEN_START;
- 09:10–09:14, after PRE_OPEN_END.

There were **0 disconnects between 09:00 and 09:09:13**, so no data is missing
from the window. The 24 WARN GAP anomalies come from these reconnects.
Possible improvement (not done): a longer stale threshold in the vendor-quiet
periods.

## 15. Live forming/settling exclusion in the DB path (2026-09-24, market hours)

| Job | Fetched (IST) | Returned per instrument | Persisted | Excluded |
|---|---|---|---|---|
| 1m intraday, 4 instruments, `--commit` | 09:32:21 | 17 (09:15 → 09:31) | **15** (through the 09:29 bar) | **2 SETTLING** (09:30, 09:31: within the 120 s margin) |
| 5m intraday, 4 instruments, `--commit` | 09:32:35 | 4 (09:15 → 09:30) | **3** (through the 09:25 bar) | **1 FORMING** (09:30) |

Rows whose `bar end + 120 s > fetched_at`: **0 for 1m and 0 for 5m**. This
satisfies item (a) of the verdict. 5m is committed under D2 (vendor-fetched,
approved).

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

## 14. M4.5 phase 1: 1D backfill from 2020 (2026-09-23, 19:46–21:05 IST)

**Decisions:** approved by the user with the M4.5 plan on 2026-09-23:
- **D1:** 1D from 2020-01-01; 1h/15m from 2022; 1m for the last 6 months.
- **D2:** vendor-fetched 5m/15m/1h.
- **Survivorship:** accepted and documented.

This section covers phase 1 only.

```bash
prajna ingest candles --timeframe 1d --from 2020-01-01 --to 2026-09-22 --all-instruments \
  --no-resume --commit --token ***                     # first pass
prajna ingest candles --timeframe 1d --from 2020-01-01 --to 2026-09-22 --all-instruments \
  --commit --token ***                                 # rerun, with the checkpoint fix (7cd51f8)
```

The first pass used `--no-resume` because the 4 instruments committed earlier
had checkpoints at 09-22 covering only 09-08 onwards. Resuming would have
skipped their older history. That is the bug fixed in `7cd51f8`.

| Check | Result |
|---|---|
| Requests | 3,528 (one decade window per instrument), no 429, no auth error |
| Inserted | **3,640,084** 1D bars (total 1D rows 3,640,124) |
| Coverage | DATA 3,522 · EMPTY 6 · VENDOR_ERROR 0 · FAILED 2 |
| Instruments with bars | 3,520; bars per instrument: min 1, median 1,184, max 1,672 |
| Indices | NIFTY 50, Nifty Bank, India VIX: 1,671 sessions each, 2020-01-01 → 2026-09-22 |
| Provenance (all 3.64 M rows) | 0 bad run · 0 missing payload · 0 wrong source · 0 knowable_at > fetched_at · 0 fetched_at ≠ payload · 0 key ≠ instrument · 0 verified · 0 on/after the fetch day |
| Sanity | 0 negative volume · 0 low > high · 0 open/close outside [low, high] · 0 non-positive price |
| Replay (150 random runs) | 165,775 rows, **0 mismatches** |
| Rerun | 0 inserted. All 3,526 checkpoints = [2020-01-01, 2026-09-22], with covered_from recorded |
| Size | ohlcv_bar 1.95 GB; disk free 311 GB |

**The 2 FAILED windows are a vendor data defect: negative daily volume.**
- **IDEA (`NSE_EQ|INE669E01016`), 2024-08-30:** volume −81,259,413.
  - That day's 1m bars sum to 4,190,718,048 shares, above 2³¹, which is
    consistent with a 32-bit overflow at the vendor.
  - The value + 2³² would be 4,213,707,883, which differs from the 1m sum by
    22,989,835. So the true value cannot be reconstructed.
- **PARAMPARA (`NSE_EQ|INE749Y01014`, SME), 2022-09-05:** volume −1,798,967,296.
  That day has a single 1m bar with volume 0.

The parser rejects the candle (PARSE_REJECT), so each window fails and **both
instruments have no 1D history**.
- **Decision required:** quarantine the single bad bar and store the rest, or
  keep the whole-window FAIL.
- Correcting the value is not an option.
- Evidence: payloads `f60a63108a9d…` and `f44bc80ec818…`, plus the 1m probes
  `062088f68818…` and `911c7583e005…`.
