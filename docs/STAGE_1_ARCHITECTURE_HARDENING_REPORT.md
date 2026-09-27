# Stage 1 architecture hardening: final report

Date: 2026-09-25 (IST). Scope: the MASTER DIRECTIVE "COMPLETE STAGE 1 HARDENING NOW".
Historical intraday backfill: **DEFERRED** (not run). Stage 3: **LOCKED** (untouched).

> **LIVE-READINESS: PASS** (the gate reports nothing FAIL or BLOCKED), **STAGE 1: NOT COMPLETE**
> (one criterion, X, is WAITING_FOR_EVIDENCE: B1 and the revised B2 need a third real
> session), **STAGE 2: PASS (16/16)**, **HISTORICAL BACKFILL: DEFERRED**, **STAGE 3: LOCKED**.

Every claim below names its evidence: a test (file::name), a command with its output,
an evidence file, or a commit.

---

## A. What was implemented (this hardening)

| Phase | What | Evidence |
|---|---|---|
| P0 | Verified database backup runbook (`ops/runbooks/db_backup.sh`: `pg_dump -Fc`, `pg_restore --list`, sha256, `--verify-counts`) | commit 76ae24a; `var/backups/*.dump(.sha256)`, 6 backups |
| P1 | Write token never in argv (`--token` also reads env `PRAJNA_SUPPLIED_TOKEN`; runbooks export it), `authz.redact_argv`, ledger redaction (`prajna db redact-argv`), token rotated | commit c32d23a; section C.6 |
| P2 | Daily instrument-master refresh: stable `instrument_id`, `instrument_lifecycle_period` and `instrument_attribute_version` (GiST no-overlap), lifecycle ACTIVE / INELIGIBLE / REMOVED_FROM_MASTER / VENDOR_REJECTED, ACTIVE-only job lists and completeness gates (migration 0007) | commit d2d1895 |
| P3 | Explainable security classification STOCK / FUND_UNIT / RIGHTS_ENTITLEMENT / OTHER (at least 2 agreeing signals, else REVIEW), D over stocks only (migration 0008) | commit fd6b4de |
| P4 | Scheduling hardening: `close_then_backfill.sh --no-backfill` with failure classes, an overrun guard, `timeout -k 120 --signal=INT` hard stops, a single re-login, run identity (pid/host/boot_id) with the orphan reaper `prajna ops reap-runs`, `prajna ops status`, `maintenance.sh`, cron | commit d4ee9d8 |
| P6 | Price-basis model: `ohlcv_payload_basis` (RAW_OBSERVED / VENDOR_ADJUSTED + basis_as_of), append-only `ohlcv_observation` (CA_ADJUSTMENT / ROUNDING / SETTLEMENT / GLOBAL_REVISION / REOBSERVED / UNEXPLAINED; a trigger blocks UPDATE/DELETE), the generic classifier `contracts/revision.py`, FAILED runs keep their raw_payload index (migration 0009) | commit ddc6573 |
| P7 | Corporate-action factors `ca_factor` (cafactor-v1, versioned; EXACT / UNCERTAIN / UNSUPPORTED) with measured vendor treatment; the PIT-safe adjusted read `pit.bars_adjusted` | commit 0d02664 |
| P5 | Global-market finality: the measured per-instrument contract `global_instrument_contract`, the `global_bar_finality` view (REVISED / PLACEHOLDER / CONFIRMED / CONFIRMED_BY_AGE / UNCONFIRMED), `canon_global_bar` exposes only confirmed bars, `canon_global_vendor_absent`, `global_refresh.sh` at 12:40 and 21:10 (migration 0010) | commit cfd4c1a |
| P9 | News as a first-class live input: `news_poll.sh` every 30 min in market hours | commit a9b5f91 |
| P8 | Acceptance regenerated with statuses PASS / FAIL / OUT_OF_SCOPE / WAITING_FOR_EVIDENCE / DEFERRED, with old and new rules side by side | commit the acceptance commit that contains this report ("stage1: complete stage1 acceptance"); `docs/STAGE_1_FINAL_ACCEPTANCE.md` |
| API | Read-only `/v1` API over the canonical layer (`backend/app/readapi`): 14 contract areas plus market session, batched latest price and global finality; point-in-time `knowable_at < as_of`; read-only transactions; contract `docs/API_CONTRACT.md` | commit a8eadd9 |
| WEB | Market-data research client `web/` over the read API (docs `docs/web/`): no fabricated or live-claimed data, missing capabilities shown as unavailable, Stage 3 locked | commit after this report ("web: …") |

### A.1 Price-basis model (Option B: raw observed canonical)

- **The first observation of a bar is immutable (D3).** A later, different vendor observation is never written over it. It goes to `ohlcv_observation` with a class:

  | Class | Rule |
  |---|---|
  | CA_ADJUSTMENT | Every price = half-even(stored / F, tick), volume = stored × F, OI unchanged, bar < ex_date ≤ fetch date, and the event is in our records. Every subset of the applicable events is tried, largest first. |
  | ROUNDING | Every price within one tick; volume and OI identical |
  | SETTLEMENT | The session's last bar only: o/h/l identical, close changed, volume up |
  | GLOBAL_REVISION | A global label changed |
  | REOBSERVED | An identical global re-observation |
  | UNEXPLAINED | Anything else: the stream FAILS (DUPLICATE_KEY), closed |

- **Tick** = `instrument.tick_size / 100` (paise).
- **No instrument is special-cased.** CHAVDA is simply the first real CA_ADJUSTMENT: 740/740 bars match factor 2, half-even. Tests: `tests/unit/test_price_basis_revision.py`, `tests/integration/test_revision_ingest.py::test_chavda_replay_is_classified_not_failed`.
- **Price basis per payload.** RAW_OBSERVED (intraday endpoint, globals) or VENDOR_ADJUSTED (historical endpoint, `basis_as_of` = fetch date). `canon_market_bar` carries `price_basis` and `basis_as_of`.

### A.2 Corporate-action factors

