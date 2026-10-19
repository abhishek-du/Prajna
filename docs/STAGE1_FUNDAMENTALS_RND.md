# Stage 1: fundamentals, R&D and build (approved 2026-10-19; BUILT, not yet on production)

**Question (user, 2026-10-19):** what is the best way to get fundamentals so that Stage 1 can be called 100% complete?

## 0. Correction

The status reply of 2026-10-19 said "only shareholding snapshots exist". **That was wrong.**

- Prajna has collected the Upstox fundamentals suite since 2026-09-24: `app/ingest/fundamentals.py` → `fundamental_snapshot` (append-only) → `canon_fundamental`.
- It is scheduled monthly (1st of the month, 11:00).

| Statement (production, 2026-10-19) | ISINs | Rows |
|---|---|---|
| income, consolidated / standalone, quarterly + yearly | 2,529–3,215 | ~16,900 |
| balance sheet, consolidated / standalone | 2,474–3,211 | ~7,600 |
| cash flow, consolidated / standalone | 2,481–3,211 | ~7,400 |
| share holdings (quarterly) | 3,208 | 3,217 |
| key ratios, profile, competitors | 3,203–3,582 | ~15,200 |

**`knowable_at` = the fetch time.** Its basis is "upstox fundamentals (no filing/publication time)", `knowable_at_verified = false`. From 2026-09-24 this is point-in-time safe, but late by up to a month.

## 1. What the sources offer (verified)

### Upstox Company Fundamentals API (launched 2026-05-11)

- **Endpoints:** profile, balance sheet, cash flow, income statement (yearly / quarterly), share holdings, key ratios, corporate actions, competitors. All are under `/v2/fundamentals/{isin}/…`.
- **Probe 2026-10-19 (read-only GETs, RELIANCE and TCS):**
  - every statement returns **4 periods only** (4 quarters or 4 years);
  - there is **no filing or announcement date**, only period labels;
  - key ratios are a **current snapshot** (P/E, P/B, ROA, ROE, ROCE, EV/EBITDA plus the sector value);
  - `competitors` refuses an ISIN (it wants an instrument key);
  - TCS already shows the Sep 2026 quarter (results about 2026-10-09). The data is updated within days.
- **Consequence:**
  - **forward** point-in-time collection: yes, by snapshotting;
  - **history:** about one year deep;
  - **as-first-reported values:** none;
  - **dissemination time:** none.

### NSE

- **Announcements RSS** (`Online_announcements.xml`, already a production news source since 2026-09-29, NEWS-COMPLIANCE scope: headline, summary, URL, timestamps). It carries the results events with an exchange timestamp:

  | Category | Rows since 2026-09-28 |
  |---|---|
  | Board Meeting Intimation (the future results date) | 757 |
  | Outcome of Board Meeting | 516 |
  | Financial Results Updates | 31 |
  | Outcome of Board Meeting-XBRL | 31 |
  | Integrated Filing- Financial | 7 |

- **`Financial_Results.xml` RSS:** **stale.** On 2026-10-19 it holds 4 items, the latest 2026-08-24, all legacy filings. Results now go through Integrated Filing, so this feed is not usable.
- **Financial Results / Integrated Filing JSON + XBRL archive:**
  - legacy data from FY2015-16, integrated data from 2025, with filing dates;
  - **not an official API**;
  - **NSE's Terms of Use prohibit systematic or automated extraction (scraping, data mining) and redistribution without written permission**;
  - the same pages **offer a CSV export**, which is a manual, human download.

### Paid, licensed vendors (not contacted)

- **Options:** CMIE Prowess (the reference Indian fundamentals database), ACE Equity / Capitaline, CMOTS, TrueData (6+ years standardised, exchange PDF links), FinEdge (P&L, balance sheet and cash flow REST, XBRL).
- **None of them documents point-in-time, as-first-reported history with dissemination timestamps.** That must be asked before buying.

### Analyst earnings estimates

- No free or compliant source was found. Refinitiv, Bloomberg and Trendlyne-type data are paid.

