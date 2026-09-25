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

RESUME / CHECKPOINT. The watermark stream is ohlcv.<tf>.<key>. A checkpoint
is a CONTIGUOUS range [covered_from, last_logical_date]: every bar in it is
persisted. last_logical_date lives on ingest_watermark; covered_from lives in
the outcome of the run that set it (request_params.outcome.checkpoint), so no
migration is needed. Rules:
  * a batch trusts the checkpoint only if covered_from <= the batch's first
    window start. Otherwise (an earlier start than any before, or a legacy
    checkpoint without covered_from) no window is skipped, and the batch
    rebuilds the range from its own first window. Stored bars dedupe as no-ops;
  * a window advances the checkpoint only if it is contiguous with it
    (from_date <= last_logical_date + 1 day). A window beyond a hole persists
    its bars but never moves the checkpoint, so the hole is never skipped;
  * windows run oldest first; a window that fails STOPS its stream, so the
    watermark can never jump over a gap;
  * a window with FORMING/SETTLING bars advances the watermark only to the day
    before the first such bar, so a later run fetches it again (and the
    windows after it are then not contiguous, so they do not move it);
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
from decimal import Decimal
from typing import Any

from sqlalchemy import literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import candles as C
from app.contracts import timing
from app.contracts import revision as REV
from app.contracts.ca_factor import factor_for
from app.contracts.identity import GLOBAL_SEGMENTS
from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.clock import IST
from app.core.errors import IngestCheckFailed, RateLimited, VendorAuthError, VendorError
from app.db.models import (
    CorporateAction,
    IngestRun,
    IngestWatermark,
    Instrument,
    OhlcvBar,
    OhlcvObservation,
    OhlcvPayloadBasis,
    TradingSession,
)
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


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """[covered_from, through]: every bar in it is persisted. Both None = nothing
    known. through set but covered_from None = a legacy checkpoint (start unknown)."""
    covered_from: _dt.date | None = None
    through: _dt.date | None = None

    def covers_start(self, start: _dt.date) -> bool:
        return (self.through is not None and self.covered_from is not None
                and self.covered_from <= start)

    def advance(self, window: C.Window, through: _dt.date) -> tuple[Checkpoint, str]:
        """The checkpoint after a COMPLETE window whose bars are persisted up to
        `through` (which may be before window.from_date: nothing settled yet)."""
        if through < window.from_date:
            return self, "nothing complete in the window"
        if self.through is None:
            return Checkpoint(window.from_date, through), "started"
        if window.from_date > self.through + _dt.timedelta(days=1):
            return self, f"not contiguous with the checkpoint ({self.through})"
        return Checkpoint(min(self.covered_from or window.from_date, window.from_date),
                          max(self.through, through)), "advanced"

    def as_dict(self) -> dict[str, str | None]:
        return {"covered_from": None if self.covered_from is None else str(self.covered_from),
                "through": None if self.through is None else str(self.through)}


