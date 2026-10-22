"""Pre-open archive -> database, through the standard run lifecycle.

This is the ONLY path by which pre-open rows reach the database. A live
capture archives frames and then replays its own archive through here, so
"live" and "replay" cannot disagree: they are the same code reading the same
bytes.

    archive (frames on disk)
        -> FrameArchiveReader       sha256 per record, truncation detected
        -> parse_frame()            pure; rows + issues
        -> IngestRunner             one transaction; anomalies; fail loud

Idempotent: replaying an archive twice writes its rows once. A key collision
whose CONTENT differs is not a duplicate — it is two observations the schema
cannot both hold — and it fails the run rather than keeping whichever came
first.
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.provenance import AnomalyKind, AnomalySeverity, RunStatus, Source
from app.core.errors import IngestCheckFailed
from app.db.models import PreopenBook, PreopenSessionStatus, PreopenTick, TradingSession
from app.ingest.runner import IngestRunner
from app.parsers.upstox_feed_v3 import FrameDecodeError, ParsedFrame, TickRow, parse_frame
from app.storage.frame_archive import ArchiveCorrupt, FrameArchiveReader, RecordKind
from app.storage.payload_store import StoredPayload
from app.vendor.upstox.proto import PROTO_SHA256

STREAM = "preopen"
CONTENT_TYPE = "application/x-protobuf"
# asyncpg caps a statement at 32,767 bind parameters; a tick row has ~30.
_CHUNK = 500

# Columns that make two observations of the same key the SAME observation.
_TICK_VALUE_COLS = (
    "request_mode", "iep", "ieq", "iiq_total", "iiq_m", "rp", "tbq", "tsq", "cas_eligible",
    "atp", "vtt", "oi", "iv", "ltp", "ltt", "ltq", "cp", "ltpc_iep",
)


@dataclass(frozen=True, slots=True)
class TailPass:
    """One pass of a tailing replay: records seq >= seq_from, read at pass_started_at."""
    seq_from: int
    pass_started_at: _dt.datetime
    final: bool = False


@dataclass(slots=True)
class ReplayReport:
    run_id: uuid.UUID | None = None
    status: str = ""
    committed: bool = False
    archive: str = ""
    records: int = 0
    frames: int = 0
    text_frames: int = 0
    events: int = 0
    undecodable: int = 0
    truncated: bool = False
    ticks_parsed: int = 0
    ticks_inserted: int = 0
    ticks_already_present: int = 0
    book_rungs_inserted: int = 0
    statuses_parsed: int = 0
    statuses_inserted: int = 0
    payloads_recorded: int = 0
    request_modes: dict[str, int] = field(default_factory=dict)
    feed_types: dict[str, int] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    next_seq: int = 0

    @property
    def rows_written(self) -> int:
        return self.ticks_inserted + self.book_rungs_inserted + self.statuses_inserted


def _chunks(seq: list, n: int = _CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class _Writer:
    """Stages rows on the runner's session. Commits nothing itself."""

    def __init__(self, runner: IngestRunner, report: ReplayReport, archive: pathlib.Path):
        self.runner, self.report, self.archive = runner, report, archive
        self.s: AsyncSession = runner.session
        assert runner.ctx
        self.run_id = runner.ctx.run_id

    async def payload(self, seq: int, data_len: int, sha: str, recv_at: _dt.datetime) -> None:
        stored = StoredPayload(sha, self.archive, data_len, CONTENT_TYPE, recv_at, None, False)
        if await self.runner.record_payload(stored, storage_uri=f"{self.archive}#seq={seq}"):
            self.report.payloads_recorded += 1

    async def ticks(self, rows: list[TickRow]) -> None:
        for chunk in _chunks(rows):
            values = [{**r.columns(), "run_id": self.run_id} for r in chunk]
            res = await self.s.execute(
                pg_insert(PreopenTick).values(values)
                .on_conflict_do_nothing(constraint="uq_preopen_tick_observation")
                .returning(PreopenTick.tick_id, PreopenTick.instrument_key, PreopenTick.vendor_ts)
            )
            inserted = {(k, ts): tid for tid, k, ts in res.all()}
            self.report.ticks_inserted += len(inserted)

            book = [
                {"tick_id": inserted[(r.instrument_key, r.vendor_ts)], "rung_no": b.rung_no,
                 "bid_qty": b.bid_qty, "bid_price": b.bid_price,
                 "ask_qty": b.ask_qty, "ask_price": b.ask_price}
                for r in chunk if (r.instrument_key, r.vendor_ts) in inserted
                for b in r.book
            ]
            for bchunk in _chunks(book, 2000):
                await self.s.execute(pg_insert(PreopenBook).values(bchunk))
            self.report.book_rungs_inserted += len(book)

            clashes = [r for r in chunk if (r.instrument_key, r.vendor_ts) not in inserted]
            if clashes:
                await self._compare_existing(clashes)

    async def _compare_existing(self, rows: list[TickRow]) -> None:
        """A conflict is fine only if the stored observation is the same one."""
        cols = [getattr(PreopenTick, c) for c in _TICK_VALUE_COLS]
        existing = {
            (r.instrument_key, r.vendor_ts): r
            for r in (await self.s.execute(
                select(PreopenTick.tick_id, PreopenTick.instrument_key, PreopenTick.vendor_ts,
                       PreopenTick.payload_sha256, *cols)
                .where(PreopenTick.session_date == rows[0].session_date,
                       PreopenTick.source == Source.UPSTOX_WS_V3.value,
                       tuple_(PreopenTick.instrument_key, PreopenTick.vendor_ts).in_(
                           [(r.instrument_key, r.vendor_ts) for r in rows]))
            )).all()
        }
        ids = [e.tick_id for e in existing.values()]
        books: dict[int, list[tuple]] = {}
        for b in (await self.s.execute(
            select(PreopenBook).where(PreopenBook.tick_id.in_(ids)).order_by(
                PreopenBook.tick_id, PreopenBook.rung_no)
        )).scalars():
            books.setdefault(b.tick_id, []).append(
                (b.rung_no, b.bid_qty, b.bid_price, b.ask_qty, b.ask_price))

        for r in rows:
            e = existing[(r.instrument_key, r.vendor_ts)]
            diff = [c for c in _TICK_VALUE_COLS if getattr(e, c) != getattr(r, c)]
            new_book = [(b.rung_no, b.bid_qty, b.bid_price, b.ask_qty, b.ask_price) for b in r.book]
            if books.get(e.tick_id, []) != new_book:
                diff.append("book")
            if diff:
                self.runner.ctx.checks.add(
                    AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, r.instrument_key,
                    vendor_ts=r.vendor_ts.isoformat(), differing=diff,
                    stored_payload_sha256=e.payload_sha256,
                    new_payload_sha256=r.provenance.payload_sha256, frame_seq=r.frame_seq,
                )
            else:
                self.report.ticks_already_present += 1

    async def statuses(self, frame: ParsedFrame) -> None:
        if not frame.statuses:
            return
        res = await self.s.execute(
            pg_insert(PreopenSessionStatus)
            .values([{**st.columns(), "run_id": self.run_id} for st in frame.statuses])
            .on_conflict_do_nothing()
            .returning(PreopenSessionStatus.status)
        )
        # A status transition re-reported in a later frame is the same fact;
        # the first (earliest-known) observation is the one kept.
        self.report.statuses_inserted += len(res.all())