## 2. Proposal (best approach)

**Principle: Upstox stays the only market-data vendor.** NSE is used only through the already-approved announcements RSS. Nothing is scraped.

| # | What | How | Point-in-time |
|---|---|---|---|
| **F1** | **Event-driven refresh** | A daily job after the close. For every ISIN with a results event in the NSE announcements since the last run (Outcome of Board Meeting, Financial Results Updates, Integrated Filing- Financial, Outcome-XBRL), refetch income (quarterly + yearly), balance sheet, cash flow and share holdings. That is about 50–150 ISINs per day in results season, about 1–2k Upstox GETs. The monthly full sweep stays | `knowable_at` stays the fetch time. The NSE event (exchange timestamp < fetch) is linked as evidence; `knowable_at_verified` = true only when such an event exists |
| **F2** | **Results calendar** | Parse Board Meeting Intimation ("to consider … financial results … on <date>") into an append-only `results_calendar`: ISIN, meeting date, period, announcement time | Knowable at the announcement's timestamp. Feeds the "avoid earnings day" filter (diagram Stage 5) and event features (days to results, results today) |
| **F3** | **Ratios computed by us** | P/E and P/B daily from the PIT price and the TTM EPS / book value of F1's snapshots. The vendor's key-ratios snapshot stays a cross-check | Fully PIT, daily, no extra requests |
| **F4** | **History before 2026-09-24** | Values: **NOT_AVAILABLE_HISTORICALLY** (the existing Stage 4 policy, never zero). Results dates: optional, from a **manual** NSE Financial Results CSV export by the user (2022–2026, offered for download), loaded once with provenance | The dates are exact. Values only from a licensed vendor (a cost decision) |
| **F5** | **Earnings estimates** | **In scope (user, 2026-10-19):** F5a seasonal-random-walk expectation, F5b street verdict from headlines, F5c numeric consensus needs a licensed vendor (§5) | F5a and F5b are point-in-time by construction |

**Stage 1 acceptance would gain criterion FUND.** It PASSES when, over 10 sessions:
- F1 refreshed every ISIN with a results event within 1 trading day, with `knowable_at` > the event's timestamp;
- F2 parsed at least 95% of the results intimations (the rest listed);
- no `fundamental_snapshot` row has `knowable_at` < `fetched_at`;
- F4's and F5's status is recorded.

**Then Stage 1 is 100%:** all collectable data is collected point-in-time, and what cannot be collected is named, with its reason.

## 3. Not recommended

- **Automated NSE JSON / XBRL downloading:** NSE's Terms of Use forbid it. The community tools are unofficial, rate-limited (6 s spacing with backoff, Oct 2026) and can break.
- **Backdating Upstox values to period end + the SEBI deadline (45 / 60 days) as AS_IF history:**
  - Upstox shows the *latest* values, so restatements would leak;
  - only about one year exists anyway.
  - If ever wanted, it stays research-only, flagged ASSUMED.

## 4. Decisions (user, 2026-10-19)

"haan F1 F2 F3 f4 shuru karo, 5m 12 mahine theek hai OR ISKO SCOPE MAI LAAO 5. F5":
- F1–F4 approved.
- 5m approved for 12 months.
- **F5 is brought into scope** (it is no longer OUT_OF_SCOPE).

## 5. Built (2026-10-19)