@dataclass(slots=True)
class JobResult:
    job: CandleJob
    status: str                      # COMPLETE / FAILED / ABORTED / NOT_ATTEMPTED / SKIPPED
    run_id: uuid.UUID | None = None
    coverage: dict[str, Any] | None = None
    inserted: int = 0
    already_present: int = 0
    observations: dict[str, int] = field(default_factory=dict)   # class -> count
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
            "settling": cv.settling, "invalid": cv.invalid, "quarantined": cv.quarantined,
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

    async def checkpoint(self, stream: str) -> Checkpoint:
        wm = await self.s.get(IngestWatermark, (SOURCE, stream))
        if wm is None or wm.last_logical_date is None:
            return Checkpoint()
        run = await self.s.get(IngestRun, wm.last_run_id) if wm.last_run_id else None
        cf = ((run.request_params or {}).get("outcome") or {}).get("checkpoint", {}) \
            .get("covered_from") if run else None
        return Checkpoint(_dt.date.fromisoformat(cf) if cf else None, wm.last_logical_date)

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
            first = next((j.window.from_date for j in sjobs if j.window), None)
            cp = await self.checkpoint(stream) if resume else Checkpoint()
            if first is not None and not cp.covers_start(first):
                cp = Checkpoint()             # untrusted: rebuild from this batch's start
            mark = cp.through
            broken = False
            for j in sjobs:
                if stop_all or broken:
                    rep.results.append(JobResult(j, "NOT_ATTEMPTED",
                                                 error=stop_all or "earlier window failed"))
                    continue
                if mark and j.window and j.window.to_date <= mark:
                    rep.results.append(JobResult(j, "SKIPPED", complete_through=str(mark)))
                    continue
                res, cp = await self._one(j, cp)
                rep.results.append(res)
                if res.status == "ABORTED":
                    stop_all = res.error
                elif res.status != "COMPLETE":
                    broken = True
        rep.stopped = stop_all
        return rep

    async def _one(self, job: CandleJob, cp: Checkpoint) -> tuple[JobResult, Checkpoint]:
        runner = IngestRunner(
            self.s, source=SOURCE, stream=job.stream, vendor_endpoint=job.path(),
            request_params={"instrument_key": job.instrument_key, "timeframe": job.timeframe,
                            "endpoint": job.endpoint.value,
                            "window": None if job.window is None else
                            [str(job.window.from_date), str(job.window.to_date)],
                            "completion_margin_s": None if job.timeframe == C.DAILY else
                            timing.margin(job.timeframe).total_seconds(),
                            "completion_basis": timing.BASIS},
            operator=self.operator,
            logical_date=cp.through,
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
                return res, cp
            except VendorError as e:
                checks.add(AnomalySeverity.FAIL, AnomalyKind.VENDOR_ERROR, job.instrument_key,
                           error=str(e)[:300])
                raise IngestCheckFailed(str(e)) from None

            # Raw first: the response is on disk before anything reads it.
            stored = self.store.put(r.data, source=SOURCE, fetched_at=r.fetched_at, ext="json")
            if self.commit:
                await runner.record_payload(stored, http_status=r.status,
                                            vendor_endpoint=r.url)
                await self._record_basis(stored, job, r.fetched_at)

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
                checks.add(i.severity, i.kind, i.subject,
                           **{"payload_sha256": stored.sha256, **i.detail})
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
                res.inserted, res.already_present, res.observations = await self._write(
                    rows, checks, fetched_at=r.fetched_at)
                checks.raise_if_failed()
                if res.observations:
                    res.coverage["observations"] = res.observations

            if job.window is None:
                # An intraday job never moves the checkpoint: it shares the
                # stream with the historical backfill, and advancing to today
                # would let a later backfill skip every older window. Its rows
                # are persisted; the historical run of that day dedupes them.
                new, why = cp, "intraday job: checkpoint unchanged"
            else:
                new, why = cp.advance(job.window,
                                      _complete_through(pc, job.window, r.fetched_at))
            ctx.logical_date = new.through
            res.complete_through = None if new.through is None else str(new.through)
            res.coverage["checkpoint"] = {**new.as_dict(), "change": why}
            await runner.finalize(rows_written=res.inserted, outcome=res.coverage)
            res.status = "COMPLETE"
            return res, new
        except IngestCheckFailed as e:
            await runner.fail(str(e), outcome=res.coverage)
            res.status, res.error, res.inserted = "FAILED", str(e)[:500], 0
            return res, cp
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

    async def _record_basis(self, stored, job: CandleJob, fetched_at) -> None:
        """The price basis of this payload (hardening phase 6)."""
        is_global = job.instrument_key.split("|", 1)[0] in GLOBAL_SEGMENTS
        raw = is_global or job.endpoint.value == "intraday"
        rule = ("global: no corporate actions" if is_global else
                "intraday endpoint: same-day bars as traded" if raw else
                "historical endpoint: vendor-adjusted as of the fetch")
        await self.s.execute(pg_insert(OhlcvPayloadBasis).values(
            payload_sha256=stored.sha256, endpoint=job.endpoint.value,
            price_basis="RAW_OBSERVED" if raw else "VENDOR_ADJUSTED",
            basis_as_of=fetched_at.astimezone(IST).date(), basis_confidence="HIGH",
            method_version="basis-v1", evidence={"rule": rule}).on_conflict_do_nothing())

    async def _events(self, key: str) -> list[REV.Event]:
        """Recorded split/bonus events of an instrument with a proven factor."""
        out = []
        for ca in (await self.s.execute(select(CorporateAction).where(
                CorporateAction.instrument_key == key,
                CorporateAction.action_type.in_(("SPLIT", "BONUS"))))).scalars():
            f = factor_for(ca.action_type, ratio=(ca.vendor_payload or {}).get("ratio"),
                           fv_before=ca.face_value_before, fv_after=ca.face_value_after)
            if f.status == "EXACT" and ca.ex_date is not None:
                out.append(REV.Event(ca.id, ca.ex_date, f.factor_price))
        return out

    async def _tick(self, iid: int) -> Decimal | None:
        ts = (await self.s.execute(select(Instrument.tick_size).where(
            Instrument.instrument_id == iid))).scalar()
        return None if ts is None else Decimal(str(ts)) / 100      # master: paise

    async def _observe(self, r: dict, klass: str, reason: str, explained: dict, fetched):
        await self.s.execute(pg_insert(OhlcvObservation).values(
            instrument_id=r["instrument_id"], timeframe=r["timeframe"],
            session_date=r["session_date"], bar_start_utc=r["bar_start_utc"],
            source=r["source"], instrument_key=r["instrument_key"],
            **{f: r[f] for f in C.BAR_VALUE_FIELDS}, run_id=r["run_id"],
            payload_sha256=r["payload_sha256"], fetched_at=fetched, classification=klass,
            reason=reason, explained_by=explained, method_version=REV.METHOD_VERSION))

    async def _write(self, rows: list[dict], checks, *, fetched_at=None
                     ) -> tuple[int, int, dict[str, int]]:
        """First observation wins (D3): a new key is inserted; an identical one
        is a no-op; a DIFFERENT value is classified (contracts.revision) and,
        when explained, recorded in ohlcv_observation - the stored bar is never
        touched. UNEXPLAINED still fails the run."""
        pk = ("instrument_id", "timeframe", "session_date", "bar_start_utc", "source")
        inserted = present = 0
        observed: dict[str, int] = {}
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
            events: dict[str, list[REV.Event]] = {}
            ticks: dict[int, Decimal | None] = {}
            for r in clash:
                e = existing[tuple(r[k] for k in pk)]
                key = r["instrument_key"]
                if C.same_observation({f: getattr(e, f) for f in C.BAR_VALUE_FIELDS}, r):
                    present += 1
                    if key.split("|", 1)[0] in GLOBAL_SEGMENTS:
                        # positive evidence of finality for a provisional global
                        # label (phase 5): the vendor returned it unchanged again
                        await self._observe(r, "REOBSERVED", "unchanged re-observation",
                                            {}, r["fetched_at"] or fetched_at)
                        observed["REOBSERVED"] = observed.get("REOBSERVED", 0) + 1
                    continue
                if key not in events:
                    events[key] = await self._events(key)
                if r["instrument_id"] not in ticks:
                    ticks[r["instrument_id"]] = await self._tick(r["instrument_id"])
                fetched = r["fetched_at"] or fetched_at
                width = C.BAR_WIDTH.get(r["timeframe"]) if r["timeframe"] != "1d" else None
                last_bar = width is not None and (
                    (r["bar_start_utc"] + width).astimezone(IST).time() >= _dt.time(15, 29))
                v = REV.classify({f: getattr(e, f) for f in C.BAR_VALUE_FIELDS}, r,
                                 bar_date=r["session_date"],
                                 fetch_date=fetched.astimezone(IST).date(),
                                 tick=ticks[r["instrument_id"]], events=events[key],
                                 is_global=key.split("|", 1)[0] in GLOBAL_SEGMENTS,
                                 last_bar_of_session=last_bar)
                if v.fails:
                    checks.add(AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, key,
                               reason="a different bar is already stored and no rule explains "
                                      "it (D3: UNEXPLAINED revisions fail)",
                               timeframe=r["timeframe"],
                               bar_start_utc=r["bar_start_utc"].isoformat(),
                               stored={f: str(getattr(e, f)) for f in C.BAR_VALUE_FIELDS},
                               new={f: str(r[f]) for f in C.BAR_VALUE_FIELDS},
                               stored_payload_sha256=e.payload_sha256,
                               classification=v.classification, why=v.reason)
                    continue
                await self._observe(r, v.classification, v.reason, v.explained_by, fetched)
                observed[v.classification] = observed.get(v.classification, 0) + 1
        return inserted, present, observed
