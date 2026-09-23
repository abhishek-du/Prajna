"""Archive-first: bytes survive verbatim, crashes lose at most one record,
corruption is detected rather than decoded."""

from __future__ import annotations

import gzip
import hashlib
import json
import os

import pytest

from app.storage.frame_archive import (
    ArchiveCorrupt,
    FrameArchiveReader,
    FrameArchiveWriter,
    RecordKind,
    manifest_path,
)
from tests.support.upstox_frames import ist

HEADER = {"session_date": "2026-09-24", "source": "UPSTOX_WS_V3"}


def _payloads(n=20):
    # Includes bytes that JSON/text encodings would mangle.
    return [bytes([i % 256]) * i + b"\x00\xff\x80" + os.urandom(64) for i in range(n)]


def test_roundtrip_is_byte_exact(tmp_path):
    p = tmp_path / "s.frames.gz"
    frames = _payloads()
    with FrameArchiveWriter(p, HEADER) as w:
        w.append_event("connected", ist(8, 55), endpoint="wss://x")
        for i, f in enumerate(frames):
            w.append_frame(f, ist(9, 0, i, 123))
        w.append_frame("text frame", ist(9, 1))

    r = FrameArchiveReader(p)
    recs = list(r)
    assert r.header["session_date"] == "2026-09-24" and r.header["format_version"] == 1
    assert [x.seq for x in recs] == list(range(len(frames) + 2))
    assert recs[0].kind is RecordKind.EVENT and recs[0].event()["event"] == "connected"
    binary = [x for x in recs if x.kind is RecordKind.BINARY]
    assert [x.payload for x in binary] == frames
    assert all(x.sha256 == hashlib.sha256(x.payload).hexdigest() for x in recs)
    assert binary[3].recv_at == ist(9, 0, 3, 123)
    assert recs[-1].kind is RecordKind.TEXT and recs[-1].payload == b"text frame"
    assert r.truncated is False


def test_manifest_matches_what_the_reader_sees(tmp_path):
    p = tmp_path / "s.frames.gz"
    with FrameArchiveWriter(p, HEADER) as w:
        for f in _payloads(5):
            w.append_frame(f)
    m = json.loads(manifest_path(p).read_text())
    r = FrameArchiveReader(p)
    list(r)
    assert m["closed_cleanly"] and m["records"] == 5 and m["counts"]["BINARY"] == 5
    assert m["stream_sha256"] == r.stream_sha256


def test_never_appends_to_an_existing_session(tmp_path):
    p = tmp_path / "s.frames.gz"
    FrameArchiveWriter(p, HEADER).close()
    with pytest.raises(FileExistsError):
        FrameArchiveWriter(p, HEADER)


def test_a_crash_keeps_every_completed_record(tmp_path):
    """Killed at 09:14 must not mean the session is gone."""
    p = tmp_path / "s.frames.gz"
    frames = _payloads(30)
    w = FrameArchiveWriter(p, HEADER)
    for f in frames:
        w.append_frame(f)
    # No close(): simulate the process dying mid-write of a final record.
    w._fh.flush()
    data = p.read_bytes()
    p.write_bytes(data[:-7])

    r = FrameArchiveReader(p)
    recs = list(r)
    assert r.truncated is True
    assert r.stream_sha256 is None
    assert 25 <= len(recs) < 30
    assert [x.payload for x in recs] == frames[: len(recs)]
    assert not manifest_path(p).exists()


def test_corrupted_payload_is_detected_not_decoded(tmp_path):
    p = tmp_path / "s.frames.gz"
    with FrameArchiveWriter(p, HEADER) as w:
        w.append_frame(b"A" * 100)
    raw = bytearray(gzip.decompress(p.read_bytes()))
    raw[-10] ^= 0xFF
    p.write_bytes(gzip.compress(bytes(raw)))
    with pytest.raises(ArchiveCorrupt, match="sha256"):
        list(FrameArchiveReader(p))


def test_foreign_file_is_rejected(tmp_path):
    p = tmp_path / "x.gz"
    p.write_bytes(gzip.compress(b"not an archive at all"))
    with pytest.raises(ArchiveCorrupt, match="not a prajna frame archive"):
        list(FrameArchiveReader(p))


def test_naive_receive_time_is_refused(tmp_path):
    import datetime as _dt
    with FrameArchiveWriter(tmp_path / "s.gz", HEADER) as w, pytest.raises(ValueError):
        w.append_frame(b"x", _dt.datetime(2026, 9, 24, 9, 0))
