# News coverage check: the 12 market stories of 2026-09-29

**Checked:** 2026-09-29, about 15:50–16:00 IST, read-only.

**Sources checked:**

- **Production:** the database `prajna`, Upstox `news_article` / `news_instrument`, plus the market data (`ohlcv_bar` global labels, `macro_observation` FII/DII).
- **Multi-source news dry-run:** 8 sources in `backend/var/news/dryrun/*/events_2026-09-2{8,9}.jsonl`. These are **files only; production news writes are locked**, and `news_item` has 0 rows.

**Method:** a keyword search of titles and summaries for each topic. It covers items **published on 2026-09-29 IST**, or first seen then when a source gives only a date. The headlines were read to confirm each match, not just counted.

## Result per story

| # | Story | Captured? | First capture (IST) | Where | Exact figure in the text? | Market data in the DB |
|---|---|---|---|---|---|---|
| 1 | US–Iran / Middle East | **YES** (14 today) | 00:51 Mint: "Oil prices settle slightly higher … as Trump rejects Iran proposal" | Mint, CNBC-TV18, BusinessLine, BS, ET | — | — |
| 2 | Brent ~$107 | **YES** | 07:10 CNBC-TV18: "Brent above $106"; 07:56 BS: "Brent crude near $107" | CNBC-TV18, BS | "$107" yes (BS) | Brent daily labels only: stored 26 Sep = 106.12; **final (as used by Stage 3) = 25 Sep 104.33**. Intraday crude is not captured |
| 3 | Rupee past ₹96/USD | **YES** | 09:26 CNBC-TV18: "Rupee edges lower to 96.05"; 10:12 BL: "96.13"; 10:50 BS: "INR … below … 96" | CNBC-TV18, BL, BS | yes | USD/INR daily labels only: stored 27 Sep label 95.973; final 25 Sep 95.802. Intraday FX is not captured |
| 4 | US 10Y ~5.27% | **YES (the topic)**; **the exact 5.27% figure is not in any title or summary** | 00:20 Mint: "Wall St declines as oil prices, Treasury yields remain elevated"; 09:56 CNBC-TV18: "…5.3% treasury yield"; 14:56 Mint: "US bond yields hit 19-year high" | Mint, CNBC-TV18, BL, BS | no (bodies are not fetched) | **No US yield instrument exists** (Upstox has none; the one "TNX" name hit is an NSE stock ISIN) |
| 5 | Foreign investors selling | **YES** | 06:00 ET pre-market setup; several FII/FPI stories | ET, Mint, BS, BL | — | **FII NSE cash net:** −5,353 cr (28 Sep), −3,694 (25 Sep), −5,027 (24 Sep). Captured; used by Stage 3 |
| 6 | RBI liquidity / FX management | **YES** | 12:49 BL: "RBI's forex blitz drains nearly $20 billion from surplus liquidity" (also 28 Sep: "RBI intervention a 'reliable' buffer") | BL, ET | — | — |
| 7 | US tariff exemption, Indian specialty medicines | **YES**, **including production Upstox** | 00:06 CNBC-TV18: "India among 20 countries exempted from US tariffs on certain speciality drugs"; Upstox 10:46 "…Nifty Pharma up … as US exempts certain drugs" | CNBC-TV18, ET, BS, Upstox | yes | — |
| 8 | Tata Trusts → Tata Sons restructuring | **YES**, **the evening before**, and in production Upstox | **28 Sep 19:27**: Indian Express "Tata Trusts proposes strategic reorganisation to avoid listing" (published 19:23); 20:38 CNBC-TV18 explainer; Upstox 09:59 today | IE, CNBC-TV18, ET, Mint, Upstox | yes | — |
| 9 | Jio +~2.4m wireless subscribers (Aug) | **PARTIAL**: only the industry story; **no Jio-specific story** | 10:06 ET: "…telcos add 26 lakh mobile subscribers in Aug" (Airtel/Vi angle) | ET | the 2.4m Jio figure: **no** | — |
| 10 | Nifty monthly expiry | **YES** | 06:16 CNBC-TV18: "Nifty aims to arrest fall on monthly expiry"; Mint (3) | CNBC-TV18, Mint | — | no derivatives data in scope |
| 11 | Asian markets weak | **YES** | 06:49 Mint (Kospi, Nikkei cues); 07:56 BS: "Asian markets decline" | Mint, BS, ET | — | Nikkei stored 28 Sep 65,225 (−1.4% vs 27 Sep), not yet final; Hang Seng stored 28 Sep. **KOSPI: no instrument** |
| 12 | US equities fell overnight | **YES** | 00:20 Mint: "Wall St declines…"; 10:50 BS: "US stocks start week on negative note" | Mint, BS | — | S&P stored 28 Sep 7,705.4 (−0.67% vs 25 Sep), **not yet final** (confirmed at the 21:10 re-observation). **DJI: no 28 Sep label from the vendor** (the 12:40 and 21:10 fetches COMPLETED with 0 new rows) |

