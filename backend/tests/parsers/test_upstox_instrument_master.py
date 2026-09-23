"""NSE.json.gz -> instruments, with every row accounted for."""

from __future__ import annotations

import pytest

from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.parsers.upstox_instrument_master import (
    RULE_KEY_SEGMENT,
    RULE_MALFORMED,
    MasterDecodeError,
    parse_master,
)
from tests.support import upstox_master as M


def test_gzip_and_plain_json_parse_identically():
    assert parse_master(M.master_bytes(M.ALL)).instruments == \
        parse_master(M.master_bytes(M.ALL, gz=False)).instruments


def test_fields_survive():
    (r,) = parse_master(M.master_bytes([M.NIFTYBEES])).instruments
    assert (r.instrument_key, r.segment, r.instrument_type, r.isin, r.trading_symbol) == (
        "NSE_EQ|INF204KB14I2", "NSE_EQ", "EQ", "INF204KB14I2", "NIFTYBEES")


def test_malformed_rows_are_named_not_dropped():
    rows = [M.RELIANCE, "not-an-object", {"segment": "NSE_EQ"},
            {"instrument_key": "NOPIPE", "segment": "NSE_EQ"}]
    p = parse_master(M.master_bytes(rows))
    assert [i.instrument_key for i in p.instruments] == [M.RELIANCE["instrument_key"]]
    assert p.rejected == {RULE_MALFORMED: [1, 2, 3]}
    assert all(i.severity is AnomalySeverity.WARN and i.kind is AnomalyKind.PARSE_REJECT
               for i in p.issues)


def test_key_segment_contradiction_is_excluded_explicitly():
    bad = {**M.RELIANCE, "segment": "NSE_FO"}
    p = parse_master(M.master_bytes([bad]))
    assert p.instruments == [] and p.rejected == {RULE_KEY_SEGMENT: [0]}


def test_identical_duplicate_warns_and_keeps_one():
    p = parse_master(M.master_bytes([M.RELIANCE, M.RELIANCE]))
    assert len(p.instruments) == 1
    (i,) = p.issues
    assert (i.severity, i.kind, i.detail["identical"]) == (
        AnomalySeverity.WARN, AnomalyKind.DUPLICATE_KEY, True)


def test_conflicting_duplicate_fails():
    p = parse_master(M.master_bytes([M.RELIANCE, {**M.RELIANCE, "instrument_type": "BE"}]))
    (i,) = p.issues
    assert (i.severity, i.kind, i.detail["identical"]) == (
        AnomalySeverity.FAIL, AnomalyKind.DUPLICATE_KEY, False)


def test_every_row_is_accounted_for():
    rows = [*M.ALL, M.RELIANCE, 42]
    p = parse_master(M.master_bytes(rows))
    dupes = sum(1 for i in p.issues if i.kind is AnomalyKind.DUPLICATE_KEY)
    rejected = sum(len(v) for v in p.rejected.values())
    assert len(p.instruments) + dupes + rejected == p.row_count == len(rows)


@pytest.mark.parametrize("data", [b"{}", b'{"a": 1}', b"\xff\xfe garbage", b"[1,"])
def test_non_array_payload_is_refused(data):
    with pytest.raises(MasterDecodeError):
        parse_master(data)