| Action | Factor |
|---|---|
| split | old face value / new face value |
| bonus a:b | (a+b)/b |
| several actions | multiplied in ex-date order |
| reverse split | same formula |
| rights | **UNSUPPORTED**: the structured Premium is 0.0 on 60/60 events while the Details text carries the premium, so TERP cannot be proven |
| dividends | never a price factor |
| mergers / demergers | UNSUPPORTED |

- `vendor_applied` answers: "is the vendor's history fetched after the ex-date adjusted for it?"
  - APPLIED: CA_ADJUSTMENT observations exist, or the series is smooth across the ex-date.
  - NOT_APPLIED: the price jump ≈ F.
  - UNKNOWN: |ln F| < 0.2, or the pre-ex bars predate the ex-date.
- `pit.bars_adjusted(key, tf, as_of)`: adj(t | as_of) = raw / Π F over ex_date in (t, as_of] with `ca.knowable_at < as_of`.
  - Vendor-baked factors are divided out (net = target / baked).
  - Statuses: AS_STORED / ADJUSTED / RECONSTRUCTED. RECONSTRUCTED is refused unless `allow_reconstructed`.
  - LOW confidence is refused unless `allow_low_confidence`: no basis, UNKNOWN treatment, or a vendor-adjusted bar before the CA horizon 2025-09-24.
  - Bar `knowable_at` is not relaxed.
  - Test: `tests/stage2/test_bars_adjusted.py`, including "a future bonus cannot change an earlier as_of".

### A.3 Global finality

- The first observation of a global daily label is stored but **not exposed**.
- It becomes **CONFIRMED** when re-observed unchanged at least `confirm_hours` (6) later. Its knowable_at and fetched_at become the confirmation time.
- It becomes **CONFIRMED_BY_AGE** when first fetched at least 4 days after the label.
- It is **REVISED** (never exposed) when a later fetch differs.
- It is a **PLACEHOLDER** (never exposed) when O=H=L=C = previous close with volume 0.
- **Vendor-absent weekdays** inside a COMPLETE fetch window are listed in `canon_global_vendor_absent`, never counted as failures.
- **Per-instrument contract** in `global_instrument_contract`: label semantics, weekday profile, weekend share, gap p50/p99/max, placeholder and same-open counts, revisions. Measured for all 13 global instruments (`prajna derive global-contracts --commit`, 2026-09-25). The eight named in the directive:

  | Instrument | Weekend-label share | Absent weekdays/yr | Gap p99 / max (days) | Flat placeholders | Same open as prev. | Label semantics | Finality, last 10 days |
  |---|---|---|---|---|---|---|---|
  | ^N225 | 0.0515 | 29.33 | 4 / 7 | 1 | 36 | shifted calendar (Fri→Sat) | 1 CONFIRMED, 2 BY_AGE, **1 PLACEHOLDER, 1 REVISED** |
  | USDINR | 0.1516 | 26.54 | 4 / 41 | 20 | 216 | shifted calendar (Mon→Sun) | 4 CONFIRMED, 3 BY_AGE, 1 UNCONFIRMED |
  | ^HSI | 0.0050 | 17.46 | 4 / 7 | 0 | 26 | weekdays | 3 CONFIRMED, 3 BY_AGE, 1 UNCONFIRMED |
  | ^GSPC | 0.0055 | 6.63 | 4 / 5 | 0 | 38 | weekdays | 4 / 3 / 1 |
  | ^DJI | 0.0076 | 9.78 | 4 / 6 | 0 | 37 | weekdays | 4 / 3 / 1 |
  | ^FTSE | 0.0105 | 14.49 | 4 / 6 | 0 | 43 | weekdays | 4 / 3 / 1 |
  | ^FCHI | 0.0095 | 6.63 | 4 / 6 | 0 | 40 | weekdays | 4 / 3 / 1 |
  | SGX NIFTY (GIFT NIFTY) | 0.0342 | 4.71 | 3 / 5 | 3 | 59 | shifted calendar | 4 / 3 / 1 |

  The confirm window is 6 h for all 13 (`confirm_hours`). Each UNCONFIRMED is the latest label, which awaits the 21:10 re-observation.
- Test: `tests/integration/test_global_finality.py` replays the real N225 13:41 and 14:11 bodies.

### A.4 Scheduling (installed crontab == `backend/ops/cron/prajna.cron`)

| When (IST) | Job |
|---|---|
| 06:30 daily | master refresh, lifecycle, classification (`daily.sh --login refresh`, candles lock) |
| 06:40 daily | `maintenance.sh all`: reap orphans, derive price basis / CA factors / global contracts, status snapshot |
| 07:00 Mon–Fri | morning: previous session 1D, FII/DII, news |
| 08:25 Mon–Fri | real pre-open capture |
| 09:30–15:30 every 30 min Mon–Fri | `news_poll.sh` (own lock, fraction 0.2, no login) |
| 11:00 and 19:00 Sat–Sun | `news_poll.sh` weekend sweep (added 2026-09-28: without it the weekend went ~55 h without a news sweep and criterion N failed; the longest gap is now 16 h) |
| 12:40 and 21:10 daily | `global_refresh.sh` (13 requests, fraction 0.1) |
| 16:05 Mon–Fri | `close_then_backfill.sh --no-backfill`: close, then the same-day rerun check; hard stop 06:40 |
| 23:55 daily | `maintenance.sh status` |
| Sat 10:00 / 1st 11:00 | weekly corporate actions / monthly calendar and fundamentals |
| backfill | two lines commented `# DEFERRED_FOR_STAGE_1:` |

Close failure classes (`CLOSE_COMPLETED failure_class=`):
- SUCCESS;
- SINGLE_INSTRUMENT_VENDOR_FAILURE (ran through; per-key errors listed);
- TOKEN_FAILURE, QUOTA_FAILURE, TOO_EARLY;
- ABORTED (anything else, including an empty or truncated report after a hard stop).

A close that is not completed triggers nothing downstream.

### A.5 News as a live input

