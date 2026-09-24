Real Upstox responses, recorded 2026-09-23 with account 2UB7PH. They are
byte-identical to the archived payloads; the sha256 prefix is shown for each.

| file | endpoint | sha256 |
|---|---|---|
| holidays_2026.json | GET /v2/market/holidays | eff843d4995d |
| timings_2026-09-24.json | GET /v2/market/timings/2026-09-24 (Thu, normal) | c8ee15cb1d42 |
| timings_2026-02-01.json | GET /v2/market/timings/2026-02-01 (Sun, Budget session) | bb94b99f9a58 |
| timings_2026-11-08.json | GET /v2/market/timings/2026-11-08 (Sun, Muhurat) | bc4f97fbf66b |
| timings_empty.json | GET /v2/market/timings/2026-09-26 (Sat) and 2026-10-02 (holiday), identical bytes | 20bc1392a17b |
| market_status_NSE.json | GET /v2/market/status/NSE | 1f5bddc05029 |
| holidays_on_2024-01-26.json | GET /v2/market/holidays/2024-01-26 (recorded 2026-09-24; Republic Day) | e13212be74c4 |
| holidays_on_ordinary_day.json | GET /v2/market/holidays/2021-11-04 (recorded 2026-09-24; no entry) | same bytes as the live answer |
