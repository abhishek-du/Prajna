# Stage 1 hardening: detailed work report (2026-09-25)

> **Superseded in part.** This snapshot was written at 17:38 IST. At about 18:30 IST the B1/B2 poller showed that the B2 timing contract is contradicted (Nifty 50 1m closes revised up to 95.6 s after the bar end on 2026-09-25). Criterion X is now BLOCKED (decision TIMING-B2) and live readiness is NOT PASS. The authoritative final state is `docs/STAGE_1_ARCHITECTURE_HARDENING_REPORT.md`.

**Status at 17:38 IST, 2026-09-25**

- Phases **P0 to P3** are committed.
- Phases **P4 to P8** plus market-hours news polling are implemented, tested and
  migrated to production, but **not committed yet**.
- Today's close (started 16:05) is still running its intraday 1m/15m/1h step.
  It is at 2,640 of about 10.6k jobs and should finish around 23:40 IST.
- The final steps wait for the close, because the directive says not to touch
  files a running close uses.
- Historical backfill: **DEFERRED** (not run).
- Stage 3: **LOCKED** (untouched).

| Area | Result |
|---|---|
| Stage 1 overall | **NOT COMPLETE**: R and X need future sessions |
| Live readiness | **PASS**: no criterion FAIL or BLOCKED |
| Test suite | 808 tests. 5 failures, all fixed by the staged close-script fix (verified: 47/47). 2 live tests skipped by default. |
| Production DB | alembic head **0010**; a verified backup before every migration |
| Secret exposure | 0 hits outside the files meant to hold secrets; the revoked token appears only in the session transcript |

---

## 1. Why this work was needed

The forensic investigation earlier on 2026-09-25 (live vendor calls, archived bodies) showed that the remaining Stage 1 problems were **undefined data contracts and operational gaps**, not missing data:

1. **The vendor rewrites history after splits and bonuses.** Upstox adjusts both 1D and intraday history when a split or bonus goes ex, rounding half-even to the tick. CHAVDA's 740 of 740 bars matched factor 2 exactly. Our "first observation is immutable" rule (D3) therefore turned a legitimate adjustment into a DUPLICATE_KEY failure.
2. **Mixed price basis.** Stored history mixes bases, and the vendor's corporate-action feed covers only about 1 year.
3. **Global daily labels are not trading dates.** USDINR labels Monday sessions with a Sunday date; N225 labels Friday sessions with a Saturday date. A stored N225 bar changed between 13:41 and 14:11 IST, so criterion Q was wrong in both directions.
4. **A stale instrument master.** RCDL-RE was dead (vendor error UDAPI100011) and 4 new listings were missing.
5. **Criterion D's denominator.** It included 353 non-stocks (fund units, rights entitlements).
6. **The write token was exposed:**
   - in 24,674 `ingest_run.argv` rows;
   - in `ps` output;
   - in the transcript.
7. **Scheduling gaps:**
   - the Upstox token expires around 03:30;
   - no overrun guard;
   - no kill escalation;
   - no orphan-run cleanup;
   - no global refresh;
   - news was fetched only twice a day.

---

## 2. Phase by phase

### P0: Safety audit and backups (committed 76ae24a)

- **Backup runbook.** `ops/runbooks/db_backup.sh`:
  - `pg_dump -Fc`, verified with `pg_restore --list`, plus a sha256 file;
  - `--verify-counts`: dump row counts must equal live row counts.
- **Trial restore replaced.** A trial restore into a scratch DB is impossible: the `prajna_rw` role has no CREATEDB and there is no docker access. `--verify-counts` replaced it; this is recorded as a limitation.
- **Six verified backups** in `backend/var/backups/`:

| Backup | Before | sha256 prefix |
|---|---|---|
| `prajna_20260925T1506_phase0_baseline.dump` | anything | – |
| `prajna_20260925T1517_phase1_pre_redaction.dump` | argv redaction | – |
| `prajna_20260925T1537_phase2_pre_0007.dump` | migration 0007 | a97fbcc4 |
| `prajna_20260925T1550_phase3_pre_0008.dump` | migration 0008 | 1cd2afc0 |
| `prajna_20260925T1648_phase6_pre_0009.dump` | migration 0009 | c050ef84 |
| `prajna_20260925T1658_phase5_pre_0010.dump` | migration 0010 | 3a37848e |

