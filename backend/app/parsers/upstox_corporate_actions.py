"""Upstox corporate actions -> typed events. PURE.

Endpoint: GET /v2/fundamentals/{ISIN}/corporate-actions

Shape MEASURED 2026-09-24 on 250 random NSE_EQ ISINs (fixtures in
tests/fixtures/upstox_corporate_actions):
  {"status": "success", "data": [event, ...]}      (an empty list is common)
  event = {name, expiry_date, amount, ratio, event_details: [{name, value}, ...]}
  name -> labels observed (all dates "DD Mon YYYY", no time):
    Dividend      Announcement date, Ex dividend date, Record date, Dividend type,
                  Amount, Dividend %, Details
    Bonus         Announcement date, Ex Bonus date, Record date, Ratio, Details
    Split         Announcement date, Ex split date, Record date, Ratio,
                  Old face value, New face value, Details
    Rights Issue  Announcement date, Ex rights date, Record date, Ratio, Premium,
                  Details
  History is short: roughly the last year (the earliest announcement seen was
  Sep 2025).

IDENTITY. Two different events can share (ISIN, type, ex-date): 7 of 172
sampled events were a second dividend on the same ex-date with another amount
and announcement date. An event is therefore identified by its whole content
(`content_sha256`, over the vendor's event object, canonical JSON). A vendor
edit of an event is indistinguishable from a new event; it is stored as one,
and the ingest flags every (ISIN, type, ex-date) that gains a second event.

TIME. The announcement is a DATE without a time, so `announced_at` stays NULL
(no invented time) and the date is kept in `announcement_date` and the raw
payload. knowable_at follows decision KN-CA (user, 2026-09-24):
contracts.knowable.for_announcement_date = the END of the announcement day in
IST, never later than fetched_at, unverified. Without an announcement date:
fetched_at (for_announced_fact with no instant).

RATIO. Stored verbatim in the vendor's A:B order (ratio_from = A,
ratio_to = B). A split "5:10" with face value 10 -> 5 shows A = new, B = old
for splits; the Details text is kept, and no direction is assumed here.

Nothing here touches the network, the database or the filesystem.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.contracts.knowable import Knowable, for_announced_fact, for_announcement_date
from app.contracts.provenance import AnomalyKind, AnomalySeverity

TYPES = {"Dividend": "DIVIDEND", "Bonus": "BONUS", "Split": "SPLIT", "Rights Issue": "RIGHTS"}
LABELS = {
    "Dividend": {"Announcement date", "Ex dividend date", "Record date", "Dividend type",
                 "Amount", "Dividend %", "Details"},
    "Bonus": {"Announcement date", "Ex Bonus date", "Record date", "Ratio", "Details"},
    "Split": {"Announcement date", "Ex split date", "Record date", "Ratio", "Old face value",
              "New face value", "Details"},
    "Rights Issue": {"Announcement date", "Ex rights date", "Record date", "Ratio", "Premium",
                     "Details"},
}
_EVENT_KEYS = frozenset({"name", "expiry_date", "amount", "ratio", "event_details"})
KNOWABLE_WHAT = "upstox corporate action (announcement is a date, no time)"


class CorporateActionDecodeError(Exception):
    """Not a corporate-actions response at all."""


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Event:
    isin: str
    action_type: str
    ex_date: _dt.date | None
    record_date: _dt.date | None
    announcement_date: _dt.date | None
    amount: Decimal | None
    ratio_from: Decimal | None
    ratio_to: Decimal | None
    face_value_before: Decimal | None
    face_value_after: Decimal | None
    content_sha256: str
    vendor_payload: dict[str, Any]
    knowable: Knowable


@dataclass(slots=True)
class ParsedActions:
    isin: str
    events: list[Event] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(i.severity is AnomalySeverity.FAIL for i in self.issues)


def content_sha256(event: dict) -> str:
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def _date(s: Any) -> _dt.date | None:
    if not isinstance(s, str) or not s.strip():
        return None
    return _dt.datetime.strptime(s.strip(), "%d %b %Y").date()


def _dec(s: Any) -> Decimal | None:
    if s is None or isinstance(s, bool):
        return None
    try:
        d = Decimal(str(s))
    except InvalidOperation:
        raise ValueError(f"not a number: {s!r}") from None
    if not d.is_finite():
        raise ValueError(f"not finite: {s!r}")
    return d


def _ratio(s: Any) -> tuple[Decimal | None, Decimal | None]:
    if s in (None, ""):
        return None, None
    a, sep, b = str(s).partition(":")
    if not sep:
        raise ValueError(f"ratio without ':': {s!r}")
    return _dec(a), _dec(b)


def parse_corporate_actions(data: bytes, *, http_status: int, isin: str,
                            fetched_at: _dt.datetime) -> ParsedActions:
    if http_status != 200:
        raise CorporateActionDecodeError(f"HTTP {http_status}")
    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError) as e:
        raise CorporateActionDecodeError(f"not JSON: {e}") from None
    if not isinstance(body, dict) or body.get("status") != "success":
        raise CorporateActionDecodeError(f"not a success envelope: {str(body)[:200]}")
    out = ParsedActions(isin)

    def issue(sev, kind, **d):
        out.issues.append(Issue(sev, kind, isin, d))

    if set(body) != {"status", "data"}:
        issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, envelope_keys=sorted(body))
    data_ = body.get("data")
    if data_ is None:
        data_ = []
    if not isinstance(data_, list):
        issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, reason="data is not a list")
        return out
    seen: set[str] = set()
    for ev in data_:
        if not isinstance(ev, dict) or set(ev) != _EVENT_KEYS \
                or not isinstance(ev.get("event_details"), list):
            issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, reason="event keys differ",
                  keys=sorted(ev) if isinstance(ev, dict) else None)
            continue
        name = ev["name"]
        details: dict[str, Any] = {}
        for x in ev["event_details"]:
            if not isinstance(x, dict) or set(x) != {"name", "value"}:
                issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT, reason="detail shape",
                      detail=str(x)[:100])
                continue
            details[x["name"]] = x["value"]
        if name not in TYPES:
            issue(AnomalySeverity.WARN, AnomalyKind.SCHEMA_DRIFT,
                  reason="event type not measured; stored as OTHER with the raw event",
                  name=str(name)[:40])
        elif set(details) != LABELS[name]:
            issue(AnomalySeverity.WARN, AnomalyKind.SCHEMA_DRIFT,
                  reason="detail labels differ from the measured set (raw kept)", name=name,
                  extra=sorted(set(details) - LABELS[name]),
                  missing=sorted(LABELS[name] - set(details)))
        try:
            ex_label = next((k for k in details if k.lower().startswith("ex ")), None)
            ex_date = _date(details.get(ex_label)) if ex_label else None
            expiry = _date(ev.get("expiry_date"))
            record = _date(details.get("Record date"))
            announced = _date(details.get("Announcement date"))
            amount = _dec(ev.get("amount"))
            r_from, r_to = _ratio(ev.get("ratio"))
            fv_old = _dec(details.get("Old face value"))
            fv_new = _dec(details.get("New face value"))
        except ValueError as e:
            issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, reason=str(e)[:200],
                  event=str(ev)[:300])
            continue
        if ex_date is None:
            ex_date = expiry
            if expiry is not None:
                issue(AnomalySeverity.WARN, AnomalyKind.SCHEMA_DRIFT,
                      reason="no 'Ex ...' detail; expiry_date used as the ex-date", name=name)
        elif expiry is not None and expiry != ex_date:
            issue(AnomalySeverity.WARN, AnomalyKind.SCHEMA_DRIFT,
                  reason="expiry_date differs from the ex-date detail", name=name,
                  ex_date=str(ex_date), expiry_date=str(expiry))
        if announced and ex_date and announced > ex_date:
            issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT,
                  reason="announced after the ex-date (kept as sent)", name=name,
                  announced=str(announced), ex_date=str(ex_date))
        knowable = (for_announcement_date(announced, fetched_at, what=KNOWABLE_WHAT)
                     if announced else for_announced_fact(None, fetched_at, what=KNOWABLE_WHAT))
        h = content_sha256(ev)
        if h in seen:
            continue                        # the same event listed twice in one response
        seen.add(h)
        out.events.append(Event(
            isin=isin, action_type=TYPES.get(name, "OTHER"), ex_date=ex_date,
            record_date=record, announcement_date=announced,
            amount=amount if name == "Dividend" else (amount or None),
            ratio_from=r_from, ratio_to=r_to, face_value_before=fv_old, face_value_after=fv_new,
            content_sha256=h, vendor_payload=ev, knowable=knowable))
    return out