def _count(d: dict[str, int], k: str, n: int = 1) -> None:
    d[k] = d.get(k, 0) + n


async def replay_archive(
    session: AsyncSession,
    archive: pathlib.Path,
    *,
    commit: bool,
    token: str | None,
    session_date: _dt.date | None = None,
    operator: str = "cli",
    tail: TailPass | None = None,
) -> ReplayReport:
    """Replay one frame archive. Dry-run parses and checks everything and
    writes only the run ledger and its anomalies.

    `tail` replays only the records from `tail.seq_from` to what is readable now, of an
    archive the recorder may still be writing (PREOPEN-TAIL): the same reader, parser and
    writer, one run per pass. The end-of-archive checks (truncation, manifest, stream
    sha256) belong to the `final` pass only, after the recorder closed the file. A pass
    with nothing new opens no run (status EMPTY)."""
    # Replay is a batch job: archive reads are synchronous by design. The live
    # recorder must not call this on its event loop.
    archive = pathlib.Path(archive).resolve()  # noqa: ASYNC240
    reader = FrameArchiveReader(archive)
    report = ReplayReport(archive=str(archive), committed=commit)

    it = iter(reader)
    first = next(it, None)          # reads the header
    if tail is not None:            # the whole readable range first: the pass's extent
        recs = [r for r in _chain([first] if first is not None else [], it)
                if r.seq >= tail.seq_from]
        report.next_seq = recs[-1].seq + 1 if recs else tail.seq_from
        if not recs and not tail.final:
            report.status = "EMPTY"
            return report
        first, it = None, iter(recs)
    hdr_date = reader.header.get("session_date")
    if session_date is None:
        if not hdr_date:
            raise ValueError("archive header has no session_date; pass one explicitly")
        session_date = _dt.date.fromisoformat(hdr_date)
    elif hdr_date and hdr_date != session_date.isoformat():
        raise ValueError(f"archive is for session {hdr_date}, not {session_date}")

    manifest = reader.manifest()
    runner = IngestRunner(
        session, source=Source.UPSTOX_WS_V3.value, stream=STREAM,
        vendor_endpoint=reader.header.get("endpoint", "upstox market-data-feed v3"),
        request_params={
            "replay_of": archive.name,
            "archive_header": reader.header,
            "manifest_stream_sha256": (manifest or {}).get("stream_sha256"),
            **({"tail": {"seq_from": tail.seq_from, "seq_to": report.next_seq,
                         "final": tail.final,
                         "pass_started_at": tail.pass_started_at.isoformat()}}
               if tail is not None else {}),
        },
        operator=operator, logical_date=session_date,
    )
    ctx = await runner.open(commit=commit, token=token)
    report.run_id = ctx.run_id
    checks = ctx.checks
    writer = _Writer(runner, report, archive) if commit else None

    try:
        if reader.header.get("proto_sha256") != PROTO_SHA256:
            checks.add(AnomalySeverity.WARN, AnomalyKind.SCHEMA_DRIFT, "archive_header",
                       reason="archive was captured under a different proto pin",
                       archive_proto_sha256=reader.header.get("proto_sha256"),
                       decoder_proto_sha256=PROTO_SHA256)

        if await session.get(TradingSession, session_date) is None:
            # Never fabricated here: the calendar row is M2's to assert.
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "trading_session",
                       reason="no trading_session row for this session_date",
                       session_date=str(session_date))

        records = [first] if first is not None else []
        for rec in _chain(records, it):
            report.records += 1
            if rec.kind is RecordKind.EVENT:
                report.events += 1
                _event_anomaly(checks, rec)
                continue
            if rec.kind is RecordKind.TEXT:
                report.text_frames += 1
                checks.add(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT, "text_frame",
                           frame_seq=rec.seq, payload_sha256=rec.sha256,
                           preview=rec.payload[:200].decode("utf-8", "replace"))
                continue

            report.frames += 1
            try:
                frame = parse_frame(rec.payload, frame_seq=rec.seq, fetched_at=rec.recv_at,
                                    session_date=session_date)
            except FrameDecodeError as e:
                report.undecodable += 1
                checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "FeedResponse",
                           frame_seq=rec.seq, payload_sha256=rec.sha256, error=str(e)[:300])
                continue

            for i in frame.issues:
                checks.add(i.severity, i.kind, i.subject, **i.detail)
            _count(report.feed_types, frame.feed_type)
            for t in frame.ticks:
                _count(report.request_modes, t.request_mode)
            report.ticks_parsed += len(frame.ticks)
            report.statuses_parsed += len(frame.statuses)

            if writer and not checks.failed:
                await writer.payload(rec.seq, len(rec.payload), rec.sha256, rec.recv_at)
                await writer.ticks(frame.ticks)
                await writer.statuses(frame)

        if tail is not None and not tail.final:
            checks.raise_if_failed()       # the end-of-archive checks wait for the final pass
            report.anomalies = [_anomaly(a) for a in checks.anomalies]
            await runner.finalize(rows_written=report.rows_written)
            report.status = RunStatus.COMPLETE.value
            return report
        report.truncated = reader.truncated
        if reader.truncated:
            checks.add(AnomalySeverity.WARN, AnomalyKind.GAP, "archive",
                       reason="archive ends mid-record (capture did not close cleanly)",
                       records_read=report.records)
        if manifest is None:
            checks.add(AnomalySeverity.WARN, AnomalyKind.GAP, "archive",
                       reason="no manifest: capture did not close cleanly")
        elif not reader.truncated and manifest.get("stream_sha256") != reader.stream_sha256:
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "archive",
                       reason="stream sha256 disagrees with manifest",
                       manifest=manifest.get("stream_sha256"), actual=reader.stream_sha256)

        checks.raise_if_failed()
    except (IngestCheckFailed, ArchiveCorrupt) as e:
        report.error = str(e)
        if isinstance(e, ArchiveCorrupt):
            checks.add(AnomalySeverity.FAIL, AnomalyKind.PARSE_REJECT, "archive", error=str(e))
        report.anomalies = [_anomaly(a) for a in checks.anomalies]
        await runner.fail(str(e))
        report.status = RunStatus.FAILED.value
        report.ticks_inserted = report.book_rungs_inserted = report.statuses_inserted = 0
        report.payloads_recorded = 0
        return report
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}")
        raise

    report.anomalies = [_anomaly(a) for a in checks.anomalies]
    await runner.finalize(rows_written=report.rows_written)
    report.status = RunStatus.COMPLETE.value
    return report


