# Stage 1: daily corporate-action refresh, proposed design (PLAN ONLY)

**Status:** PROPOSED 2026-10-15, read-only analysis. No schedule, cron, code or production refresh was changed or run.

## 1. Why

**Three incidents in a week**, all blocking Stage 1 F, then S, then the Stage 3 lock. The vendor re-served adjusted history for a split/bonus our database did not yet hold:

| Instrument | Action | Ex-date |
|---|---|---|
| MOLDTECH | BONUS 1:1 | 2026-10-09 |
| MOLDTKPAC | BONUS 1:1 | 2026-10-09 |
| OLIL | BONUS 1:2 | 2026-10-15 |

**Measured vendor behaviour:**
- **The vendor lists an action only near its ex-date.**
  - Across 2,344 stored events, the maximum of (ex-date − first fetch) is 0 days (Stage 3 audit, 2026-10-13).
  - OLIL, announced 2026-09-04, was absent in the weekly sweeps of 2026-09-26, 10-03 and 10-10: each completed with 0 rows written.
  - The `GET /v2/fundamentals/INE0OPS01011/corporate-actions` of 2026-10-15 13:28 IST lists it.
- **The vendor applies the adjustment to the 1D history no later than the morning of the ex-date.** The 07:03 IST ingest of 2026-10-15 received the adjusted history.

## 2. Current implementation (inspected)

| Item | Current |
|---|---|
| Full sweep | `daily.sh weekly`, Saturday 10:00 cron: `ingest corporate-actions --commit` over every current NSE_EQ ISIN. 2026-10-10: 73 runs, 3,577 ISINs; the sweep ran about 10:30–12:33 IST (the 06:30 run that day was the daily new-listing refresh); 6 rows. Rate fraction 0.3, about 2 h. |
| New listings | `daily.sh refresh` (06:30 daily): only ISINs first seen as new listings |
| Endpoint | one request per ISIN: `GET /v2/fundamentals/{isin}/corporate-actions` |
| Write semantics | identical event: no-op; new: insert; changed content: insert + WARN (`app/ingest/corporate_actions.py`). The raw payload is archived. `knowable_at` = announcement end of day, observed at the fetch (CA-OBSERVED). |
| Derive | `derive ca-factors` daily at 06:40 (global upsert of every factor); `price-basis` insert-only |
| Rate limits | the shared in-process limiter at 90% of the vendor window; a 429 stops without retry and keeps the checkpoint (`app/vendor/upstox/rest.py`). There is no cross-process limiter. |

## 3. Proposed design

**Option D1 (recommended): a targeted daily sweep before the morning candles.**

1. **06:45 IST daily (Mon–Fri):** `ingest corporate-actions --commit` over all about 3,580 current NSE_EQ ISINs.
   - Measured: about 3,577 ISINs took about 2 h at fraction 0.3 on Saturday, i.e. about 0.5 requests/s. At fraction 0.5 that is still about 1.2 h, which collides with the 07:00 morning candles.
   - **A full daily sweep does not fit before 07:00. Hence D1 targets.**
2. **D1 targeting:** sweep only ISINs that could have an action **today or tomorrow**, from evidence available before 06:45:
   - (a) NSE announcements, `news_item` source NSE_ANNOUNCEMENTS (already ingested from 2026-09-28): categories "Bonus", "Split", "Record date", "Corporate action", and board-meeting outcomes mentioning bonus or split, within the last 60 days;
   - (b) every ISIN whose 1D stream FAILED yesterday or today with `DUPLICATE_KEY` / D3 UNEXPLAINED (the OLIL signature);
   - (c) a rolling 1/5 of all ISINs each weekday, so every ISIN is swept at least weekly. The Saturday full sweep stays.
   - Expected size: about 20–100 ISINs plus about 715 rolling, 5–15 min at fraction 0.5. That fits 06:45–07:00 only for (a)+(b), so run (c) at 16:30 after the close.
3. **07:00 morning candles:** unchanged. They now find the action already stored, record the revision as `CA_ADJUSTMENT` observations, and the stream is COMPLETE.
4. **Self-heal for misses:** after the morning candles, any 1D stream that FAILED with D3 UNEXPLAINED triggers a single-ISIN `ingest corporate-actions --isin <ISIN> --commit`, then one bounded re-ingest of that key's 1D history (last 10 sessions), then `derive price-basis` / `derive ca-factors`. This is the OLIL procedure, automated and **bounded to the failing keys**.
   - It needs an explicit design decision, because it performs writes without a human in the loop.

**Option D2:** keep weekly, and make OLIL-type failures a documented manual runbook (what was done for MOLDTEK and OLIL). It costs a Stage 3 day per incident.

## 4. Expected data changes (D1)

- **`corporate_action`:** only genuinely new events (a few per week, 6 on 2026-10-10). Inserts only.
- **`ohlcv_observation`:** `CA_ADJUSTMENT` rows for re-served pre-ex bars. Stored bars are never overwritten.
- **`ca_factor`:** one new row per new event. The daily global upsert rewrites `derived_at` / `run_id` for all rows, as today.
- **No change** to features, registry, labels or Stage 4.

## 5. Operational risks and mitigations

| Risk | Mitigation |
|---|---|
| Rate-limit contention with the 07:00 morning candles (no cross-process limiter) | Finish before 07:00 (targeted set only); `flock` the candles lock; rolling sweep at 16:30, which must not overlap the 16:05 close job: take the same lock |
| A vendor CA listing is still absent at 06:45 on the ex-date | The self-heal (step 4) after the morning candles. Otherwise the D2 manual runbook. |
| Announcement parsing misses an action | The rolling + weekly full sweeps, and the (b) failure trigger |
| Global `derive ca-factors` side effects | As today (06:40 daily); compare value-level diffs in the run summary |
| Token expiry | The existing single daily TOTP login (standing approval, 1 per day) is at 06:30; the 06:45 job reuses it |

## 6. Monitoring

- Daily log line `CA_REFRESH targeted=N rolling=M inserted=K failed=F`.
- `ops/runbooks/maintenance.sh status` reports the latest CA refresh age.
- **An alert condition:** any 1D stream FAILED with D3 UNEXPLAINED after 07:30.
- Stage 1 acceptance F/S remains the gate. Nothing bypasses it.

## 7. Rollback

- A cron line removal reverts the schedule.
- The data is insert-only. Erroneous `corporate_action` rows are identified by `run_id`. Removing one needs a backup and its own approval, as any production delete does.
- The self-heal can be disabled with a flag (proposed `PRAJNA_CA_SELF_HEAL=false`, default false until approved).

## 8. Approvals needed (none requested yet)

1. D1 vs D2.
2. The code for target selection, the rolling sweep and the self-heal, with tests.
3. The cron lines (06:45 targeted, 16:30 rolling) and the self-heal flag.
