"""Append-only archive of WebSocket frames, written as they arrive.

RULE: a frame's bytes are on disk, verbatim, BEFORE anything decodes them.

A pre-open capture is one long-lived connection producing thousands of frames
over ~25 minutes. PayloadStore.put() (one file per payload) suits REST
responses; a stream needs a single file that survives a crash at 09:14 with
everything up to 09:14 intact. Hence:

  * one gzip member, SYNC-flushed after every record, so the bytes already
    written are always decompressible — a killed process loses at most the
    record it was in the middle of writing;
  * length-prefixed binary records, so vendor bytes are never re-encoded
    (no base64, no JSON escaping) and replay hands the decoder exactly what
    the socket delivered;
  * a sha256 per record, checked on read, so corruption is detected rather
    than decoded into plausible-looking rows.

Layout of the decompressed stream:

    MAGIC  b"PRJFRM01"
    u32    header length, then the header as sorted-key UTF-8 JSON
    record*:
        u8   kind       1 = vendor binary frame, 2 = vendor text frame,
                        3 = our lifecycle event (JSON)
        u64  seq        monotonic across all records in the file, from 0
        i64  recv_ns    our wall clock at receipt, epoch nanoseconds UTC
        u32  length
        32B  sha256 of the payload
        ...  payload

On a clean close a sidecar `<file>.manifest.json` records counts, the time
span and the sha256 of the whole decompressed stream. A missing manifest means
the session did not close cleanly; the archive is still fully readable.
"""

from __future__ import annotations

import datetime as _dt
import enum
import hashlib
import json
import os
import pathlib
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.core.clock import UTC, now, to_utc

MAGIC = b"PRJFRM01"
FORMAT_VERSION = 1
_REC = struct.Struct(">BQqI32s")
_U32 = struct.Struct(">I")
_GZIP_WBITS = 16 + zlib.MAX_WBITS
_READ_CHUNK = 1 << 20


class ArchiveCorrupt(Exception):
    """The archive's bytes do not match what was written. Never decoded past."""


class RecordKind(enum.IntEnum):
    BINARY = 1
    TEXT = 2
    EVENT = 3


@dataclass(frozen=True, slots=True)
class FrameRecord:
    kind: RecordKind
    seq: int
    recv_at: _dt.datetime
    payload: bytes
    sha256: str

    def event(self) -> dict[str, Any]:
        if self.kind is not RecordKind.EVENT:
            raise ValueError(f"record {self.seq} is {self.kind.name}, not EVENT")
        return json.loads(self.payload)


def _to_ns(at: _dt.datetime) -> int:
    d = to_utc(at) - _dt.datetime(1970, 1, 1, tzinfo=UTC)
    return (d.days * 86_400 + d.seconds) * 1_000_000_000 + d.microseconds * 1_000


def _from_ns(ns: int) -> _dt.datetime:
    return _dt.datetime(1970, 1, 1, tzinfo=UTC) + _dt.timedelta(microseconds=ns // 1_000)


def manifest_path(archive: pathlib.Path) -> pathlib.Path:
    return archive.with_name(archive.name + ".manifest.json")


# ── writing ─────────────────────────────────────────────────────────────────
class FrameArchiveWriter:
    """Single-writer, create-only. Never appends to an existing session file:
    a restarted process starts a new file rather than splicing into an old one.
    """

    def __init__(self, path: pathlib.Path, header: dict[str, Any], *, fsync_every: int = 64):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "xb")
        self._z = zlib.compressobj(level=6, wbits=_GZIP_WBITS)
        self._stream_hash = hashlib.sha256()
        self._fsync_every = fsync_every
        self._since_fsync = 0
        self._seq = 0
        self._counts = {k.name: 0 for k in RecordKind}
        self._first: _dt.datetime | None = None
        self._last: _dt.datetime | None = None
        self._closed = False

        self.header = {**header, "format": "prajna-frames", "format_version": FORMAT_VERSION}
        hdr = json.dumps(self.header, sort_keys=True, separators=(",", ":"), default=str).encode()
        self._emit(MAGIC + _U32.pack(len(hdr)) + hdr)
        self._sync(force=True)

    def _emit(self, raw: bytes) -> None:
        self._stream_hash.update(raw)
        self._fh.write(self._z.compress(raw))
        self._fh.write(self._z.flush(zlib.Z_SYNC_FLUSH))

    def _sync(self, *, force: bool = False) -> None:
        self._fh.flush()
        self._since_fsync += 1
        if force or self._since_fsync >= self._fsync_every:
            os.fsync(self._fh.fileno())
            self._since_fsync = 0

    def append(self, kind: RecordKind, payload: bytes, recv_at: _dt.datetime | None = None) -> int:
        """Write one record. Returns its seq. The payload is not transformed."""
        if self._closed:
            raise ValueError("archive is closed")
        recv_at = to_utc(recv_at or now())
        seq = self._seq
        sha = hashlib.sha256(payload).digest()
        self._emit(_REC.pack(int(kind), seq, _to_ns(recv_at), len(payload), sha) + payload)
        self._sync()
        self._seq += 1
        self._counts[kind.name] += 1
        self._first = self._first or recv_at
        self._last = recv_at
        return seq

    def append_frame(self, data: bytes | str, recv_at: _dt.datetime | None = None) -> int:
        if isinstance(data, str):
            return self.append(RecordKind.TEXT, data.encode("utf-8"), recv_at)
        return self.append(RecordKind.BINARY, bytes(data), recv_at)

    def append_event(self, event: str, recv_at: _dt.datetime | None = None, **detail) -> int:
        """Lifecycle evidence (connect, subscribe, reconnect, stale...) in-band,
        so the archive alone explains any gap in the frames."""
        body = json.dumps({"event": event, **detail}, sort_keys=True, default=str).encode()
        return self.append(RecordKind.EVENT, body, recv_at)

    def close(self) -> dict[str, Any]:
        if self._closed:
            raise ValueError("archive already closed")
        self._fh.write(self._z.flush(zlib.Z_FINISH))
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        self._closed = True
        manifest = {
            "archive": self.path.name,
            "header": self.header,
            "records": self._seq,
            "counts": self._counts,
            "first_recv_at": self._first.isoformat() if self._first else None,
            "last_recv_at": self._last.isoformat() if self._last else None,
            "stream_sha256": self._stream_hash.hexdigest(),
            "closed_cleanly": True,
        }
        mp = manifest_path(self.path)
        tmp = mp.with_suffix(".part")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        os.replace(tmp, mp)
        return manifest

    def __enter__(self) -> FrameArchiveWriter:
        return self

    def __exit__(self, *exc) -> None:
        if not self._closed:
            self.close()