# Recorder lifecycle events that a reader of the DATABASE must also see. They
# are WARN, not FAIL: the frames that were captured are still true.
_EVENT_ANOMALY = {
    "coverage_cap": AnomalyKind.COVERAGE_CAP,
    "disconnected": AnomalyKind.GAP,
    "stale": AnomalyKind.GAP,
    "gave_up": AnomalyKind.GAP,
    "auth_failed": AnomalyKind.VENDOR_ERROR,
}


def _event_anomaly(checks, rec) -> None:
    try:
        ev = rec.event()
    except ValueError:
        checks.add(AnomalySeverity.WARN, AnomalyKind.PARSE_REJECT, "event_record",
                   frame_seq=rec.seq, reason="event record is not JSON")
        return
    name = ev.get("event")
    detail = {k: v for k, v in ev.items() if k != "event"}
    if name in _EVENT_ANOMALY:
        checks.add(AnomalySeverity.WARN, _EVENT_ANOMALY[name], f"recorder.{name}",
                   frame_seq=rec.seq, recorded_at=rec.recv_at.isoformat(), **detail)
    elif name == "capture_end" and ev.get("never_seen_count"):
        # Subscribed, but not one frame arrived for these keys (B5/B8 evidence).
        checks.add(AnomalySeverity.WARN, AnomalyKind.COVERAGE_DROP, "recorder.never_seen",
                   frame_seq=rec.seq, count=ev["never_seen_count"],
                   keys=ev.get("never_seen_keys", []))


