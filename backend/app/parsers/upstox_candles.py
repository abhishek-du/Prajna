"""Upstox V3 candle response -> classified candle rows + one coverage record. PURE.

Shape MEASURED 2026-09-23 on 13 real responses (tests/fixtures/upstox_candles):
  200  {"status": "success", "data": {"candles": [[ts, o, h, l, c, v, oi], ...]}}
       newest first; ts an ISO-8601 string with offset; o..c float; v, oi int
  4xx  {"status": "error", "errors": [{"errorCode": "UDAPI1148", ...}]}
  an empty 200 has "candles": [] (before availability, holiday, not listed)

Every candle becomes a CandleRow with a state from contracts.candles:
  COMPLETE  may be persisted
  FORMING   the bar has not ended (or a daily bar from the intraday endpoint,
            or a same-day daily bar)
  SETTLING  ended, but within COMPLETION_MARGIN
FORMING and SETTLING rows are returned, counted and never persisted; the
archived response keeps them, and a later fetch persists them once complete.

A candle that breaks the contract is INVALID: bad timestamp, non-numeric or
insane OHLC, precision beyond the column, off the session grid, outside the
requested window, or a duplicate with different values. It raises an Issue,
FAIL severity, and is never returned as a row. Unknown envelope fields are
SCHEMA_DRIFT (FAIL).

Nothing here touches the network, the database or the filesystem.
"""

from __future__ import annotations

import datetime as _dt
import enum
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.contracts import candles as C
from app.contracts.knowable import Knowable, for_daily_bar, for_intraday_bar
from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.contracts.timeframe import validate_bar
from app.core.clock import IST, to_utc

# Column scale in ohlcv_bar: price numeric(18,4), volume/oi numeric(22,0).
_PRICE_SCALE = 4
_ENVELOPE_OK = frozenset({"status", "data"})
_ENVELOPE_ERR = frozenset({"status", "errors"})
_DATA_KEYS = frozenset({"candles"})
CANDLE_WIDTH = 7


class Endpoint(str, enum.Enum):
    HISTORICAL = "historical"   # /v3/historical-candle/{key}/{unit}/{step}/{to}/{from}
    INTRADAY = "intraday"       # /v3/historical-candle/intraday/{key}/{unit}/{step}


class CandleDecodeError(Exception):
    """Not a candle response at all. The archived bytes stay re-parseable."""


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CandleRow:
    instrument_key: str
    timeframe: str
    session_date: _dt.date
    bar_start_utc: _dt.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    open_interest: Decimal | None
    vendor_ts_raw: str
    state: C.BarState
    knowable: Knowable

    def values(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in C.BAR_VALUE_FIELDS}


@dataclass(slots=True)
class ParsedCandles:
    instrument_key: str
    timeframe: str
    endpoint: Endpoint
    window: C.Window
    rows: list[CandleRow] = field(default_factory=list)      # oldest first
    issues: list[Issue] = field(default_factory=list)
    coverage: C.CoverageRecord | None = None
    grid_unchecked: int = 0     # intraday rows whose session open was not supplied

    @property
    def complete(self) -> list[CandleRow]:
        return [r for r in self.rows if r.state is C.BarState.COMPLETE]

    def fail(self, subject: str, **detail: Any) -> None:
        self.issues.append(Issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, subject,
                                 {"instrument_key": self.instrument_key,
                                  "timeframe": self.timeframe, **detail}))

    def quarantine(self, subject: str, **detail: Any) -> None:
        """Decision Q1: a value-insane vendor bar is skipped, never stored, and
        recorded with everything needed to audit it; its window continues."""
        self.issues.append(Issue(AnomalySeverity.WARN, AnomalyKind.QUARANTINED, subject,
                                 {"instrument_key": self.instrument_key,
                                  "timeframe": self.timeframe, "decision": "Q1", **detail}))


def _decimal(v: Any, name: str, pc: ParsedCandles, ts: str) -> Decimal | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        pc.fail(f"candle[{ts}]", field=name, reason="not a number", value=repr(v)[:40])
        return None
    if isinstance(v, float) and not math.isfinite(v):
        pc.fail(f"candle[{ts}]", field=name, reason="non-finite", value=repr(v))
        return None
    return Decimal(repr(v)) if isinstance(v, float) else Decimal(v)