| Part | Code | What |
|---|---|---|
| Migration 0023 | `results_event`, `fundamental_refresh` (append-only) | Applied to `prajna_test`. **Production after a backup**, in the daytime window |
| F2 + F1 trigger + F5b | `app/fundamentals/events.py` (pure), `store.extract_events`, `prajna fundamentals events` | Real data, 2026-09-28..10-19: 652 results intimations parsed (641 with meeting date and period; 11 periods dropped as impossible, e.g. "June 2027" in October 2026, flagged `PERIOD_AFTER_MEETING`); 216 outcomes; 20 estimate headlines (16 BEAT, 4 MISS) |
| F1 | `store.refresh`, `prajna fundamentals refresh`, `ops/runbooks/fundamentals_events.sh` | One Upstox run per due ISIN (batch 1). Cron proposed 13:15 daily, commented `APPROVED_NOT_INSTALLED` in `ops/cron/prajna.cron` |
| F3 + F5a | `app/fundamentals/ratios.py` (pure), `store.ratios_as_of`, `prajna fundamentals ratios KEY [--as-of]` | Share count from **standalone** PAT / EPS: TCS 3.618 bn, RELIANCE 13.53 bn, INFY 4.12 bn, HDFCBANK 15.36 bn. Consolidated overstated RELIANCE at 16.0 bn |
| F4 | `store.import_results_csv`, `prajna fundamentals import-results-csv FILE` | Waits for the user's CSV export (below) |
| FUND | `store.fund_report`, `prajna acceptance fundamentals` | A report only; not wired into the Stage 1 gate until it PASSES |

**Bug found while building:** a float threshold 0.9 is bound by asyncpg as numeric 0.9000000000000000222…, which silently excluded every 0.900-confidence link. That is almost every NSE announcement link. It is now a `Decimal`, and a test covers it.

### F5 in scope

- **F5a (built):** the analyst-free expectation, a seasonal random walk (Foster, Olsen & Shevlin 1984). It covers every name with stored quarters, from the first quarter whose year-ago quarter was snapshotted (the Sep 2026 results onward).
- **F5b (built):** the street's verdict (BEAT / MISS / INLINE / MIXED) from results headlines of the already-approved news sources. It covers about the 100–200 most-followed names.
- **F5c (numeric consensus EPS, needs a decision):** no free or compliant source exists.
  - **Twelve Data:** `/earnings_estimate` and `/eps_trend`, NSE listed, a documented API.
  - **LSEG I/B/E/S:** the reference, enterprise priced.
  - **Trendlyne Forecaster:** about 900 companies; an API only on request.
  - Yahoo pages are not an API, and their terms forbid scraping.
  - The choice needs the user's budget and a new secret in `.env`.

### F4: how to export the CSV (a manual download, allowed by NSE's terms)

1. Open nseindia.com → Companies Listing → Corporate Filings → Financial Results.
2. Pick a date range (2022-01-01 onward, one year at a time if the site limits it) and choose **Download (.csv)**.
3. Save the files under `backend/var/imports/nse_results/`. Claude runs `prajna fundamentals import-results-csv <file>` (a dry run first). The loader refuses a file without symbol, period-ended and broadcast columns, and lists the header it saw.

## 6. Decisions requested (earlier)

| # | Decision | Proposed |
|---|---|---|
| FD1 | Build F1 + F2 + F3 and criterion FUND | Yes |
| FD2 | History (F4) | Values NOT_AVAILABLE_HISTORICALLY; the results-dates CSV only if you export it from NSE yourself |
| FD3 | Paid vendor for as-reported history | Not now; ask CMIE / ACE about point-in-time first, if fundamentals ever become a strategy input |
| FD4 | Earnings estimates | OUT_OF_SCOPE |

## Sources

- https://upstox.com/developer/api-documentation/announcements/company-fundamentals-api/
- https://upstox.com/developer/api-documentation/get-income-statement/
- https://upstox.com/developer/api-documentation/get-key-ratios/
- https://upstox.com/developer/api-documentation/get-share-holdings/
- https://upstox.com/developer/api-documentation/get-balance-sheet/
- https://www.nseindia.com/companies-listing/corporate-filings-financial-results
- https://www.nseindia.com/static/nse-terms-of-use
- https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml
- https://www.tigzig.com/vigil/india-xbrl-filings
- https://github.com/dhananjaym182/india-xbrl-filings
- https://www.truedata.in/products/marketdataapi
- https://www.finedgeapi.com/
- https://tradingqna.com/t/what-are-api-for-getting-fundamental-data-for-stocks-trading-in-nse-india-free-or-paid/145292
