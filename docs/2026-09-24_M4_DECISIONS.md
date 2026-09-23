# M4 decisions required before M4.5 (historical backfill)

**Prepared:** 2026-09-23 evening, from commit `d72df15` + live validation.
**Status:** NONE of the decisions below has been taken. Each needs explicit
approval. Evidence comes from real Upstox responses archived under
`backend/var/archive/` and the live DB validation in
[`2026-09-24_M4_LIVE_VALIDATION.md`](2026-09-24_M4_LIVE_VALIDATION.md).

### Measured inputs used below

| Input | Value | Source |
|---|---|---|
| Universe | 3,525 NSE_EQ + 3 indices = **3,528** | `instrument` table (M3.0) |
| Rate limit | 2000 / 30 min per API per user; limiter runs at **1,800 / 30 min** | Upstox docs; `vendor/upstox/rest.py` |
| Request span | 1m/5m/15m: 1 calendar month · 30m/1h: 3 months · 1D: 1 decade | measured 2026-09-23 (UDAPI1148 beyond) |
| Earliest data | 1D: 2000-01-03 · intraday: 2022-01-03 | measured |
| Bars per session | 1m 375 · 5m 75 · 15m 25 · 1h 7 (liquid names; illiquid SMEs fewer) | measured |
| Sessions 2022-01-03 → 2026-09-23 | ≈ 1,170 | estimate: 4.72 years × ~248 sessions |
| DB size | **≈ 585 B per `ohlcv_bar` row**, indexes included | measured on 1,540 rows |
| Archive size | ≈ 3–16 B per bar, gzipped | measured on real payloads |
| Free disk | ≈ 317 GB | `df`, 2026-09-22 |

---

## D1: historical depth per timeframe

Every figure is an **upper bound**: it assumes every instrument traded every
session of the range. Recent listings and illiquid SMEs have fewer bars. The
request figure is exact (one request per window, per instrument).

| Timeframe, depth | Requests | Runtime at 1,800/30 min | DB rows (upper) | DB size | Archive |
|---|---|---|---|---|---|
| 1D since 2000 | 3 decades × 3,528 = **10,584** | **≈ 2.9 h** | ≤ 23.5 M | ≤ 14 GB | ≈ 0.4 GB |
| 1h since 2022 | 19 quarters × 3,528 = 67,032 | ≈ 18.6 h | ≤ 28.9 M | ≤ 17 GB | < 0.5 GB |
| 15m since 2022 | 57 months × 3,528 = 201,096 | ≈ 55.9 h | ≤ 103 M | ≤ 60 GB | ≈ 1.5 GB |
| 5m since 2022 | 201,096 | ≈ 55.9 h | ≤ 310 M | ≤ 181 GB | ≈ 4 GB |
| 1m since 2022 | 201,096 | ≈ 55.9 h | ≤ **1.55 B** | ≤ **~905 GB** | ≈ 18 GB |
| 1m, last 6 months | 6 × 3,528 = 21,168 | ≈ 5.9 h | ≤ 164 M | ≤ 96 GB | ≈ 2 GB |
| 1m, last 1 month | 3,528 | ≈ 1 h | ≤ 27 M | ≤ 16 GB | < 0.5 GB |

Implications:
- **Full 1m history does not fit on this host.** ~905 GB against ~317 GB free.
- **Full 5m + 15m + 1h history** is ≈ 260 GB, about 130 h of fetching, and
  would fill the disk.
- **Is the depth required by Stage 1?** No Stage-1 document sets a depth. The
  diagram says "historical data" without a range. Depth is a research
  requirement of Stages 3–4 (feature windows, walk-forward), not of ingestion.
  Stage 1 needs a *correct, resumable* backfill mechanism (M4.3, done) and
  *some* verified history.

**Options, none chosen:**
- (a) 1D since 2000 only, plus a rolling 1m window (e.g. 1–6 months).
- (b) (a) plus 1h/15m since 2022.
- (c) Decide the depth in Stage 3 and keep Stage 1 at 1D since 2000 plus the
  daily incremental.

**Decision required:** the depth per timeframe.

---

## D2: vendor 5m/15m/1h, or derive them from 1m

**Evidence so far (one session, 2026-09-23, after the close, 4 instruments):**
- Vendor 5m/15m/1h for RELIANCE, HDFCBANK, NIFTY 50 and India VIX, compared
  with the same bars aggregated from the **persisted 1m bars**: **428 bars,
  0 mismatches** in O, H, L, C and volume.
- Earlier the same day, during the session: RELIANCE 5m/15m/1h against 1m:
  89 bars, 0 mismatches.
- **Behaviour while forming:** vendor 5m/15m/1h serve forming bars that change;
  a 5m bar changed up to 30.9 s after its end. 1m is never served forming.

**Implications:**
| | Vendor-fetched | Derived from 1m |
|---|---|---|
| Provenance | its own payload per bar (a direct vendor observation) | derived rows point at their 1m inputs; needs a derivation record, and a source value other than `UPSTOX_REST_V3` |
| Requests | + 3 × 1m's volume for history (≈ +470 k requests since 2022) | none extra |
| Revisions | each timeframe can change independently | follows 1m automatically |
| Forming-bar risk | real (settling margin of 120 s) | none beyond 1m |
| Correctness risk | none known | depends on 1m completeness; illiquid gaps propagate |
| Schema | none | probably a new `source` value, and possibly lineage columns (a migration) |

