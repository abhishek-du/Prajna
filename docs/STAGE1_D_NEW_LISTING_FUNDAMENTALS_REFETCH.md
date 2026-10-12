# Stage 1 D: new-listing fundamentals re-fetch, 2026-10-12 (Option 1)

**Approval:** Option 1 only (Options 2 and 3 not authorised).

**Instruments:**
- ORIENTCABL `NSE_EQ|INE0J1N01028`
- BLSE `NSE_EQ|INE0NLT01028`
- BUILDPRO `NSE_EQ|INE24OJ01029`
- TRIVENIPT `NSE_EQ|INE2WKE01011`

**Backup:** `var/backups/prajna_20261012T1427_newlisting_fund_refetch.dump` (verified).

## Why Stage 3 was refused on 2026-10-12

- Stage 1 D failed: REVIEW = 1 outside the 7-day grace (ORIENTCABL, first seen 2026-10-02), plus 3 inside the grace.
- All four were REVIEW only because the vendor had served no key ratios or shareholding when they listed. Fundamentals of a new listing are fetched once, on its first day, then monthly.

## Vendor calls: 48 (12 endpoints × 4 ISINs)

Run `07330374-acd9-41f1-8083-2636b78792bb`, 2026-10-12 14:39:50–53 IST, the normal `prajna ingest fundamentals --isin …` path.

- Result: 47 DATA, 1 EMPTY. 39 new snapshots (content changed); 8 unchanged.
- 1 WARN: ORIENTCABL shareholding period "Oct 2026" ends after the fetch. It is kept as sent, as the ingest does for every such case.

| Instrument | key_ratios | share_holdings | competitors | Profile sector |
|---|---|---|---|---|
| ORIENTCABL | 7 ratios | 5 categories | 10 | Cables |
| BLSE | 7 ratios | 5 categories | 10 | DVR |
| BUILDPRO | 7 ratios | 5 categories | 10 | Trading |
| TRIVENIPT | **EMPTY** | 5 categories | 10 | Engineering |

## Classification (existing path: `prajna classify securities`)

- **Dry run** (run `9ddd2246`): changed = 4, exactly these four keys; REVIEW = []. Committed only after that.
- **Commit** (run `c5113a29-d726-4620-b400-56db08f0e0be`): all four are **STOCK / CLASSIFIED**, "company equity with financials (signals: isin, financials)".
  - ORIENTCABL, BLSE, BUILDPRO: financials vote from sector and key ratios.
  - **TRIVENIPT: financials vote from the profile sector only** (key ratios EMPTY). This is within the existing rule `financials_vote`: sector or key ratios / shareholding → FINANCIALS.

**Unchanged:**
- The other instruments' classifications: md5 over class, subclass, status, signals and reason is identical, `5630b099…`. The global upsert rewrote only `classified_at` / `run_id`, as the daily 06:30 run does.
- Their fundamentals: 48,493 rows, max id 48,529.
- `feature_value` (801,434) and `stage3_event` (38).
- Cron (sha `dbc5b41b…`) and flags.

## Gates (actual)

| Gate | Result |
|---|---|
| `prajna acceptance stage1` | **COMPLETE**: D PASS (REVIEW 0, in-grace 0, unclassified 0, coverage 100%, eligible stocks 3,198); S/G/I/J DEFERRED (BACKFILL-DEFER); failing [] |
| `prajna stage3 locks` (read-only) | **RUN: UNLOCKED**, 7/7 |

No Stage 3 run was started. The next scheduled runs are 2026-10-13 at 09:00:30 and 09:22. Stage 1 is re-evaluated then.

## Findings and remaining

1. **Latent classifier bug (reported, not fixed).**
   - `security_class.classify_securities` tests `statement_type in ('key_ratios', 'shareholding')`, but the ingest stores `share_holdings`. So shareholding never counts as a financials signal.
   - It did not change today's result: the three with ratios had them; TRIVENIPT has a sector.
   - A fix needs a separate approval.
2. **Structural (Option 3, not authorised).** New listings get fundamentals once, on day one, then monthly. Any new listing whose vendor financials arrive later stays in REVIEW and fails D after 7 days. This will recur.
3. **Grace policy (Option 2, not authorised):** unchanged.
4. Stage 3 E and the news gate P stay PENDING until a scheduled Stage 3 run succeeds.
