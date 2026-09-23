Real Upstox FII/DII activity responses (`GET /v2/market/fii`, `/v2/market/dii`),
recorded 2026-09-23 with account 2UB7PH. They are byte-identical to the
archive; `manifest.json` gives each file's sha256 and request.

Measured semantics:
- `from` is the END date of a 30-trading-day window.
- No `from` returns the latest 30 trading days.
- Data starts 2026-04-01; a `from` before it returns an empty list.
- `time_stamp` is the session date at 00:00 IST: a label, not a publication time.