def _chain(head: list, tail):
    yield from head
    yield from tail


def _anomaly(a) -> dict[str, Any]:
    return {"severity": a.severity.value, "kind": a.kind.value, "subject": a.subject,
            "detail": a.detail}


@dataclass(slots=True)
class SessionReplayReport:
    session_id: str = ""
    session_date: str = ""
    manifest: str = ""
    shards: list[ReplayReport] = field(default_factory=list)
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return RunStatus.FAILED.value
        ok = self.shards and all(r.status == RunStatus.COMPLETE.value for r in self.shards)
        return RunStatus.COMPLETE.value if ok else RunStatus.FAILED.value

    @property
    def rows_written(self) -> int:
        return sum(r.rows_written for r in self.shards)


async def replay_session(
    session: AsyncSession, manifest: pathlib.Path, *, commit: bool, token: str | None,
    operator: str = "cli",
) -> SessionReplayReport:
    """Replay every connection archive of a capture session, each as its own
    run (a row's provenance is its own archive and frame). Refuses an archive
    whose header does not belong to this session."""
    import json

    # Batch job, like replay_archive: synchronous reads are deliberate.
    manifest = pathlib.Path(manifest).resolve()  # noqa: ASYNC240
    doc = json.loads(manifest.read_text())
    rep = SessionReplayReport(session_id=doc["session_id"], session_date=doc["session_date"],
                              manifest=str(manifest))
    for shard in doc["shards"]:
        arc = pathlib.Path(shard["archive"])
        header_reader = FrameArchiveReader(arc)
        next(iter(header_reader), None)
        h = header_reader.header
        if h.get("session_id") != rep.session_id or h.get("shard_index") != shard["index"]:
            rep.error = (f"{arc.name}: header session {h.get('session_id')}/"
                         f"{h.get('shard_index')} does not match manifest "
                         f"{rep.session_id}/{shard['index']}")
            return rep
    for shard in doc["shards"]:
        rep.shards.append(await replay_archive(
            session, pathlib.Path(shard["archive"]), commit=commit, token=token,
            session_date=_dt.date.fromisoformat(rep.session_date), operator=operator,
        ))
    return rep