### P1: Token security (committed c32d23a)

- **Token kept out of argv.**
  - Every `--token` option also reads the env var `PRAJNA_SUPPLIED_TOKEN`.
  - All runbooks export it from `.env`, so the token never appears in argv.
  - `authz.redact_argv` redacts any token the runner stores.
- **Ledger cleaned.** `prajna db redact-argv --commit`, recorded as an auditable PRAJNA_MAINT run, redacted **24,674** historical argv rows.
- **Token rotated** in a verified quiet window. The old fingerprint 89f24a1070d0 is revoked and rejected; the new one is c583526dcbad. Only fingerprints were ever printed.
- **Scans:** DB, logs and git all showed 0 occurrences.

### P2: Instrument master refresh and lifecycle (committed d2d1895, migration 0007)

- **Identity model.** A stable `instrument_id` per key, plus:
  - `instrument_lifecycle_period`;
  - `instrument_attribute_version`, append-only, with a GiST no-overlap constraint.
- **Lifecycle states:**
  - ACTIVE;
  - INELIGIBLE;
  - REMOVED_FROM_MASTER;
  - VENDOR_REJECTED: UDAPI100011 on ≥ 2 sessions; recovers after a COMPLETE run.
- **Daily refresh** at 06:30. New listings get 1D history, fundamentals and corporate actions.
- **Real results:**
  - 4 new listings: SPECTRAA, SONA, AXIOMGAS, KHERIAAUTO;
  - RCDL-RE marked REMOVED_FROM_MASTER, with its history kept;
  - CHAVDA's lot size change (1000 → 2000) recorded as a new attribute version with the same id.
- **ACTIVE-only selection.** Job lists and completeness gates use only ACTIVE instruments.

### P3: Security classification and stock-only D (committed fd6b4de, migration 0008)

- **Classes:** STOCK / FUND_UNIT / RIGHTS_ENTITLEMENT / OTHER.
- **Rule:** a class needs **≥ 2 agreeing signals**. Otherwise the instrument goes to REVIEW, with its evidence stored.
- **Signals used:**
  - ISIN issuer and security code;
  - series;
  - vendor financials;
  - the `-RE` suffix;
  - a fund-scheme name pattern.
- **Result:** 3,155 STOCK.
  - The directive cited 3,172; the difference is the **21 InvITs**, now classified OTHER (ISIN code 23, series IV).
  - This is reported, not hidden.
- **Criterion D** now uses STOCK with sector ÷ STOCK, keeps the 90 % threshold, and prints the full class breakdown.

### P4: Scheduling hardening (implemented and tested; commit pending)

**Runbooks**
- `close_then_backfill.sh --no-backfill`: close, then the same-day rerun check (R evidence), then a BACKFILL_DEFERRED marker.
- **Failure classes:** SUCCESS / SINGLE_INSTRUMENT_VENDOR_FAILURE / TOKEN_FAILURE / QUOTA_FAILURE / TOO_EARLY / ABORTED. A close that is not completed triggers nothing downstream.
- **Hard stops** with `timeout -k 120 --signal=INT` (SIGINT, then SIGKILL 120 s later):
  - the close stops at 06:40 the next day;
  - the backfill honours `--until`.
- **Overrun guard:** no backfill handoff between 06:50 and 16:00 IST. `backfill.sh` itself refuses to start in that window on trading days.
- **Re-login:** exactly one after the ~03:30 token expiry. This is the day's single permitted TOTP login.

**Orphan cleanup and status**
- **Run identity:** every ingest run records pid, host and boot_id in `request_params`. This is excluded from `config_sha256`.
- **Orphan reaper** `prajna ops reap-runs --commit`: marks RUNNING runs ABORTED, with the reason, when the pid is dead, the machine rebooted, or the run has no identity and is > 48 h old.
- **`prajna ops status [--write]`** gives:
  - the last run per job family, and running / reaped / complete counts over 24 h;
  - the candles lock holder;
  - token age;
  - disk;
  - recent runbook markers.
