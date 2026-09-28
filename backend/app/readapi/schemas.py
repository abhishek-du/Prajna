"""Response contracts of the read API (/v1). Stable, documented, frontend-agnostic.

Conventions (every endpoint):
  * timestamps are ISO-8601 with offset (UTC); market dates are YYYY-MM-DD (IST)
  * prices/volumes are JSON numbers (float64 of the stored exact numerics)
  * `meta.as_of` is the knowledge instant: only rows with knowable_at < as_of are
    returned (point-in-time); `meta.point_in_time` is false where an endpoint
    reports the CURRENT state (e.g. today's sector, pipeline status)
  * missing data is absent, never filled; coverage/freshness say why
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

KNOWLEDGE_RULE = "knowable_at < as_of"


class Meta(BaseModel):
    as_of: _dt.datetime = Field(description="knowledge instant of the answer (UTC)")
    generated_at: _dt.datetime
    point_in_time: bool = Field(description="true: only rows knowable before as_of")
    knowledge_rule: str = KNOWLEDGE_RULE
    notes: list[str] = Field(default_factory=list)
    total: int | None = Field(None, description="list endpoints: rows matching the filter "
                                                "(for pagination)")


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


class Instrument(BaseModel):
    instrument_key: str = Field(description="vendor-stable key, e.g. 'NSE_EQ|INE002A01018'")
    trading_symbol: str
    name: str | None
    isin: str | None
    segment: str
    exchange: str
    instrument_type: str | None
    security_class: str | None = Field(
        None, description="STOCK / FUND_UNIT / RIGHTS_ENTITLEMENT / OTHER (explainable, "
                          ">= 2 signals); null for indices")
    lifecycle_status: str | None = Field(
        None, description="ACTIVE / INELIGIBLE / REMOVED_FROM_MASTER / VENDOR_REJECTED")
    lifecycle_since: _dt.datetime | None
    sector: str | None = Field(None, description="CURRENT sector (latest profile); not "
                                                 "point-in-time - see /profile?as_of")


class SearchHit(Instrument):
    match: str = Field(description="SYMBOL_EXACT / SYMBOL_PREFIX / ISIN / NAME")


class Profile(BaseModel):
    instrument: Instrument
    sector_as_of: str | None = Field(description="sector of the latest profile snapshot "
                                                 "knowable before as_of")
    security_class_signals: dict[str, Any] | None
    lifecycle_periods: list[dict[str, Any]]
    profile: dict[str, Any] | None = Field(description="latest vendor profile payload "
                                                       "knowable before as_of")


class Candle(BaseModel):
    timeframe: str
    bar_start: _dt.datetime
    market_date: _dt.date
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None
    knowable_at: _dt.datetime = Field(description="earliest instant Prajna knew this bar "
                                                  "(its fetch; never bar end)")
    fetched_at: _dt.datetime
    price_basis: str | None = Field(description="RAW_OBSERVED / VENDOR_ADJUSTED (as of "
                                                "basis_as_of)")
    basis_as_of: _dt.date | None
    adjustment_status: str | None = Field(None, description="adjusted=true only: AS_STORED "
                                          "/ ADJUSTED / RECONSTRUCTED")
    factor_applied: float | None = None
    basis_confidence: str | None = None


class CandleSeries(BaseModel):
    instrument_key: str
    timeframe: str
    adjusted: bool
    candles: list[Candle]
    refused: dict[str, int] | None = Field(None, description="adjusted=true: rows withheld "
                                           "(low confidence / reconstructed) unless allowed")


class Quote(BaseModel):
    instrument_key: str
    source: str = Field(description="what the numbers are; Stage 1 has no canonical live "
                                    "tick store")
    last_1m: Candle | None
    last_1d: Candle | None
    age_seconds: float | None = Field(description="as_of minus the newest bar's knowable_at")


class Fundamental(BaseModel):
    statement_type: str
    period_end: _dt.date | None
    period_type: str | None
    payload: dict[str, Any] | list[Any] | None
    knowable_at: _dt.datetime
    fetched_at: _dt.datetime


class CorporateAction(BaseModel):
    id: int
    action_type: str
    announcement_date: _dt.date | None
    ex_date: _dt.date | None
    record_date: _dt.date | None
    amount: float | None
    ratio_from: float | None
    ratio_to: float | None
    face_value_before: float | None
    face_value_after: float | None
    knowable_at: _dt.datetime
    factor_status: str | None = Field(None, description="EXACT / UNCERTAIN / UNSUPPORTED")
    factor_price: float | None = None
    vendor_applied: str | None = Field(None, description="does the vendor's later history "
                                       "include this action (APPLIED / NOT_APPLIED / UNKNOWN)")


class SectorCount(BaseModel):
    sector: str | None
    stocks: int


class GlobalInstrument(BaseModel):
    instrument_key: str
    name: str | None
    segment: str
    label_semantics: str | None
    confirm_hours: int | None
    latest: dict[str, Any] | None = Field(description="latest CONFIRMED bar knowable "
                                                      "before as_of")


class GlobalBar(BaseModel):
    label_date: _dt.date = Field(description="the vendor's label; NOT necessarily the "
                                             "instrument's trading date")
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    finality: str = Field(description="CONFIRMED / CONFIRMED_BY_AGE (others never exposed)")
    knowable_at: _dt.datetime
    first_fetched_at: _dt.datetime


class NewsItem(BaseModel):
    news_id: int
    instrument_key: str | None
    headline: str
    publisher: str | None = Field(None, description="as supplied by the vendor (often none)")
    url: str | None
    published_at: _dt.datetime | None = Field(description="vendor publication time")
    received_at: _dt.datetime = Field(description="when Prajna fetched it")
    knowable_at: _dt.datetime


class Freshness(BaseModel):
    dataset: str
    last_complete_run_finished: _dt.datetime | None
    age_hours: float | None
    last_status: str | None
    expected_cadence: str


class Quality(BaseModel):
    instrument_key: str
    coverage: dict[str, list[dict[str, Any]]] = Field(description="current coverage ranges "
                                                                  "per timeframe (NOT PIT)")
    observations: dict[str, int] = Field(description="later vendor observations by class "
                                                     "(append-only)")
    price_basis: dict[str, int]
    quarantined_bars: int
    provenance: dict[str, Any]


class MarketSession(BaseModel):
    date: _dt.date
    is_trading_day: bool
    session_type: str = Field(description="NORMAL / SPECIAL / HOLIDAY / WEEKEND")
    preopen_start_ist: _dt.time | None
    open_ist: _dt.time | None
    close_ist: _dt.time | None
    state: str = Field(description="at as_of: PRE_OPEN / OPEN / CLOSED / NON_TRADING_DAY "
                                   "(calendar only; not a feed status)")
    previous_trading_day: _dt.date | None
    next_trading_day: _dt.date | None
    calendar_source: str


class LatestPrice(BaseModel):
    instrument_key: str
    market_date: _dt.date = Field(description="session of the latest 1d bar knowable before "
                                              "as_of")
    close: float
    previous_market_date: _dt.date | None
    previous_close: float | None
    change: float | None = Field(description="close - previous_close (null when not "
                                             "comparable)")
    change_pct: float | None
    volume: float
    comparable: bool = Field(description="false when a split/bonus ex-date falls between the "
                                         "two sessions or their price basis differs: the raw "
                                         "difference would not be a market move")
    comparable_reason: str | None
    knowable_at: _dt.datetime
    price_basis: str | None


class GlobalLabel(BaseModel):
    label_date: _dt.date
    finality: str = Field(description="REVISED / PLACEHOLDER / UNCONFIRMED (withheld: no "
                                      "values) or CONFIRMED / CONFIRMED_BY_AGE")
    exposed: bool
    close: float | None = Field(description="only for exposed labels")
    first_fetched_at: _dt.datetime
    confirmed_at: _dt.datetime | None
    revised_at: _dt.datetime | None


class FeatureValue(BaseModel):
    instrument_key: str = Field(description="instrument, or the context key (an index, a "
                                            "global instrument, or MARKET)")
    scope: str = Field(description="INSTRUMENT | CONTEXT")
    session_date: _dt.date
    snapshot: str = Field(description="PRE_SESSION | PRE_OPEN")
    snapshot_as_of: _dt.datetime = Field(description="the snapshot instant every input predates")
    feature_id: str
    feature_version: int
    value: float | None = Field(description="null exactly when `reason` is set")
    reason: str | None = Field(description="why the value is null (MISSING_INPUT, "
                                           "INSUFFICIENT_HISTORY, MALFORMED_INPUT, ...)")
    input_max_knowable_at: _dt.datetime | None
    computed_at: _dt.datetime = Field(description="when Prajna stored it (its knowable_at)")
    registry_sha256: str