# ── tailing replay (PREOPEN-TAIL, user 2026-10-22: PRE_OPEN features before the open) ──
READY_MARGIN = _dt.timedelta(seconds=5)    # frames arrive <= 0.87 s after currentTs (measured
                                           # 2026-10-22, both connections); 5 s is the margin
TAIL_INTERVAL_S = 10.0


def ready_marker_path(day: _dt.date) -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2] / "var" / "run" / \
        f"preopen_ready_{day.isoformat()}.json"


def _archive_closed(arc: pathlib.Path) -> bool:
    from app.storage.frame_archive import manifest_path
    return manifest_path(arc).exists()


async def _analyze(session: AsyncSession) -> dict[str, Any]:
    """Planner statistics for today's rows before PRE_OPEN reads them (2026-10-13: without
    them the per-instrument query scanned the whole day, 842 s). Best effort."""
    import time

    from sqlalchemy import text
    t = time.monotonic()
    try:
        await session.execute(text("set local lock_timeout = '30s'"))
        await session.execute(text("set local statement_timeout = '240s'"))
        await session.execute(text("analyze preopen_tick, preopen_book"))
        await session.commit()
        return {"ok": True, "seconds": round(time.monotonic() - t, 2)}
    except Exception as e:                      # logged; changes nothing else
        await session.rollback()
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


async def tail_session(
    session: AsyncSession, manifest: pathlib.Path, *, token: str | None,
    ready_at: _dt.datetime | None, interval_s: float = TAIL_INTERVAL_S,
    marker: pathlib.Path | None = None, operator: str = "cli",
    max_passes: int | None = None,
) -> dict[str, Any]:
    """Replay a capture session WHILE it records: every `interval_s`, each connection's
    new records as one COMMIT run (the same path as a full replay), until every archive
    is closed and its final pass verified the stream against the manifest.

    The first pass that STARTED at or after `ready_at` (PRE_OPEN as_of + READY_MARGIN)
    holds every frame whose currentTs is before as_of: such a frame is received within
    0.87 s (measured) and archived on receipt, before the recorder reads the next one, so
    it is on disk well before ready_at. After that pass the planner statistics are
    refreshed and `marker` is written; Stage 3 PRE_OPEN verifies it against ingest_run
    before it computes. At the end, `late_ticks` counts the ticks knowable before as_of
    that the ready pass did not hold (expected 0; else a recompute would differ).
    Fails closed: a FAILED pass stops the tail (exit status), and the caller falls back
    to the full replay."""
    import asyncio
    import json

    from app.core.clock import now

    manifest = pathlib.Path(manifest).resolve()  # noqa: ASYNC240
    doc = json.loads(manifest.read_text())
    day = _dt.date.fromisoformat(doc["session_date"])
    shards = [{"index": sh["index"], "archive": pathlib.Path(sh["archive"]), "next_seq": 0,
               "runs": [], "final_done": False} for sh in doc["shards"]]
    out: dict[str, Any] = {"session_id": doc["session_id"], "session_date": str(day),
                           "manifest": str(manifest), "passes": 0, "ready": None,
                           "status": "RUNNING", "error": None}
    while True:
        started = now()
        for sh in shards:
            if sh["final_done"]:
                continue
            final = _archive_closed(sh["archive"])
            rep = await replay_archive(
                session, sh["archive"], commit=True, token=token, session_date=day,
                operator=operator, tail=TailPass(sh["next_seq"], started, final))
            if rep.status == RunStatus.FAILED.value:
                out.update(status="FAILED", error=f"{sh['archive'].name}: {rep.error}",
                           failed_run=str(rep.run_id))
                return out
            if rep.status == RunStatus.COMPLETE.value:
                sh["runs"].append({"run_id": str(rep.run_id), "seq_from": sh["next_seq"],
                                   "seq_to": rep.next_seq, "rows": rep.rows_written})
            sh["next_seq"] = rep.next_seq
            sh["final_done"] = final
        out["passes"] += 1
        if out["ready"] is None and ready_at is not None and started >= ready_at:
            an = await _analyze(session)
            out["ready"] = {
                "session_id": doc["session_id"], "session_date": str(day),
                "manifest": str(manifest), "ready_at": ready_at.isoformat(),
                "pass_started_at": started.isoformat(), "written_at": now().isoformat(),
                "analyze": an,
                "shards": [{"index": sh["index"], "archive": sh["archive"].name,
                            "next_seq": sh["next_seq"],
                            "run_ids": [r["run_id"] for r in sh["runs"]]} for sh in shards]}
            if marker is not None:
                marker.parent.mkdir(parents=True, exist_ok=True)
                tmp = marker.with_suffix(".part")
                tmp.write_text(json.dumps(out["ready"], indent=2))
                tmp.replace(marker)
        if all(sh["final_done"] for sh in shards):
            break
        if max_passes is not None and out["passes"] >= max_passes:
            out["status"] = "STOPPED"
            break
        await asyncio.sleep(max(0.0, interval_s - (now() - started).total_seconds()))
    if out["ready"] is not None and out["status"] == "RUNNING":
        from sqlalchemy import text
        ready_runs = [r for sh in out["ready"]["shards"] for r in sh["run_ids"]]
        out["late_ticks"] = (await session.execute(text("""
            select count(*) from preopen_tick t join ingest_run r using (run_id)
            where t.session_date = :d and t.knowable_at < :a and r.stream = :st
              and r.request_params->>'replay_of' = any(:names)
              and not (t.run_id = any(cast(:rr as uuid[])))"""),
            {"d": day, "a": ready_at - READY_MARGIN, "st": STREAM, "rr": ready_runs,
             "names": [sh["archive"].name for sh in shards]})).scalar()
        await session.rollback()
    out["shards"] = [{"index": sh["index"], "archive": sh["archive"].name,
                      "records": sh["next_seq"], "runs": len(sh["runs"]),
                      "rows": sum(r["rows"] for r in sh["runs"])} for sh in shards]
    if out["status"] == "RUNNING":
        out["status"] = RunStatus.COMPLETE.value
    return out


