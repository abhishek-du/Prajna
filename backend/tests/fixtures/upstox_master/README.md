`NSE_2026-09-23.json.gz` is the real Upstox instrument master
(`assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz`), exactly as
served on 2026-09-23 07:51 UTC. It is byte-identical to the archived payload.

sha256 `bf4a5db89c9e4129e5a281d9397e1f2d979ef8681e322e8479693fe20ba12331`,
1,988,515 bytes, 80,226 rows, 3,525 pre-open-eligible NSE_EQ instruments.

`NSE_2026-09-25.json.gz` is the same master as served on 2026-09-25 (captured
08:55 IST by the hardening investigation; byte-identical to the archived
payload fetched 02:55 UTC). sha256
`35d55ff300abc3685389c0886bf8fba1da6dab628c1b694becb6a1f9b569683e`, 1,971,383
bytes, 79,346 rows. Against the 09-23 master it has 4 new S1 listings
(SPECTRAA, SONA, AXIOMGAS, KHERIAAUTO), RCDL-RE (INE0BZQ20011) removed, and
attribute changes (e.g. CHAVDA lot size 1000 -> 2000 after its 1:1 bonus).
Used by tests/integration/test_instrument_refresh.py (replay).
