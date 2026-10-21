# Stage 3: features-v5 (APPROVED 2026-10-21; ACTIVE from the 2026-10-22 PRE_SESSION run)

**Decision FEATURES-V5** (user, 2026-10-21: "sab approve hai you go ahead"). The aim is that every item of the Stage 3 diagram is either implemented or OUT_OF_SCOPE with its reason named. Nothing is left silently unsupported.

## What v5 changes

| Diagram item | Before (v4) | v5 |
|---|---|---|
| Support / resistance | 20-session range | + `dist_high_252`, `dist_low_252` (52-week range) |
| Valuation ratios | vendor `pe`, `pb` (snapshot about monthly) | + `pe_ttm`, `earnings_yield_ttm`, `pb_own`: previous close with the fundamentals history known at as_of (F3) |
| Earnings surprises | UNSUPPORTED | `eps_surprise_srw`, `eps_surprise_srw_price` (seasonal random walk, F5a) and `street_verdict_90d` (BEAT +1 / MISS −1 / INLINE, MIXED 0, F5b). Numeric consensus (F5c) is OUT_OF_SCOPE until a vendor is chosen |
| Earnings dates | UNSUPPORTED | `results_days_to_next`, `results_today`, `results_days_since`, from NSE announcements (intimations and outcomes) |
| Analyst upgrades / downgrades | UNSUPPORTED | `analyst_upgrades_30d`, `analyst_downgrades_30d` (rule-based `analyst-v1` on headlines linked to exactly one company) |
| News sentiment | volume / recency only | + `mnews_company_sentiment_24h`, `_3d` (mean rule-based headline direction `assess-v1`; not a language model) |
| Market regime | UNKNOWN | `market_regime_trend` (`regime-v1`: NIFTY 50 close and SMA50 vs SMA200: +1 / −1 / 0) and `india_vix_pctile_252` |
| Sector / market events | UNKNOWN | market-wide events as the existing scope counts; sector-level events OUT_OF_SCOPE (no definition in any source) |
| Bid-ask spread, order book | UNSUPPORTED | OUT_OF_SCOPE: needs an all-day tick store (Stage 1 L); the pre-open imbalance exists |
| `ca_days_to_*` | never had a value | registered UNSUPPORTED (CA-TO-UNSUPPORTED, prepared 2026-10-13) |

The registry has 104 v4 features. v5 adds 17 and keeps the four `ca_days_to_*` registered, but they are no longer computed.

## Point in time

- **Results events** are parsed at the snapshot from the news rows visible then (`app/canon/results_pit.py`):
  - news item and link both `knowable_at < as_of`, PRODUCTION polls only;
  - the text as of the latest observation before as_of;
  - the same parser as `results_event` (`results-events-v1`).
  - The `results_event` table is filled at 13:15, so reading it would give a live snapshot less than a later recompute. Parsing at the snapshot gives both the same.
- **Coverage:**
  - before the NSE announcements source's first successful PRODUCTION poll (2026-09-29), every results feature is MISSING_INPUT;
  - `results_days_since` stays MISSING_INPUT for the first 120 days without an outcome;
  - the analyst counts are MISSING_INPUT until 30 days of news coverage (2026-10-29) and whenever news coverage is not NORMAL.
- **Fundamentals history:** every snapshot knowable before as_of (`pit.fundamentals_history`), merged by `app/fundamentals/ratios.py`. A split or bonus after the share-count fiscal year makes the share-based values MISSING_INPUT; the vendor gives no share count, so no factor is guessed.

## Activation (like FEATURE-NEWS-V2)

1. The canary, `ops/measure/features_v5_canary.py` (read-only, the whole universe), runs on real snapshots: PIT, v4 rows unchanged, determinism, an independent SQL recount of the results calendar, own vs vendor P/E, coverage and time. Evidence goes to `audit/evidence/features_v5_canary_<session>_<kind>.json`.
2. When it passes on 12 snapshots (6 sessions × 2), `FEATURES_V5_ACTIVE = True` at a session boundary: after the PRE_OPEN run, before the next 09:00. The registry becomes features-v5 with a new hash.
3. Values stored under features-v1..v4 keep their own hash. Stage 4 datasets v3 stay pinned to features-v4 (immutable); a later dataset version uses v5.

## Activation record

- **Canary:** 12 of 12 snapshots PASS (2026-10-13, 14, 15, 16, 19, 21; PRE_SESSION and PRE_OPEN; 3,565 instruments each). Evidence: `audit/evidence/features_v5_canary_*.json`.
  - PIT: 0 inputs at or after as_of;
  - v4 rows identical, except the four `ca_days_to_*`;
  - determinism holds;
  - the independent results-calendar recount equals the reader (248 to 566 instruments);
  - own vs vendor P/E: 92 % in band;
  - the extra time is 8–23 s per snapshot.
- **Activated 2026-10-21 evening** (a session boundary: after the PRE_OPEN run, before the next 09:00).
- **Registry:** features-v5, sha256 `466790726ac24c7b50bac417cae8e438cc48859ac8d3d865dffe3fdf69b18387`, 121 features (117 IMPLEMENTED; the four `ca_days_to_*` UNSUPPORTED).
- **The v4 document** stays reproducible (`registry.v4_document()`, sha `6f998a76…`).

## Known limits

- Own P/E vs vendor P/E (2026-10-21, 150 names): 91 of 94 are within ±50 %, median ratio 0.94.
  - The outliers are corporate restructurings (e.g. a demerger) or stale vendor values. They are listed by the canary.
- `eps_surprise_srw` needs the year-ago quarter in a stored snapshot. Snapshots start on 2026-09-24, so the first values appear with the September 2026 results refreshed by F1.
- `analyst-v1` is rule-based: an upgrade or downgrade word, or a raised or cut target, with no amount within three words. It misses phrasings such as "analysts raise earnings estimate, target". A headline about several companies is never attributed.
