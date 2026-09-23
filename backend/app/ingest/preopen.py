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
) -> ReplayReport:
    """Replay one frame archive. Dry-run parses and checks everything and
    writes only the run ledger and its anomalies."""
    # Replay is a batch job: archive reads are synchronous by design. The live
    # recorder must not call this on its event loop.
    archive = pathlib.Path(archive).resolve()  # noqa: ASYNC240
    reader = FrameArchiveReader(archive)
    report = ReplayReport(archive=str(archive), committed=commit)

    it = iter(reader)
    first = next(it, None)          # reads the header
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


def _chain(head: list, tail):
    yield from head
    yield from tail


def _anomaly(a) -> dict[str, Any]:
    return {"severity": a.severity.value, "kind": a.kind.value, "subject": a.subject,
            "detail": a.detail}
