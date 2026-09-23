"""The Upstox Market Data Feed V3 wire contract, vendored and pinned.

MarketDataFeed.proto is Upstox's own file, byte-for-byte, fetched from
PROTO_URL on 2026-09-23. MarketDataFeed_pb2.py is generated from it:

    python -m grpc_tools.protoc -Iapp/vendor/upstox/proto \
        --python_out=app/vendor/upstox/proto --pyi_out=app/vendor/upstox/proto \
        app/vendor/upstox/proto/MarketDataFeed.proto

PROTO_SHA256 is asserted by tests/unit/test_proto_pin.py. If Upstox changes
the contract, re-vendoring is a deliberate, reviewed act — the pin fails until
someone updates it, rather than the decoder drifting silently.

Every archived frame session records this hash, so a replay can always say
which contract its bytes were decoded against.
"""

PROTO_URL = "https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto"
PROTO_SHA256 = "3e1c939dce2c83a3fef91405c5ca268dfa089aae973319f56685f12a5afcf612"