def _price(v: Any, name: str, pc: ParsedCandles, ts: str) -> Decimal | None:
    d = _decimal(v, name, pc, ts)
    if d is not None and d != d.quantize(Decimal(1).scaleb(-_PRICE_SCALE)):
        pc.fail(f"candle[{ts}]", field=name, reason="precision exceeds numeric(18,4)",
                value=repr(v))
        return None
    return d


def _count(v: Any, name: str, pc: ParsedCandles, ts: str) -> Decimal | None:
    """An integer count. Its SIGN is a value-sanity question (Q1), judged in _one."""
    d = _decimal(v, name, pc, ts)
    if d is not None and d != d.to_integral_value():
        pc.fail(f"candle[{ts}]", field=name, reason="not an integer", value=repr(v))
        return None
    return d


QUARANTINED = object()          # _one's marker for a Q1-quarantined bar


def parse_candles(
    data: bytes,
    *,
    http_status: int,
    endpoint: Endpoint,
    instrument_key: str,
    timeframe: str,
    fetched_at: _dt.datetime,
    window: C.Window | None = None,
    payload_sha256: str | None = None,
    session_opens: Mapping[_dt.date, _dt.time] | None = None,
) -> ParsedCandles:
    """One response -> rows, issues and exactly one CoverageRecord.

    `window` is required for the historical endpoint and must be omitted for
    the intraday one, whose window is the IST date it was fetched on.
    `session_opens` (session_date -> open) enables the grid check; sessions
    without an entry are checked against nothing and counted as such.
    """
    if timeframe not in C.M4_TIMEFRAMES:
        raise ValueError(f"{timeframe!r} is not an M4 timeframe")
    fetched_at = to_utc(fetched_at)
    fetched_day = fetched_at.astimezone(IST).date()
    if endpoint is Endpoint.HISTORICAL:
        if window is None:
            raise ValueError("the historical endpoint needs its request window")
    else:
        if window is not None:
            raise ValueError("the intraday endpoint has no request window")
        window = C.Window(fetched_day, fetched_day)
    pc = ParsedCandles(instrument_key, timeframe, endpoint, window)

    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError) as e:
        raise CandleDecodeError(f"not JSON: {e}") from None
    if not isinstance(body, dict):
        raise CandleDecodeError(f"a {type(body).__name__}, not an object")

    # ── vendor error ──────────────────────────────────────────────────────
    if http_status != 200:
        extra = set(body) - _ENVELOPE_ERR
        if extra:
            pc.issues.append(Issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "envelope",
                                   {"unknown": sorted(extra), "http_status": http_status}))
        codes = [str(e.get("errorCode") or e.get("error_code"))
                 for e in body.get("errors") or [] if isinstance(e, dict)
                 and (e.get("errorCode") or e.get("error_code"))]
        pc.coverage = C.CoverageRecord(
            instrument_key, timeframe, window, C.WindowOutcome.VENDOR_ERROR,
            payload_sha256=payload_sha256,
            vendor_error_code=",".join(codes) or f"HTTP{http_status}")
        return pc

    # ── success envelope ──────────────────────────────────────────────────
    extra = set(body) - _ENVELOPE_OK
    d = body.get("data")
    extra_data = set(d) - _DATA_KEYS if isinstance(d, dict) else set()
    if extra or extra_data:
        pc.issues.append(Issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "envelope",
                               {"unknown": sorted(extra), "unknown_in_data": sorted(extra_data)}))
    if body.get("status") != "success" or not isinstance(d, dict) \
            or not isinstance(d.get("candles"), list):
        raise CandleDecodeError(f"unexpected envelope: {str(body)[:200]}")
    raw = d["candles"]

    seen: dict[_dt.datetime, CandleRow] = {}
    invalid = identical_dupes = quarantined = 0
    for c in raw:
        got = _one(c, pc, endpoint, timeframe, fetched_at, window, session_opens)
        if got is QUARANTINED:
            quarantined += 1
            continue
        if got is None:
            invalid += 1
            continue
        row, grid_unchecked = got
        pc.grid_unchecked += grid_unchecked
        prior = seen.get(row.bar_start_utc)
        if prior is None:
            seen[row.bar_start_utc] = row
        elif C.same_observation(prior.values(), row.values()):
            identical_dupes += 1
            pc.issues.append(Issue(AnomalySeverity.WARN, AnomalyKind.DUPLICATE_KEY,
                                   f"candle[{row.vendor_ts_raw}]",
                                   {"identical": True, "instrument_key": instrument_key}))
        else:
            pc.fail(f"candle[{row.vendor_ts_raw}]", reason="same bar twice, different values",
                    first=str(prior.values()), second=str(row.values()))
            del seen[row.bar_start_utc]
            invalid += 2                        # neither observation can be trusted

    pc.rows = sorted(seen.values(), key=lambda r: r.bar_start_utc)
    n = {s: sum(1 for r in pc.rows if r.state is s) for s in C.BarState}
    # CoverageRecord refuses counts that do not add up: nothing disappears silently.
    pc.coverage = C.CoverageRecord(
        instrument_key, timeframe, window,
        C.WindowOutcome.DATA if raw else C.WindowOutcome.EMPTY,
        returned=len(raw) - identical_dupes,
        complete=n[C.BarState.COMPLETE], forming=n[C.BarState.FORMING],
        settling=n[C.BarState.SETTLING], invalid=invalid, quarantined=quarantined,
        payload_sha256=payload_sha256,
    )
    return pc


