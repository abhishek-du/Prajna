Real Upstox V3 candle responses, recorded 2026-09-23 with account 2UB7PH.
They are byte-identical to the archived payloads under
var/archive/UPSTOX_REST_V3/2026/09/23. `manifest.json` gives each file's
sha256, endpoint, request, HTTP status and fetched_at, plus where that time
came from:
- the B1/B2 poller log, which is exact; or
- the archive mtime, which is written after receipt and so is a late bound.
