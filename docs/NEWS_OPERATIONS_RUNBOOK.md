# Multi-source news: operations runbook

**Scope:** the 8 approved adapters. NEWS-COMPLIANCE was APPROVED 2026-09-29 for headline, summary, URL and timestamps; bodies stay TERMS_BLOCKED.

The Upstox `/v2/news` production path is separate and unchanged: cron every 30 minutes, `ops/runbooks/news_poll.sh`.

## 1. Modes and what unlocks them

| Mode | Writes | Visible to Stage 2 / 3 / API | Unlocked by (all of) |
|---|---|---|---|
| DRY_RUN | files: `var/news/dryrun/<SRC>/` | no | kill switch off; the adapter exists |
| SHADOW | `news_*` tables, `news_poll.mode = 'SHADOW'` | **no** (the reader joins PRODUCTION polls only) | the source's own flag `PRAJNA_NEWS_<SRC>_ENABLED=true`; kill switch off; terms APPROVED; the source **PASSES** `prajna acceptance news` (including the human mapping review); Stage 2 PASS (≤ 7 days, with tests); write token |
| PRODUCTION | the same tables, `mode = 'PRODUCTION'` | **yes** | everything for SHADOW, plus `PRAJNA_NEWS_MULTI_SOURCE_ENABLED=true` |

**There is no switch that enables every source.** Every refusal names each unmet condition and is written to `news_audit` (REFUSED).

The per-source flags are:

| Source | Flag |
|---|---|
| NSE | `PRAJNA_NEWS_NSE_ENABLED` |
| ET | `PRAJNA_NEWS_ET_ENABLED` |
| BS | `PRAJNA_NEWS_BS_ENABLED` |
| BL | `PRAJNA_NEWS_BL_ENABLED` |
| Mint | `PRAJNA_NEWS_MINT_ENABLED` |
| CNBC-TV18 | `PRAJNA_NEWS_CNBC_ENABLED` |
| IE | `PRAJNA_NEWS_IE_ENABLED` |
| SEBI | `PRAJNA_NEWS_SEBI_ENABLED` |

The exact names are in `app/news/sources/__init__.py`. They are set in `backend/.env` only, by the operator, with the user's approval.

## 2. Commands

| Purpose | Command | Writes |
|---|---|---|
| Source list and status | `prajna news sources` | — |
| DRY_RUN evidence | `prajna news dry-run --source ALL\|KEY[,KEY] --until HH:MM` | files |
| Acceptance gate | `prajna acceptance news --run-tests` | `var/acceptance/news.json` |
| Mapping samples to judge | `prajna news review-sample --source KEY` | `var/news/review/KEY.json` |
| One locked poll | `PRAJNA_SUPPLIED_TOKEN=… prajna news poll --source KEY --commit` | DB (SHADOW) |
| **Scheduled collection** | `ops/runbooks/news_collect.sh --mode SHADOW\|PRODUCTION --sources ALL\|KEYS --until HH:MM --token-from-dotenv` | DB |
| Daily reconciliation, monitoring states | `prajna news reconcile --day D --mode M --md docs/NEWS_DAILY_RECONCILIATION.md --json audit/evidence/news_reconcile_D.json` | report files, `var/status/news_health.json` |
| Operational status | `prajna ops status` (key `news_collector`) | — |
| Kill switch | `prajna news kill on --reason "…"` / `prajna news kill off` | audited |

### The collector (`news_collect.sh`)

**Invariants:**

- **One instance:** `flock -n var/run/news_collect.lock`. A second start logs NEWS_COLLECT_SKIP and exits 1.
- **Token handling:** the token goes through the environment only (`--token-from-dotenv` reads `.env` at run time); it is never in argv and never printed.
- **Every poll is one committed transaction.** It is serialised per source (advisory lock), with one shared story lock. `ON CONFLICT DO NOTHING` is the last guard.

**Behaviour on failure:**

- **A refusal** stops that source; the others continue. If all are refused: NEWS_COLLECT_REFUSED, exit 3.
- **An HTTP or DB error** fails that poll's run (rolled back; `ingest_run` FAILED). The source backs off: exponential, capped at 30 minutes, honouring `Retry-After`.
- **403 / 401** stop the source for good (BLOCKED / AUTH_FAILED). There is no bypass.

**Pacing:**

- Politeness: the source's interval by market phase, never below the feed's `<ttl>`, with jitter of 0.8×–1.2×.
- The deadline (`--until`) is checked before every poll and never slept past.
- A restart waits out the interval since the last stored poll.

**Markers** in `var/logs/daily/news_collect_<day>.log`: NEWS_COLLECT_START / DONE / REFUSED / FAILED / SKIP. The JSON summary is `news_collect_<day>_<MODE>.json`.

## 3. Scheduling (INSTALLED 2026-09-29 ~20:14 IST, user-approved; `ops/cron/prajna.cron` == the crontab)

