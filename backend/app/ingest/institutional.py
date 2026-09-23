"""FII / DII activity: Upstox -> raw archive -> parse -> macro_observation.

    for each (side, data_type) STREAM, windows oldest first:
        IngestRunner.open            one run per request, BEFORE the request
        UpstoxRestClient.get         rate limited; 429 / auth stops everything
        PayloadStore.put             archived BEFORE parsing, errors included
        parse_institutional          pure; applicable fields only
        continuity + calendar check  a gap FAILS the run
        rows -> macro_observation    identical = no-op, different = FAIL
        finalize(outcome=...)        what the window returned, on the run

WINDOWS. A 1D request with from=X returns the 30 trading days ENDING at X
(measured). Consecutive requests step X by STEP_DAYS calendar days past the
last date already covered. 28 calendar days hold at most 20 trading days, so
every window overlaps the one before it by at least 10 trading days, and the
overlap is CHECKED: a window whose first date is later than the checkpoint
means the vendor skipped days, which is a GAP (FAIL) and stops the stream.

WHAT IS PERSISTED.
  * Only the fields that apply to the data_type (see the parser).
  * Only dates BEFORE the fetch day (IST). The publication time is unmeasured
    and a same-day figure may still be provisional, so the fetch day is
    fetched again on a later day. This is the same rule as the daily candle.
  * knowable_at = fetched_at, unverified: the vendor gives no publication time.
  * REVISIONS follow D3's current policy (not decided here): the same
    (series, date) with the same value is a no-op; a different value is a
    DUPLICATE_KEY FAIL and nothing is overwritten. macro_observation's unique
    key includes knowable_at, so versioned storage would need no migration,
    but it is not enabled without a D3 decision.

CHECKPOINT. Stream macro.<side>.<data_type>.1D; last_logical_date means "every
date from the earliest stored date up to this one is persisted". It never moves
backwards and never passes the day before the fetch. A run asking for an
earlier start than the earliest stored date ignores it and walks from start.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.clock import IST, now
from app.core.errors import IngestCheckFailed, RateLimited, VendorAuthError, VendorError
from app.db.models import IngestWatermark, MacroObservation, TradingSession
from app.ingest.checks import check_provenance_complete
from app.ingest.runner import IngestRunner
from app.parsers import upstox_institutional as P
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import UpstoxRestClient

SOURCE = Source.UPSTOX_REST_V2.value
STEP_DAYS = 28                    # calendar days; <= 20 trading days < a 30-day window
INTERVAL = "1D"


def watermark_stream(side: str, data_type: str, interval: str = INTERVAL) -> str:
    return f"macro.{side}.{data_type}.{interval}"


@dataclass(slots=True)
class WindowResult:
    side: str
    data_type: str
    end: _dt.date
    status: str      # COMPLETE / STALLED / FAILED / ABORTED / NOT_ATTEMPTED
    run_id: uuid.UUID | None = None
    outcome: dict[str, Any] | None = None
    inserted: int = 0
    already_present: int = 0
    complete_through: str | None = None
    error: str | None = None


@dataclass(slots=True)
class InstitutionalReport:
    committed: bool
    results: list[WindowResult] = field(default_factory=list)
    stopped: str | None = None

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    def summary(self) -> dict[str, Any]:
        return {
            "committed": self.committed, "requests": len(self.results),
            "inserted": sum(r.inserted for r in self.results),
            "already_present": sum(r.already_present for r in self.results),
            "stopped": self.stopped,
            **{s.lower(): self.count(s) for s in ("COMPLETE", "STALLED", "FAILED", "ABORTED",
                                                   "NOT_ATTEMPTED")},
            "streams": {watermark_stream(r.side, r.data_type): r.complete_through
                        for r in self.results if r.status in ("COMPLETE", "STALLED")},
        }


class InstitutionalIngestor:
    def __init__(self, session: AsyncSession, rest: UpstoxRestClient, store: PayloadStore, *,
                 commit: bool, token: str | None, operator: str = "cli"):
        self.s, self.rest, self.store = session, rest, store
        self.commit, self.token, self.operator = commit, token, operator

    async def watermark(self, stream: str) -> _dt.date | None:
        wm = await self.s.get(IngestWatermark, (SOURCE, stream))
        return wm.last_logical_date if wm else None

    async def run(self, series: list[tuple[str, str]], *, start: _dt.date = P.DATA_START,
                  resume: bool = True, max_requests: int = 50) -> InstitutionalReport:
        """series: (side, data_type) pairs. Each is walked from its checkpoint
        (or `start`) up to today, one request per window."""
        rep = InstitutionalReport(committed=self.commit)
        start = max(start, P.DATA_START)      # nothing exists before it (measured)
        for side, dtype in series:
            P.request_path(side, (dtype,), INTERVAL, None)      # validates the pair
        for side, dtype in series:
            mark = await self.watermark(watermark_stream(side, dtype)) if resume else None
            if mark is not None and mark < start:
                mark = None                   # a checkpoint older than the ask is no help
            if mark is not None:
                # The checkpoint covers "from the first requested date". A run
                # asking for an earlier start must not resume from it: walk from
                # `start` instead (what is stored already dedupes as a no-op).
                first = await self._first_stored(side, dtype)
                if first is None or first > start:
                    mark = None
            sent = 0
            while True:
                if rep.stopped:
                    rep.results.append(WindowResult(side, dtype, now().astimezone(IST).date(),
                                                    "NOT_ATTEMPTED", error=rep.stopped))
                    break
                today = now().astimezone(IST).date()
                end = min((mark or start) + _dt.timedelta(days=STEP_DAYS), today)
                res = await self._one(side, dtype, end, mark=mark, start=start)
                rep.results.append(res)
                sent += 1
                if res.status == "ABORTED":
                    rep.stopped = res.error
                    break
                if res.status != "COMPLETE" or end >= today:
                    break
                through = _dt.date.fromisoformat(res.complete_through) \
                    if res.complete_through else None
                if through is None or (mark is not None and through <= mark):
                    # No progress: a window 28 days past the checkpoint held no
                    # newer date. The run itself is fine (COMPLETE in the
                    # ledger); the WALK is stalled, which is reported, not hidden.
                    res.status = "STALLED"
                    res.error = f"no date after {mark} in the window ending {end}"
                    break
                mark = through
                if sent >= max_requests:
                    rep.stopped = f"max_requests={max_requests} reached"
                    break
        return rep

    async def _first_stored(self, side: str, dtype: str) -> _dt.date | None:
        codes = [P.series_code(side, dtype, INTERVAL, f) for f in P.APPLICABLE[dtype]]
        return (await self.s.execute(
            select(func.min(MacroObservation.observation_date)).where(
                MacroObservation.series_code.in_(codes),
                MacroObservation.source == SOURCE))).scalar()

    async def _trading_days(self, lo: _dt.date, hi: _dt.date) -> tuple[set[_dt.date], int]:
        """Trading days the calendar KNOWS in [lo, hi], and how many calendar
        rows it has there. Dates with no calendar row are not assumed either
        way; they are covered by the overlap check only."""
        rows = (await self.s.execute(
            select(TradingSession.session_date, TradingSession.is_trading_day).where(
                TradingSession.session_date.between(lo, hi)))).all()
        return {d for d, t in rows if t}, len(rows)

    async def _one(self, side: str, dtype: str, end: _dt.date, *, mark: _dt.date | None,
                   start: _dt.date) -> WindowResult:
        stream = watermark_stream(side, dtype)
        path = P.request_path(side, (dtype,), INTERVAL, end)
        runner = IngestRunner(
            self.s, source=SOURCE, stream=stream, vendor_endpoint=path,
            request_params={"side": side, "data_type": dtype, "interval": INTERVAL,
                            "from": str(end), "from_semantics":
                            "END of a window of 30 trading days (measured 2026-09-23)",
                            "checkpoint_before": None if mark is None else str(mark),
                            "start": str(start)},
            operator=self.operator, logical_date=mark,
        )
        ctx = await runner.open(commit=self.commit, token=self.token)
        res = WindowResult(side, dtype, end, "RUNNING", run_id=ctx.run_id)
        checks = ctx.checks
        try:
            try:
                r = await self.rest.get(path)
            except (RateLimited, VendorAuthError) as e:
                await runner.fail(str(e), status=RunStatus.ABORTED)
                res.status, res.error = "ABORTED", f"{type(e).__name__}: {e}"
                return res
            except VendorError as e:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, stream,
                           error=str(e)[:300])
                raise IngestCheckFailed(str(e)) from None

            stored = self.store.put(r.data, source=SOURCE, fetched_at=r.fetched_at, ext="json")
            if self.commit:
                await runner.record_payload(stored, http_status=r.status, vendor_endpoint=r.url)
            res.outcome = {"payload_sha256": stored.sha256, "http_status": r.status}
            if r.status != 200:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, stream,
                           http_status=r.status, codes=r.error_codes,
                           payload_sha256=stored.sha256)
                raise IngestCheckFailed(f"HTTP {r.status} {r.error_codes}")
            try:
                pi = P.parse_institutional(r.data, http_status=r.status, side=side,
                                           interval=INTERVAL, data_types=(dtype,),
                                           fetched_at=r.fetched_at)
            except P.InstitutionalDecodeError as e:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, stream,
                           error=str(e)[:300], payload_sha256=stored.sha256)
                raise IngestCheckFailed(str(e)) from None
            for i in pi.issues:
                checks.add(i.severity, i.kind, i.subject, **i.detail,
                           payload_sha256=stored.sha256)
            checks.raise_if_failed()

            fetch_day = r.fetched_at.astimezone(IST).date()
            ps = pi.series[dtype]
            dates = ps.dates
            res.outcome |= {"returned": len(dates),
                            "first": str(dates[0]) if dates else None,
                            "last": str(dates[-1]) if dates else None}
            if not dates:
                if end < P.DATA_START:
                    res.outcome["coverage"] = "BEFORE_AVAILABILITY"
                else:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.COVERAGE_DROP, stream,
                               reason="empty window after the vendor's first day",
                               end=str(end), payload_sha256=stored.sha256)
            else:
                # Continuity: this window must reach back to what is covered.
                need = mark if mark is not None else max(start, P.DATA_START)
                if dates[0] > need:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.GAP, stream,
                               reason="window does not overlap the covered range",
                               first_returned=str(dates[0]), needed_on_or_before=str(need))
                known, n_cal = await self._trading_days(dates[0], dates[-1])
                missing = sorted(known - set(dates))
                if missing:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.GAP, stream,
                               reason="calendar trading days absent from the window",
                               missing=[str(d) for d in missing[:20]])
                res.outcome["calendar_days_checked"] = n_cal
                res.outcome["calendar_days_unchecked"] = (dates[-1] - dates[0]).days + 1 - n_cal
            checks.raise_if_failed()

            keep = [o for o in ps.rows if o.observation_date < fetch_day]
            res.outcome["same_day_excluded"] = len(ps.rows) - len(keep)
            rows = [self._row(o, ctx.run_id, stored.sha256, r.fetched_at) for o in keep]
            check_provenance_complete(checks, rows=rows, stream=stream)
            checks.raise_if_failed()
            res.inserted, res.already_present = await self._write(rows, checks,
                                                                  write=self.commit)
            checks.raise_if_failed()

            kept_dates = sorted({o.observation_date for o in keep})
            through = kept_dates[-1] if kept_dates else mark
            if through is not None and mark is not None and through < mark:
                through = mark
            ctx.logical_date = through
            res.complete_through = None if through is None else str(through)
            res.outcome["complete_through"] = res.complete_through
            await runner.finalize(rows_written=res.inserted, outcome=res.outcome)
            res.status = "COMPLETE"
            return res
        except IngestCheckFailed as e:
            await runner.fail(str(e), outcome=res.outcome)
            res.status, res.error, res.inserted = "FAILED", str(e)[:500], 0
            return res
        except BaseException as e:
            await runner.fail(f"{type(e).__name__}: {e}", outcome=res.outcome)
            raise

    @staticmethod
    def _row(o: P.Observation, run_id, sha: str, fetched_at) -> dict[str, Any]:
        return {"series_code": o.series_code, "observation_date": o.observation_date,
                "observation_ts": None, "value": o.value, "unit": o.unit,
                "vendor_payload": o.vendor_payload, "source": SOURCE, "run_id": run_id,
                "payload_sha256": sha, "fetched_at": fetched_at,
                "knowable_at": o.knowable.at, "knowable_at_verified": o.knowable.verified,
                "knowable_at_basis": o.knowable.basis[:200]}

    async def _write(self, rows: list[dict], checks, *, write: bool) -> tuple[int, int]:
        """The observation identity is (series_code, observation_date, source):
        knowable_at is in the table's unique key, so ON CONFLICT cannot see a
        re-fetch. Existing observations are looked up and compared instead.
        In a dry run the comparison still runs, so a revision is reported."""
        if not rows:
            return 0, 0
        codes = sorted({r["series_code"] for r in rows})
        lo = min(r["observation_date"] for r in rows)
        hi = max(r["observation_date"] for r in rows)
        existing: dict[tuple[str, _dt.date], MacroObservation] = {}
        for e in (await self.s.execute(
                select(MacroObservation).where(
                    MacroObservation.series_code.in_(codes),
                    MacroObservation.observation_date.between(lo, hi),
                    MacroObservation.source == SOURCE)
                .order_by(MacroObservation.knowable_at))).scalars():
            existing[(e.series_code, e.observation_date)] = e      # latest wins
        new, present = [], 0
        for r in rows:
            e = existing.get((r["series_code"], r["observation_date"]))
            if e is None:
                new.append(r)
            elif e.value == r["value"] and e.unit == r["unit"]:
                present += 1
            else:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, r["series_code"],
                           reason="a different value is already stored (D3: revisions are "
                                  "not stored; conflict fails)",
                           observation_date=str(r["observation_date"]),
                           stored=str(e.value), new=str(r["value"]),
                           stored_payload_sha256=e.payload_sha256)
        if write and new and not checks.failed:
            await self.s.execute(insert(MacroObservation), new)
        return (len(new) if write else 0), present
