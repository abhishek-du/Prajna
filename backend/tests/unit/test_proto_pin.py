"""The vendored wire contract is exactly the one we pinned.

If Upstox changes MarketDataFeed.proto, updating the copy here must be a
deliberate, reviewed act — this test fails until PROTO_SHA256 is bumped too.
"""

from __future__ import annotations

import hashlib
import pathlib

from app.vendor.upstox.proto import PROTO_SHA256
from app.vendor.upstox.proto import MarketDataFeed_pb2 as pb

PROTO = pathlib.Path(pb.__file__).with_name("MarketDataFeed.proto")


def test_vendored_proto_matches_pin():
    assert hashlib.sha256(PROTO.read_bytes()).hexdigest() == PROTO_SHA256


def test_generated_code_matches_the_vendored_proto():
    """The pb2 must have been generated from THIS file, not an older copy."""
    assert pb.DESCRIPTOR.name == "MarketDataFeed.proto"
    src = PROTO.read_text()
    for msg in ("FeedResponse", "Feed", "MarketFullFeed", "LTPC", "MarketInfo", "StatusInfo"):
        assert f"message {msg}" in src and msg in pb.DESCRIPTOR.message_types_by_name


def test_preopen_field_numbers_are_the_ones_the_schema_documents():
    """app/db/models/preopen.py documents these wire numbers; hold it to them."""
    f = pb.MarketFullFeed.DESCRIPTOR.fields_by_name
    assert {n: f[n].number for n in
            ("tbq", "tsq", "iep", "rp", "ieq", "iiqTotal", "iiqM", "casEligible")} == {
        "tbq": 9, "tsq": 10, "iep": 11, "rp": 12, "ieq": 13, "iiqTotal": 14, "iiqM": 15,
        "casEligible": 16,
    }


def test_request_modes_on_the_wire():
    """B6 context: the contract names full_d5 and full_d30, not 'full'."""
    assert set(pb.RequestMode.keys()) == {"ltpc", "full_d5", "option_greeks", "full_d30"}
