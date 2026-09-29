# Audit: all-day live LTP / depth capability

**Audited:** 2026-09-29, read-only, at HEAD `17c4617` plus the working tree.

**Verdict: NOT IMPLEMENTED in production.**

- A WebSocket **recorder** exists and has been validated live, but it is used only for the pre-open window.
- **No component captures or stores LTP or depth during the trading session.**
- This absence is a recorded decision, not an accident: **D5** (APPROVED by the user, 2026-09-24) reads "all-day LTP/depth persistence stays in Stage 7; recorder capability kept; pre-open persisted". Stage 1 criterion L is OUT_OF_SCOPE accordingly.

## 1. What exists (DIRECT evidence)

| Component | State | Evidence |
|---|---|---|
| WebSocket recorder `app/sources/upstox_preopen_ws.py` | **built; runs daily for the pre-open window only** | Protobuf v3 feed, `full` mode (served as `full_d5`: LTP, LTQ, ATP, volume, OI, buy/sell quantity, IEP/IEQ, **5 depth levels**). It has event-driven readiness, ping/pong, a 60 s stale watchdog, bounded reconnects with a fresh authorisation each time, and archive-first writes (bytes on disk before any parsing) |
| Capacity | measured | **2,000 keys per connection** in `full` mode, enforced silently; 2 connections cover the universe (3,527 of 3,527 keys served, 2026-09-24) |
| Scheduling | pre-open only | cron `25 8 * * 1-5` → `preopen_day.sh`: capture 08:55–09:20, then replay into `preopen_tick` / `preopen_book` from 09:20 (finished 09:32 on 29 Sep) |
| `tick_archive` table | **schema only, 0 rows** | writer disabled by `PRAJNA_TICK_PERSISTENCE_ENABLED` (default false). Its columns are LTP, LTQ, VTT, ATP, TBQ and TSQ; it has **no depth columns** |
| Dashboard WebSocket `backend/app/api/ws.py` (another tool; not modified) | **not live market data** | Every 2 s it re-broadcasts the **latest stored `ohlcv_bar`** for each subscribed key as `"type": "tick"`. During a session the newest stored bar is the previous day's (intraday bars are stored after the close), so the messages carry `stale: true` (age > 180 s). It opens no Upstox connection. It runs under the `uvicorn app.api.app` process (PID 1126488, up 3 days) |
| Intraday OHLCV | after the close, not live | the 16:05 close job; newest 1m bar 2026-09-28 15:29 |

## 2. Measured load (continuous trading, from the pre-open capture's last 5 minutes)

| Measure | 2026-09-28 | 2026-09-29 |
|---|---|---|
| Ticks per minute, 09:15–09:19 (`full`, 3,5xx keys) | 31,528 – 33,276 | 32,369 – 33,157 |
| Ticks 09:15–09:20 / instruments ticking | — | 164,057 / 3,393 |
| Ticks per minute in pre-open order entry, 09:00–09:08 | ~21,300 | ~21,400 |
| DB bytes per tick in the current schema (`preopen_tick` + 5-level `preopen_book`) | 1,061 (809 MB + 843 MB for 1,557,588 ticks) | |
| Raw archive per tick (gzip frames) | ~120 B (47.7 MB for 395,746 ticks) | |
| Replay throughput (archive → DB, after the window) | 395,746 ticks in ~12 min (09:20:01 → 09:32:05), i.e. **about the live rate** | |

## 3. Projection for a full session (DERIVED; not measured)

This extrapolates the **opening five minutes**, which are probably the busiest, to all 375 minutes (09:15–15:30).

| Quantity | Projection | Basis |
|---|---|---|
| Ticks per day | **~12.3 million** (upper-bound estimate) | 32,800/min × 375 |
| DB growth per day, current schema with depth | **~13 GB** | × 1,061 B |
| Raw archive per day | **~1.5 GB** | × 120 B |
| Days until the 60 GB safety floor, from 298 GB free | **~18 trading days**, DB schema only | (298 − 60) / 13 |
| After-the-fact replay per day | **~6 hours** at the measured replay rate | 12.3 M ÷ ~33 k/min |

**Midday tick rates are UNKNOWN:** no session-hours capture has been stored. The first measurement needed is a full-day **archive-only** capture (no database writes), about 1.5 GB of disk.

## 4. What is missing for a live capability

1. **All-day process.** The recorder runs one fixed window. Needed: an all-day supervised process (09:15–15:30), restart on failure, and alerting. Today there is no alerting anywhere (see `docs/ARCHITECTURE_LIVE_STATUS.md`, Stage 8).
2. **Storage design.** At ~13 GB/day the current row-per-tick-plus-book schema is not sustainable on this disk. `tick_archive` stores no depth at all. Retention, compression or aggregation (for example 1-second or 1-minute LTP and top-of-book), and whether depth is kept at all, are **undecided design questions**.
3. **Streaming ingestion.** Replay after the window only just keeps pace with the live rate. An all-day stream needs incremental, live insertion or aggregation, not a replay after the close.
4. **Point-in-time contract for live ticks.** It exists for pre-open (`knowable_at` = vendor `currentTs`, decision P1) and would carry over. A tick-to-bar consistency check against the vendor's 1m bars is not built.
5. **A consumer.** Nothing in Stages 3–7 uses intraday ticks today. Stage 3 features are two pre-session snapshots, and Stages 4–7 do not exist. D5 places this capability in **Stage 7**, with execution.
6. **Upstox limits during the session.** Per-connection key cap 2,000 (measured). Whether full-universe `full` mode is served for 6 hours without throttling is **UNKNOWN**: the longest measured session is 25 minutes (08:55–09:20), with 12 watchdog reconnects on 24 Sep in quiet periods.

## 5. Classification

| Item | Status |
|---|---|
| All-day live LTP capture | **NOT IMPLEMENTED** (recorder capability exists, pre-open only) |
| All-day depth capture | **NOT IMPLEMENTED** |
| Storage of live ticks | **NOT IMPLEMENTED** (schema only, writer disabled, no depth columns) |
| Live tick delivery to a consumer | **NOT IMPLEMENTED**. The dashboard's "tick" stream replays stored bars |
| Decision | **D5 APPROVED**: Stage 7 scope. Changing it is the user's decision |

**Smallest evidence-gathering next step, if wanted:** one full session captured **to archive only**. It uses the existing recorder with a longer window and writes nothing to the database. It would measure the real all-day tick rate, reconnects and archive size before any storage design is chosen.
