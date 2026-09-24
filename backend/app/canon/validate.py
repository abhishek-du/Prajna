"""Stage 2 validation of canonical inputs: the SAME rules Stage 1 enforces at
ingest (contracts.timeframe.validate_bar, Q1 quarantine), re-applied as an
audit so nothing invalid can reach a Stage 3 read unnoticed. Pure.

At ingest a value-insane vendor bar is QUARANTINED (never stored, one anomaly
with its payload sha); a structurally invalid response FAILS its window.
Stage 2 does not re-decide that; it verifies it held.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.contracts.identity import is_valid_isin, parse_instrument_key
from app.contracts.timeframe import validate_bar

CANON_TIMEFRAMES = ("1d", "1h", "15m", "1m")        # D1; 5m OUT_OF_SCOPE (D2-5m)
STORED_TIMEFRAMES = frozenset({*CANON_TIMEFRAMES, "5m"})   # 5m test bars exist


@dataclass(frozen=True, slots=True)
class Violation:
    rule: str
    detail: str


def validate_bar_row(row: dict[str, Any]) -> list[Violation]:
    """One canonical bar. Returns every violated rule (empty = valid)."""
    out: list[Violation] = []
    try:
        parse_instrument_key(row["instrument_key"])
    except (ValueError, KeyError, TypeError) as e:
        out.append(Violation("instrument", f"bad instrument_key: {e}"))
    if row.get("timeframe") not in STORED_TIMEFRAMES:
        out.append(Violation("timeframe", f"unknown timeframe {row.get('timeframe')!r}"))
    o, h, lo, c, v = (row.get(k) for k in ("open", "high", "low", "close", "volume"))
    if None in (o, h, lo, c, v):
        out.append(Violation("ohlcv_null", "open/high/low/close/volume missing"))
    else:
        try:
            validate_bar(o, h, lo, c, v)
        except ValueError as e:
            out.append(Violation("ohlc_sanity", str(e)))
        if min(Decimal(str(x)) for x in (o, h, lo, c)) <= 0:
            out.append(Violation("price_nonpositive", "a price <= 0"))
    k, f = row.get("knowable_at"), row.get("fetched_at")
    if not isinstance(k, _dt.datetime) or not isinstance(f, _dt.datetime) \
            or k.tzinfo is None or f.tzinfo is None:
        out.append(Violation("timestamp", "knowable_at/fetched_at missing or naive"))
    elif k > f:
        out.append(Violation("knowable_after_fetched", f"{k} > {f}"))
    return out


def validate_identifiers(row: dict[str, Any]) -> list[Violation]:
    """Required identifiers of an NSE-universe instrument."""
    out = []
    if not row.get("trading_symbol"):
        out.append(Violation("symbol", "missing trading_symbol"))
    if row.get("segment") == "NSE_EQ" and not is_valid_isin(row.get("isin")):
        out.append(Violation("isin", f"invalid ISIN {row.get('isin')!r}"))
    return out