- **`ops/runbooks/maintenance.sh [reap|derive|status|all]`.**

**Cron**
- The cron file `backend/ops/cron/prajna.cron` is **installed and identical to the repo**, verified by `tests/live/test_installed_cron.py` (2 passed with `-m live`).
- The two backfill lines stay commented `# DEFERRED_FOR_STAGE_1:`.

**Close-script bug**
- An empty or truncated intraday report (a hard stop mid-write) produced a blank failure class instead of ABORTED.
- The fix is **staged in the scratchpad and passes all 47 chain tests**. It gets swapped in atomically once today's close exits, because `close_then_backfill.sh` must not be edited while it runs.

**Tests**
- `tests/unit/test_ops_close_then_backfill.py` (47 tests);
- `tests/unit/test_ops_hard_stop.py` (6 real-process tests);
- `tests/integration/test_ops_reaper.py`, including a real SIGKILL crash;
- `tests/live/test_installed_cron.py`.

### P6: Price-basis model (implemented, migrated; commit pending; migration 0009)

**Option B: the raw observed canonical basis.**
- **`ohlcv_payload_basis`**, one row per payload:
  - RAW_OBSERVED: intraday endpoint, globals;
  - VENDOR_ADJUSTED: historical endpoint, `basis_as_of` = fetch date.
  - Seeded for **18,488** existing payloads, with no rewrite of the 3.7 M bars.
- **`ohlcv_observation`**: append-only; a trigger blocks UPDATE and DELETE.
- **`contracts/revision.py`**: a generic classifier with no instrument special cases. When a stored bar clashes with a new observation, it assigns one class:

  | Class | Rule |
  |---|---|
  | CA_ADJUSTMENT | Every price = half-even(stored / F, tick); volume = stored × F; OI unchanged; bar < ex_date ≤ fetch date. Every subset of the recorded events is tried. |
  | ROUNDING | Every price within one tick |
  | SETTLEMENT | Last bar of the session: o/h/l equal, volume up |
  | GLOBAL_REVISION / REOBSERVED | Global labels (see P5) |
  | UNEXPLAINED | The stream **fails closed** (DUPLICATE_KEY), so D3 is not weakened |

- **Failed runs keep their raw_payload index rows.** This fixes the gap where CHAVDA's conflicting payload disappeared on rollback.
- **`canon_market_bar`** now exposes `price_basis` and `basis_as_of`.
- **Live proof:** the CHAVDA 1D rerun is COMPLETE, with **4 CA_ADJUSTMENT observations** (factor 2). It used to be a DUPLICATE_KEY failure.
- **Evidence fixtures:** 26 archived vendor bodies in `tests/fixtures/vendor_evidence/`, with a sha256 README.
- **Tests:**
  - `tests/unit/test_price_basis_revision.py` (20): CHAVDA 740/740, the AHCL split plus bonus, a reverse split, rounding, and an unexplained change that fails;
  - `tests/integration/test_revision_ingest.py` (3): CHAVDA replayed through the real ingestor, an in-range tamper that must fail, and append-only enforcement.

### P7: Corporate-action factors and PIT-safe adjustment (implemented, migrated; commit pending)

**`ca_factor`** (method `cafactor-v1`, versioned). Statuses: EXACT / UNCERTAIN / UNSUPPORTED.

| Action | Factor |
|---|---|
| split | old face value ÷ new face value |
| bonus a:b | (a+b)/b |
| several actions | multiplied in ex-date order |
| rights | **UNSUPPORTED**: the structured premium is 0.0 on 60/60 events, so TERP cannot be proven |
| dividends | never a price factor |
| mergers | UNSUPPORTED |