**Summary:** 10 of 12 stories were captured in full, 1 was captured as a topic without its exact figure (item 4), and 1 partially (item 9). **All captures except items 7 and 8 exist only in the dry-run files, not in the production database.**

## Why

1. **The production news feed is Upstox `/v2/news`, requested per instrument.** It returns only stock-tagged news:
   - 3,5xx keys in batches of 30;
   - about 27 articles a day;
   - every stored article is linked to an instrument (0 unlinked).

   Macro stories (Iran, crude, rupee, yields, RBI, global markets) reach production only if the vendor tags a stock. Today it caught items 7 and 8 and crash stories tagged to RIL and HDFC Bank.
2. **The broad macro coverage comes from the multi-source news adapters**, which run in **DRY_RUN**. Production writes are locked (per-source flags, NEWS-COMPLIANCE PENDING, mapping review pending). So the stories are captured, but in files, and nothing in Stages 2 or 3 reads them. FEATURE-NEWS-V2 is PENDING.
3. **Only headlines and summaries are stored.** Article bodies are not fetched (content collection TERMS_BLOCKED by default), so figures such as "5.27%" or "2.4 million" that appear only in the body are not captured.
4. **Market data is daily and lagged, not live.**
   - Global labels (Brent, USD/INR, S&P, Nikkei) are fetched at 12:40 and 21:10.
   - A label is **final** only after an unchanged re-observation 6 hours or more after the first fetch, so Monday's labels became final only tonight.
   - There is no intraday FX, crude or index capture (see `docs/LIVE_LTP_DEPTH_AUDIT.md`).
   - There is no US yield or KOSPI instrument from the vendor.
5. **Indian Express published nothing new today.** The feed is stale at the source:
   - `lastBuildDate` 29 Sep 07:36 IST;
   - newest item 28 Sep 19:27 IST;
   - 49 HTTP 200 responses, each with the same 200 items (4 distinct payload hashes; 0 new);
   - 4 transient connection errors.
6. **SEBI RSS:** 16 healthy polls and 0 new items; no new SEBI press releases were in the feed.

## Defect found (news track, not fixed here)

- **The dry-run collector overshoots `--until`.** `app/news/collector.py:352-378` checks the deadline only after a poll, then sleeps and polls again.
- **Observed:** started with `--until 2026-09-29T15:45+05:30`, the collector still polled at 15:46, 15:47 and 15:48, and was alive at 15:56. Each source makes one extra poll and can run up to one poll interval past the deadline.
- **Fix, if wanted:** check the deadline before each poll, and cap the sleep at the deadline.

## Reproduce

The search scripts are in the session scratchpad:

- `news_today.py`: topics published today;
- `news_earliest.py`: the first capture per topic;
- `news_topics.py`: all items since the 28 Sep close.

They read the dry-run JSONL files and query `news_article` read-only.
