"""Upstox fundamentals responses -> snapshots. PURE.

Endpoints (GET /v2/fundamentals/{id}/{endpoint}; id = ISIN, except
competitors, which needs the instrument key; the docs say ISIN, and live it
answers 400 UDAPI100011 for an ISIN):

  statement_type                    endpoint + query
  profile                           profile
  key_ratios                        key-ratios
  share_holdings                    share-holdings
  competitors                       competitors                     (by instrument key)
  balance_sheet:<type>              balance-sheet?type=<type>&fs=true
  cash_flow:<type>                  cash-flow?type=<type>&fs=true
  income:<type>:<period>            income-statement?type=<type>&time_period=<period>&fs=true
  with <type> in consolidated / standalone and <period> in yearly / quarterly.

Shapes MEASURED 2026-09-24 (RELIANCE, an SME, an InvIT): statements are
objects {type, time_period, units_in ("crore"), <history lists>, full_statement};
key_ratios and share_holdings are lists; periods are "Mon YYYY" (e.g. "Mar 2026").
The data is KEPT AS SENT (fundamental_snapshot.payload): flattening is Stage 2.

TIME. No endpoint gives a publication or filing time. knowable_at = fetched_at,
unverified (for_announced_fact with no instant). period_end is the END of the
latest period in the response: a result for the quarter ending 30 Jun is NOT
knowable on 30 Jun, and nothing here claims it was.

Nothing here touches the network, the database or the filesystem.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.contracts.knowable import Knowable, for_announced_fact
from app.contracts.provenance import AnomalyKind, AnomalySeverity

TYPES = ("consolidated", "standalone")
PERIODS = ("yearly", "quarterly")
KNOWABLE_WHAT = "upstox fundamentals (no filing/publication time)"
_PERIOD = re.compile(r"^([A-Z][a-z]{2}) (\d{4})$")


@dataclass(frozen=True, slots=True)
class Variant:
    statement_type: str
    endpoint: str
    by_key: bool = False             # competitors: identified by instrument key

    def path(self, isin: str, instrument_key: str) -> str:
        from urllib.parse import quote
        ident = quote(instrument_key, safe="") if self.by_key else isin
        return f"/v2/fundamentals/{ident}/{self.endpoint}"


VARIANTS: tuple[Variant, ...] = (
    Variant("profile", "profile"),
    Variant("key_ratios", "key-ratios"),
    Variant("share_holdings", "share-holdings"),
    Variant("competitors", "competitors", by_key=True),
    *(Variant(f"balance_sheet:{t}", f"balance-sheet?type={t}&fs=true") for t in TYPES),
    *(Variant(f"cash_flow:{t}", f"cash-flow?type={t}&fs=true") for t in TYPES),
    *(Variant(f"income:{t}:{p}", f"income-statement?type={t}&time_period={p}&fs=true")
      for t in TYPES for p in PERIODS),
)


class FundamentalsDecodeError(Exception):
    """Not a fundamentals success response."""


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(slots=True)
class Snapshot:
    statement_type: str
    payload: Any                            # the vendor's `data`, verbatim
    period_end: _dt.date | None
    period_type: str | None                 # FY / Q / None
    periods: list[_dt.date]
    knowable: Knowable
    issues: list[Issue] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.payload in (None, {}, [])


def period_end(label: str) -> _dt.date:
    m = _PERIOD.match(label.strip())
    if not m:
        raise ValueError(f"period {label!r} is not 'Mon YYYY'")
    month = list(calendar.month_abbr).index(m.group(1))
    if month == 0:
        raise ValueError(f"period {label!r}: unknown month")
    year = int(m.group(2))
    return _dt.date(year, month, calendar.monthrange(year, month)[1])


def _periods(obj: Any) -> list[str]:
    """Every "period" value anywhere in the structure."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "period" and isinstance(v, str):
                out.append(v)
            else:
                out += _periods(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _periods(v)
    return out


def parse_fundamentals(data: bytes, *, http_status: int, variant: Variant, subject: str,
                       fetched_at: _dt.datetime) -> Snapshot:
    if http_status != 200:
        raise FundamentalsDecodeError(f"HTTP {http_status}")
    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError) as e:
        raise FundamentalsDecodeError(f"not JSON: {e}") from None
    if not isinstance(body, dict) or body.get("status") != "success":
        raise FundamentalsDecodeError(f"not a success envelope: {str(body)[:200]}")
    snap = Snapshot(variant.statement_type, body.get("data"), None, None, [],
                    for_announced_fact(None, fetched_at, what=KNOWABLE_WHAT))

    def issue(sev, kind, **d):
        snap.issues.append(Issue(sev, kind, subject, d))

    if set(body) != {"status", "data"}:
        issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, envelope_keys=sorted(body),
              statement_type=variant.statement_type)
    d = snap.payload
    expect_list = variant.statement_type in ("key_ratios", "share_holdings", "competitors")
    if d is not None and not isinstance(d, list if expect_list else dict):
        issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT,
              reason=f"data is {type(d).__name__}", statement_type=variant.statement_type)
        return snap
    if isinstance(d, dict) and ":" in variant.statement_type:
        want_type = variant.statement_type.split(":")[1]
        if d.get("type") not in (None, want_type):
            issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, reason="type differs",
                  asked=want_type, got=d.get("type"))
        if variant.statement_type.startswith("income:"):
            want_p = variant.statement_type.split(":")[2]
            if d.get("time_period") not in (None, want_p):
                issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT,
                      reason="time_period differs", asked=want_p, got=d.get("time_period"))
    if variant.statement_type in ("profile", "competitors"):
        return snap
    try:
        ends = sorted({period_end(p) for p in _periods(d)})
    except ValueError as e:
        issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, reason=str(e)[:200],
              statement_type=variant.statement_type)
        return snap
    snap.periods = ends
    if ends:
        snap.period_end = ends[-1]
        quarterly = variant.statement_type.endswith(":quarterly") \
            or variant.statement_type == "share_holdings"
        snap.period_type = "Q" if quarterly else "FY"
        if snap.period_end > fetched_at.date() + _dt.timedelta(days=1):
            issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT,
                  reason="latest period ends after the fetch (kept as sent)",
                  period_end=str(snap.period_end), statement_type=variant.statement_type)
    return snap