The machine timezone is Asia/Kolkata, so cron times are IST. `B=/home/cis/windows/prajna/backend`.

```
# collection SUPERVISOR, every 15 min 06:00-23:15 (7 accepted sources; Indian Express not enabled)
*/15 6-22 * * *  cd $B && ops/runbooks/news_collect.sh --mode PRODUCTION --sources NSE_ANNOUNCEMENTS,SEBI_RSS,ET_STOCKS_RSS,BS_MARKETS_RSS,BL_MARKETS_RSS,MINT_MARKETS_RSS,CNBCTV18_NEWS_SITEMAP --until 23:30 --token-from-dotenv >> var/logs/cron.log 2>&1
0,15 23 * * *    (the same command)
# nightly reconciliation, read-only, separate responsibility
45 23 * * *      cd $B && ops/runbooks/news_reconcile.sh --mode PRODUCTION >> var/logs/cron.log 2>&1
```

**Why a supervisor, not one long start:**

- `news_collect.sh` holds `flock -n var/run/news_collect.lock`. While a collector runs, each 15-minute start logs NEWS_COLLECT_SKIP and exits 1. Observed at 20:12 (manual) and 20:15 (cron).
- **After a crash, kill or reboot**, the next slot (≤ 15 min) starts a new collector. Each source waits out its interval since its last stored poll, so a restart is never impolite.
- **No retry storm:** failures back off inside the collector (exponential, capped at 30 min, honouring `Retry-After`). BLOCKED / AUTH_FAILED stop that source.

**Environment:**

- cron runs `bash` with a minimal PATH.
- The runbook `cd`s to `backend/` and calls `.venv/bin/python` explicitly.
- Settings and flags come from `backend/.env` (pydantic settings); the token reaches the process only through the environment (`--token-from-dotenv`).
- Verified with an `env -i` cron-equivalent run on 2026-09-29 20:11 IST: it collected in production, and a concurrent second start was refused by the lock.

**Coverage gap 23:30–06:00:**

- The feeds are rolling windows, so items published overnight are knowable from the first morning poll, never back-dated.
- The Stage 3 news features need a successful poll within 2 h before `as_of` (08:59:59 / 09:08:00). The 06:00 start provides it.

## 4. Monitoring states (from `prajna news reconcile`)

| State | Meaning | Action |
|---|---|---|
| HEALTHY | — | — |
| COLLECTOR_DOWN | no poll for 3× the interval | check the cron log and `news_collect_<day>.log`; restart the runbook (the flock makes a double start harmless) |
| SOURCE_DOWN | BLOCKED / AUTH_FAILED, or no successful poll for 3× the interval | read the failures in the reconciliation; **never bypass a 403** |
| RATE_LIMITED | the latest poll was rate-limited | nothing: the collector honours `Retry-After` |
| FETCH_FAILURE | more than 20% of the last 10 polls failed | read the failures; NSE's truncated 200s (MALFORMED) are a known pattern |
| SOURCE_STALE | market hours, polls succeed, no new item for longer than the source's norm | check whether the source itself is stale (Indian Express, 2026-09-29) |
| UNUSUAL_VOLUME | stored items above 3× the trailing daily median | check for a feed change or a re-published backlog |
| UNUSUAL_DUP_RATE | duplicates above 30% | check for GUID/URL churn at the source |

**There is no alert channel in Prajna.** The states go to `var/status/news_health.json`, `prajna ops status` and the log markers. An alert channel is a later decision.

## 5. Stopping, rollback, recovery

| Action | How |
|---|---|
| **Stop everything now** | `prajna news kill on --reason "…"`. Every poll is refused at its next lock check (audited). The collector stops each source |
| **Stop one source** | set its flag to false in `.env`; its next poll is refused |
| **Leave PRODUCTION** | set `PRAJNA_NEWS_MULTI_SOURCE_ENABLED=false`. PRODUCTION polls are refused; rows already written stay (append-only) and remain point-in-time correct |
| **Undo a bad day** | **nothing is deleted.** Stage 3 v2 features read only PRODUCTION rows, so the fix is the kill switch plus a documented decision. A data correction would be a new, reviewed, append-only operation, never a DELETE |
| **Crash mid-poll** | the transaction rolls back (tested). The run row stays FAILED; the next poll re-fetches, and the rows it writes are the committed truth |
| **Migration 0015** | additive; back up first (`ops/runbooks/db_backup.sh --label news_pre_0015`), then `prajna db upgrade`. Downgrade drops only `news_decision` |

## 6. Daily checks

1. `prajna news reconcile --day <yesterday> --mode <M>` → invariants OK (exit 0); states reviewed.
2. `prajna ops status` → `news_collector.not_healthy` is empty, or explained.
3. Compare with Upstox (`upstox_articles` in the reconciliation). Multi-source coverage should be a superset for macro topics.
4. Disk: news rows are small. About 1,400 live items a day measured, plus observations and enrichments.
