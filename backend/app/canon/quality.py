"""Stage 2 data-quality gates over the canonical layer. Read-only.

Each gate returns {gate, status PASS/FAIL, count, sample, diagnostic}. A FAIL
names what to look at; nothing is silently passed. Gates run on the whole
canonical layer (set-based SQL), not on samples.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# (gate, sql returning offending rows (limit applied by the runner), diagnostic)
GATES: list[tuple[str, str, str]] = [
    ("duplicate_bars", """
        select instrument_id, timeframe, bar_start_utc, count(*) from canon_market_bar
        group by 1, 2, 3 having count(*) > 1""",
     "two canonical bars with one key: the ohlcv_bar primary key or the view join is broken"),
    ("invalid_ohlc", """
        select instrument_key, timeframe, bar_start_utc, open, high, low, close
        from canon_market_bar where not (high >= low and high >= open and high >= close
          and low <= open and low <= close) or least(open, high, low, close) <= 0""",
     "an impossible bar reached the canonical layer: Q1 quarantine was bypassed"),
    ("negative_volume", """
        select instrument_key, timeframe, bar_start_utc, volume from canon_market_bar
        where volume < 0 or open_interest < 0""",
     "negative volume/OI in canonical bars: Q1 quarantine was bypassed"),
    ("null_required_bar_fields", """
        select instrument_key, timeframe, bar_start_utc from canon_market_bar
        where open is null or high is null or low is null or close is null or volume is null
           or knowable_at is null or fetched_at is null or payload_sha256 is null""",
     "a canonical bar lacks a required value or provenance"),
    ("knowable_after_fetched", """
        select 'bar' t, instrument_key, knowable_at, fetched_at from canon_market_bar
          where knowable_at > fetched_at
        union all select 'corporate_action', instrument_key, knowable_at, fetched_at
          from canon_corporate_action where knowable_at > fetched_at
        union all select 'news', instrument_key, knowable_at, fetched_at from canon_news
          where knowable_at > fetched_at
        union all select 'fundamental', instrument_key, knowable_at, fetched_at
          from canon_fundamental where knowable_at > fetched_at
        union all select 'preopen', instrument_key, knowable_at, fetched_at from canon_preopen
          where knowable_at > fetched_at
        union all select 'macro', series_code, knowable_at, fetched_at
          from canon_macro_observation where knowable_at > fetched_at""",
     "knowable_at after fetched_at: a point-in-time contract is violated"),
    ("bar_knowable_before_event_end", """
        select instrument_key, timeframe, bar_start_utc, event_end, knowable_at
        from canon_market_bar where event_end is not null and knowable_at < event_end""",
     "a bar is knowable before its market event ended: look-ahead"),
    ("daily_bar_fetched_same_session", """
        select instrument_key, market_date, fetched_at from canon_market_bar
        where timeframe = '1d'
          and (fetched_at at time zone 'Asia/Kolkata')::date <= market_date""",
     "a daily bar persisted on its own session day (B1: only from the next day)"),
    ("non_session_bars_exposed", """
        select b.instrument_key, b.market_date from canon_market_bar b
        left join trading_session t on t.session_date = b.market_date
        where t.is_trading_day is not true""",
     "a bar on a non-trading day is visible to Stage 3 (canon_market_bar must hide it)"),
    ("orphan_instruments", """
        select b.instrument_id, b.instrument_key from ohlcv_bar b
        left join canon_instrument ci on ci.instrument_id = b.instrument_id
        where ci.instrument_id is null limit 20""",
     "Stage 1 bars of an instrument Stage 2 has not decided on: run `prajna stage2 process`"),
    ("invalid_exchange", """
        select instrument_key, segment, exchange from canon_instrument
        where included and (exchange <> 'NSE' or segment not in ('NSE_EQ', 'NSE_INDEX'))""",
     "a non-NSE instrument is in the NSE universe"),
    ("invalid_timeframe", """
        select distinct timeframe from canon_market_bar
        where timeframe not in ('1d', '1h', '15m', '1m', '5m')""",
     "an unknown timeframe in canonical bars"),
    ("missing_identifiers", """
        select instrument_key, trading_symbol, isin from canon_instrument
        where included and (trading_symbol is null or trading_symbol = ''
          or (segment = 'NSE_EQ' and (isin is null or isin !~ '^IN[A-Z0-9]{9}[0-9]$')))""",
     "an NSE-universe instrument without a symbol or a valid ISIN"),
    ("unexpected_gaps", """
        select ci.instrument_key, c.timeframe, c.from_date, c.to_date, c.sessions
        from canon_coverage c join canon_instrument ci using (instrument_id)
        where c.state = 'MISSING'""",
     "sessions inside a Stage 1 checkpoint that no COMPLETE window covers"),
    ("duplicate_corporate_actions", """
        select isin, content_sha256, count(*) from canon_corporate_action
        group by 1, 2 having count(*) > 1""",
     "the same vendor corporate-action event stored twice"),
    ("duplicate_news_mappings", """
        select news_id, instrument_key, count(*) from canon_news
        group by 1, 2 having count(*) > 1""",
     "one article linked twice to the same instrument"),
    ("invalid_fundamentals", """
        select instrument_key, statement_type, period_end, fetched_at from canon_fundamental
        where payload is null or payload = 'null'::jsonb or statement_type is null""",
     "a fundamentals snapshot without a payload or statement type"),
    ("calendar_gaps_in_depth", """
        select d::date from generate_series('2020-01-01'::date, current_date - 1,
                                            interval '1 day') d
        where not exists (select 1 from trading_session t where t.session_date = d::date)""",
     "the calendar does not cover the approved depth: coverage cannot name expected "
     "sessions there (run `prajna ingest calendar`)"),
    ("coverage_contradicts_bars", """
        select ci.instrument_key, c.timeframe, c.from_date, c.state, c.bars
        from canon_coverage c join canon_instrument ci using (instrument_id)
        where (c.state = 'DATA') <> (c.bars > 0)""",
     "a coverage range says DATA without bars (or bars without DATA)"),
]


async def run_gates(s: AsyncSession, sample: int = 5) -> dict[str, Any]:
    results = []
    for name, sql, diag in GATES:
        n = (await s.execute(text(f"select count(*) from ({sql}) x"))).scalar()  # noqa: S608
        rows = [] if not n else [list(map(str, r)) for r in (await s.execute(
            text(f"select * from ({sql}) x limit {int(sample)}"))).all()]    # noqa: S608
        results.append({"gate": name, "status": "PASS" if n == 0 else "FAIL", "count": n,
                        "sample": rows, "diagnostic": diag if n else ""})
    null_rate = (await s.execute(text("""
        select round(avg((sector is null)::int)::numeric, 4) from canon_instrument
        where included and segment = 'NSE_EQ'"""))).scalar()
    excluded = (await s.execute(text(
        "select count(*) from canon_excluded_bar"))).scalar()
    # A period LABEL ("Sep 2026") read as its month end can lie after the fetch:
    # in-quarter filings (measured 2026-09-24: 2 shareholding snapshots). Not a
    # look-ahead (knowable_at = fetched_at); period_end is a label, not a date
    # the data describes. Reported, never hidden.
    label_after = (await s.execute(text("""
        select count(*) from canon_fundamental where period_end is not null
          and period_end > (fetched_at at time zone 'Asia/Kolkata')::date + 1"""))).scalar()
    return {"status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL",
            "gates": results,
            "informational": {"sector_null_rate_nse_eq": float(null_rate or 0),
                              "bars_excluded_non_session (canon_excluded_bar)": excluded,
                              "fundamentals_period_label_after_fetch": label_after}}
