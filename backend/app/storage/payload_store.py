"""Content-addressed archive of raw vendor bytes.

RULE: the bytes hit disk BEFORE anything tries to parse them.

This is the property V1 lacked everywhere. Its pre-open handler assigned
NSE's preOpenMarket payload to a variable and never referenced it again; its
replay harnesses had to re-call live APIs because nothing kept the original
response. If a decode fails here, or the vendor changes its schema mid-session,
the session is still on disk and can be re-parsed later with no re-fetch.

Layout:  <archive>/<source>/<YYYY>/<MM>/<DD>/<sha256>.<ext>.gz
The hash covers vendor bytes only — never our wall clock — so the same response
always addresses the same file and re-ingestion is idempotent by construction.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import os
import pathlib
import tempfile
from dataclasses import dataclass

from app.contracts.provenance import payload_sha256
from app.core.clock import now, to_utc


@dataclass(frozen=True, slots=True)
class StoredPayload:
    sha256: str
    path: pathlib.Path
    byte_size: int
    content_type: str
    fetched_at: _dt.datetime
    vendor_reported_at: _dt.datetime | None
    deduplicated: bool  # True = these exact bytes were already archived


class PayloadStore:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)

    def _path_for(self, source: str, sha: str, fetched_at: _dt.datetime, ext: str) -> pathlib.Path:
        d = to_utc(fetched_at)
        return (
            self.root / source / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"
            / f"{sha}.{ext}.gz"
        )

    def put(
        self,
        data: bytes,
        *,
        source: str,
        content_type: str = "application/json",
        ext: str = "json",
        fetched_at: _dt.datetime | None = None,
        vendor_reported_at: _dt.datetime | None = None,
    ) -> StoredPayload:
        """Archive bytes atomically. Returns the content address.

        Atomic because a half-written archive that looks complete is worse than
        no archive: write to a temp file in the same directory, fsync, rename.
        """
        fetched_at = fetched_at or now()
        sha = payload_sha256(data)
        target = self._path_for(source, sha, fetched_at, ext)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            return StoredPayload(sha, target, len(data), content_type,
                                 fetched_at, vendor_reported_at, deduplicated=True)

        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                gz.write(data)
            os.replace(tmp, target)
        except BaseException:
            pathlib.Path(tmp).unlink(missing_ok=True)
            raise

        return StoredPayload(sha, target, len(data), content_type,
                             fetched_at, vendor_reported_at, deduplicated=False)

    def get(self, source: str, sha: str, fetched_at: _dt.datetime, ext: str = "json") -> bytes:
        """Read archived bytes back and verify they still hash correctly."""
        return self.read(self._path_for(source, sha, fetched_at, ext), sha)

    @staticmethod
    def read(path: pathlib.Path | str, sha: str) -> bytes:
        """Read an archived payload by its stored path (raw_payload.storage_uri)
        and refuse it unless it still hashes to `sha`."""
        p = pathlib.Path(path)
        data = gzip.decompress(p.read_bytes())
        actual = payload_sha256(data)
        if actual != sha:
            raise ValueError(f"archive corrupt: {p} hashes to {actual}, expected {sha}")
        return data

    def open_append_stream(self, source: str, name: str, fetched_at: _dt.datetime | None = None):
        """Append-only gzip stream, for WebSocket sessions.

        A pre-open capture produces thousands of frames over 20 minutes. Holding
        them in memory until the end would mean a crash at 09:14 loses the whole
        session, so frames are flushed to disk as they arrive.
        """
        fetched_at = fetched_at or now()
        d = to_utc(fetched_at)
        p = (self.root / source / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}" / name)
        p.parent.mkdir(parents=True, exist_ok=True)
        return gzip.open(p, "ab"), p
