# Vendor evidence (hardening investigation, 2026-09-25)

Response BODIES only (no headers, no credentials), exactly as Upstox served them.
Captured with `scratchpad/up.sh` (the access token is read in-process, never logged).
Used by the phase 5-7 regression tests. Do not edit: tests check the sha256.

| file | captured (UTC) | HTTP | request | sha256 |
|---|---|---|---|---|
| AHCL_1d_live.json | 2026-09-25T08:35:29Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0Y8W01025/days/1/2026-09-25/2023-09-01` | `158c350c1c28122fe71626814df719d51aa0b7c2c0663acd1133b8986985f79a` |
| AILIMITED_1d_live.json | 2026-09-25T08:35:25Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0CAJ01017/days/1/2026-09-25/2023-09-01` | `8b8efc5d7707bc3de1151de6dc37470b970c60f1c8f24fdb54877c814a5b2ee0` |
| BZUSD_global_live.json | 2026-09-25T08:41:53Z | 200 | `/v3/historical-candle/GLOBAL_INDICATOR%7CBZUSD/days/1/2026-09-25/2026-09-18` | `227dddc066defb7ca47ca3299e8af65a856eb00d6db4021b01ec5f9de6f3ccdc` |
| CHAVDA_minutes_1_sep.json | 2026-09-25T08:36:04Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0PT101017/minutes/1/2026-09-24/2026-09-22` | `0a3c685d7fce01aa9fa6b361585e9099202c5b5a9b3440de7075494fa9928919` |
| DHARIWAL_1d_live.json | 2026-09-25T08:35:23Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0YRN01025/days/1/2026-09-25/2023-09-01` | `acb09f8f7f806263857ada1d0f0f96a953dd1851fcc860f05869c9a13af77837` |
| ENGINERSIN_1d_live.json | 2026-09-25T08:36:42Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE510A01028/days/1/2026-09-25/2026-06-01` | `35db506a0f99579f0880342c4c7b89896ba1df3f6373c753daee4ed3c895a621` |
| GSPC_global_live.json | 2026-09-25T08:41:53Z | 200 | `/v3/historical-candle/GLOBAL_INDEX%7C%5EGSPC/days/1/2026-09-25/2026-09-18` | `db692ed2dfb146a5ac70812797419d4cff44fa3484f2c7fa3b78a259ad72dcc9` |
| HSI_global_live.json | 2026-09-25T08:41:52Z | 200 | `/v3/historical-candle/GLOBAL_INDEX%7C%5EHSI/days/1/2026-09-25/2026-09-18` | `8ce922ffb1248dcfaaa804f6ba99cc7ef7448bedbeef9fdd6626f9edc58e781e` |
| IDEALTECHO_1d_live.json | 2026-09-25T08:35:22Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0T9I01011/days/1/2026-09-25/2023-09-01` | `4f452aff167b3815dde992663af27cb6be95364d641fe6922e31e697cd5d312c` |
| JAKHARIA_1d_live.json | 2026-09-25T08:35:24Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE00N401018/days/1/2026-09-25/2023-09-01` | `ce7fe0e47e71a1b99b54a04eea091e8ff63a039f440253cee0fab95f780f7176` |
| LICI_1d_live.json | 2026-09-25T08:35:30Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0J1Y01017/days/1/2026-09-25/2023-09-01` | `2d07a2543b2da711f89a096d3f9dca15064300f913ea1524055da6ee5e8eba3c` |
| N225_global_archived_20260925_1341.json | 2026-09-25T08:11:44Z | 200 | `archive sha 8c012c78... (the run that first stored N225 label 2026-09-24)` | `8c012c78c9f7e7d68ae1ffbd5066dd97e3b5b37dd037e5c1fc27d7904f30c4d2` |
| N225_global_live.json | 2026-09-25T08:41:52Z | 200 | `/v3/historical-candle/GLOBAL_INDEX%7C%5EN225/days/1/2026-09-25/2026-09-18` | `496833f780df497857e6e8855b203ff10badd273257355137a9e0c04f2741e97` |
| RCDL_1d_live.json | 2026-09-25T08:36:53Z | 400 | `/v3/historical-candle/NSE_EQ%7CINE0BZQ20011/days/1/2026-09-25/2026-08-01` | `c43b67215d53ef2890dbde2401e0ced4089d85d5a7607b726644662f9916828d` |
| RCDL_intraday_live.json | 2026-09-25T08:36:54Z | 400 | `/v3/historical-candle/intraday/NSE_EQ%7CINE0BZQ20011/minutes/1` | `c43b67215d53ef2890dbde2401e0ced4089d85d5a7607b726644662f9916828d` |
| RELIANCE_ca_live.json | 2026-09-25T08:39:17Z | 200 | `/v2/fundamentals/INE002A01018/corporate-actions` | `65f915126d15e933fd56db0c05f59afbaa5bbc90b6175d3dd65ae4b83b55065a` |
| SGX_global_live.json | 2026-09-25T08:41:53Z | 200 | `/v3/historical-candle/GLOBAL_INDEX%7CSGX%20NIFTY/days/1/2026-09-25/2026-09-18` | `5d00cb3532f69a5a72e7b1bb1ea428dbf55bc2f2ef2fd0d601e6e903f6e6c3fd` |
| TDPOWERSYS_1d_live.json | 2026-09-25T08:35:28Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE419M01035/days/1/2026-09-25/2023-09-01` | `2a2c8c7ad448c7fa08fd9a67aea31518501f4917a02e42bcae352fcf69486371` |
| TDPOWERSYS_minutes_1_aug.json | 2026-09-25T08:36:03Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE419M01035/minutes/1/2026-08-24/2026-08-21` | `76166ebbce93428ae074d48e040072fa5ada9e87ee772fcca24682ed9fc3268d` |
| TRENT_1d_live.json | 2026-09-25T08:35:27Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE849A01020/days/1/2026-09-25/2023-09-01` | `a01ca9bb0d53af9e58338a3786b972d34002974405164a99ce1ec945be229165` |
| TRENT_ca_live.json | 2026-09-25T08:39:18Z | 200 | `/v2/fundamentals/INE849A01020/corporate-actions` | `2cbdb02e1a505640d40b57ff4b5607bb72dc5d58bfbae9783e7545415f014e11` |
| UEL_1d_live.json | 2026-09-25T08:35:25Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE899L01030/days/1/2026-09-25/2023-09-01` | `2dd7706fbd5dffa351bf728b44a0f26ff360550c56aebde0012ab5fb7cbef29b` |
| USASEEDS_1d_live.json | 2026-09-25T08:35:26Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0CBM01019/days/1/2026-09-25/2023-09-01` | `207a07fdb32219c6ae6eac59cebb3409bed46cea2bd037e01e4474200fd4b2dd` |
| USDINR_global_live.json | 2026-09-25T08:41:51Z | 200 | `/v3/historical-candle/GLOBAL_INDICATOR%7CUSDINR/days/1/2026-09-25/2026-09-18` | `7da37184064ad9c41f5e60e1da9ab3af7974982062593e982caab452225b4a65` |
| chavda_1d_archived_20260923.json | 2026-09-23T14:25:14Z | 200 | `archive var/archive/UPSTOX_REST_V3/2026/09/23/329f7100... (the run that stored CHAVDA 1D)` | `329f7100c0872d93d81b925c232e8cc2eb6794403b3d18b05777dd3fefbd1c65` |
| chavda_1d_live.json | 2026-09-25T08:34:23Z | 200 | `/v3/historical-candle/NSE_EQ%7CINE0PT101017/days/1/2026-09-25/2023-09-01` | `e7564c50470759d153f1b68e08a401c270b5308d4a261ad7abd8525f8470cbc2` |