**Status: evidence only.** One session is not enough to prove equality in
general. More sessions are being recorded by the B1/B2 poller.
**Decision required:** vendor, derived, or both (derived kept as a check).

---

## D3: revisions

**Current policy** (M1/M2/M4, tested): same key + identical values = no-op;
same key + different values = **DUPLICATE_KEY FAIL**, the run rolls back, the
stored row is untouched. Nothing is overwritten and no second version is stored.

**Observed revisions:**
- **Same-day:** RELIANCE 1D (09-08..09-22) and 5m (09-22) re-fetched ~4.5 h
  apart were **byte-identical** (sha `add44abb…`, `783c6747…`).
- **Forming bars:** the intraday daily bar changed until ~16:02 IST (close
  adjusted at 15:52, volume +3,175 for RELIANCE on 09-23); 5m/15m/1h change
  while forming. These are *forming*, not revisions of completed bars, and are
  never persisted.
- **Long horizon:** not yet observed. Next-day comparisons are being recorded
  (B1 poller).

**Implications of versioned storage:** the `ohlcv_bar` PK has no observation
time, so storing versions needs a **migration**: `knowable_at` or
`fetched_at` in the key, as `fundamental_snapshot` already has. Readers would
then need an explicit "as of" rule.

**Decision required:** keep conflict = FAIL, or approve versioned storage (and
its migration).

---

## D5: all-day LTP / depth

Remains **Stage 7**, per M0 (`PRAJNA_TICK_PERSISTENCE_ENABLED=false`). The
WebSocket infrastructure can already record any window (proven with
2 × 2,000 keys). Persisting it would need `tick_archive` changes (a unique
observation key, ltt, cp, depth), i.e. a migration.

**Decision required only if** it should move into Stage 1.

---

## S1: universe series policy

**Unchanged:** NSE_EQ with series EQ/BE/SM/BZ/ST/IV. That excludes REIT `RR`
(6 instruments: EMBASSY, MINDSPACE, BIRET, NXST, KRT, BAGMANE), while InvIT
`IV` is included. Also excluded: D1 (1), E1 partly-paid (2), IT (1), SZ (1),
W1 warrants (1).

**Decision required:** include RR and/or any of D1/E1/IT/SZ/W1.

---

## S2: approved-source investigation (Upstox only)

The earlier "UNKNOWN" status is **superseded by Upstox's own documentation**.
All four exist on Upstox:

| Data | Upstox endpoint | Verified | Point-in-time field | Depth |
|---|---|---|---|---|
| **Corporate actions** | `GET /v2/fundamentals/{ISIN}/corporate-actions` ([docs](https://upstox.com/developer/api-documentation/get-corporate-actions/)) | **live 2026-09-23: HTTP 200**, sha `65f91512…` | `event_details` → "Announcement date" (**date only, no time**), ex-date, record date | RELIANCE returned **1 event** (June 2026 dividend). It looks like recent events only; history depth **UNKNOWN** |
| **Fundamentals** (8 endpoints: profile, balance sheet, cash flow, income statement, shareholding, key ratios, corporate actions, competitors) | `/v2/fundamentals/{ISIN}/…` ([announcement](https://upstox.com/developer/api-documentation/announcements/company-fundamentals-api/)) | docs only (except corporate actions) | statements are historical by period; **no report/announcement timestamp is documented**, so knowable_at would be fetched_at | UNKNOWN |
| **News** | `GET /v2/news?category=instrument_keys&instrument_keys=…` (≤30 keys, page ≤100) ([announcement](https://upstox.com/developer/api-documentation/announcements/news-api/)) | **live 2026-09-23: HTTP 200**, sha `c9e138d5…` | `published_time` (epoch ms) | page_size=5 returned 1 article; history depth **UNKNOWN** |
| **FII / DII activity** | under `/v2/market` ([announcement](https://upstox.com/developer/api-documentation/announcements/analytics-apis/)), launched 2026-05-11; data "from 1st April 2026" | **path UNVERIFIED**: the doc pages return 404 | UNKNOWN | from 2026-04-01 |

**Consequence:** B4 ("does Upstox expose FII/DII?") is now **yes, per Upstox's
docs**, with history only from 2026-04-01. No substitute source is needed or
used.

**Decision required:**
- which of the four are in Stage 1 scope;
- approval to probe the FII/DII endpoint and to measure the history depth of
  corporate actions and news, before designing their ingestion.

---

## P1: WebSocket knowable_at

**Measured (2026-09-23):** frame receipt − `currentTs` = **11–148 ms**
(median ~16 ms). `preopen_tick.knowable_at` = vendor `currentTs` (the M0
contract) is therefore earlier than the moment Prajna held the frame.

**Not changed.** Changing it alters the M0 contract `for_preopen_tick`.
**Decision required:** `knowable_at = fetched_at` for WebSocket rows, or keep
the vendor time and require consumers to read `fetched_at`.

---

## Survivorship

The `instrument` table is a **current** load: the 2026-09-23 master, rows
valid from 2026-09-23. Instruments delisted before that date are absent, and a
historical candle points at an instrument row that is valid from 2026-09-23.
**Historical survivorship is NOT solved.**

Upstox serves candles by `instrument_key`. Whether it serves delisted keys, or
historical masters at all, is **UNKNOWN**. The *Expired Instruments* API
listed in Upstox's Market Data docs is a lead for derivatives, not yet
investigated.

**Decision required:** accept a survivorship-biased equity history (documented
as such), or block the historical backfill until delisted coverage is known.
