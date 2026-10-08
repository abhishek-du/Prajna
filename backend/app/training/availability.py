"""The missingness contract of the training datasets.

  VALID                       a value
  MISSING_INPUT               the family was being collected at as_of, but this
                              value's input is absent or too short (engine reasons
                              MISSING_INPUT / INSUFFICIENT_HISTORY / DIVISION_UNDEFINED,
                              kept in the `reason` column)
  STALE_INPUT                 the input exists but is not the previous session's
                              (bars) or the news collector was silent (STALE)
  INVALID                     a malformed input (engine MALFORMED_INPUT)
  NOT_APPLICABLE              e.g. a pre-open feature at PRE_SESSION
  NOT_AVAILABLE_HISTORICALLY  the family had never been collected before as_of
                              (in the dataset's knowability). Value null, whatever
                              the engine computed: the legacy news counts return 0
                              on an empty input, and "no coverage" must never read
                              as "no news".

A family is AVAILABLE at as_of when at least one of its inputs is knowable before
as_of in the dataset's view (the train_asif shadow for AS_IF_LIVE). It is a
property of the collection, never of one instrument.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.compute import (
    DIVISION_UNDEFINED,
    INSUFFICIENT_HISTORY,
    MALFORMED_INPUT,
    MISSING_INPUT,
    NOT_APPLICABLE,
)

VALID, STALE, INVALID, NA_HIST = "VALID", "STALE_INPUT", "INVALID", "NOT_AVAILABLE_HISTORICALLY"

# registry input -> collection family
FAMILY = {"daily_bars": "bars", "nifty_bars": "bars", "key_ratios": "fundamentals",
          "income_yearly": "fundamentals", "income_quarterly": "fundamentals",
          "balance_sheet": "fundamentals", "corporate_actions": "corporate_actions",
          "news": "legacy_news", "preopen": "preopen", "multi_news": "multi_news",
          "fii_dii": "fii_dii", "global_bars": "global", "sector": "sector"}
BAR_FAMILIES = {"bars", "preopen"}

_EXISTS = {
    "bars": "select exists(select 1 from canon_market_bar where timeframe = '1d' "
            "and knowable_at < :a)",
    "fundamentals": "select exists(select 1 from canon_fundamental where knowable_at < :a "
                    "and statement_type <> 'profile')",
    "sector": "select exists(select 1 from canon_fundamental where knowable_at < :a "
              "and statement_type = 'profile')",
    "corporate_actions": "select exists(select 1 from canon_corporate_action "
                         "where knowable_at < :a)",
    "legacy_news": "select exists(select 1 from canon_news where knowable_at < :a)",
    "preopen": "select exists(select 1 from canon_preopen where knowable_at < :a)",
    "multi_news": "select exists(select 1 from news_poll where mode = 'PRODUCTION' "
                  "and finished_at < :a)",
    "fii_dii": "select exists(select 1 from canon_macro_observation where knowable_at < :a "
               "and split_part(series_code, '|', 1) in ('FII', 'DII'))",
    "global": "select exists(select 1 from ohlcv_bar b join instrument i using (instrument_id) "
              "where i.segment in ('GLOBAL_INDEX', 'GLOBAL_INDICATOR') and b.timeframe = '1d' "
              "and b.knowable_at < :a)",
}


async def available(s: AsyncSession, as_of: _dt.datetime) -> dict[str, bool]:
    """Family -> collected before as_of (through the session's search_path)."""
    return {f: bool((await s.execute(text(q), {"a": as_of})).scalar()) for f, q in _EXISTS.items()}


def status(reason: str | None, families: set[str], avail: dict[str, bool], *,
           bar_stale: bool, news_stale: bool) -> str:
    if any(not avail[f] for f in families):
        return NA_HIST
    if reason is None:
        return VALID
    if reason == NOT_APPLICABLE:
        return NOT_APPLICABLE
    if reason == MALFORMED_INPUT:
        return INVALID
    if reason in (MISSING_INPUT, INSUFFICIENT_HISTORY, DIVISION_UNDEFINED):
        if "multi_news" in families and news_stale:
            return STALE
        if bar_stale and families & BAR_FAMILIES:
            return STALE
        return MISSING_INPUT
    return INVALID                      # UNSUPPORTED / UNKNOWN: never in the active registry