class NotReady(RuntimeError):
    """The PRE_OPEN fast path's evidence is absent or does not hold."""


async def verify_ready(session: AsyncSession, day: _dt.date, as_of: _dt.datetime,
                       marker: pathlib.Path | None = None) -> dict[str, Any]:
    """Stage 3 PRE_OPEN's check of the tail's marker against the database: the pass
    started at or after as_of + READY_MARGIN, and per connection the COMPLETE tail runs
    cover the records [0, next_seq) without a gap. Raises NotReady."""
    import json

    from sqlalchemy import text
    marker = marker or ready_marker_path(day)
    if not marker.exists():
        raise NotReady(f"no marker {marker.name}")
    m = json.loads(marker.read_text())
    if m.get("session_date") != day.isoformat():
        raise NotReady(f"marker is for {m.get('session_date')}, not {day}")
    if _dt.datetime.fromisoformat(m["pass_started_at"]) < as_of + READY_MARGIN:
        raise NotReady(f"the pass started {m['pass_started_at']}, before as_of + "
                       f"{READY_MARGIN.total_seconds():.0f} s")
    doc = json.loads(pathlib.Path(m["manifest"]).read_text())  # noqa: ASYNC240 - tiny file
    if doc["session_id"] != m["session_id"] or len(doc["shards"]) != len(m["shards"]):
        raise NotReady("marker does not match its capture session")
    for sh in m["shards"]:
        rows = (await session.execute(text("""
            select run_id::text as run_id, status, request_params->>'replay_of' as arc,
                   (request_params->'tail'->>'seq_from')::bigint as a,
                   (request_params->'tail'->>'seq_to')::bigint as b
            from ingest_run where stream = :st and mode = 'COMMIT'
              and run_id = any(cast(:r as uuid[]))"""),
            {"st": STREAM, "r": sh["run_ids"]})).all()
        if len(rows) != len(sh["run_ids"]) or any(
                r.status != RunStatus.COMPLETE.value or r.arc != sh["archive"] for r in rows):
            raise NotReady(f"{sh['archive']}: a tail run is missing or not COMPLETE")
        seq = 0
        for r in sorted(rows, key=lambda r: r.a):
            if r.a != seq:
                raise NotReady(f"{sh['archive']}: records {seq}..{r.a} not replayed")
            seq = r.b
        if seq != sh["next_seq"]:
            raise NotReady(f"{sh['archive']}: runs end at {seq}, marker says {sh['next_seq']}")
    return {"marker": marker.name, "pass_started_at": m["pass_started_at"],
            "records": [sh["next_seq"] for sh in m["shards"]], "analyze": m.get("analyze")}
