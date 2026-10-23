# Yahoo Finance analyst data (RESEARCH ONLY, approved 2026-10-23)

**Approval.** The user wrote "approved yfinance research-only" on 2026-10-23, after the comparison in the session:
- numeric analyst consensus for NSE names has no free, compliant source;
- Twelve Data has it only on its Ultra plan ($999/month);
- Yahoo has it, through the unofficial yfinance library, for about 200–300 covered names.

## What it is and what it is not

- **Not a production source.**
  - Nothing writes the Prajna database.
  - Nothing is read by Stage 3, Stage 4, E5, E6, the dashboard or any model. Prajna's stored market data stays Upstox-only.
- **Output:** append-only files under `backend/var/research/yahoo/`:
  - `<day>.jsonl.gz`: one line per symbol;
  - `<day>.manifest.json`: counts and sha256;
  - `coverage.json`;
  - `universe_<day>.csv`.
  A file that exists is never overwritten.
- **Point in time.**
  - A value is knowable to Prajna only from its line's `fetched_at`.
  - Yahoo publishes no revision dates. `eps_trend` gives 7/30/60/90-day-ago values, but not when each estimate was made.
  - The history in `earnings_dates` (about 24 quarters of estimate vs reported EPS) is Yahoo's current view of the past. It is research **AS_IF / ASSUMED** data and may have been revised.
- **Terms.**
  - yfinance is not an official Yahoo API.
  - Yahoo's terms restrict automated collection and any commercial use or redistribution.
  - This is personal research only. Nothing is redistributed or shown on the dashboard.
- **Environment.**
  - A separate venv, `backend/.venv-research`, with yfinance pinned to 1.7.0.
  - It is never installed into the production venv, whose packages the frozen E5 model depends on.

## Fields per symbol

`earnings_estimate`, `revenue_estimate`, `earnings_history`, `eps_trend`, `eps_revisions`, `growth_estimates`, `recommendations` (strong buy … strong sell, last 4 months), `analyst_price_targets`, `earnings_dates`.

## Schedule (`ops/runbooks/yahoo_research.sh`, installed 2026-10-23)

| When | Universe |
|---|---|
| Mon–Fri 18:20 IST | the covered names in `coverage.json` |
| Saturday 10:20 IST | every ACTIVE NSE_EQ name with a median traded value ≥ ₹5 cr over the last 20 sessions (about 1,100). This refreshes `coverage.json` |

- **The first run is always full.**
- **Rate limits:** three consecutive rate-limit errors stop the run (STOPPED_RATE_LIMIT). The next run starts over; nothing is retried in a loop. Auto-Trade Pro (V1) saw that a hammered Yahoo session does not recover.

## Known data-quality issues (seen 2026-10-23)

- **Coverage:** in a sample of 18 names:

  | Group | Coverage |
  |---|---|
  | Large caps | 5/6 with full data |
  | Mid caps | 2/6 full, 2 partial |
  | Small caps | 0/6 |

  V1 found the same in 2026-08: 6/18 with any coverage.
- **Inconsistent values:** RELIANCE shows two different estimates for the Jun-2026 quarter (14.97 in `earnings_history`, 7.10 in `earnings_dates`), zeros in `eps_trend`, and a revenue growth of +134 %. Every study must check consistency.
- **Normalised EPS:** "Reported EPS" is Yahoo's comparable figure, not the statutory EPS. For example, TCS Dec-2025 is 36.59 on Yahoo against about 29.6 from the statutory profit. A surprise must use Yahoo's own pair.
- **Upgrades / downgrades:** empty for NSE names.

## Planned studies (exploratory; never inside a research TEST window)

1. **Surprise vs drift.** Join `earnings_dates` (estimate vs reported) to the NSE results dates (F4) and the E6 event study. Question: does the numeric surprise separate the drift better than the price reaction? Data: up to 2026-10-21 only.
2. **Revisions.** After a few months of daily snapshots: do estimate revisions (`eps_trend`, `eps_revisions`) predict the next weeks?

A result here becomes an input only through its own pre-registration and the user's approval of Yahoo as more than a research source.
