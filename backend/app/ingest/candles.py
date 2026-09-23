"""M4.3 — candle ingest: Upstox -> raw archive -> parse -> complete-only -> ohlcv_bar.

    for each (instrument, timeframe) STREAM, windows oldest first:
        IngestRunner.open            one run per window, BEFORE the request
        UpstoxRestClient.get         rate limited; 429 stops everything
        PayloadStore.put             every response archived, errors included,
                                     BEFORE parsing
        parse_candles                pure; rows + one CoverageRecord
        COMPLETE rows -> ohlcv_bar   identical = no-op, different = FAIL
        finalize(outcome=coverage)   coverage kept on the run (request_params.outcome)

WHAT THIS DECIDES AND WHAT IT DOES NOT. It ingests whatever jobs it is given.
Which timeframes (D2: vendor-fetched vs derived 5m/15m/1h) and how far back
(D1) are the caller's choice, not encoded here.

RESUME / CHECKPOINT. The watermark stream is ohlcv.<tf>.<key>, and
last_logical_date means "every bar up to and including this date is
persisted". Rules:
  * windows run oldest first; a window that fails STOPS its stream, so the
    watermark can never jump over a gap;
  * a window with FORMING/SETTLING bars advances the watermark only to the day
    before the first such bar, so a later run fetches it again;
  * it never advances past the day BEFORE the fetch (IST): on the fetch day
    itself not all bars exist yet (a daily bar is not published same-day);
  * pending windows are those ending after the watermark;
  * an intraday job (today's bars) never moves the watermark: its rows are
    persisted, and the historical run of that day later dedupes them;
  * RateLimited or VendorAuthError stops the whole batch; every stream keeps
    its checkpoint, and every job not reached is reported NOT_ATTEMPTED.

INTRADAY-GRID CHECK. Session opens come from trading_session. Dates without a
calendar row are NOT assumed to open at 09:15; their bars are counted as
grid-unchecked in the outcome.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import candles as C
from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.clock import IST
from app.core.errors import IngestCheckFailed, RateLimited, VendorAuthError, VendorError
from app.db.models import IngestWatermark, Instrument, OhlcvBar, TradingSession
from app.ingest.checks import check_provenance_complete
from app.ingest.runner import IngestRunner
from app.parsers.upstox_candles import (
    CandleDecodeError,
    CandleRow,
    Endpoint,
    ParsedCandles,
    parse_candles,
)
from app.storage.payload_store import PayloadStore
from app.vendor.upstox.rest import (
    UpstoxRestClient,
    historical_candle_path,
    intraday_candle_path,
)

SOURCE = Source.UPSTOX_REST_V3.value
_INFINITY = literal_column("'infinity'::date")
_CHUNK = 1000          # 20 bind parameters per row; stays far under asyncpg's 32,767


@dataclass(frozen=True, slots=True)
class CandleJob:
    instrument_key: str
    timeframe: str
    window: C.Window | None        # None = the intraday endpoint (today's bars)

    @property
    def endpoint(self) -> Endpoint:
        return Endpoint.INTRADAY if self.window is None else Endpoint.HISTORICAL

    @property
    def stream(self) -> str:
        return C.watermark_stream(self.timeframe, self.instrument_key)

    def path(self) -> str:
        if self.window is None:
            return intraday_candle_path(self.instrument_key, self.timeframe)
        return historical_candle_path(self.instrument_key, self.timeframe, self.window)


def plan_jobs(keys: Iterable[str], timeframes: Iterable[str], start: _dt.date,
              end: _dt.date) -> tuple[list[CandleJob], list[C.CoverageRecord]]:
    """Historical jobs for every (key, timeframe), oldest window first, plus a
    BEFORE_AVAILABILITY coverage record for any part older than the vendor serves."""
    jobs: list[CandleJob] = []
    unavailable: list[C.CoverageRecord] = []
    for key in sorted(set(keys)):
        for tf in timeframes:
            wp = C.plan_windows(tf, start, end)
            jobs += [CandleJob(key, tf, w) for w in wp.windows]
            if wp.unavailable:
                unavailable.append(C.CoverageRecord(key, tf, wp.unavailable,
                                                    C.WindowOutcome.BEFORE_AVAILABILITY))
    return jobs, unavailable


@dataclass(slots=True)
class JobResult:
    job: CandleJob
    status: str                      # COMPLETE / FAILED / ABORTED / NOT_ATTEMPTED / SKIPPED
    run_id: uuid.UUID | None = None
    coverage: dict[str, Any] | None = None
    inserted: int = 0
    already_present: int = 0
    complete_through: str | None = None
    error: str | None = None


@dataclass(slots=True)
class CandleIngestReport:
    committed: bool
    jobs: int = 0
    results: list[JobResult] = field(default_factory=list)
    stopped: str | None = None       # why the batch stopped early, if it did

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def inserted(self) -> int:
        return sum(r.inserted for r in self.results)

    def summary(self) -> dict[str, Any]:
        return {"committed": self.committed, "jobs": self.jobs, "inserted": self.inserted,
                "stopped": self.stopped,
                **{s.lower(): self.count(s) for s in
                   ("COMPLETE", "FAILED", "ABORTED", "NOT_ATTEMPTED", "SKIPPED")}}


def _coverage_dict(cv: C.CoverageRecord) -> dict[str, Any]:
    return {"outcome": cv.outcome.value, "window": [str(cv.window.from_date),
                                                    str(cv.window.to_date)],
            "returned": cv.returned, "complete": cv.complete, "forming": cv.forming,
            "settling": cv.settling, "invalid": cv.invalid,
            "payload_sha256": cv.payload_sha256, "vendor_error_code": cv.vendor_error_code}


def _complete_through(pc: ParsedCandles, window: C.Window,
                      fetched_at: _dt.datetime) -> _dt.date:
    """Last date up to which every bar of this window is persisted.

    Capped at the day BEFORE the fetch (IST). On the fetch day itself it is
    never certain that all of the session's bars exist: the daily bar is not
    published the same day (B1), and intraday bars are still arriving. Without
    the cap, a window ending today would checkpoint a day whose bars never came.
    """
    cap = fetched_at.astimezone(IST).date() - _dt.timedelta(days=1)
    through = min(window.to_date, cap)
    pending = [r.session_date for r in pc.rows if r.state is not C.BarState.COMPLETE]
    if pending:
        through = min(through, min(pending) - _dt.timedelta(days=1))
    return through


class CandleIngestor:
    def __init__(self, session: AsyncSession, rest: UpstoxRestClient, store: PayloadStore, *,
                 commit: bool, token: str | None, operator: str = "cli"):
        self.s, self.rest, self.store = session, rest, store
        self.commit, self.token, self.operator = commit, token, operator
        self._ids: dict[str, int] = {}

    async def _instrument_ids(self, keys: set[str]) -> dict[str, int]:
        missing = keys - set(self._ids)
        if missing:
            for key, iid in (await self.s.execute(
                    select(Instrument.instrument_key, Instrument.instrument_id).where(
                        Instrument.instrument_key.in_(missing),
                        Instrument.valid_to == _INFINITY))).all():
                self._ids[key] = iid
        return self._ids

    async def watermark(self, stream: str) -> _dt.date | None:
        wm = await self.s.get(IngestWatermark, (SOURCE, stream))
        return wm.last_logical_date if wm else None

    async def _session_opens(self, window: C.Window) -> dict[_dt.date, _dt.time]:
        return {r.session_date: r.open_ist for r in (await self.s.execute(
            select(TradingSession.session_date, TradingSession.open_ist).where(
                TradingSession.session_date.between(window.from_date, window.to_date),
                TradingSession.is_trading_day.is_(True)))).all()}

    async def run(self, jobs: Iterable[CandleJob], *, resume: bool = True) -> CandleIngestReport:
        jobs = list(jobs)
        rep = CandleIngestReport(committed=self.commit, jobs=len(jobs))
        await self._instrument_ids({j.instrument_key for j in jobs})
        by_stream: dict[str, list[CandleJob]] = {}
        for j in jobs:
            by_stream.setdefault(j.stream, []).append(j)

        stop_all: str | None = None
        for stream in sorted(by_stream):
            sjobs = sorted(by_stream[stream],
                           key=lambda j: (j.window.from_date if j.window else _dt.date.max))
            mark = await self.watermark(stream) if resume else None
            broken = False
            for j in sjobs:
                if stop_all or broken:
                    rep.results.append(JobResult(j, "NOT_ATTEMPTED",
                                                 error=stop_all or "earlier window failed"))
                    continue
                if mark and j.window and j.window.to_date <= mark:
                    rep.results.append(JobResult(j, "SKIPPED", complete_through=str(mark)))
                    continue
                res = await self._one(j, mark)
                rep.results.append(res)
                if res.status == "ABORTED":
                    stop_all = res.error
                elif res.status != "COMPLETE":
                    broken = True
                elif res.complete_through and (mark is None or
                                               _dt.date.fromisoformat(res.complete_through) > mark):
                    mark = _dt.date.fromisoformat(res.complete_through)
        rep.stopped = stop_all
        return rep

    async def _one(self, job: CandleJob, mark: _dt.date | None) -> JobResult:
        runner = IngestRunner(
            self.s, source=SOURCE, stream=job.stream, vendor_endpoint=job.path(),
            request_params={"instrument_key": job.instrument_key, "timeframe": job.timeframe,
                            "endpoint": job.endpoint.value,
                            "window": None if job.window is None else
                            [str(job.window.from_date), str(job.window.to_date)],
                            "completion_margin_s": C.COMPLETION_MARGIN.total_seconds(),
                            "completion_basis": C.COMPLETION_MARGIN_BASIS},
            operator=self.operator,
            logical_date=job.window.to_date if job.window else None,
        )
        ctx = await runner.open(commit=self.commit, token=self.token)
        res = JobResult(job, "RUNNING", run_id=ctx.run_id)
        checks = ctx.checks
        try:
            iid = self._ids.get(job.instrument_key)
            if iid is None:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.COVERAGE_DROP, job.instrument_key,
                           reason="no current instrument row (M3.0) for this key")
                raise IngestCheckFailed(f"{job.instrument_key}: not in instrument")

            try:
                r = await self.rest.get(job.path())
            except (RateLimited, VendorAuthError) as e:
                await runner.fail(str(e), status=RunStatus.ABORTED)
                res.status, res.error = "ABORTED", f"{type(e).__name__}: {e}"
                return res
            except VendorError as e:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, job.instrument_key,
                           error=str(e)[:300])
                raise IngestCheckFailed(str(e)) from None

            # Raw first: the response is on disk before anything reads it.
            stored = self.store.put(r.data, source=SOURCE, fetched_at=r.fetched_at, ext="json")
            if self.commit:
                await runner.record_payload(stored, http_status=r.status,
                                            vendor_endpoint=r.url)

            today = r.fetched_at.astimezone(IST).date()
            opens = await self._session_opens(job.window or C.Window(today, today))
            try:
                pc = parse_candles(r.data, http_status=r.status, endpoint=job.endpoint,
                                   instrument_key=job.instrument_key, timeframe=job.timeframe,
                                   fetched_at=r.fetched_at, window=job.window,
                                   payload_sha256=stored.sha256, session_opens=opens)
            except CandleDecodeError as e:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, job.instrument_key,
                           error=str(e)[:300], payload_sha256=stored.sha256)
                raise IngestCheckFailed(str(e)) from None
            for i in pc.issues:
                checks.add(i.severity, i.kind, i.subject, **i.detail)
            cov = pc.coverage
            res.coverage = {**_coverage_dict(cov), "grid_unchecked": pc.grid_unchecked}
            if cov.outcome is C.WindowOutcome.VENDOR_ERROR:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, job.instrument_key,
                           http_status=r.status, codes=cov.vendor_error_code,
                           payload_sha256=stored.sha256)

            rows = [self._row(row, iid, ctx.run_id, stored.sha256, r.fetched_at)
                    for row in pc.complete]
            check_provenance_complete(checks, rows=rows, stream=job.stream)
            checks.raise_if_failed()

            if self.commit and rows:
                res.inserted, res.already_present = await self._write(rows, checks)
                checks.raise_if_failed()

            if job.window is None:
                # An intraday job never moves the checkpoint: it shares the
                # stream with the historical backfill, and advancing to today
                # would let a later backfill skip every older window. Its rows
                # are persisted; the historical run of that day dedupes them.
                through = mark
            else:
                through = _complete_through(pc, job.window, r.fetched_at)
                if mark and through < mark:
                    through = mark                # never move a checkpoint backwards
            ctx.logical_date = through
            res.complete_through = None if through is None else str(through)
            await runner.finalize(rows_written=res.inserted, outcome=res.coverage)
            res.status = "COMPLETE"
            return res
        except IngestCheckFailed as e:
            await runner.fail(str(e), outcome=res.coverage)
            res.status, res.error, res.inserted = "FAILED", str(e)[:500], 0
            return res
        except BaseException as e:
            await runner.fail(f"{type(e).__name__}: {e}", outcome=res.coverage)
            raise

    @staticmethod
    def _row(row: CandleRow, iid: int, run_id, sha: str, fetched_at) -> dict[str, Any]:
        return {"instrument_id": iid, "timeframe": row.timeframe,
                "session_date": row.session_date, "bar_start_utc": row.bar_start_utc,
                "source": SOURCE, "instrument_key": row.instrument_key,
                "open": row.open, "high": row.high, "low": row.low, "close": row.close,
                "volume": row.volume, "open_interest": row.open_interest,
                "vendor_ts_raw": row.vendor_ts_raw, "run_id": run_id, "payload_sha256": sha,
                "fetched_at": fetched_at, "knowable_at": row.knowable.at,
                "knowable_at_verified": row.knowable.verified,
                "knowable_at_basis": row.knowable.basis[:200]}

    async def _write(self, rows: list[dict], checks) -> tuple[int, int]:
        pk = ("instrument_id", "timeframe", "session_date", "bar_start_utc", "source")
        inserted = present = 0
        for i in range(0, len(rows), _CHUNK):
            chunk = rows[i : i + _CHUNK]
            res = await self.s.execute(
                pg_insert(OhlcvBar).values(chunk).on_conflict_do_nothing()
                .returning(OhlcvBar.instrument_id, OhlcvBar.timeframe, OhlcvBar.session_date,
                           OhlcvBar.bar_start_utc, OhlcvBar.source))
            new = {tuple(x) for x in res.all()}
            inserted += len(new)
            clash = [r for r in chunk if tuple(r[k] for k in pk) not in new]
            if not clash:
                continue
            existing = {
                tuple(getattr(e, k) for k in pk): e for e in (await self.s.execute(
                    select(OhlcvBar).where(tuple_(*(getattr(OhlcvBar, k) for k in pk)).in_(
                        [tuple(r[k] for k in pk) for r in clash])))).scalars()}
            for r in clash:
                e = existing[tuple(r[k] for k in pk)]
                if C.same_observation({f: getattr(e, f) for f in C.BAR_VALUE_FIELDS}, r):
                    present += 1
                else:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, r["instrument_key"],
                               reason="a different bar is already stored (D3: revisions are "
                                      "not stored; conflict fails)",
                               timeframe=r["timeframe"],
                               bar_start_utc=r["bar_start_utc"].isoformat(),
                               stored={f: str(getattr(e, f)) for f in C.BAR_VALUE_FIELDS},
                               new={f: str(r[f]) for f in C.BAR_VALUE_FIELDS},
                               stored_payload_sha256=e.payload_sha256)
        return inserted, present