def _one(c, pc: ParsedCandles, endpoint: Endpoint, timeframe: str,
         fetched_at: _dt.datetime, window: C.Window,
         session_opens: Mapping[_dt.date, _dt.time] | None):
    if not isinstance(c, list) or len(c) != CANDLE_WIDTH:
        pc.issues.append(Issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, "candle",
                               {"reason": f"expected a {CANDLE_WIDTH}-element array",
                                "value": repr(c)[:80], "instrument_key": pc.instrument_key}))
        return None
    ts = c[0] if isinstance(c[0], str) else repr(c[0])
    try:
        if timeframe == C.DAILY:
            session = C.daily_session_date(c[0])
            start = C.daily_bar_start(session)
        else:
            start, session = C.intraday_bar_start(c[0])
    except C.CandleTimestampError as e:
        pc.fail(f"candle[{ts}]", reason=str(e))
        return None

    o, h, lo, cl = (_price(c[i], f, pc, ts) for i, f in
                    ((1, "open"), (2, "high"), (3, "low"), (4, "close")))
    v = _count(c[5], "volume", pc, ts)
    oi = None if c[6] is None else _count(c[6], "open_interest", pc, ts)
    if None in (o, h, lo, cl, v) or (c[6] is not None and oi is None):
        return None
    reason = None
    try:
        validate_bar(o, h, lo, cl, v)
    except ValueError as e:
        reason = f"insane OHLC: {e}"
    if reason is None and oi is not None and oi < 0:
        reason = f"negative open_interest {oi}"
    if reason is not None:
        pc.quarantine(f"candle[{ts}]", reason=reason, session_date=str(session),
                      vendor_values=[str(x) for x in c[1:7]])
        return QUARANTINED

    if not (window.from_date <= session <= window.to_date):
        pc.fail(f"candle[{ts}]", reason="outside the requested window",
                session_date=str(session), window=[str(window.from_date), str(window.to_date)])
        return None

    grid_unchecked = 0
    if timeframe != C.DAILY:
        opened = (session_opens or {}).get(session)
        if opened is None:
            grid_unchecked = 1
        elif not C.aligned(start, timeframe, opened):
            pc.fail(f"candle[{ts}]", reason="off the session grid",
                    session_open=opened.isoformat())
            return None

    if timeframe == C.DAILY:
        state = (C.BarState.FORMING if endpoint is Endpoint.INTRADAY
                 else C.daily_state(session, fetched_at,
                                    segment=pc.instrument_key.split("|", 1)[0]))
        k = for_daily_bar(session, fetched_at)
    else:
        state = C.intraday_state(start, timeframe, fetched_at)
        k = for_intraday_bar(start, timeframe, fetched_at)

    row = CandleRow(pc.instrument_key, timeframe, session, start, o, h, lo, cl, v, oi, c[0],
                    state, k)
    return (row, grid_unchecked)
