# News source matrix

**Measured:** one full trading session, **2026-09-29** (00:00–15:45 IST), from the DRY_RUN evidence files `backend/var/news/dryrun/<SRC>/events_2026-09-29.jsonl`. Acceptance was rerun at 16:34 IST (HEAD `6af7952`).

**Latency** means **detection latency**: Prajna's first observation − the publisher's stated time. It is measured on live items only; backlog is excluded. **It is reported, never claimed as "first"**: a publisher's own time may be earlier or later than when the item actually appeared in its feed (see ET).

## Summary matrix

| Source | Type | Market coverage | Latency p50 / p95 | Timestamp | URL | Body | Reliability (09-29) | Duplicate risk | Compliance | Production status |
|---|---|---|---|---|---|---|---|---|---|---|
| NSE_ANNOUNCEMENTS | official exchange RSS | every listed company's filings (results, board meetings, fundraising, M&A, management, credit ratings) | 214 s / 568 s | date+time, **no zone** (exchange local, parsed as IST) | stable attachment URL | no (PDF attachment; not fetched) | 115 polls, **9.6% failed** (8 truncated 200s, 3 connect errors) | low per filing; **titles = company name** (213 same-title repeats are separate filings) | APPROVED | **PRODUCTION_PENDING_REVIEW** |
| SEBI_RSS | official regulator RSS | circulars, orders, press releases | NOT_MEASURABLE (date only) | **date only**, +0530 | stable | no | 16 polls, 0% failed | low | APPROVED | **PRODUCTION_PENDING_REVIEW** |
| ET_STOCKS_RSS | publisher RSS | markets, stocks, IPOs, broker calls, FII flows | 3,566 s / 10,508 s overall. **Articles 1,251 s / 2,050 s; "Live Updates" pages 5,840 s / 11,210 s** | RFC 822, +0530 | stable article URL | summary only | 253 polls, 0.8% failed | medium: live-blog pages repeat per stock | APPROVED | **PRODUCTION_PENDING_REVIEW** |
| BS_MARKETS_RSS | publisher RSS | markets, macro, global cues, IPOs | 447 s / 1,128 s | RFC 822, +0530 | stable | summary only | 170 polls, 0.6% failed | low (1 same-title repeat) | APPROVED | **PRODUCTION_PENDING_REVIEW** |
| BL_MARKETS_RSS | publisher RSS | markets, commodities, rupee, RBI | 2,039 s / 3,652 s (bounded by its **60-min `<ttl>`**) | RFC 822, +0530 | stable | summary only | 16 polls (hourly by ttl), 0% failed | low | APPROVED | **PRODUCTION_PENDING_REVIEW** |
| MINT_MARKETS_RSS | publisher RSS | markets, global, yields, crude | 233 s / 684 s | RFC 822, +0530 (98.1% have a time) | stable | summary only | 168 polls, 0.6% failed | low; **148 edits** of 53 items (frequent re-publication) | APPROVED | **PRODUCTION_PENDING_REVIEW** |
| CNBCTV18_NEWS_SITEMAP | publisher news sitemap | broadest: markets, macro, policy, geopolitics, courts, companies | 497 s / 1,023 s | ISO 8601, +05:30 | stable | headline only (sitemap) | 116 polls, 0% failed | low | APPROVED | **PRODUCTION_PENDING_REVIEW** |
| INDIANEXPRESS_BUSINESS_RSS | publisher RSS | business, policy | not measured on 09-29 (0 new items) | RFC 822, **+0000** (UTC, converted) | stable | summary only | 170 polls, 2.4% failed; **feed stale at source** | low | APPROVED | **NOT_RELIABLE** (for this day) → PENDING_REVIEW when it publishes again |
| MONEYCONTROL | — | — | — | — | — | — | HTTP 403 (robots.txt and RSS) | — | REJECTED | **NOT_SUPPORTED** |
| ZEE_BUSINESS | — | — | — | — | — | — | HTTP 403 | — | REJECTED | **NOT_SUPPORTED** |
| REUTERS | — | — | — | — | — | — | robots `Disallow: /` | — | REJECTED | **NOT_SUPPORTED** (licence only) |
| Upstox `/v2/news` | vendor API | **stock-tagged only** (~27 articles/day) | not measured here (30-min polling) | vendor time | vendor URL | no | production (cron) | handled by `uq_news_observation` | vendor contract | **SUPPORTED_PRODUCTION** (path 1) |

