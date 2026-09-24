# Stage 1 final acceptance

**Generated:** 2026-09-24T07:22:56.023089+00:00 by `prajna acceptance stage1` (read-only, computed from the prajna database; regenerate, do not edit).

## Overall: **NOT COMPLETE**

Stage 2 remains LOCKED unless the overall is COMPLETE.

| # | Criterion | Status | DB state | Evidence | Notes / decisions |
|---|---|---|---|---|---|
| A | Database isolation | **PASS** |  | {"current_database": "prajna", "v1_database": "autotrade_pro (never used)"} |  |
| B | Provenance | **PASS** | {"ohlcv_bar": {"rows": 3641696, "bad_run": 0, "no_payload": 0, "no_basis": 0}, "macro_observation": {"rows": 4760, "bad_run": 0, "no_payload": 0, "no_basis": 0}, "news_article": {"rows": 124, "bad_run": 0, "no_payload": 0, "no_basis": 0}, "news_instrument": {"rows": 389, "bad_run": 0, "no_payload": 0, "no_basis": 0}, "corporate_action": {"rows": 628, "bad_run": 0, "no_payload": 0, "no_basis": 0}, "fundamental_snapshot": {"rows": 0, "bad_run": 0, "no_payload": 0, "no_basis": 0}, "instrument": {"rows": 3541, "bad_run": 0, "no_payload": 0, "no_basis": 0}, "trading_session": {"rows": 1561, "bad_ru | {"violations": 0} |  |
| C | Point-in-time safety (knowable_at <= fetched_at) | **PASS** |  | {"violations": {"ohlcv_bar": 0, "macro_observation": 0, "news_article": 0, "news_instrument": 0, "corporate_action": 0, "fundamental_snapshot": 0, "instrument": 0, "trading_session": 0, "preopen_tick": 0, "preopen_session_status": 0, "instrument_universe_membership": 0}} |  |
| D | Instrument master | **FAIL** | {"nse_eq": 3525, "nse_index": 3, "global": 13, "nse_eq_missing_isin_or_symbol": 0, "instruments_with_sector": 0} | {"sector_source": "fundamental_snapshot(profile).payload.sector", "listing_status": "UNAVAILABLE: Upstox 'suspended' instruments file answers 403 AccessDenied (archived sha a824bc77...)"} | sector comes from fundamentals (not a master field); needs >= 90 % of NSE_EQ |
| E | Trading calendar | **FAIL** | {"rows": 1561, "from": "2020-01-01", "to": "2026-12-31", "contiguous": false, "trading_days": 1097} | {"trading_day_without_nifty_bar": 37, "non_trading_day_with_nifty_bar": 2} | required: every date 2020-01-01 .. today+30, and agreement with the NIFTY 50 daily bars for past dates |
| F | 1D candles (from 2020-01-01) | **BLOCKED** | {"instruments": 3528, "covered_to_depth": 3526, "without_checkpoint": 2, "bars": 3640124, "instruments_with_bars": 3520, "required_from": "2020-01-01", "required_through": "2026-09-23", "sample_missing": ["NSE_EQ\|INE669E01016", "NSE_EQ\|INE749Y01014"]} | {"failed_streams": [["NSE_EQ\|INE669E01016", "not a non-negative integer", "candle[2024-08-30T00:00:00+05:30]"], ["NSE_EQ\|INE749Y01014", "not a non-negative integer", "candle[2022-09-05T00:00:00+05:30]"]]} | instruments listed after 2020 are covered from their first bar **Blocked by:** Q1 |
| G | 1m candles (last 6 months) | **FAIL** | {"instruments": 3528, "covered_to_depth": 0, "without_checkpoint": 3528, "bars": 1560, "instruments_with_bars": 4, "required_from": "2026-03-25", "required_through": "2026-09-23", "sample_missing": ["NSE_EQ\|IN9175A01010", "NSE_EQ\|IN9623B01058", "NSE_EQ\|INE001B01026", "NSE_EQ\|INE001E01012", "NSE_EQ\|INE002A01018"]} |  | historical backfill (D1) |
| H | 5m candles | **BLOCKED** | {"bars": 12} |  | not in the approved backfill plan **Blocked by:** D2-5m |
| I | 15m candles (from 2022-01) | **FAIL** | {"instruments": 3528, "covered_to_depth": 0, "without_checkpoint": 3528, "bars": 0, "instruments_with_bars": 0, "required_from": "2022-01-03", "required_through": "2026-09-23", "sample_missing": ["NSE_EQ\|IN9175A01010", "NSE_EQ\|IN9623B01058", "NSE_EQ\|INE001B01026", "NSE_EQ\|INE001E01012", "NSE_EQ\|INE002A01018"]} |  | historical backfill (D1) |
| J | 1h candles (from 2022-01) | **FAIL** | {"instruments": 3528, "covered_to_depth": 0, "without_checkpoint": 3528, "bars": 0, "instruments_with_bars": 0, "required_from": "2022-01-03", "required_through": "2026-09-23", "sample_missing": ["NSE_EQ\|IN9175A01010", "NSE_EQ\|IN9623B01058", "NSE_EQ\|INE001B01026", "NSE_EQ\|INE001E01012", "NSE_EQ\|INE002A01018"]} |  | historical backfill (D1) |
| K | Pre-open | **BLOCKED** | {"ticks": 392371, "sessions_captured": 1, "trading_sessions_missed_since_first": 0} | {"report": "var/acceptance/preopen_2026-09-24.json", "verdict": "WARN", "real_market_data": true, "non_pass": {"C6": "WARN"}, "B7": "OBSERVED", "B8": "RESOLVED"} | required: a PASS verdict (C6 is the only WARN, explained) and recurring daily capture (>= 2 sessions, none missed) **Blocked by:** C6 |
| L | Live WebSocket data | **BLOCKED** | {"tick_archive_rows": 0} | {"recorder": "live-validated 2026-09-23/24: 2 connections, 3,527 keys, 5-level depth; archived; pre-open persisted"} | all-day persistence is Stage 7 per M0 unless D5 says otherwise **Blocked by:** D5 |
| M | Corporate actions | **FAIL** | {"events": 628, "isins_with_events": 377, "announcement_range": ["2025-03-27", "2026-09-09"]} | {"isins_swept": 950, "nse_isins": 3525} | vendor depth ~1 year; announcement is a date (knowable_at = fetched_at) |
| N | News | **PASS** | {"articles": 124, "links": 389, "published_range": ["2026-09-17 02:58:30.938000+00:00", "2026-09-24 06:25:40.779000+00:00"]} | {"last_complete_sweep": "2026-09-24 06:36:05.765001+00:00"} | vendor keeps 7 days: must be swept at least daily |
| O | Fundamentals | **FAIL** | {"snapshots": 0, "instruments": 0, "statement_types": 0} | {"isins_swept": 0, "nse_isins": 3525} |  |
| P | FII/DII | **PASS** | {"streams": {"macro.FII.NSE_FO\|INDEX_FUTURES.1D": "2026-09-22", "macro.FII.NSE_FO\|INDEX_OPTIONS.1D": "2026-09-22", "macro.FII.NSE_FO\|STOCK_FUTURES.1D": "2026-09-22", "macro.FII.NSE_FO\|STOCK_OPTIONS.1D": "2026-09-22", "macro.DII.NSE_EQ\|CASH.1D": "2026-09-22", "macro.FII.NSE_EQ\|CASH.1D": "2026-09-22"}, "rows": 4760} | {"required_through": ">= 2023-12-29 (one session publication lag)"} |  |
| Q | Global / macro | **BLOCKED** | {"global_bars": 0} | {"available": "13 global instruments (S&P, Dow, USD/INR, ...) loaded; 1D from 2020-04-03 served", "defect": "all 13 have invalid daily bars (263 total); dry run FAILED all windows (PARSE_REJECT)", "bond_yields": "UNAVAILABLE on Upstox (not in any instrument file)"} | bond yields: OUT_OF_SCOPE/UNAVAILABLE **Blocked by:** Q1 |
| R | Daily incremental ingestion | **FAIL** |  | {"sessions_with_full_close_run": [], "runbook": "ops/runbooks/daily.sh close\|morning\|weekly\|monthly"} |  |
| S | Historical backfill to the approved depth | **FAIL** |  | {"from": ["F", "G", "I", "J"]} |  |
| T | Replay (archive -> parser -> DB) | **PASS** |  | {"runs": 75, "mismatches": 0, "by_family": {"candles": {"runs": 25, "rows": 25472, "available": true}, "fii_dii": {"runs": 25, "rows": 2768, "available": true}, "news": {"runs": 25, "rows": 46, "available": true}}, "per_family": 25} |  |
| U | Idempotency (no duplicate observations) | **PASS** |  | {"duplicates": {"macro": 0, "news": 0, "corporate_action": 0}} | ohlcv_bar is keyed by its primary key; reruns inserted 0 (validation doc §6, §13, §14) |
| V | Crash recovery | **PASS** |  | {"stale_running_runs": 0, "tests": "test_interrupted_insert_rolls_back_and_resume_completes, rate-limit abort tests (candles, news, corporate actions, fundamentals, FII/DII)"} |  |
| W | Coverage reconciliation | **PASS** |  | {"1d_without_outcome": 0, "1d_failed": 2} | EMPTY windows are recorded outcomes (new listings) |
| X | No look-ahead | **PASS** |  | {"violations": {"daily_nse_fetched_same_day": 0, "intraday_before_end_plus_margin": 0, "fii_dii_same_day": 0, "news_published_after_knowable": 0, "corporate_announced_after_fetch": 0}} |  |
| Y | Survivorship policy | **PASS** |  | {"policy": "survivorship-biased equity history accepted and documented: Upstox publishes no delisted/historical master (the 'suspended' file answers 403)", "ref": "M4.5 plan approved 2026-09-23"} |  |

## Decision register

| id | status | decision | reference |
|---|---|---|---|
| D1 | **APPROVED** | 1D from 2020-01-01; 1h and 15m from 2022-01; 1m for the last 6 months | M4.5 plan approved 2026-09-23 (M4_DECISIONS) |
| D2 | **APPROVED** | vendor-fetched 15m/1h (and 1m) | M4.5 plan approved 2026-09-23 |
| D2-5m | **PENDING** | 5m: the approved plan does not fetch it ("can be derived from 1m later"); the Stage-1 spec lists 5m. Fetch 5m since 2022 (~201k requests), fetch for the 1m depth only, or formally exclude | - |
| D3 | **IN_FORCE** | a changed value for a stored bar/observation FAILS; nothing is overwritten (versioned storage not enabled) | M1/M4 contracts; not changed |
| D5 | **PENDING** | all-day LTP/depth persistence: Stage 7 per M0 (PRAJNA_TICK_PERSISTENCE_ENABLED=false); needs explicit confirmation as a Stage-1 exclusion | M0 |
| S1 | **IN_FORCE** | universe = NSE_EQ series EQ/BE/SM/BZ/ST/IV (REIT RR, D1/E1/IT/SZ/W1 excluded) | M1; not changed |
| S2 | **APPROVED** | FII/DII, corporate actions, news, fundamentals, global (where Upstox has it) are in Stage 1 | user 2026-09-23 (FII/DII) and Stage-1 completion mission 2026-09-24 |
| P1 | **PENDING** | WebSocket knowable_at = vendor currentTs (11-148 ms before receipt, M0 contract) vs fetched_at | - |
| SURV | **APPROVED** | survivorship-biased equity history accepted and documented: Upstox publishes no delisted/historical master (the 'suspended' file answers 403) | M4.5 plan approved 2026-09-23 |
| Q1 | **PENDING** | invalid vendor bars (negative volume; OHLC outside [low, high]): quarantine the single bar and store the rest, or keep the whole-window FAIL | - |
| C6 | **PENDING** | pre-open completeness C6 (88.6 % ticked in window): explained (no IEP ever = no pre-open activity); accept as expected or keep as WARN | - |
| KN-CA | **IN_FORCE** | corporate actions: announcement is a date only; knowable_at = fetched_at (for_announced_fact). Alternative (end of the announcement date, IST) needs approval | M0 contract |
