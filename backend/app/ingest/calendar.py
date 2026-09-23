"""Upstox calendar -> trading_session, through the standard run lifecycle.

    holidays payload + one timings payload per date
      -> PayloadStore.put()      every payload archived BEFORE parsing
      -> parse + decide()        pure; both sources must agree
      -> trading_session         one transaction

A row's payload_sha256 is the TIMINGS payload for its date (it sets the
hours); the holidays payload that classified it is named in `note`.

knowable_at: neither endpoint states when the calendar was published, so the
honest bound is fetched_at (unverified). A session is known in advance of its
day, so this bound is conservative, never optimistic.

trading_session is keyed by session_date alone: one assertion per day. A
repeated run with the same decision is a no-op; a DIFFERENT decision for a day
already recorded fails the run and leaves the recorded row untouched. Revising
the calendar is a deliberate act, never an overwrite.
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.knowable import for_announced_fact
from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.errors import IngestCheckFailed
from app.db.models import TradingSession
from app.ingest.checks import check_provenance_complete
from app.ingest.runner import IngestRunner
from app.parsers.upstox_calendar import (
    CalendarDecodeError,
    SessionDecision,
    decide,
    parse_holidays,
    parse_timings,
)
from app.sources.upstox_calendar import API, HOLIDAYS_PATH, Fetched
from app.storage.payload_store import PayloadStore

SOURCE = Source.UPSTOX_REST_V2.value
STREAM = "calendar.nse"
MAX_DAYS = 400

HolidaysFn = Callable[[], Awaitable[Fetched]]
TimingsFn = Callable[[_dt.date], Awaitable[Fetched]]

_COMPARE = ("is_trading_day", "session_type", "preopen_start_ist", "preopen_end_ist",
            "open_ist", "close_ist")


@dataclass(slots=True)
class CalendarReport:
    run_id: uuid.UUID | None = None
    status: str = ""
    committed: bool = False
    date_from: str = ""
    date_to: str = ""
    holidays_sha256: str = ""
    by_type: dict[str, int] = field(default_factory=dict)
    days: int = 0
    rows_written: int = 0
    already_recorded: int = 0
    sessions: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _cover(holidays) -> tuple[_dt.date, _dt.date] | None:
    """The years the holiday list speaks for. Assumption, documented: a list
    that has entries for year Y lists every NSE holiday of year Y."""
    if not holidays:
        return None
    years = sorted({d.year for d in holidays})
    return _dt.date(years[0], 1, 1), _dt.date(years[-1], 12, 31)


def _row(d: SessionDecision) -> dict[str, Any]:
    return {"session_date": d.session_date, "is_trading_day": d.is_trading_day,
            "session_type": d.session_type.value, "open_ist": d.open_ist,
            "close_ist": d.close_ist, "preopen_start_ist": d.preopen_start_ist,
            "preopen_end_ist": d.preopen_end_ist}


async def ingest_calendar(
    session: AsyncSession,
    *,
    date_from: _dt.date,
    date_to: _dt.date,
    holidays: HolidaysFn,
    timings: TimingsFn,
    store: PayloadStore,
    commit: bool,
    token: str | None,
    operator: str = "cli",
) -> CalendarReport:
    if date_to < date_from:
        raise ValueError("date_to is before date_from")
    ndays = (date_to - date_from).days + 1
    if ndays > MAX_DAYS:
        raise ValueError(f"{ndays} days requested; at most {MAX_DAYS} per run")

    report = CalendarReport(committed=commit, date_from=date_from.isoformat(),
                            date_to=date_to.isoformat(), days=ndays)
    runner = IngestRunner(
        session, source=SOURCE, stream=STREAM, vendor_endpoint=API + HOLIDAYS_PATH,
        request_params={"from": date_from.isoformat(), "to": date_to.isoformat(),
                        "exchange": "NSE"},
        operator=operator, logical_date=date_from,
    )
    ctx = await runner.open(commit=commit, token=token)
    report.run_id = ctx.run_id
    checks = ctx.checks

    def archive(f: Fetched):
        return store.put(f.data, source=SOURCE, fetched_at=f.fetched_at, ext="json")

    try:
        hf = await holidays()
        hstored = archive(hf)
        report.holidays_sha256 = hstored.sha256
        if commit:
            await runner.record_payload(hstored, http_status=hf.http_status,
                                        vendor_endpoint=hf.url)
        try:
            hol, issues = parse_holidays(hf.data)
        except CalendarDecodeError as e:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "holidays", error=str(e))
            raise IngestCheckFailed(str(e)) from None
        for i in issues:
            checks.add(i.severity, i.kind, i.subject, **i.detail)
        cover = _cover(hol)

        rows: list[dict[str, Any]] = []
        decided: list[SessionDecision] = []
        for n in range(ndays):
            day = date_from + _dt.timedelta(days=n)
            tf = await timings(day)
            tstored = archive(tf)
            if commit:
                await runner.record_payload(tstored, http_status=tf.http_status,
                                            vendor_endpoint=tf.url)
            try:
                nse = parse_timings(tf.data, day)
            except CalendarDecodeError as e:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, f"timings[{day}]",
                           error=str(e))
                continue
            res = decide(day, hol, nse, holidays_cover=cover)
            for i in res.issues:
                checks.add(i.severity, i.kind, i.subject, **i.detail)
            if res.decision is None:
                continue
            d = res.decision
            k = for_announced_fact(None, tf.fetched_at, what="NSE session calendar")
            note = {**d.note, "holidays_payload_sha256": hstored.sha256,
                    "timings_url": tf.url}
            rows.append({**_row(d), "note": json.dumps(note, sort_keys=True),
                         "source": SOURCE, "run_id": ctx.run_id,
                         "payload_sha256": tstored.sha256, "fetched_at": tf.fetched_at,
                         "knowable_at": k.at, "knowable_at_verified": k.verified,
                         "knowable_at_basis": k.basis})
            decided.append(d)
            report.by_type[d.session_type.value] = report.by_type.get(d.session_type.value, 0) + 1

        report.sessions = [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                            for k, v in _row(d).items()} for d in decided]
        check_provenance_complete(checks, rows=rows, stream=STREAM)

        # One assertion per day: identical is a no-op, different is refused.
        existing = {
            r.session_date: r for r in (await session.execute(
                select(TradingSession).where(TradingSession.session_date.between(
                    date_from, date_to)))).scalars()
        }
        fresh = []
        for row in rows:
            old = existing.get(row["session_date"])
            if old is None:
                fresh.append(row)
                continue
            diff = [c for c in _COMPARE if getattr(old, c) != row[c]]
            if diff:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY,
                           f"trading_session[{row['session_date']}]",
                           reason="a different session is already recorded for this date",
                           differing=diff,
                           recorded={c: str(getattr(old, c)) for c in diff},
                           new={c: str(row[c]) for c in diff})
            else:
                report.already_recorded += 1

        checks.raise_if_failed()
        if commit and fresh:
            await session.execute(pg_insert(TradingSession).values(fresh))
            report.rows_written = len(fresh)
    except IngestCheckFailed as e:
        report.error = str(e)
        report.anomalies = [_anomaly(a) for a in checks.anomalies]
        await runner.fail(str(e))
        report.status, report.rows_written = RunStatus.FAILED.value, 0
        return report
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}")
        raise

    report.anomalies = [_anomaly(a) for a in checks.anomalies]
    await runner.finalize(rows_written=report.rows_written)
    report.status = RunStatus.COMPLETE.value
    return report


def _anomaly(a) -> dict[str, Any]:
    return {"severity": a.severity.value, "kind": a.kind.value, "subject": a.subject,
            "detail": a.detail}