**`vendor_applied`** (is the vendor's history adjusted?) is measured on our own stored series:
- APPLIED: CA_ADJUSTMENT observations exist, or the series is smooth across the ex-date;
- NOT_APPLIED: the price jump ≈ F;
- UNKNOWN: an indistinguishable factor, or pre-ex bars that predate the ex-date.

**Live derivation: 2,320 corporate actions**

| Action | APPLIED | NOT_APPLIED | UNKNOWN |
|---|---|---|---|
| BONUS | 52 | 3 | 11 |
| SPLIT | 68 | 1 | 4 |

CHAVDA is APPLIED, proven by its observations.

**`pit.bars_adjusted(key, tf, as_of)`**
- Formula: adj(t | as_of) = raw ÷ Π F over ex_date in (t, as_of] with `knowable_at < as_of`.
- Factors the vendor already applied are divided out.
- Statuses: AS_STORED / ADJUSTED / RECONSTRUCTED. RECONSTRUCTED is refused unless explicitly allowed.
- LOW-confidence bars are refused unless explicitly allowed: no basis, UNKNOWN treatment, or before the CA horizon 2025-09-24.
- Bar `knowable_at` is **not** relaxed.

**Tests:**
- `tests/stage2/test_bars_adjusted.py` (7), including "a future bonus cannot change an earlier as_of";
- `tests/unit/test_ca_vendor_treatment.py` (9).

### P5: Global-market finality (implemented, migrated; commit pending; migration 0010)

**Measured contract.** `global_instrument_contract` covers all **13** global instruments:
- label semantics;
- weekday profile;
- weekend-label share;
- absent weekdays per year;
- gap p50 / p99 / max;
- placeholder and same-open counts;
- revisions;
- `confirm_hours` = 6.

**The `global_bar_finality` view:**

| Status | Rule | Exposed? |
|---|---|---|
| REVISED | a later fetch differs | never |
| PLACEHOLDER | O=H=L=C = previous close, volume 0 | never |
| CONFIRMED | re-observed unchanged ≥ 6 h after the first fetch; knowable_at moves to the confirmation time | yes |
| CONFIRMED_BY_AGE | first fetched ≥ 4 days after the label | yes |
| UNCONFIRMED | otherwise | not yet |

- **`canon_global_bar`** exposes only the two confirmed statuses.
- **`canon_global_vendor_absent`** lists weekdays the vendor returned no bar for. They are **never counted as failures**.
- **`ops/runbooks/global_refresh.sh`**, cron 12:40 and 21:10 IST (13 requests, fraction 0.1). Markers:
  - `GLOBAL_REFRESH_STARTED` / `COMPLETED` / `PARTIAL`;
  - `GLOBAL_REVISION_DETECTED`;
  - `GLOBAL_VENDOR_ABSENT`;
  - `GLOBAL_FINALITY`.
- **Live run:**
  - 13/13 COMPLETE;
  - **1 real revision** (N225, label 2026-09-24), withheld as REVISED;
  - 61 REOBSERVED;
  - 5 vendor-absent days.

**The instruments named in the directive, as measured:**

| Instrument | Weekend-label share | Absent weekdays/yr | Gap p99 / max (days) | Flat placeholders | Semantics |
|---|---|---|---|---|---|
| ^N225 | 0.0515 | 29.33 | 4 / 7 | 1 | shifted calendar |
| USDINR | 0.1516 | 26.54 | 4 / 41 | 20 | shifted calendar |
| ^HSI | 0.0050 | 17.46 | 4 / 7 | 0 | weekdays |
| ^GSPC | 0.0055 | 6.63 | 4 / 5 | 0 | weekdays |
| ^DJI | 0.0076 | 9.78 | 4 / 6 | 0 | weekdays |
| ^FTSE | 0.0105 | 14.49 | 4 / 6 | 0 | weekdays |
| ^FCHI | 0.0095 | 6.63 | 4 / 6 | 0 | weekdays |
| GIFT NIFTY (`SGX NIFTY`) | 0.0342 | 4.71 | 3 / 5 | 3 | shifted calendar |

- **Test:** `tests/integration/test_global_finality.py` (4). It replays the real N225 bodies from 13:41 and 14:11, the vendor's holiday placeholder, vendor-absent days, and a real flat-looking day that must stay visible.
- **A correction to my own draft:** it first said SGX NIFTY is not served. That was wrong; I checked and fixed it. GIFT NIFTY is served under the key `GLOBAL_INDEX|SGX NIFTY`.

### P9: News as a first-class live input (implemented, cron installed; commit pending)

- **Measured problem:** with news polled only at the 16:05 close and 07:00 morning run, publication → receipt latency had a **median of 51 h** (p90 166 h).
- **Fix:** `ops/runbooks/news_poll.sh`, running every 30 min, 09:30–15:30, Mon–Fri:
  - its own lock, fraction 0.2, no login;
  - `timeout -k 60`;
  - markers `NEWS_POLL_STARTED` / `COMPLETED` / `FAILED`;
  - about 118 requests, about 64 s per run.
- **Live:** two runs today (17:13 and 17:16), COMPLETED with failed = 0.
- **Bug found and fixed:** the first run's summary line said "unreadable report". A Python 3.11 f-string cannot contain backslashes, so I moved the summary into a heredoc.
- **News time contract:**
  - `published_at` (vendor);
  - `received_at` = `fetched_at`;
  - `processed_at` = the run's finish time;
  - `decision_at`, reserved for Stage 3.
- **Test:** `test_news_poll_runs_in_market_hours_without_login_or_candles_lock` checks:
  - Mon–Fri only, hours 9–15;
  - the 9 o'clock slot only at :30, after the 08:55–09:20 pre-open capture;
  - no candles lock, no login, no `--token` flag.

### P8: Acceptance regeneration (implemented; commit pending)

- **New statuses:** PASS / FAIL / BLOCKED / OUT_OF_SCOPE / **WAITING_FOR_EVIDENCE** / **DEFERRED**.
  - Overall is COMPLETE only when every criterion is PASS, OUT_OF_SCOPE or DEFERRED.
  - Live readiness is PASS when nothing is FAIL or BLOCKED.
- **Rule changes:** D, G, I, J, Q, R, S and X changed. Each old and new rule is shown side by side in `docs/STAGE_1_FINAL_ACCEPTANCE.md`.
- **Current result:**

  | Status | Criteria |
  |---|---|
  | PASS | A B C D E F K M N O P Q T U V W Y |
  | OUT_OF_SCOPE | H (5m), L (all-day WebSocket) |
  | DEFERRED | G I J S (historical depth) |
  | WAITING_FOR_EVIDENCE | R, X |

  - **R** needs a complete close plus a CLOSE_RERUN_CHECK line with `idempotent=True`. Tonight's close is expected to provide both.
  - **X** needs B1/B2 verified over ≥ 3 real sessions.

---

## 3. Security re-verification (done today, counts only)

- **Evidence:** `backend/var/acceptance/secret_scan_20260925.json`.
- **Secrets scanned** (by sha256[:12] fingerprint; no value was ever printed):
  - the current write token;
  - the revoked write token;
  - the Upstox access token;
  - the API secret;
  - the TOTP secret.

| Location | Scanned | Hits |
|---|---|---|
| Database (all text/jsonb/array columns) | 26 tables, 154 columns | 0 |
| `var/logs` | 78 files | 0 |
| Rest of `var/` | 234,832 files | 0 |
| Repo worktree | 306 files | 0 |
| Git history (all refs) | 3.8 MB | 0 |
| Shell history | 1 file | 0 |
| Live process argv | 609 processes | 0 (no `--token` argument) |
| Files meant to hold secrets (`.env`, `var/upstox_token.json`, `old.token`) | 3 | expected |
| Session transcript | 1 | **1: the revoked token only** (rejected since rotation) |

---

## 4. Live warm-up analysis (not the research backfill)

Stage 3 defines no features yet, so there is **no mandatory warm-up** today.

| Timeframe | ACTIVE instruments | From | Sessions |
|---|---|---|---|
| 1D | 3,528 | 2020-01-01 | 1,674 |
| 1m | 3,391 | 2026-09-23 | 2 |
| 15m | 3,450 | 2026-09-24 | 2 |
| 1h | 3,391 | 2026-09-24 | 1 |

- **Daily lookbacks:** covered now.
- **Intraday lookbacks:** grow by one session per close.
- **If Stage 3 needs 20 intraday sessions:**
  - about 3,391 × 5 ≈ **17k requests**;
  - the vendor serves 1 calendar month per request for 1m/15m and a quarter for 1h;
  - about 8.5 h at fraction 0.5, so one night;
  - compare about 293k requests for the deferred backfill.
  - Not run.

---

## 5. Test and verification evidence

- **Full suite at 17:30:** 808 tests.
  - 5 failures: exactly the close-script cases fixed by the staged script;
  - the staged script against the whole chain test file: **47/47 passed**;
  - 2 live tests skipped by default; both pass with `-m live`.
- **Commit split rehearsed** in a scratch clone:
  - six phase commits: P4, P6, P7, P5, NEWS, P8;
  - they recompose byte-for-byte to the working tree;
  - each commit imports cleanly and passes its non-DB tests:

    | Commit | Non-DB tests passed |
    |---|---|
    | P4 | 566 |
    | P6 | 586 |
    | P7 | 596 |
    | P5 | 596 |
    | NEWS | 597 |
    | P8 | 597 |

  - `git diff --check` is clean.
- **Lint:** 3 new findings in test files fixed. The remaining new findings follow patterns already in the base: the typer `B008` idiom, migration import blocks, and `ASYNC240` in the acceptance module (the base had 251 findings).

---

## 6. Mistakes and incidents (reported, not hidden)

1. **Broken import during the close.**
   - What happened: a missing `Integer` import in `market.py` broke the models import for about 2 minutes while the close ran.
   - Fix: repaired at once.
   - New rule: an import check after every shared-module edit.
2. **`pkill -f` / `pgrep -f` matched their own shell** (twice). My first close-watcher would never have exited, and a `pkill` killed its own command.
   - Both were caught before any damage.
   - I checked that the close was untouched.
   - Now: bracket patterns (`close_then_backfil[l]`) or awk filtering.
3. **The false SGX NIFTY claim** in the draft report was caught by verification and corrected (see P5).
4. **The reaper crash test hung** on a row lock held by the test session. It was rewritten with its own engine and committed cleanup.

---

## 7. What remains (runs automatically after today's close ends)

1. Swap in the fixed `close_then_backfill.sh`, then run the full suite.
2. Check tonight's close:
   - `CLOSE_COMPLETED` verdict;
   - `CLOSE_RERUN_CHECK idempotent=True`;
   - `BACKFILL_DEFERRED`.
3. Run `prajna derive price-basis --commit` for tonight's payloads.
4. Run the Stage 2 process and `acceptance stage2 --run-tests`, then regenerate the Stage 1 acceptance. R should move to PASS if the evidence holds; it will not be forced.
5. Fill in `docs/STAGE_1_ARCHITECTURE_HARDENING_REPORT.md` (sections A–O).
6. Make six commits:
   - "stage1: complete scheduling hardening";
   - "stage1: implement price basis model";
   - "stage1: implement corporate action factors";
   - "stage1: harden global market finality";
   - the news-polling commit;
   - "stage1: complete stage1 acceptance".

   Each is preceded by `git status`, `git diff --stat` and `git diff --check`.
7. Delete `var/run/token_rotation/old.token`.
8. Confirm `git status` is clean.

## 8. Start / stop

```bash
cd /home/cis/windows/prajna/backend
crontab ops/cron/prajna.cron                                  # start (the repo file is the source of truth)
crontab -l > var/run/crontab_$(date +%Y%m%dT%H%M).bak && crontab -r   # stop all scheduled jobs
.venv/bin/python -m app.cli.main --plain ops status            # status
ops/runbooks/maintenance.sh reap                               # orphan cleanup
```

## 9. Rollback

- **Code:** `git revert` per phase commit, in reverse order.
- **Schema:** `alembic downgrade 0009`, then `0008`. Both are additive and reversible. The REOBSERVED evidence is kept.
- **Data:** `pg_restore` from the verified dumps listed in P0.
