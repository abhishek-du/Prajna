# News Subsystem Forensic Reconciliation Report

**File:** `audit/evidence/NEWS_CURRENT_STATE_FORENSIC.md`  
**Execution Date:** 2026-09-28T20:25:00+05:30  
**Auditor:** Independent Auditor & Verification Engineer  
**Audit Standard:** Strict Empirical Verification — Read-Only, Zero Code Changes, Evidence-First  
**Repository:** `/home/cis/windows/prajna`  
**HEAD Commit:** `0fa483948404c32b78523df885acbf1fe7fbcd61`  
**Machine-Readable Evidence:** [`audit/evidence/news_current_state.json`](file:///home/cis/windows/prajna/audit/evidence/news_current_state.json)

---

## Executive Summary

A forensic, read-only reconciliation was conducted across all layers of the Prajna News subsystem:
1. **Raw Ingestion & Schema:** Legacy Stage 1 Upstox feed (`news_article`, `news_instrument`, `canon_news`) vs Multi-Source news architecture (`news_poll`, `news_item`, `news_story`, etc. introduced in migrations 0013 and 0014).
2. **Multi-Source Collector:** The 8 implemented external source adapters (`NSE_ANNOUNCEMENTS`, `ET_STOCKS_RSS`, `BS_MARKETS_RSS`, `BL_MARKETS_RSS`, `MINT_MARKETS_RSS`, `CNBCTV18_NEWS_SITEMAP`, `INDIANEXPRESS_BUSINESS_RSS`, `SEBI_RSS`).
3. **Decisions:** Decision records in `app/news/decisions.py` and `app/features/news_features.py`.
4. **Stage 3 Feature Engine:** Feature registry (`features-v1`) vs proposed `mnews_*` point-in-time features (`news-features-v0-proposed`).
5. **Real-World Event Capture (2026-09-28):** Forensic tracing of the September 28 market crash and associated macro, regulatory, and corporate news.

### Key Forensic Verdict

1. **Every single news event listed by the user was captured by Prajna's running Multi-Source News dry-run collector** (including SAT/Hindenburg, UPI MDR in the Supreme Court, BSE self-listing panel, Turtlemint/PB Fintech IRDAI rout, Great Eastern Shipping/Nomura, Tonbo/Shah/Runwal IPOs, Bank strike postponement, and August IIP 8% data).
2. **However, zero rows of multi-source news exist in the PostgreSQL production database.** The multi-source collector is currently running exclusively in **DRY-RUN mode** (writing state and story clusters to filesystem evidence under `var/news/dryrun/`).
3. **The live production database contains only the Stage 1 Upstox feed** (18 articles ingested today, 197 total in `news_article`). This feed captured the broad index drop, crude oil surge, and PB Fintech/IRDAI, but missed the regulatory and legal developments.
4. **Stage 3 does not understand news content.** The approved Stage 3 registry (`features-v1`) contains only 3 news features (`news_count_24h`, `news_count_7d`, `news_hours_since_last`). The ingestion pipeline discards headline, body, and sentiment at the input boundary, calculating strictly integer counts and recency.
5. **`FEATURE-NEWS-V2` is explicitly `PENDING`.** It has never been approved. Multi-source news features (`mnews_*`) remain dry-run only.

---

## A. Current Facts Verified From Code

### 1. Decision Register State
- **File:** [`backend/app/news/decisions.py`](file:///home/cis/windows/prajna/backend/app/news/decisions.py#L5-L44)
  - `NEWS-SOURCES`: **`APPROVED`** (Amends constraint #1 to allow feasible external feeds; Moneycontrol, Zee Business, and Reuters remain `UNSUPPORTED`).
  - `NEWS-CONTENT`: **`APPROVED`** (Store metadata, URL, short description, and public body; AI enrichment via AWS Bedrock allowed as versioned enrichment).
  - `NEWS-PILOT`: **`APPROVED`** (NSE corporate announcements RSS).
  - `NEWS-KNOWABLE`: **`APPROVED`** (`knowable_at = discovered_at` for all new multi-source items; `published_at` is informational only).
  - `NEWS-CADENCE`: **`PROPOSED`** (Per-source intervals matching source constraints).
  - `NEWS-COMPLIANCE`: **`PENDING`** (Terms-of-use review not yet completed; only `DRY_RUN` permitted).
- **File:** [`backend/app/features/news_features.py`](file:///home/cis/windows/prajna/backend/app/features/news_features.py#L29-L37)
  - `FEATURE-NEWS-V2`: **`PENDING`** ("Add these point-in-time news features to the Stage 3 registry as a new version... until approved they are dry-run only").
- **File:** [`backend/tests/news/test_news_features.py:79`](file:///home/cis/windows/prajna/backend/tests/news/test_news_features.py#L79)
  - Enforced by automated test: `assert NF.DECISION["FEATURE-NEWS-V2"]["status"] == "PENDING"`.

### 2. Stage 3 Registry State
- **File:** [`backend/app/features/registry.py`](file:///home/cis/windows/prajna/backend/app/features/registry.py)
  - Total registered features: **65**
  - Registry version: **`features-v1`**
  - Registry SHA-256 hash: `9061d85b3696ab70e566d8257ecb13466930792a74f9b1d8308f232331e47188`
  - Registered `mnews_*` features: **0**
  - Registered news features: Exactly **3**
    1. `news_count_24h` (Group: `event`, Status: `IMPLEMENTED`, Inputs: `('news',)`, Lookback: 0)
    2. `news_count_7d` (Group: `event`, Status: `IMPLEMENTED`, Inputs: `('news',)`, Lookback: 0)
    3. `news_hours_since_last` (Group: `event`, Status: `IMPLEMENTED`, Inputs: `('news',)`, Lookback: 0)

### 3. Multi-Source Adapter Implementations
- **File:** [`backend/app/news/sources/__init__.py`](file:///home/cis/windows/prajna/backend/app/news/sources/__init__.py#L42-L98)
  - **Implemented Adapters (8):**
    1. `NSE_ANNOUNCEMENTS` (Kind: `RSS`, Status: `PILOT`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_NSE_ENABLED`, Priority: 1)
    2. `ET_STOCKS_RSS` (Kind: `RSS`, Status: `ADAPTER`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_ET_ENABLED`, Priority: 3)
    3. `BS_MARKETS_RSS` (Kind: `RSS`, Status: `ADAPTER`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_BS_ENABLED`, Priority: 3)
    4. `BL_MARKETS_RSS` (Kind: `RSS`, Status: `ADAPTER`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_BL_ENABLED`, Priority: 3)
    5. `MINT_MARKETS_RSS` (Kind: `RSS`, Status: `ADAPTER`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_MINT_ENABLED`, Priority: 3)
    6. `CNBCTV18_NEWS_SITEMAP` (Kind: `SITEMAP`, Status: `ADAPTER`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_CNBC_ENABLED`, Priority: 3)
    7. `INDIANEXPRESS_BUSINESS_RSS` (Kind: `RSS`, Status: `ADAPTER`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_IE_ENABLED`, Priority: 3)
    8. `SEBI_RSS` (Kind: `RSS`, Status: `ADAPTER`, Compliance: `PENDING`, Flag: `PRAJNA_NEWS_SEBI_ENABLED`, Priority: 1)
  - **Unsupported Feeds (3):**
    - `MONEYCONTROL` (Status: `UNSUPPORTED`, Compliance: `REJECTED`, HTTP 403 bot protection)
    - `ZEE_BUSINESS` (Status: `UNSUPPORTED`, Compliance: `REJECTED`, HTTP 403 bot protection)
    - `REUTERS` (Status: `UNSUPPORTED`, Compliance: `REJECTED`, robots.txt `Disallow: /`)

### 4. Production Configuration Flags
- **File:** [`backend/app/core/config.py:88-103`](file:///home/cis/windows/prajna/backend/app/core/config.py#L88-L103)
  - Every flag defaults to `False`:
    - `PRAJNA_NEWS_UPSTOX_ENABLED = False`
    - `PRAJNA_NEWS_NSE_ENABLED = False`
    - `PRAJNA_NEWS_ET_ENABLED = False`
    - `PRAJNA_NEWS_BS_ENABLED = False`
    - `PRAJNA_NEWS_BL_ENABLED = False`
    - `PRAJNA_NEWS_MINT_ENABLED = False`
    - `PRAJNA_NEWS_CNBC_ENABLED = False`
    - `PRAJNA_NEWS_IE_ENABLED = False`
    - `PRAJNA_NEWS_SEBI_ENABLED = False`
    - `PRAJNA_NEWS_AI_ENABLED = False`
    - `PRAJNA_NEWS_MULTI_SOURCE_ENABLED = False`
    - `PRAJNA_NEWS_LIVE_STREAM_ENABLED = False`
  - In `backend/.env`, **none** of these flags are present, confirming that all are strictly `False` at runtime.

---

## B. Current Facts Verified From Database

Direct SQL execution against the production PostgreSQL database (`prajna`) yields the following row counts:

| Table Name | Schema / Purpose | Verified Row Count | Notes |
|---|---|---|---|
| `news_article` | Stage 1 Raw Articles (Upstox) | **197** | 18 rows ingested today (2026-09-28) |
| `news_instrument` | Stage 1 Vendor Instrument Links | **604** | Upstox stock associations |
| `canon_news` | Stage 2 Point-in-Time News View | **604** | Projected from `news_article` + `news_instrument` |
| `news_poll` | Multi-Source Polling Log | **0** | Empty (0 production polls written) |
| `news_item` | Multi-Source Raw Items | **0** | Empty (0 multi-source items stored) |
| `news_item_observation` | Multi-Source Item Observations | **0** | Empty |
| `news_classification` | Multi-Source Item Categories | **0** | Empty |
| `news_entity_link` | Multi-Source Instrument Mappings | **0** | Empty |
| `news_story` | Multi-Source Clustered Stories | **0** | Empty |
| `news_story_member` | Multi-Source Story Members | **0** | Empty |
| `news_entity_mention` | Multi-Source Entity Mentions | **0** | Empty |
| `news_assessment` | Multi-Source Impact & Direction | **0** | Empty |
| `news_content` | Multi-Source Scraped Bodies | **0** | Empty |
| `news_ai_enrichment` | Multi-Source Bedrock AI Summaries | **0** | Empty |
| `news_audit` | Subsystem Execution Audits | **2** | 2 `REFUSED` audit records (NSE write tests) |
| `feature_value` | Stage 3 Feature Store | **0** | Empty (Stage 3 locked) |
| `ingest_run` (`features.%`) | Stage 3 Feature Ingestion Runs | **0** | Empty |
| `stage3_event` | Stage 3 Execution Audit Events | **4** | 4 `REFUSED` audit records |

---

## C. Current Git / Commit Evidence

Tracking of `FEATURE-NEWS-V2` and multi-source news in the git history shows:

1. **Commit `747ab2e`:** `docs: multi-source news audit, source feasibility and proposed design`  
   Initial architecture document outlining external feasibility and proposing decision `FEATURE-NEWS-V2`.
2. **Commit `144c9f3`:** `news: multi-source news pilot, NSE corporate announcements (DRY_RUN; SHADOW locked)`  
   Implementation of the pilot NSE announcements collector in dry-run mode.
3. **Commit `bba29b0`:** `news: proposed point-in-time news features (dry-run only, decision FEATURE-NEWS-V2 pending)`  
   Author: `cis <ad0652222@gmail.com>` | Date: `Mon Sep 28 17:04:55 2026 +0530`  
   Created [`backend/app/features/news_features.py`](file:///home/cis/windows/prajna/backend/app/features/news_features.py) with 22 proposed `mnews_*` indicators and explicitly set `DECISION["FEATURE-NEWS-V2"]["status"] = "PENDING"`.
4. **Commit `45cb3ac`:** `news: per-source acceptance gate, human mapping review, restart-safe politeness, status report`  
   Added per-source acceptance testing and documented remaining blockers in `docs/NEWS_SUBSYSTEM_STATUS.md`.
5. **Commit `1ee5e54`:** `docs: news status - migration 0014 applied to production (backup verified), API live and empty while locked`  
   Applied migration 0014 schema to `prajna` production DB after taking backup `prajna_20260928T1712_news_pre_0014.dump`. Recorded that tables remain empty while locked.
6. **Subsequent Commits to HEAD (`580f587`, `c42cb0d`, `0fa4839`):**  
   Touched Stage 3 FII/DII staleness, repeatable read snapshots, and adversarial PIT tests. **None modified `FEATURE-NEWS-V2`**.

---

## D. Dry-Run Evidence

An active background collector daemon is currently executing:
- **PID:** `2312405`
- **Command:**
  ```bash
  .venv/bin/python .venv/bin/prajna news dry-run \
    --source NSE_ANNOUNCEMENTS,ET_STOCKS_RSS,BS_MARKETS_RSS,BL_MARKETS_RSS,MINT_MARKETS_RSS,CNBCTV18_NEWS_SITEMAP,INDIANEXPRESS_BUSINESS_RSS,SEBI_RSS \
    --until 2026-09-29T15:45+05:30
  ```
- **Evidence Storage Directory:** [`backend/var/news/dryrun/`](file:///home/cis/windows/prajna/backend/var/news/dryrun/)
- **Live Statistics Across Feeds (as of 20:20 IST):**
  - `NSE_ANNOUNCEMENTS`: 21 polls, **2,713 items seen**
  - `CNBCTV18_NEWS_SITEMAP`: 20 polls, **331 items seen**
  - `INDIANEXPRESS_BUSINESS_RSS`: 16 polls, **204 items seen**
  - `BL_MARKETS_RSS`: 8 polls, **75 items seen**
  - `BS_MARKETS_RSS`: 19 polls, **58 items seen**
  - `ET_STOCKS_RSS`: 27 polls, **56 items seen**
  - `SEBI_RSS`: 6 polls, **50 items seen**
  - `MINT_MARKETS_RSS`: 21 polls, **45 items seen**
  - `stories.json`: **692 story clusters**, **1,203 member articles**

### Tracing Today's Events in Dry-Run Evidence
A forensic string search across `backend/var/news/dryrun/*/state.json` proved that **every single news story inquired about by the user was captured by the multi-source dry-run**:

| Event | Source | Title in Dry-Run Evidence | Published Time | Discovered Time (knowable_at) |
|---|---|---|---|---|
| **SEBI Self-Listing Panel (BSE)** | `CNBCTV18` / `Mint` | *"SEBI may form panel to examine self-listing rules for stock exchanges: Sources"* / *"BSE stock falls 2.3% as SEBI mulls self-listing rules revamp"* | 07:58 UTC / 09:01 UTC | 10:29:29 UTC |
| **SAT / Hindenburg FPI Appeals** | `BS_MARKETS_RSS` | *"SAT disposes of appeals by five FPIs named in Hindenburg report"* | 12:57:46 UTC | 13:17:38 UTC |
| **Supreme Court UPI MDR Notice** | `CNBCTV18` | *"UPI MDR case: Supreme Court refuses interim stay on levy, asks Centre to explain rationale"* | 02:55:30 UTC | 10:29:29 UTC |
| **PB Fintech / Turtlemint Rout** | `ET_STOCKS_RSS` | *"Trouble continues: Turtlemint, PB Fintech, other insurance stocks drop up to 38% in 3 days. What are analysts saying?"* | 06:33:14 UTC | 10:29:29 UTC |
| **PB Fintech F&O Open Interest** | `ET_STOCKS_RSS` | *"PB Fintech among 4 F&O stocks with a sharp rise in futures open interest"* | 06:32:54 UTC | 10:29:29 UTC |
| **Great Eastern Shipping / Nomura** | `ET_STOCKS_RSS` | *"Great Eastern Shipping rises 3% as Nomura retains Buy; projects up to 28%. Here's why"* | 09:11:01 UTC | 10:29:29 UTC |
| **Tonbo Imaging IPO SEBI Nod** | `BS_MARKETS_RSS` | *"Pioneer Fil-Med, Tonbo Imaging among 3 firms to get Sebi nod for IPOs"* | 07:59:25 UTC | 10:29:29 UTC |
| **Shah Investor's Home IPO** | `BS_MARKETS_RSS` | *"Shah Investor's Home IPO: Brokerages divided on growth, valuations"* | 07:58:33 UTC | 10:29:29 UTC |
| **Runwal Enterprises IPO** | `MINT_MARKETS_RSS` | *"IPO GMP: Moneyview, A One Steels, Orient Cable, German Green, Ace Vector, Runwal..."* | 03:41:00 UTC | 10:29:29 UTC |
| **Bank Strike Deferred** | `BS_MARKETS_RSS` / `CNBCTV18` | *"Central Bank of India announces deferment of bank strike"* / *"Bank strike postponed, UPI MDR in Supreme Court..."* | 09:46 UTC / 05:23 UTC | 10:29:29 UTC |
| **August IIP / Industrial Output 8%** | `BS_MARKETS_RSS` / `Indian Express` | *"IIP growth rebounds to 8% in Aug-26, mining sector contracts"* / *"Eye on festive demand as manufacturing drives August industrial output 8% higher"* | 11:20 UTC / 12:36 UTC | 11:29:44 UTC / 12:41:14 UTC |
| **Market Crash / PSU Banks** | `BS_MARKETS_RSS` | *"Sensex, Nifty end sharply lower; PSU Bank shares bear brunt"* | 10:34:01 UTC | 10:38:09 UTC |

---

## E. Production State

- **Multi-Source Production Writes:** **0 rows**.
- **Lock Enforcement:** Verified via [`backend/app/news/locks.py`](file:///home/cis/windows/prajna/backend/app/news/locks.py). Writing requires:
  1. Per-source flag `PRAJNA_NEWS_<SRC>_ENABLED = true`
  2. Subsystem kill switch file (`var/run/news.kill`) absent
  3. Source status `PILOT` or `ADAPTER`
  4. Terms compliance `APPROVED` (decision `NEWS-COMPLIANCE`)
  5. Source acceptance passing (`prajna acceptance news`)
  6. Stage 2 status `PASS`
  7. Valid write token supplied via `PRAJNA_SUPPLIED_TOKEN`
- **Audit Proof of Rejection:** Two unauthorized test attempts to write `NSE_ANNOUNCEMENTS` were recorded as `REFUSED` in `news_audit` (IDs 1 and 2), confirming that the lock halts write attempts and audits the refusal.

---

## F. FEATURE-NEWS-V2 Decision

- **Status:** **`PENDING`**
- **Location:** Defined in [`backend/app/features/news_features.py:30-37`](file:///home/cis/windows/prajna/backend/app/features/news_features.py#L30-L37)
- **Content:**
  ```python
  DECISION = {
      "FEATURE-NEWS-V2": {
          "status": "PENDING",
          "decision": "Add these point-in-time news features to the Stage 3 registry as a new "
          "version (windows 1h/4h/24h/3d as listed); until approved they are dry-run only",
          "ref": "news programme phase 11 (2026-09-28)",
      }
  }
  ```
- **Consequence:** Proposed features `mnews_*` (22 indicators) are quarantined in dry-run mode and cannot be computed into the approved Stage 3 registry.

---

## G. What Stage 3 Currently Consumes

The live production feature pipeline is traced end-to-end:

```
[Upstox REST API]
       │
       ▼
[news_article & news_instrument] (Raw Ingestion)
       │
       ▼
[canon_news] (Stage 2 Point-in-Time SQL View)
       │
       ▼
[app.canon.pit.news(as_of, instrument_key)] (Stage 2 Accessor)
       │
       ▼
[app.features.inputs.instrument_inputs()] (Feature Input Extractor)
       │
       │  ===> Discards headline, body, publisher, and vendor_payload!
       │  ===> Extracts ONLY: [n["published_at"] for n in news]
       │
       ▼
[app.features.compute.event.news_count()] & [news_hours_since_last()]
       │
       │  ===> Performs simple timestamp math: sum(1 for t in published if cutoff <= t < as_of)
       │
       ▼
[Stage 3 Registry: features-v1]
       │  - news_count_24h (integer count)
       │  - news_count_7d (integer count)
       │  - news_hours_since_last (float hours)
       │
       ▼
[app.features.engine.persist()]
       │
       X  LOCKED (PRAJNA_STAGE3_ENABLED=false; 0 rows written in feature_value)
```

### Forensic Proof:
1. In [`backend/app/features/inputs.py:117`](file:///home/cis/windows/prajna/backend/app/features/inputs.py#L117):
   ```python
   news_published=[n["published_at"] for n in news if n.get("published_at")]
   ```
   Only `published_at` is forwarded to the feature computation layer.
2. In [`backend/app/features/compute/event.py:15-35`](file:///home/cis/windows/prajna/backend/app/features/compute/event.py#L15-L35):
   ```python
   def news_count(published: list[_dt.datetime], as_of: _dt.datetime, window_hours: float) -> Result:
       cutoff = as_of - _dt.timedelta(hours=window_hours)
       return ok(sum(1 for t in published if cutoff <= t < as_of))

   def news_hours_since_last(published: list[_dt.datetime], as_of: _dt.datetime) -> Result:
       visible = [t for t in published if t < as_of]
       if not visible:
           return ok(None)
       return ok(round((as_of - max(visible)).total_seconds() / 3600.0, 2))
   ```
   The engine performs pure timestamp arithmetic. It possesses **zero textual parsing, zero sentiment logic, and zero semantic classification**.

---

## H. What Is Still Missing

To elevate Multi-Source News from dry-run evidence to production trading integration, the following blockers remain:

1. **Terms-of-Use Compliance Review (`NEWS-COMPLIANCE`):** Still `PENDING`. Operator must review per-source compliance.
2. **Human Entity Mapping Review:** Operator must sample and validate entity mappings via `prajna news review-sample --source <K>`.
3. **Full Market Session Evidence:** The dry-run collector must finish its measurement period ending `2026-09-29 15:45 IST`.
4. **Source Acceptance Gate:** `prajna acceptance news` currently reports `NEWS: NOT PASSED` (all sources `PENDING`).
5. **Operator Decision `FEATURE-NEWS-V2`:** Required before `mnews_*` indicators can join the Stage 3 registry as a new version.
6. **Per-Source Production Flags:** Setting `PRAJNA_NEWS_<SRC>_ENABLED = true` in `.env`.
7. **Stage 3 Production Unlock:** Fixing `BUG-STAGE3-PERSIST-PARAM-LIMIT` and setting `PRAJNA_STAGE3_ENABLED = true`.

---

## I. Conflicts With Previous Audits

- **Status of `FEATURE-NEWS-V2`:**
  - Previous Audit Claim: `FEATURE-NEWS-V2` is `PENDING`.
  - Current Forensic Finding: `FEATURE-NEWS-V2` is **`PENDING`**.
  - **Verdict:** **NO CONFLICT**. The status has been verified at current HEAD (`0fa4839`) across code, tests, and documentation.
- **Multi-Source News Data Presence:**
  - Previous Audit Claim: Multi-source news has 0 rows in production.
  - Current Forensic Finding: 0 rows in production DB; ~3,500 items and 692 stories exist strictly in filesystem dry-run evidence (`var/news/dryrun/`).
  - **Verdict:** **NO CONFLICT**. Completely consistent.

---

## J. Exact Evidence For Every Conclusion

| Conclusion | File / Query / Command | Exact Line / Reference / Output |
|---|---|---|
| `FEATURE-NEWS-V2` is PENDING | [`app/features/news_features.py`](file:///home/cis/windows/prajna/backend/app/features/news_features.py#L31) | `"status": "PENDING"` |
| Automated test enforces PENDING | [`tests/news/test_news_features.py`](file:///home/cis/windows/prajna/backend/tests/news/test_news_features.py#L79) | `assert NF.DECISION["FEATURE-NEWS-V2"]["status"] == "PENDING"` |
| Multi-source DB tables empty | `SELECT count(*) FROM news_item, news_story...` | 0 rows across all 11 tables in DB `prajna` |
| Upstox raw articles present | `SELECT count(*) FROM news_article` | 197 rows (18 from 2026-09-28) |
| Stage 3 registry news count | [`app/features/registry.py`](file:///home/cis/windows/prajna/backend/app/features/registry.py#L120-L135) | Exactly 3 features (`news_count_24h`, `news_count_7d`, `news_hours_since_last`) |
| Stage 3 ignores article text | [`app/features/inputs.py`](file:///home/cis/windows/prajna/backend/app/features/inputs.py#L117) | `news_published=[n["published_at"] for n in news if n.get("published_at")]` |
| Dry-run collector active | `ps -fp 2312405` | PID 2312405 running `prajna news dry-run --until 2026-09-29T15:45+05:30` |
| User news captured in dry-run | `var/news/dryrun/*/state.json` | 12/12 specific user stories matched with timestamps in dry-run files |
| Production flags disabled | [`app/core/config.py`](file:///home/cis/windows/prajna/backend/app/core/config.py#L88-L103) & `backend/.env` | All `PRAJNA_NEWS_*_ENABLED = False` by default; 0 in `.env` |
| News acceptance gate failing | `.venv/bin/prajna acceptance news` | Exit 1 (`NEWS: NOT PASSED`) |