**Status meanings:**

- **SUPPORTED_PRODUCTION:** writing to production now.
- **PRODUCTION_PENDING_REVIEW:** terms approved and EVIDENCE / HEALTH / POLITENESS PASS; waits only for the human mapping review, then SHADOW → canary.
- **NOT_RELIABLE:** it did not deliver on the measured day.
- **NOT_SUPPORTED:** it cannot be collected without bypassing access controls or a licence.

**No source is DRY_RUN_ONLY by constraint:** all 8 adapters have terms approved for headline, summary, URL and timestamps.

## Per-source details (2026-09-29)

| Source | URL / API | Auth | Rate limits observed | Polls | Fail % | New items | Edits observed | With publish time | Median gap (s) | `<ttl>` | Conditional GET |
|---|---|---|---|---|---|---|---|---|---|---|---|
| NSE | `nsearchives.nseindia.com/content/RSS/Online_announcements.xml` | none | none (no 429) | 115 | 9.6 | 987 | 0 | 100% | 317 | 5 min | ETag + Last-Modified |
| SEBI | `www.sebi.gov.in/sebirss.xml` | none | none | 16 | 0 | 0 | 0 | 0% (date only) | 3,603 | 60 min | — |
| ET | ET markets/stocks RSS | none | none | 253 | 0.8 | 91 | 35 | 100% | 125 | — | yes (304s) |
| BS | BS markets RSS | none | none | 170 | 0.6 | 74 | 43 | 100% | 192 | — | yes |
| BL | BL markets RSS | none | none | 16 | 0 | 31 | 22 | 100% | 3,864 | 60 min | Last-Modified |
| Mint | Mint markets RSS | none | none | 168 | 0.6 | 53 | 148 | 98.1% | 192 | — | yes |
| CNBC-TV18 | Google-News sitemap | none | none | 116 | 0 | 129 | 62 | 100% | 327 | — | yes |
| IE | IE business RSS | none | none | 170 | 2.4 | 0 | 0 | — | 191 | — | yes |

The exact feed URLs are in `backend/app/news/sources/__init__.py`.

**Common properties:**

- **Historical availability:** none for any feed. Each is a rolling window: NSE carries the current day; the publishers carry their last 20–200 items. **A missed window cannot be back-filled**, so collector downtime is a permanent gap. This is why monitoring and the MISSING state matter.
- **Edit detection:** a changed title, summary or publish time for a known ID → an observation. It is never an overwrite.
- **Robots / terms:** all 8 permit feed access. Terms were approved by the user on 2026-09-29 for headline, summary, URL and timestamps. **Bodies stay TERMS_BLOCKED** (`body_allowed=False`).

## Findings behind the numbers

1. **ET latency (J5).**
   - 50 of 91 live items are "<Company> Share Price Live Updates" pages. Their `pubDate` is when the live blog was created (08:00–09:05), but they enter the feed hours later.
   - Ordinary ET articles: p50 1,251 s, p95 2,050 s, with polling every ~125 s. **The remaining ~20-minute lag is the feed's own.**
2. **NSE truncated responses (J4).** 8 HTTP 200 responses were cut short (the XML ends mid-document; sizes grew from 112 KB to 375 KB through the day). Each is rejected whole as MALFORMED, and the next poll recovers.
3. **BusinessLine's hourly `<ttl>`** bounds its latency at up to an hour. That is honoured (politeness), and since `6040d85` the gate judges coverage against it.
4. **Indian Express (J6):** 49 × HTTP 200 with the same 200 items; newest 28 Sep 19:27. This is a source-side staleness case: the SOURCE_STALE state is to be built.
5. **SEBI:** 0 new press releases on the day. Its date-only timestamps make latency NOT_MEASURABLE; `knowable_at` is Prajna's first observation.

## Reproduce

- `prajna news report --source <SRC> --day 2026-09-29` (per-source summary and latency)
- `prajna acceptance news --run-tests`
- The session scratchpad scripts `source_metrics.py` (this table) and `topics.py` (the topic coverage in the investigation doc) read the same JSONL files.