# ── reading ─────────────────────────────────────────────────────────────────
def _decompressed_chunks(path: pathlib.Path) -> Iterator[bytes]:
    """Stream-decompress, tolerating a truncated final gzip member (a crash)
    and concatenated members."""
    d = zlib.decompressobj(_GZIP_WBITS)
    with open(path, "rb") as fh:
        while chunk := fh.read(_READ_CHUNK):
            while chunk:
                out = d.decompress(chunk)
                if out:
                    yield out
                if d.eof:
                    chunk = d.unused_data
                    d = zlib.decompressobj(_GZIP_WBITS)
                else:
                    chunk = b""
    tail = d.flush()
    if tail:
        yield tail


class FrameArchiveReader:
    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)
        self.header: dict[str, Any] = {}
        self.truncated = False
        self.stream_sha256: str | None = None

    def __iter__(self) -> Iterator[FrameRecord]:
        buf = bytearray()
        chunks = _decompressed_chunks(self.path)
        h = hashlib.sha256()

        def need(n: int) -> bool:
            while len(buf) < n:
                try:
                    c = next(chunks)
                except StopIteration:
                    return False
                buf.extend(c)
                h.update(c)
            return True

        if not need(len(MAGIC) + _U32.size) or bytes(buf[: len(MAGIC)]) != MAGIC:
            raise ArchiveCorrupt(f"{self.path}: not a prajna frame archive")
        (hlen,) = _U32.unpack_from(buf, len(MAGIC))
        start = len(MAGIC) + _U32.size
        if not need(start + hlen):
            raise ArchiveCorrupt(f"{self.path}: header truncated")
        self.header = json.loads(bytes(buf[start : start + hlen]))
        del buf[: start + hlen]

        expected_seq = 0
        while True:
            if not need(_REC.size):
                self.truncated = len(buf) > 0
                break
            kind, seq, ns, length, sha = _REC.unpack_from(buf, 0)
            if not need(_REC.size + length):
                self.truncated = True
                break
            payload = bytes(buf[_REC.size : _REC.size + length])
            del buf[: _REC.size + length]
            if hashlib.sha256(payload).digest() != sha:
                raise ArchiveCorrupt(f"{self.path}: record {seq} fails its sha256")
            if seq != expected_seq:
                raise ArchiveCorrupt(f"{self.path}: record seq {seq}, expected {expected_seq}")
            try:
                rk = RecordKind(kind)
            except ValueError:
                raise ArchiveCorrupt(f"{self.path}: record {seq} has unknown kind {kind}") from None
            expected_seq += 1
            yield FrameRecord(rk, seq, _from_ns(ns), payload, sha.hex())

        self.stream_sha256 = None if self.truncated else h.hexdigest()

    def manifest(self) -> dict[str, Any] | None:
        mp = manifest_path(self.path)
        return json.loads(mp.read_text()) if mp.exists() else None
