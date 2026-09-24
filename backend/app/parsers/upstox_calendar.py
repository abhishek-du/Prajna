"""Upstox market calendar -> NSE trading-session decisions. PURE.

Two vendor payloads, semantics MEASURED on 2026-09-23 (real responses kept as
tests/fixtures/upstox_calendar):

  GET /v2/market/holidays        one year of entries:
      {date, description, holiday_type, closed_exchanges[], open_exchanges[
       {exchange, start_time, end_time}]}, times in epoch ms.
      holiday_type is TRADING_HOLIDAY (NSE listed in closed_exchanges),
      SETTLEMENT_HOLIDAY (NSE OPEN: this is B9's "holiday that wasn't"), or
      SPECIAL_TIMING (NSE open at non-standard hours: the 2026-02-01 Sunday
      Budget session at 09:15-15:30, the 2026-11-08 Sunday Muhurat at 18:00-19:00).

  GET /v2/market/timings/{date}  per-exchange hours for one date; EMPTY on
      weekends and trading holidays. NSE's start_time is the continuous-session
      open (09:15 on a normal day), NOT the pre-open start.

The decision for a date takes BOTH and requires them to agree. Session hours
always come from the timings payload; nothing assumes 09:15-15:30.

PRE-OPEN is not published by either endpoint. For a NORMAL session opening at
09:15 the window is filled as 09:00-09:15 from NSE's published rule and
labelled as derived. For any other session it is left NULL (unknown), never
guessed. The live recorder's preOpenSessionStatus transitions are the check.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.contracts.session import SessionType
from app.core.clock import IST, epoch_ms_to_utc

NSE = "NSE"
TRADING_HOLIDAY = "TRADING_HOLIDAY"
SETTLEMENT_HOLIDAY = "SETTLEMENT_HOLIDAY"
SPECIAL_TIMING = "SPECIAL_TIMING"
KNOWN_HOLIDAY_TYPES = frozenset({TRADING_HOLIDAY, SETTLEMENT_HOLIDAY, SPECIAL_TIMING})

NSE_REGULAR_OPEN = _dt.time(9, 15)
NSE_REGULAR_PREOPEN = (_dt.time(9, 0), _dt.time(9, 15))
PREOPEN_DERIVED_BASIS = ("NSE regular pre-open 09:00-09:15 (derived from the exchange rule; "
                         "not vendor-supplied; verify against preOpenSessionStatus)")


class CalendarDecodeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Issue:
    severity: AnomalySeverity
    kind: AnomalyKind
    subject: str | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Hours:
    start: _dt.datetime   # tz-aware UTC
    end: _dt.datetime

    def ist_times(self) -> tuple[_dt.time, _dt.time]:
        return self.start.astimezone(IST).time(), self.end.astimezone(IST).time()


@dataclass(frozen=True, slots=True)
class HolidayEntry:
    date: _dt.date
    description: str
    holiday_type: str
    nse_closed: bool
    nse_hours: Hours | None


@dataclass(frozen=True, slots=True)
class SessionDecision:
    session_date: _dt.date
    is_trading_day: bool
    session_type: SessionType
    open_ist: _dt.time | None
    close_ist: _dt.time | None
    preopen_start_ist: _dt.time | None
    preopen_end_ist: _dt.time | None
    note: dict[str, Any]


@dataclass(slots=True)
class DecisionResult:
    decision: SessionDecision | None = None
    issues: list[Issue] = field(default_factory=list)

    def fail(self, day: _dt.date, reason: str, **detail: Any) -> DecisionResult:
        self.issues.append(Issue(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT,
                                 f"trading_session[{day}]", {"reason": reason, **detail}))
        self.decision = None
        return self


def _body(data: bytes, what: str) -> list:
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError) as e:
        raise CalendarDecodeError(f"{what}: not JSON: {e}") from None
    if not isinstance(doc, dict) or doc.get("status") != "success" or not isinstance(
            doc.get("data"), list):
        raise CalendarDecodeError(f"{what}: unexpected envelope {str(doc)[:200]}")
    return doc["data"]


def _hours(entry: dict, what: str) -> Hours:
    try:
        return Hours(epoch_ms_to_utc(int(entry["start_time"])),
                     epoch_ms_to_utc(int(entry["end_time"])))
    except (KeyError, TypeError, ValueError):
        raise CalendarDecodeError(f"{what}: bad start_time/end_time in {entry}") from None


def parse_holidays(data: bytes) -> tuple[dict[_dt.date, list[HolidayEntry]], list[Issue]]:
    issues: list[Issue] = []
    out: dict[_dt.date, list[HolidayEntry]] = {}
    for i, e in enumerate(_body(data, "holidays")):
        try:
            day = _dt.date.fromisoformat(e["date"])
        except (KeyError, TypeError, ValueError):
            raise CalendarDecodeError(f"holidays[{i}]: bad date in {e}") from None
        htype = e.get("holiday_type")
        if htype not in KNOWN_HOLIDAY_TYPES:
            issues.append(Issue(AnomalySeverity.FAIL, AnomalyKind.SCHEMA_DRIFT,
                                f"holidays[{day}]", {"holiday_type": htype}))
        nse_open = [o for o in e.get("open_exchanges") or [] if o.get("exchange") == NSE]
        if len(nse_open) > 1:
            raise CalendarDecodeError(f"holidays[{day}]: NSE listed open {len(nse_open)} times")
        out.setdefault(day, []).append(HolidayEntry(
            date=day, description=str(e.get("description") or ""), holiday_type=str(htype),
            nse_closed=NSE in (e.get("closed_exchanges") or []),
            nse_hours=_hours(nse_open[0], f"holidays[{day}]") if nse_open else None,
        ))
    return out, issues


def parse_timings(data: bytes, day: _dt.date) -> Hours | None:
    nse = [e for e in _body(data, f"timings[{day}]") if e.get("exchange") == NSE]
    if len(nse) > 1:
        raise CalendarDecodeError(f"timings[{day}]: NSE listed {len(nse)} times")
    return _hours(nse[0], f"timings[{day}]") if nse else None


def decide(
    day: _dt.date, holidays: dict[_dt.date, list[HolidayEntry]] | None, nse: Hours | None,
    *, holidays_cover: tuple[_dt.date, _dt.date] | None,
) -> DecisionResult:
    """One date. `holidays_cover` is the date span the holiday list is known to
    cover; outside it a missing entry proves nothing and a non-trading weekday
    is refused rather than guessed."""
    res = DecisionResult()
    entries = (holidays or {}).get(day, [])
    if len(entries) > 1:
        return res.fail(day, "several holiday entries for one date",
                        types=[e.holiday_type for e in entries])
    h = entries[0] if entries else None
    weekend = day.weekday() >= 5
    covered = holidays_cover is not None and holidays_cover[0] <= day <= holidays_cover[1]
    note: dict[str, Any] = {"weekday": day.strftime("%a")}
    if h:
        note.update(holiday_type=h.holiday_type, description=h.description)

    if nse is None:
        if h and h.holiday_type == TRADING_HOLIDAY and h.nse_closed:
            res.decision = SessionDecision(day, False, SessionType.HOLIDAY,
                                           None, None, None, None, note)
        elif h and h.holiday_type in (SPECIAL_TIMING, SETTLEMENT_HOLIDAY) and not h.nse_closed:
            return res.fail(day, f"{h.holiday_type} says NSE is open but timings has no NSE")
        elif weekend and not h:
            res.decision = SessionDecision(day, False, SessionType.WEEKEND,
                                           None, None, None, None, note)
        elif not covered:
            return res.fail(day, "no NSE timings and the holiday list does not cover this date")
        else:
            return res.fail(day, "weekday with no NSE timings and no NSE holiday entry")
        return res

    # NSE is open per timings.
    if nse.start.astimezone(IST).date() != day or nse.end.astimezone(IST).date() != day:
        return res.fail(day, "timings hours fall on another IST date",
                        start=nse.start.isoformat(), end=nse.end.isoformat())
    if nse.end <= nse.start:
        return res.fail(day, "timings end is not after start")
    if h and h.nse_closed:
        return res.fail(day, "holiday list closes NSE but timings opens it",
                        holiday_type=h.holiday_type)
    if h and h.nse_hours and h.nse_hours != nse:
        return res.fail(day, "holiday list and timings disagree on NSE hours",
                        holiday=[t.isoformat() for t in h.nse_hours.ist_times()],
                        timings=[t.isoformat() for t in nse.ist_times()])

    open_t, close_t = nse.ist_times()
    if h and h.holiday_type == SPECIAL_TIMING:
        stype = SessionType.SPECIAL
    elif weekend:
        stype = SessionType.SPECIAL
        res.issues.append(Issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT,
                                f"trading_session[{day}]",
                                {"reason": "weekend session with no holiday-list entry"}))
    else:
        stype = SessionType.NORMAL

    if stype is SessionType.NORMAL and open_t == NSE_REGULAR_OPEN:
        pre = NSE_REGULAR_PREOPEN
        note["preopen_basis"] = PREOPEN_DERIVED_BASIS
    else:
        pre = (None, None)
        note["preopen_basis"] = "UNKNOWN: not vendor-supplied for this session type"
    note["hours_basis"] = "upstox /v2/market/timings NSE"
    res.decision = SessionDecision(day, True, stype, open_t, close_t, pre[0], pre[1], note)
    return res


# ── past dates ──────────────────────────────────────────────────────────────
# MEASURED 2026-09-24: for PAST dates /v2/market/timings/{date} answers the
# generic weekday schedule even on holidays (2020-10-02 Gandhi Jayanti,
# 2021-01-26, 2022-08-15 all show NSE 09:15-15:30). It is no evidence that a
# past session happened. For past dates the evidence is Upstox's own NIFTY 50
# daily candle: an index bar exists exactly on the days NSE traded.
HISTORICAL_EVIDENCE_BASIS = ("past date: session existence from the Upstox NIFTY 50 daily "
                             "bar; /v2/market/timings is a generic schedule for past dates")


def decide_historical(day: _dt.date, *, index_bar: bool,
                      holiday: HolidayEntry | None, holiday_asked: bool,
                      nse: Hours | None) -> DecisionResult:
    """One PAST date. `index_bar`: NIFTY 50 has a daily bar on `day`.
    `holiday`: the per-date holiday entry (if asked and present)."""
    res = DecisionResult()
    weekend = day.weekday() >= 5
    note: dict[str, Any] = {"weekday": day.strftime("%a"), "evidence": HISTORICAL_EVIDENCE_BASIS,
                            "index_bar": index_bar}
    if holiday:
        note.update(holiday_type=holiday.holiday_type, description=holiday.description)
    if index_bar:
        if weekend or (holiday and holiday.nse_closed):
            # e.g. a Muhurat or Budget-day session: the hours of that session
            # are not known from a generic schedule.
            note["hours_basis"] = "UNKNOWN: special session; timings is generic for past dates"
            note["preopen_basis"] = "UNKNOWN: special session"
            res.decision = SessionDecision(day, True, SessionType.SPECIAL, None, None, None,
                                           None, note)
            res.issues.append(Issue(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT,
                                    f"trading_session[{day}]",
                                    {"reason": "session on a weekend/holiday (index bar exists)"}))
            return res
        if nse is None:
            return res.fail(day, "index bar exists but timings gives no NSE hours")
        open_t, close_t = nse.ist_times()
        pre = NSE_REGULAR_PREOPEN if open_t == NSE_REGULAR_OPEN else (None, None)
        note["hours_basis"] = "upstox /v2/market/timings NSE (generic schedule for past dates)"
        note["preopen_basis"] = PREOPEN_DERIVED_BASIS if pre[0] else "UNKNOWN"
        res.decision = SessionDecision(day, True, SessionType.NORMAL, open_t, close_t,
                                       pre[0], pre[1], note)
        return res
    if weekend:
        res.decision = SessionDecision(day, False, SessionType.WEEKEND, None, None, None,
                                       None, note)
        return res
    if holiday and holiday.holiday_type == TRADING_HOLIDAY and holiday.nse_closed:
        res.decision = SessionDecision(day, False, SessionType.HOLIDAY, None, None, None,
                                       None, note)
        return res
    return res.fail(day, "weekday without an index bar and without an NSE holiday entry",
                    holiday_asked=holiday_asked,
                    holiday_type=holiday.holiday_type if holiday else None)
