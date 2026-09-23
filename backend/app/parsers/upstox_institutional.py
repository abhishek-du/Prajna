"""Upstox FII / DII activity response -> typed observations. PURE.

Endpoints (docs: get-fii-data/, get-dii-data/):
  GET /v2/market/fii?data_type=<t>[,<t>...]&interval=1D[&from=YYYY-MM-DD]
  GET /v2/market/dii?data_type=NSE_EQ|CASH&interval=1D[&from=YYYY-MM-DD]

Shape and semantics MEASURED 2026-09-23 on the real responses in
tests/fixtures/upstox_institutional:
  200  {"status": "success", "data": {"<data_type>": [record, ...]}}
       one list per requested data_type, newest first; an empty list before
       2026-04-01 (the vendor's first day)
  record  time_stamp (epoch ms) + 12 numeric fields
  time_stamp  the session DATE at 00:00 IST: a label, not a publication time
  `from`  the END of the window: 30 trading days ending at `from` are returned
          (no `from` = the latest 30)

Applicable fields per data_type. They are MEASURED: every record of every
fixture carries all 12 fields, but the vendor reports 0 for the ones that do not
apply (cash has no contracts, futures no call/put split, options no long/short
total). Storing those zeros would present "not applicable" as "zero", so only the
applicable fields become observations. A non-zero value in a non-applicable
field means the vendor's semantics changed, which is SCHEMA_DRIFT (FAIL).

Units: the docs say the amounts are INR. Their magnitude (e.g. FII cash buy of
9,845.81 in one day) is consistent with INR crore, which is UNVERIFIED. The
unit is therefore stored as "INR_vendor", meaning "vendor amount unit, not
verified", never plain "INR".

Nothing here touches the network, the database or the filesystem.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.contracts.knowable import Knowable, for_announced_fact
from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.clock import IST

SIDES = ("FII", "DII")
INTERVALS = ("1D",)            # 1M exists, but its `from` semantics are UNMEASURED
DATA_START = _dt.date(2026, 4, 1)          # measured: before it, an empty 200
WINDOW_TRADING_DAYS = 30                    # measured: records per 1D request

DATA_TYPES: dict[str, tuple[str, ...]] = {
    "FII": ("NSE_EQ|CASH", "NSE_FO|INDEX_FUTURES", "NSE_FO|INDEX_OPTIONS",
            "NSE_FO|STOCK_FUTURES", "NSE_FO|STOCK_OPTIONS"),
    "DII": ("NSE_EQ|CASH",),
}

# vendor field -> (short name in series_code, unit). The short names keep every
# series_code within varchar(48).
FIELDS: dict[str, tuple[str, str]] = {
    "buy_amount": ("buy_amt", "INR_vendor"),
    "sell_amount": ("sell_amt", "INR_vendor"),
    "buy_contracts": ("buy_ctr", "contracts"),
    "sell_contracts": ("sell_ctr", "contracts"),
    "oi_contracts": ("oi_ctr", "contracts"),
    "oi_amount": ("oi_amt", "INR_vendor"),
    "total_long_contracts": ("long_ctr", "contracts"),
    "total_short_contracts": ("short_ctr", "contracts"),
    "total_call_long_contracts": ("call_long_ctr", "contracts"),
    "total_put_long_contracts": ("put_long_ctr", "contracts"),
    "total_call_short_contracts": ("call_short_ctr", "contracts"),
    "total_put_short_contracts": ("put_short_ctr", "contracts"),
}
_RECORD_KEYS = frozenset(FIELDS) | {"time_stamp"}
_TRADED = ("buy_amount", "sell_amount", "buy_contracts", "sell_contracts",
           "oi_contracts", "oi_amount")
_FUT = (*_TRADED, "total_long_contracts", "total_short_contracts")
_OPT = (*_TRADED, "total_call_long_contracts", "total_put_long_contracts",
        "total_call_short_contracts", "total_put_short_contracts")
APPLICABLE: dict[str, tuple[str, ...]] = {
    "NSE_EQ|CASH": ("buy_amount", "sell_amount"),
    "NSE_FO|INDEX_FUTURES": _FUT, "NSE_FO|STOCK_FUTURES": _FUT,
    "NSE_FO|INDEX_OPTIONS": _OPT, "NSE_FO|STOCK_OPTIONS": _OPT,
}
_VALUE_SCALE = 6                               # macro_observation.value numeric(24,6)
_VALUE_MAX = Decimal(10) ** 18
KNOWABLE_WHAT = "upstox fii/dii activity (no publication time; lag UNMEASURED)"


class InstitutionalDecodeError(Exception):
    """Not an FII/DII response at all. The archived bytes stay re-parseable."""


def series_code(side: str, data_type: str, interval: str, vendor_field: str) -> str:
    """e.g. FII|NSE_EQ|CASH|1D|buy_amt (at most 42 characters)."""
    return f"{side}|{data_type}|{interval}|{FIELDS[vendor_field][0]}"


def request_path(side: str, data_types: tuple[str, ...], interval: str,
                 end: _dt.date | None) -> str:
    if side not in SIDES or interval not in INTERVALS:
        raise ValueError(f"unsupported side/interval {side}/{interval}")
    bad = [t for t in data_types if t not in DATA_TYPES[side]]
    if not data_types or bad:
        raise ValueError(f"{side}: unsupported data_type(s) {bad or data_types}")
    q = f"data_type={','.join(data_types)}&interval={interval}"
    return f"/v2/market/{side.lower()}?{q}" + (f"&from={end.isoformat()}" if end else "")


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Observation:
    series_code: str
    observation_date: _dt.date
    value: Decimal
    unit: str
    vendor_payload: dict[str, Any]         # the vendor's record, verbatim
    knowable: Knowable


@dataclass(slots=True)
class ParsedSeries:
    """One data_type of one response."""
    data_type: str
    dates: list[_dt.date] = field(default_factory=list)    # oldest first, valid records
    rows: list[Observation] = field(default_factory=list)


@dataclass(slots=True)
class ParsedInstitutional:
    side: str
    interval: str
    series: dict[str, ParsedSeries] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(i.severity is AnomalySeverity.FAIL for i in self.issues)

    @property
    def rows(self) -> list[Observation]:
        return [r for s in self.series.values() for r in s.rows]


def _num(v: Any) -> Decimal | None:
    if isinstance(v, bool) or not isinstance(v, int | Decimal):
        return None
    d = Decimal(v)
    if not d.is_finite() or abs(d) >= _VALUE_MAX or -d.as_tuple().exponent > _VALUE_SCALE:
        return None
    return d


def parse_institutional(
    data: bytes, *, http_status: int, side: str, interval: str,
    data_types: tuple[str, ...], fetched_at: _dt.datetime,
) -> ParsedInstitutional:
    """Raises InstitutionalDecodeError for a non-JSON or non-200 body; every
    contract breach inside a well-formed body is a FAIL Issue instead."""
    if http_status != 200:
        raise InstitutionalDecodeError(f"HTTP {http_status}")
    try:
        # parse_float=Decimal: 9845.81 stays 9845.81, never 9845.809999...
        body = json.loads(data, parse_float=Decimal)
    except (ValueError, UnicodeDecodeError) as e:
        raise InstitutionalDecodeError(f"not JSON: {e}") from None
    if not isinstance(body, dict) or body.get("status") != "success":
        raise InstitutionalDecodeError(f"not a success envelope: {str(body)[:200]}")

    out = ParsedInstitutional(side, interval)
    knowable = for_announced_fact(None, fetched_at, what=KNOWABLE_WHAT)

    def fail(kind: AnomalyKind, subject: str | None, **detail: Any) -> None:
        out.issues.append(Issue(AnomalySeverity.FAIL, kind, subject, detail))

    if set(body) != {"status", "data"}:
        fail(AnomalyKind.SCHEMA_DRIFT, side, envelope_keys=sorted(body))
    payload = body.get("data")
    if not isinstance(payload, dict):
        fail(AnomalyKind.SCHEMA_DRIFT, side, reason="data is not an object")
        return out
    if set(payload) != set(data_types):
        fail(AnomalyKind.SCHEMA_DRIFT, side, reason="data_type keys differ from the request",
             requested=sorted(data_types), returned=sorted(payload))

    for dtype in data_types:
        records = payload.get(dtype)
        if records is None:
            continue                                   # already a FAIL above
        ps = out.series[dtype] = ParsedSeries(dtype)
        if not isinstance(records, list):
            fail(AnomalyKind.SCHEMA_DRIFT, dtype, reason="records are not a list")
            continue
        applicable = APPLICABLE[dtype]
        seen: set[_dt.date] = set()
        for rec in reversed(records):                  # vendor order: newest first
            if not isinstance(rec, dict) or set(rec) != _RECORD_KEYS:
                fail(AnomalyKind.SCHEMA_DRIFT, dtype, reason="record keys differ",
                     keys=sorted(rec) if isinstance(rec, dict) else type(rec).__name__)
                continue
            ts = rec["time_stamp"]
            if isinstance(ts, bool) or not isinstance(ts, int):
                fail(AnomalyKind.PARSE_REJECT, dtype, reason="time_stamp not an int", raw=str(ts))
                continue
            label = _dt.datetime.fromtimestamp(ts / 1000, IST)
            day = label.date()
            if label.time() != _dt.time(0):
                # The date is the only meaning a label has; a label off
                # midnight means the contract above no longer holds.
                fail(AnomalyKind.SCHEMA_DRIFT, dtype, reason="time_stamp is not 00:00 IST",
                     time_stamp=ts)
                continue
            if day in seen:
                fail(AnomalyKind.PARSE_REJECT, dtype, reason="duplicate date", date=str(day))
                continue
            if day >= fetched_at.astimezone(IST).date() + _dt.timedelta(days=1):
                fail(AnomalyKind.PARSE_REJECT, dtype, reason="date after the fetch",
                     date=str(day))
                continue
            vals: dict[str, Decimal] = {}
            bad = False
            for f in FIELDS:
                v = _num(rec[f])
                if v is None:
                    fail(AnomalyKind.PARSE_REJECT, dtype, reason="not a storable number",
                         date=str(day), field=f, raw=str(rec[f])[:40])
                    bad = True
                elif f not in applicable and v != 0:
                    fail(AnomalyKind.SCHEMA_DRIFT, dtype,
                         reason="non-zero value in a field measured as not applicable",
                         date=str(day), field=f, value=str(v))
                    bad = True
                vals[f] = v
            if bad:
                continue
            seen.add(day)
            ps.dates.append(day)
            raw = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in rec.items()}
            for f in applicable:
                ps.rows.append(Observation(
                    series_code(side, dtype, interval, f), day, vals[f], FIELDS[f][1],
                    raw, knowable))
    return out