- **Measured 2026-09-25**, with news fetched only at the 16:05 close and the 07:00 morning run: publication → `received_at` latency had a median of 51 h (p90 166 h).
- **Now:** a poll every 30 min in market hours (118 requests, about 64 s per run).
- **Contract:** `published_at` (vendor) → `received_at` = `fetched_at` → `processed_at` (the run's `finished_at`) → `decision_at` (reserved for Stage 3). `knowable_at` stays the vendor's published time only where verified. Otherwise it is the fetch time; it never overclaims.
- Live runs: `var/logs/daily/news_poll_2026-09-25.log` (NEWS_POLL_COMPLETED, failed=0).
- **Contract check on real rows**, `news_article` joined with `ingest_run`: 0 articles with knowable_at > received_at; 0 with processed_at < received_at; 0 with published_at > received_at.
- **Median publication → receipt:** 51.2 h for articles fetched 2026-09-24; 4.5 h for 2026-09-25 (22 articles, the poller's first day). That is early evidence, not a steady-state claim.
- **No interference with the close.** The poller uses its own lock (`var/run/news.lock`), never the candles lock, and runs at fraction 0.2. The worst concurrent sum (close 0.35 + news 0.2 + global 0.1 = 0.65) stays within the 0.9 per-user budget. It never logs in and never passes `--token`: `tests/unit/test_ops_close_then_backfill.py::TestStaticGuards::test_news_poll_runs_in_market_hours_without_login_or_candles_lock`.
- **Scope:** live polling makes *future* news point-in-time. It does **not** make *historical* news backtesting possible. The vendor serves only the last 7 days of news, so any news history before 2026-09-24 in Prajna is exactly what was fetched, when it was fetched.

### A.6 Live warm-up (not the research backfill): LIVE FIRST, TARGETED WARM-UP, RESEARCH BACKFILL LATER

Stage 3 defines no features yet, so Stage 1 has **no mandatory warm-up**. What exists (ACTIVE NSE instruments, measured 2026-09-25):

| Timeframe | Instruments | From | Sessions |
|---|---|---|---|
| 1D | 3,528 | 2020-01-01 | 1,674 |
| 1m | 3,391 | 2026-09-23 | 2 (+ each close) |
| 15m | 3,450 | 2026-09-24 | 2 (+ each close) |
| 1h | 3,391 | 2026-09-24 | 1 (+ each close) |

- **Daily indicators** (any lookback ≤ 6 years) are warm now.
- **Intraday** history accumulates one session per close.
- **Minimal intraday warm-up** for a lookback of N sessions, when Stage 3 needs more than the accumulated sessions: requests ≈ ACTIVE × (months touched[1m] + months touched[15m] + quarters touched[1h]). The vendor accepts 1 calendar month per request for minutes ≤ 15 and 1 quarter for hours (measured, `contracts/candles.py::request_limit`).
  - 20 sessions: ≈ 3,391 × 5 ≈ **17k requests**, about 8.5 h at fraction 0.5 (1,000 per 30 min). That is one night, against about 293k for the deferred research backfill.
  - It is a bounded `ingest candles --from/--to` over the last N sessions, not the backfill runbook. It is **not run**: it becomes necessary only when Stage 3 fixes N.

**The mechanism: `prajna ops warmup-plan --sessions N --timeframe T [--timeframe ...] [--fraction F]`** (`app/ops/warmup.py`).
- Read-only: 0 vendor calls, 0 writes.
- Takes the N most recent completed sessions from `trading_session` (NORMAL / SPECIAL), never from a calendar assumption.
- Counts the ACTIVE instruments that already hold all N sessions, and plans only for the rest.
- Uses the measured request windows (`contracts.candles.plan_windows`: 1 calendar month for minutes ≤ 15, 3 consecutive months for hours) and the documented 2,000 requests / 30 min.
- Prints the exact resumable `ingest candles --from --to --keys-file` command. Those bars are recorded VENDOR_ADJUSTED as of the fetch date.
- Tests: `tests/unit/test_warmup_plan.py`.

Production plan for 20 sessions of 1m + 15m + 1h at fraction 0.5 (computed 2026-09-25, not run):
- window 2026-08-27 → 2026-09-24, 3,531 ACTIVE instruments;
- 1m: 7,062 requests; 15m: 7,062; 1h: 3,531;
- **17,655 requests ≈ 8.8 h**, against about 293k for the deferred full backfill.

### A.7 Backtesting and live trading: what Stage 1 makes possible

Backtesting is possible **to the extent point-in-time (PIT) data exists**. A naive OHLC backtest cannot reproduce what a trader knew at the time. Future research must therefore declare its mode:

| Mode | Needs | Stage 1 support today |
|---|---|---|
| A. Price-only backtest | adjusted prices | 1D since 2020, but vendor-adjusted as of the fetch date; LOW confidence before the CA horizon (2025-09-24); `bars_adjusted` refuses it unless explicitly allowed |
| B. PIT market-data backtest | raw bars + factors knowable at as_of + as-of universe + confirmed globals | from the live accumulation onward (RAW_OBSERVED intraday; lifecycle periods; confirmed global bars with knowable_at at confirmation) |
| C. News/event-aware backtest | news with publication **and** receipt time; CA with knowable_at | only from when Prajna started receiving them (news: vendor window 7 days; CA: about 1 year) |
| D. Walk-forward validation | B/C over rolling windows | as the B/C history accumulates |
| E. Live paper trading | the live pipeline | ready (live readiness PASS) |
| F. Live production | E plus execution (Stage 3+) | LOCKED |

Rules enforced in Stage 1 (these are what make B–D honest):
- **knowable_at < as_of** everywhere (criteria C and X).
- **Corporate actions** apply only when knowable before as_of (`pit.bars_adjusted`).
- **Instrument membership** comes from lifecycle periods, not today's master.
- **Revised vendor data** is never exposed as if it had been known earlier: REVISED global bars are withheld, and vendor history rewrites are observations, not overwrites.
- **Placeholders** are never data.

### A.8 Vendor behaviours that are now documented contracts

1. **Upstox rewrites history on corporate actions.**
   - 1D and intraday bars fetched after a split or bonus ex-date are divided by F, rounded half-even to the tick; volume is multiplied by F.
   - Measured: CHAVDA 740/740, fixtures in `tests/fixtures/vendor_evidence/`.
   - Prajna keeps the first observation and records the rewrite as CA_ADJUSTMENT.
2. **Mixed price basis.**
   - Historical-endpoint payloads are VENDOR_ADJUSTED as of their fetch date; intraday-endpoint and global payloads are RAW_OBSERVED.
   - Recorded per payload: 11,520 RAW_OBSERVED and 6,982 VENDOR_ADJUSTED before tonight's close.
3. **Global date labels are not trading dates.**
   - USDINR labels Monday sessions with Sunday dates; N225 labels Friday sessions with Saturday dates.
   - The share is measured per instrument (`weekend_label_share`), and no calendar is assumed.
4. **Vendor revisions.**
   - A global label can change hours after it first appears (N225 2026-09-24, 13:41 vs 14:11).
   - Hence the finality contract (A.3).
5. **Instrument lifecycle.**
   - The master changes daily: new listings, removals, attribute changes (for example lot size), vendor rejections.
   - Identity is stable; periods and attribute versions are append-only.
6. **The trial restore is not possible with this role.**
   - `db_backup.sh --trial-restore` needs CREATEDB (or docker access), and `prajna_rw` has neither.
   - Backups are verified with `pg_restore --list`, sha256, and `--verify-counts` (dump row counts == live) instead.
   - A true restore rehearsal needs a privileged role; it is recorded in O.

### A.9 B2 timing contract: original, contradiction, revision (decision TIMING-B2)

**Original B2** (set 2026-09-23, before measurement): "1m bars are never served before their end and never change once listed; the other timeframes settle inside one 120 s completion margin."

**Finding** (2026-09-25; `ops/measure/candle_timing.py`, read-only; every response archived; analysed by `ops/measure/analyze_timing.py`):
- **90 of 1,125 `NSE_INDEX|Nifty 50` 1m bars** were revised after first listing: 88 close revisions and 2 low+close revisions. The latest was seen **95.6 s after the bar end**.
- RELIANCE and HDFCBANK: 0 revisions.
- 15m settled up to 110.9 s after the end and 1h up to 111.0 s. 5m (out of scope, H) settled up to 145.9 s.
- The original B2 is therefore **CONTRADICTED**. That is recorded as `B2_original` in `var/acceptance/b1b2.json`, not hidden.

**Revised B2** (user decision TIMING-B2, 2026-09-25): a candle is **timing-final from bar_end + completion_margin(timeframe)**.
- Per-timeframe margins in `app/contracts/timing.py`: 1m / 15m / 1h = 120 s.
- The margin is an **engineering threshold**: chosen from observation, configurable, monitored. **It is not a vendor SLA.**
- A revision at or after the margin is a **LATE revision**:
  - recorded, with bar, key, first-seen time and latency;
  - X becomes **BLOCKED** (pending decision TIMING-REVIEW, an explicit contract review);
  - the margin is **never enlarged automatically**.
- 5m keeps an operational, explicitly unvalidated margin, and does not affect X.

**Evidence behind 120 s** (all collected poller data, 2026-09-24 and 2026-09-25; 3 instruments: 2 equities and 1 index):

| Timeframe | Bars sampled | Revised bars (events) after the end | p95 | p99 | Max | Margin | Headroom |
|---|---|---|---|---|---|---|---|
| 1m | 2,250 | 90 (90) | 93.0 s | 94.9 s | **95.6 s** | 120 s | **24.4 s** |
| 15m | 150 | 146 (186) | 87.1 s | 89.7 s | **110.9 s** | 120 s | **9.1 s** |
| 1h | 42 | 36 (45) | 77.3 s | 111.0 s | **111.0 s** | 120 s | **9.0 s** |
| 5m (out of scope) | 450 | 433 (554) | 83.0 s | 110.9 s | 145.9 s | 120 s (unvalidated) | −25.9 s |

15m, 1h and 5m bars are served while still forming, so most of them change shortly after their end as they settle; the original B2 already allowed that. The margin bounds *when* settling stops. For 1m, the finding is that *index* bars also change after listing.

**Is the evidence sufficient to justify 120 s statistically? No.**
- Two sessions, three instruments (one index), and a fixed sampling cadence (6 s for 1m, 60 s for the others). Latencies are the fetch time at which the new value was first seen, an upper bound on the true revision time.
- 120 s is kept as the **operational initial threshold**, not a proven bound. The 15m and 1h headroom (about 9 s) is thin, which is exactly why the late-revision monitor exists.

**Finality vs knowability** (point-in-time):
- Timing finality answers "when may the candle be regarded as settled?".
- `knowable_at` answers "when did Prajna know its value?", and is always the fetch time. A 10:00–10:01 bar fetched at 16:05 is timing-final at 10:03 and knowable at 16:05.
- **A latent flaw was found and removed.** `contracts/knowable.py` used to return `knowable_at = bar_end` for intraday bars, and `= 15:30 close` for daily bars, once B2/B1 were "verified". No caller passed that flag, but verifying the contract would have moved knowledge before the fetch.
- Both paths now return `max(bar_end or close, fetched_at)` regardless of verification. Verification changes only the flag and the basis text.
- Tests:
  - `tests/unit/test_analyze_timing.py::test_f_*`;
  - `tests/contracts/test_knowable.py::test_verified_finality_never_moves_knowable_before_the_fetch`.
  - The old assertion "verified daily bar is knowable at the exact close" was replaced; the new rule is stricter.

**Persistence** (`contracts/candles.intraday_state`): a bar is SETTLING, archived only, until bar_end + margin(timeframe). The global constant `COMPLETION_MARGIN` was removed in favour of the per-timeframe contract.

**Regression tests A–G** (`tests/unit/test_analyze_timing.py`):

| Case | Scenario | Expected |
|---|---|---|
| A | 1m revised at +95.6 s | not final at +60 s, final at +120 s; original B2 CONTRADICTED; revised B2 not contradicted, and still not PASS on 2 sessions |
| B | 1m revised at +121 s | revised B2 CONTRADICTED, even with 3 more agreeing sessions |
| C | 15m at +110.9 s | inside the margin, headroom 9.1 s |
| D | 1h at +111.0 s | inside the margin, headroom 9.0 s |
| E | 5m at +145.9 s | reported, out of scope, X unaffected |
| F | fetched at 16:05, bar end 10:00 | timing-final, `knowable_at` = 16:05, intraday and daily |
| G | revised 300 s after the end | late revision recorded as acceptance evidence, B2 CONTRADICTED; ingestion keeps the stored row (UNEXPLAINED fails closed) |

**Monitoring:**
- `ops/runbooks/timing_monitor.sh`, cron Mon–Fri 09:21 and 16:10.
- It runs the read-only poller until 09:10 the next day, then re-derives `var/acceptance/b1b2.json`, which criterion X reads.
- It skips while a poller runs; the current one runs until 2026-09-28 16:00.
- Fraction 0.55; no login; no write token.
- Markers: `TIMING_MONITOR_*`, `TIMING_LATE_REVISION_DETECTED`.

**X now:**

| Contract | Agreeing sessions | Needed |
|---|---|---|
| B1 | 2 (09-23, 09-24) | 3 |
| Revised B2 | 2 (09-24, 09-25) | 3 |

- 0 late revisions and 0 look-ahead violations, so X is **WAITING_FOR_EVIDENCE**.
- The next evidence arrives from the running poller: B1 for 09-25 after its daily bar appears overnight; B2 for 2026-09-28.
- X is not PASS and is not forced.

---

## B. What was already implemented (before this hardening; verified, not rebuilt)

- IngestRunner ledger: open → record_payload → finalize/fail, archive raw first, authorization at the write path.
- Candle ingestion with resume checkpoints, Q1 quarantine, coverage outcomes (DATA / EMPTY / VENDOR_ERROR).
- 1D history from 2020-01-01.
- Corporate actions, fundamentals, FII/DII, news, the trading calendar, the pre-open capture, and the WebSocket recorder.
- Stage 2 canonical layer (migrations 0005/0006), the PIT API, and acceptance A–P (commits ef67157 … b81d8cd).
- The scheduling chain (commit 980fed7).

---

## C. What was verified live (real vendor, real production database)

1. **Global refresh** 13/13 COMPLETE. GLOBAL_REVISION 1 (N225 label 2026-09-24 changed between 13:41 and 14:11 → REVISED, not exposed). REOBSERVED 61; vendor-absent 5 (`var/logs/daily/global_refresh_2026-09-25.log`).
2. **CHAVDA 1D rerun** COMPLETE, with 4 CA_ADJUSTMENT observations (factor 2, bonus 1:1) instead of the former DUPLICATE_KEY FAIL. Labels 09-23 and 09-24 inserted.
3. **ca_factor** derived for 2,320 corporate actions:
   - BONUS: APPLIED 52 / NOT_APPLIED 3 / UNKNOWN 11;
   - SPLIT: APPLIED 68 / NOT_APPLIED 1 / UNKNOWN 4;
   - CHAVDA APPLIED via its observations.
4. **13 global contracts** measured (`prajna derive global-contracts --commit`).
5. **News poll** runs at 17:13 and 17:16 IST: COMPLETED, 118 batches, failed 0.
6. **Security re-verification** (`var/acceptance/secret_scan_20260925.json`, counts only; fingerprints sha256[:12]):
   - Secrets scanned: current write token c583526dcbad, revoked write token 89f24a1070d0, Upstox access token, API secret, TOTP secret.
   - 0 hits in: the DB (26 tables, 154 text/jsonb/array columns), `var/logs` (78 files), the rest of `var` (234,832 files), the repo worktree (306 files), git history (all refs), shell history, and live process argv (609 processes; no `--token` argument).
   - Hits only in their homes: `.env`, `var/upstox_token.json`, `var/run/token_rotation/old.token`.
   - The **session transcript** holds the **revoked** token (89f24a1070d0), which is rejected by the write path since rotation.
7. **Today's close** (`close_then_backfill.sh --no-backfill`, cron 16:05; `var/logs/daily/close_then_backfill_2026-09-25.log`):
   - started 16:05:01; `intraday OK` 23:35:46; `news OK` 23:36:00; `done: close 2026-09-25 fail=0`;
   - `CLOSE_COMPLETED rc=0 verdict=completed failure_class=NONE complete=10593 failed=[] aborted=0 not_attempted=0 data_absent=369`. The label is `NONE` because the pre-fix script was running; the installed script calls the same outcome `SUCCESS`;
   - `CLOSE_RERUN_CHECK jobs=9 complete=9 inserted=0 failed=0 idempotent=True`;
   - `BACKFILL_DEFERRED reason=DEFERRED_FOR_STAGE_1 (--no-backfill)`;
   - no `BACKFILL_STARTED` and no backfill log;
   - 11,107 runs since 16:05, all COMPLETE; 0 RUNNING rows afterwards; no runbook process left.
   - Post-close:
     - the fixed script was installed by atomic rename (sha256 7e43e0cd70c0 → 751e3c96ffef, the verified staged version), only after checking that no process executed or held it open;
     - `prajna derive price-basis --commit` inserted **8,903** payload bases, and a re-run finds 0 missing;
     - every stored bar now has a basis (0 without), and tonight's 10,213 intraday payloads are RAW_OBSERVED;
     - `stage2 process --commit` is incremental, consumed through 18:06 UTC.
8. **Price-basis state in production** (read-only queries, 2026-09-25 18:00 IST):
   - observations: CA_ADJUSTMENT 4 (all CHAVDA, factor 2), GLOBAL_REVISION 1, REOBSERVED 61, UNEXPLAINED 0;
   - trigger `tr_observation_append_only` enabled;
   - candle payloads without a basis: 1,416, all explained:
     - 1,375 from the running close, whose process started on pre-0009 code; `derive price-basis` covers them afterwards (see item 7);
     - 41 1D payloads whose runs wrote no bars, so no basis applies.
   - ROUNDING and SETTLEMENT have no production occurrence yet. They are proven by `tests/unit/test_price_basis_revision.py`.
9. **ca_factor in production** (cafactor-v1):

    | Action | Status | vendor_applied | Count |
    |---|---|---|---|
    | BONUS | EXACT | APPLIED | 52 |
    | BONUS | EXACT | NOT_APPLIED | 3 |
    | BONUS | EXACT | UNKNOWN | 11 |
    | SPLIT | EXACT | APPLIED | 68 |
    | SPLIT | EXACT | NOT_APPLIED | 1 |
    | SPLIT | EXACT | UNKNOWN | 4 |
    | RIGHTS | UNSUPPORTED (factor null) | N/A | 60 |
    | DIVIDEND | UNSUPPORTED, "dividends are not price factors" (factor null) | N/A | 2,121 |

    The feed contains no mergers; the model marks them UNSUPPORTED.
10. **Global finality in production:**
    - 13 contracts, GIFT NIFTY (`GLOBAL_INDEX|SGX NIFTY`) included.
    - Exposed in `canon_global_bar`: CONFIRMED 48/48, CONFIRMED_BY_AGE 21,921/21,921.
    - Withheld: PLACEHOLDER 25/25, REVISED 1/1, UNCONFIRMED 12/12.
    - N225 2026-09-24 is REVISED (revision seen 17:00:53 IST) and not exposed.
    - 1,822 vendor-absent rows across 13 instruments; 0 failed global runs today.
    - Markers in `global_refresh_2026-09-25.log`: GLOBAL_REFRESH_COMPLETED, GLOBAL_REVISION_DETECTED count=1 reobserved=61, GLOBAL_VENDOR_ABSENT last7d=5.
    - The GLOBAL_FINALITY line was emitted by no run today: the 17:00 run predates the fix. Exercised directly, it printed `CONFIRMED=48 CONFIRMED_BY_AGE=38 PLACEHOLDER=1 REVISED=1 UNCONFIRMED=12` after a second fix. It had been counting the CLI's `5 row(s)` footer. Test: `tests/unit/test_global_refresh_runbook.py`.
11. **Revoked token rejected** (fingerprints only): `authorize_write`
    - revoked 89f24a1070d0 → REJECTED (AuthorizationError);
    - current c583526dcbad → accepted;
    - none → REJECTED.
12. **Process environment:** the current write token is in the environment of exactly the close's ingest process and its `timeout` wrapper. That is by design (`PRAJNA_SUPPLIED_TOKEN`, not argv); 0 processes have it in argv. Crontab: 0 hits. Evidence: `var/acceptance/secret_scan_20260925_precleanup.json`.
13. **Installed crontab == repository file**: `tests/live/test_installed_cron.py` (2 passed with `-m live`).

---

## D. Migrations (all additive; each preceded by a verified backup)

| Rev | Content | Backup (sha256 prefix) |
|---|---|---|
| 0007 | instrument lifecycle + attribute versions | `prajna_20260925T1537_phase2_pre_0007.dump` (a97fbcc4) |
| 0008 | instrument_security_class | `prajna_20260925T1550_phase3_pre_0008.dump` (1cd2afc0) |
| 0009 | ohlcv_payload_basis (seeded 18,488 payloads), ohlcv_observation + append-only trigger, corporate_action first/last_seen_at, ca_factor | `prajna_20260925T1648_phase6_pre_0009.dump` (c050ef84) |
| 0010 | global_instrument_contract, REOBSERVED class, views global_bar_finality / canon_global_bar / canon_global_vendor_absent, canon_market_bar + price basis | `prajna_20260925T1658_phase5_pre_0010.dump` (3a37848e) |

- Production is at alembic head **0010**.
- No OHLCV row was updated or deleted: the classification lives in side tables and views.
- Every downgrade was tested on the test database. The 0010 downgrade re-adds the old class check `NOT VALID`, so REOBSERVED evidence is never destroyed.

## E. Test results

**Backend** (`pytest tests`, final run 2026-09-26 00:08 IST, after the close, with every staged fix and both test-clock fixes installed; `-o addopts=""`):

| Scope | Collected | Passed | Failed | Skipped | xfail |
|---|---|---|---|---|---|
| everything | 856 | 854 | 0 | 2 | 0 |
| — of which ours | 841 | 839 | 0 | 2 | 0 |
| — of which the external tool's `tests/unit/test_api_endpoints.py` | 15 | 15 | 0 | 0 | 0 |

- **Skips:** the 2 skipped are `tests/live/test_installed_cron.py`, skipped by default with the reason "live test; run with -m live". Run explicitly with `-m live`: **2 passed**.
- **Latest additions**, all included in the counts above:
  - `tests/integration/test_derive_price_basis.py` (1): the regression for the defect in G; proven to fail on the old code and pass on the fix;
  - `tests/stage2/test_api.py` (13);
  - `tests/unit/test_analyze_timing.py` (10, cases A–G);
  - `tests/unit/test_warmup_plan.py` (5);
  - `tests/unit/test_global_refresh_runbook.py` (2);
  - the close-chain tests (48, including the news-poll and timing-monitor schedule tests; made clock-independent, see G).
- **Web client** (`web/`):
  - `tsc` strict: 0 errors;
  - Vitest: **70 passed**;
  - Playwright against the real read API in system Chrome: **7 passed**;
  - `vite build` succeeds.
- **Stage 2** `acceptance stage2 --run-tests`: **16/16 PASS**, including L (resume) and P (all Stage 1 tests pass).

## F. Acceptance matrix

`prajna acceptance stage1`, regenerated after the close, the price-basis derivation, Stage 2 and the full test suite. Full table with old and new rules: `docs/STAGE_1_FINAL_ACCEPTANCE.md`.

| Status | Criteria |
|---|---|
| PASS | A B C D E F K M N O P Q **R** T U V W Y |
| OUT_OF_SCOPE | H (5m), L (all-day WebSocket persistence) |
| DEFERRED | G I J S (historical intraday depth: decision BACKFILL-DEFER) |
| WAITING_FOR_EVIDENCE | **X** |
| FAIL / BLOCKED | none |

- **R PASS:**
  - sessions 2026-09-24 and 2026-09-25 are complete for 1m, 15m and 1h over the ACTIVE universe;
  - `CLOSE_RERUN_CHECK … idempotent=True`.
- **X WAITING:**
  - 0 look-ahead violations and 0 late revisions;
  - B1 agreeing on 2026-09-23 and 2026-09-24 (3 needed);
  - revised B2 agreeing on 2026-09-24 and 2026-09-25 (3 needed);
  - original B2 recorded as CONTRADICTED.

**Overall: NOT COMPLETE. Live readiness: PASS.**

## G. Remaining failures

**None.** The gate has no FAIL or BLOCKED criterion, and the test suites have no failures.

**Defect found and fixed during tonight's verification.** `derive_price_basis --commit` failed with `AmbiguousColumnError`:
- **Cause:** `instrument` also carries a `payload_sha256` provenance column, so `left join … using (payload_sha256)` was ambiguous.
- **Why it was missed:** the dry run only counts, and no test exercised the commit path. The nightly `maintenance.sh derive` step would have failed every day.
- **Impact:** two FAILED derivation runs, both rolled back, with nothing written.
- **Fix:** an explicit `on p.payload_sha256 = b.payload_sha256`.
- **Regression test:** `tests/integration/test_derive_price_basis.py`.

**Test fragility found by the per-commit rehearsal at 23:58 IST.** 12 backfill-runbook tests failed only in the minutes before midnight:
- **Cause:** they pinned the hard stop to `--until 23:59`, while `backfill.sh` budgets against the real clock, so near midnight the budget was 0 and every stage was skipped.
- **Classification:** a test defect. The runbook's behaviour is correct.
- **Fix:** the tests set the hard stop 3 h after the current IST time.
- **A second instance appeared when the full suite ran across midnight.** 8 chain tests failed at 00:03 because the module computed `TODAY` once at import (2026-09-25) while the scripts used the real date (2026-09-26).
  - **Fix:** an autouse fixture recomputes `TODAY` and the hard stop at the start of every test.
  - No other test holds a module-level date.
- **Verification:** the file passes 48/48 before and after midnight; the full-suite results are in E.

## H. Waiting for evidence (cannot be produced today; never faked)

| Item | What completes it | Earliest |
|---|---|---|
| R (daily incremental) | **resolved 2026-09-25 23:36 IST: PASS** (see F) | — |
| X (no look-ahead, B1/B2) | B1/B2 knowable_at verified over ≥ 3 real sessions (live poller evidence) | after 3 sessions |
| Global `confirm_hours` calibration | only one real revision observed so far (N225 2026-09-24); the 6 h window is a measured minimum, not yet a distribution | weeks of refreshes |
| Rights factor | a vendor payload with a structured premium (none among 60 events) | vendor-dependent |

## I. Deferred historical backfill

- **Status: DEFERRED_FOR_STAGE_1.** G / I / J (historical depth) and S are DEFERRED. The capability is kept:
  - `ops/runbooks/backfill.sh`: resumable from stream checkpoints; refuses to run 06:50–16:00 on trading days; `timeout -k 120`; a single re-login;
  - `close_then_backfill.sh` without `--no-backfill`.
- The two cron lines are commented `# DEFERRED_FOR_STAGE_1:`.
- About 293k requests are not spent.
- **To enable later (an explicit decision only):**
  1. remove `--no-backfill` from the 16:05 line;
  2. uncomment the two DEFERRED lines;
  3. `crontab backend/ops/cron/prajna.cron`.

## J. Stage 3 status

**LOCKED.** No strategy, signal, execution or backtesting code was added or changed (`git log --stat` of this hardening touches only `backend/app/{ingest,contracts,canon,ops,acceptance,db,cli}`, `backend/ops`, `backend/tests`, `docs`).

## K. Live readiness

**PASS**, per the gate: nothing is FAIL or BLOCKED.

What is live and verified:
- the 16:05 close: all ACTIVE instruments × 1m/15m/1h, idempotent rerun;
- the 07:00 daily bars; 08:25 pre-open;
- news every 30 min in market hours;
- global refresh at 12:40 and 21:10, with finality;
- the 06:30 master refresh and lifecycle;
- 06:40 maintenance: reap, derive, status;
- the timing monitor;
- the installed crontab equals the repo file (live test).

What "live-ready" does **not** mean:
- there is no live tick store (criterion L is OUT_OF_SCOPE);
- intraday history starts 2026-09-23 (backfill DEFERRED);
- X still needs a third session;
- this is the data foundation only. Stages 3–7 (features, strategy, execution) have their own validation; nothing here makes the system ready for autonomous trading.

## L. Commits

Every commit below was checked before it was made: `git status`, `git diff --cached --stat` and `git diff --cached --check` (clean). Each was verified in an isolated checkout afterwards: import check plus the non-DB suite.

| Commit | Phase | Isolated non-DB tests |
|---|---|---|
| 76ae24a | P0 ops: verified database backup runbook | (earlier) |
| c32d23a | P1 security: token never in argv; ledger redaction; rotation | (earlier) |
| d2d1895 | P2 instruments: master refresh, lifecycle, attribute history | (earlier) |
| fd6b4de | P3 classification; D over stocks | (earlier) |
| d4ee9d8 | stage1: complete scheduling hardening | 571 passed |
| ddc6573 | stage1: implement price basis model | 591 passed |
| 0d02664 | stage1: implement corporate action factors | 601 passed |
| cfd4c1a | stage1: harden global market finality | 603 passed |
| a9b5f91 | stage1: add market-hours news polling | 604 passed |
| a8eadd9 | readapi: documented read-only /v1 contracts | 604 passed (+13 DB API tests in the full suite) |
| this commit | stage1: complete stage1 acceptance | full suite 854 passed / 0 failed / 2 live-skipped (2/2 with `-m live`) |
| next commit | web: market-data research client | Vitest 70 passed; Playwright 7 passed; build OK |

**Never committed:** `frontend/`, `backend/app/api/`, `backend/tests/unit/test_api_endpoints.py`, and the docs `API_INVENTORY.md`, `FRONTEND_ARCHITECTURE.md`, `STAGE_1_TIMING_AND_FINAL_ACCEPTANCE_REPORT.md`, `WEBSOCKET_LIVE_CONTRACT.md`, `STAGE_3_READINESS_REPORT.md`. These are another tool's concurrent work and are treated as an external worktree, so `git status` still lists them as untracked.

## M. Start / stop live ingestion

```bash
cd /home/cis/windows/prajna/backend
# start (install the schedule; the file is the single source of truth)
crontab ops/cron/prajna.cron && crontab -l | diff - ops/cron/prajna.cron && echo installed
# stop all scheduled ingestion (keeps a copy)
crontab -l > var/run/crontab_$(date +%Y%m%dT%H%M).bak && crontab -r
# stop a running close cleanly (SIGINT: the current run aborts and rolls back; resume is automatic)
pkill -INT -f 'app.cli.main --plain ingest candles'
# status and orphan cleanup
.venv/bin/python -m app.cli.main --plain ops status
ops/runbooks/maintenance.sh reap
# one-off runs
ops/runbooks/global_refresh.sh
ops/runbooks/news_poll.sh
flock -w 3600 var/run/candles.lock ops/runbooks/close_then_backfill.sh --no-backfill
```

## N. Rollback

- **Code:** `git revert <commit>` per phase (section L). The phases are separate commits; P8 → NEWS → P5 → P7 → P6 → P4 is the reverse order.
- **Schema:** `alembic downgrade 0009` (drops the 0010 views and table; REOBSERVED rows are kept, the old check is added NOT VALID). Then `alembic downgrade 0008` (drops ca_factor, observation, payload basis, CA seen columns). Take a backup first (`ops/runbooks/db_backup.sh`).
- **Data:** restore from `var/backups/*.dump` with `pg_restore -d prajna --clean` (verified dumps, sha256 files alongside).
- **Schedule:** `crontab var/run/crontab_*.bak`, or the scratch copies taken before each change.
- **Token:** rotation is one-way. A new token is issued by editing `.env` `PRAJNA_WRITE_TOKEN` (fingerprints only, never printed).

## O. Known limitations

**Post-report finding (2026-09-27/28).** Over the first weekend, criterion N (News: a sweep within 36 h) failed:
- **Cause:** every news job was scheduled Mon–Fri, so there was no sweep from Fri 23:36 to Mon 07:00. That is a scheduling gap, not data loss, since the vendor keeps 7 days of news.
- **Fix:** a weekend sweep (Sat/Sun 11:00 and 19:00 IST), with its test.
- **Rule:** unchanged.

1. **Pre-horizon history.** Raw 1D prices before the corporate-action horizon (2025-09-24; the vendor feed is about 1 year deep) are unrecoverable. The stored history is vendor-adjusted as of its fetch date, and `bars_adjusted` marks it LOW confidence and refuses it by default.
2. **Stock count 3,155 vs 3,172.** The 21 InvITs are classified OTHER (ISIN security code 23, series IV), so D counts 3,155 STOCK. The directive's 3,172 included them; the difference is reported, not hidden.
3. **USDINR** has 20 flat-repeat placeholders and a 41-day maximum label gap in its stored series since 2021. Placeholders are withheld and gaps are listed as vendor-absent, never filled (Upstox-only).
4. **Global confirmation** needs two fetches at least 6 h apart, so a label becomes visible at the second daily refresh (21:10 IST) at the earliest.
5. **Rights issues** are UNSUPPORTED (see A.2), so adjusted series across a rights ex-date are refused.
6. **`db_backup --trial-restore`** is impossible with the current role (no CREATEDB, no docker socket). `--verify-counts` is used instead: dump row counts == live.
7. **News `processed_at`** is the run's `finished_at` (run granularity, not per-article).
8. **Historical news** is limited to what Prajna received: the vendor serves 7 days. News-aware backtests (A.7 mode C) are possible only from 2026-09-24 onward.

### O.1 Incidents during this hardening (not concealed)

| When | Incident | Impact | Fix |
|---|---|---|---|
| 2026-09-25 ~16:50 | `app/db/models/market.py` lost its `Integer` import for about 2 min while the close ran | none observed: the close's process had already imported the models; no new process started in the window | fixed at once; rule: import check after every shared-module edit |
| 2026-09-25 | `pkill -f` / `pgrep -f` patterns matched their own shell (twice): a watcher that would never exit; a pkill that killed its own command | none: the close was verified untouched each time | bracket patterns (`close_then_backfil[l]`) or awk-filtered PIDs |
| 2026-09-25 | the reaper crash test hung on a row lock held by the test session | test DB only | own engine with committed cleanup |
| 2026-09-25 | the draft report claimed SGX NIFTY is not served | documentation only | caught by verification; GIFT NIFTY is served and measured |
| 2026-09-25 | the first news-poll summary printed "unreadable report" (a backslash inside a Python 3.11 f-string) | log line only | heredoc summary |
| 2026-09-25 | the global GLOBAL_FINALITY marker counted the CLI footer | log line only | awk filter + test |
| 2026-09-25 | the close script gave a blank failure class on an empty or truncated intraday report | would have mislabelled a hard-stopped close (no backfill would have started either way) | ABORTED; installed after the running close exited |
| 2026-09-25 ~17:45 | a diagnostic query (a correlated EXISTS over `ohlcv_bar`) ran 12 min beside the close | extra DB load; the close continued | cancelled with `pg_cancel_backend`; re-run via the run ledger |
