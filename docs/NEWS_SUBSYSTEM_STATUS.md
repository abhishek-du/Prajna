# Multi-source news subsystem: status (2026-09-28, evening)

**Not production-ready.**

The code, tests and locks are in place, and a dry-run is collecting evidence. Production writes stay **locked** for every source until:
- your terms review of each source;
- a full market session of dry-run evidence (the first is 2026-09-29);
- a human review of each source's mapping sample;
- the per-source acceptance gate, `prajna acceptance news`;
- explicit per-source enablement.

Related documents:
- `docs/NEWS_SUBSYSTEM_INVENTORY.md`: what existed before this work;
- `docs/NEWS_MULTI_SOURCE_DESIGN.md`: the design and decisions;
- `docs/NEWS_MULTI_SOURCE_ACCEPTANCE.md`: the generated gate report.

## A. What existed before

- **Upstox news** runs in production as Stage 1 ingestion (criterion N). Its raw `knowable_at` is the publication time, but every point-in-time reader was already bounded by the fetch time.
- The **NSE pilot** and five media adapters ran in dry-run only.
- There was **one global crawler flag**.
- There was **no story grouping**, **no non-company entities**, **no assessment**, **no content fetch or AI**, **no Stage 2 multi-source layer**, **no API** beyond `/v1/news`, and **no gate**. See the inventory, gaps G1–G12.

## B. What was implemented (commits after `c557e68`)

| Phase | Component | Where | Commit |
|---|---|---|---|
| 1 | Inventory | `docs/NEWS_SUBSYSTEM_INVENTORY.md` | e84fbb9 |
| 17 | **One write flag per source** (all false, no global switch). A write needs terms APPROVED + a source acceptance PASS + Stage 2 PASS + a token; PRODUCTION also needs `PRAJNA_NEWS_MULTI_SOURCE_ENABLED` | `app/news/locks.py`, `app/core/config.py` | 7dbaece |
| 2, 3, 6, 8, 9 | Schema 0014: normalisation fields; append-only `news_story`, `news_story_member`, `news_entity_mention`, `news_assessment`, `news_content`, `news_ai_enrichment`, each with its own `knowable_at` | `migrations/0014`, `db/models/news.py` | 1ef70a9 |
| 4 | Non-company entities (index, sector, commodity, currency, yield, geopolitics, regulator, central bank, government, macro, exchange, court). Reviewed aliases that fail closed ("SBI Life" ≠ SBI; "L&T Finance" ≠ L&T; "M&M Financial" ≠ M&M) | `app/news/entities.py` | 71fe47a |
| 3 | Story grouping story-v1: SAME_URL, SAME_TITLE, or SIMILAR (title similarity + time + a shared company or entity/category), with evidence. Point in time. Exact matches only for regulator and exchange documents | `app/news/stories.py` | 71fe47a |
| 5, 6 | Assessment assess-v1: scope, potential impact, direction and breaking from explicit rules and words. Never a prediction; breaking is observable only | `app/news/assess.py` | 71fe47a |
| 8 | Content retrieval: TERMS_BLOCKED (no request) unless terms are APPROVED and bodies allowed; robots fail-closed; HTTP_BLOCKED / PAYWALL / ERROR are statuses, never fatal | `app/news/content.py` | 14725c2 |
| 9 | AI enrichment (Bedrock), off by default; closed-schema validation; model, prompt, input hash and time recorded; never a fact | `app/news/ai.py` | 14725c2 |
| 7, 14 | Latency p50/p90/p95/p99/max (discovery, processing, end-to-end; market vs off hours; backlog excluded); health (STALE, DEGRADED, RATE_LIMITED, BLOCKED) | `app/news/report.py` | 14725c2 |
| 10 | Stage 2 point-in-time layer (additive): items and enrichments by their own `knowable_at`; PRODUCTION rows only; Upstox projected at first fetch | `app/canon/news_pit.py` | 0c38fe0 |
| 11 | 22 proposed news features `mnews_*`, dry-run only (decision FEATURE-NEWS-V2 PENDING), MISSING_INPUT without proven coverage | `app/features/news_features.py` | bba29b0 |
| 12 | Read API: `/v1/news/articles`, `/v1/news/breaking`, `/v1/news/{id}`, `/v1/stories[/{id}]`, `/v1/instruments/{key}/news`, `/v1/news/sources`, `/v1/news/latency`, `/v1/news/freshness`, `/v1/news/stats` | `app/readapi` | 0df42c5 |
| 16 | Per-source acceptance gate + human mapping review + restart-safe politeness | `app/acceptance/news.py` | (this commit) |

## C. What was tested

`tests/news`: 149 tests. They cover:
- **Parsing and normalisation:** malformed and hostile XML, and date-only feeds.
- **Timing:** backlog, `knowable_at = first observation`, and the adversarial case (published 10:00, seen 10:07: invisible at 10:03 and 10:07, visible at 10:08).
- **Point in time:** edits visible only after they were observed; story members that join later invisible earlier; SHADOW never visible; Upstox visible at first fetch only.
- **Entity mapping and aliases,** including every measured false positive.
- **Story grouping and assessment.**
- **Source behaviour:** 304/403/401/429/5xx handling, backoff, the ttl floor, restart politeness, the kill switch, database-down isolation, crash and restart without re-discovery.
- **Locks:** each write condition refuses on its own; one source's flag never enables another; all flags default false.
- **Content:** terms, robots, paywall and HTTP blocks.
- **AI:** OK, INVALID, ERROR and TIMEOUT.
- **Features:** calculations, and MISSING_INPUT propagation.
- **API:** read-only (405), point in time (404), and source facts kept apart from derived fields and AI.
- **The gate itself.**

The full backend suite also passes.

## D. What was measured (2026-09-28, dry-run, evening only)

| Measure | Result |
|---|---|
| Items seen across 8 sources | ~2,000, mostly **backlog** from the first read of each feed |
| Live discoveries | a handful. Examples: ET p50 ≈ 20 min (n = 2); NSE p50 4.7 min (n = 51, about one poll interval) |
| NSE mapping | 74.4%, strict |
| Media headline mapping | precision-first. Measured false positives were fixed: Kalpataru Projects → Kalpataru Ltd; Kotak ETFs; Sundaram Home → Sundaram Finance; M&M Financial → M&M |
| Story grouping on 716 media items | 12 multi-article groups, 5 multi-publisher. One false grouping of SEBI orders against different parties is fixed |
| Politeness | restarts re-polled early (ET after 16.9 s). **Fixed** |

**Market-session latency is not yet measured.** The collector runs until 2026-09-29 15:45 IST.

## E. Source status

| SOURCE | IMPLEMENTED | DRY-RUN | LATENCY MEASURED | TERMS APPROVED | DB WRITE | PRODUCTION |
|---|---|---|---|---|---|---|
| Upstox (Stage 1) | yes (existing) | n/a: live in Stage 1 | publication → fetch median ≈ 26 h (the schedule) | yes (vendor) | yes (Stage 1 tables) | Stage 1 yes. Its projection into the new layer is off (`PRAJNA_NEWS_UPSTOX_ENABLED=false`) |
| NSE announcements | yes | running | partial (evening; n = 51) | **PENDING** | LOCKED | no |
| Economic Times | yes | running | partial (n = 2) | **PENDING** | LOCKED | no |
| Business Standard | yes | running | partial | **PENDING** | LOCKED | no |
| BusinessLine | yes | running (ttl 60 min) | not yet | **PENDING** | LOCKED | no |
| Livemint | yes | running | not yet | **PENDING** | LOCKED | no |
| CNBC-TV18 | yes | running | partial | **PENDING** | LOCKED | no |
| Indian Express | yes | running | not yet | **PENDING** | LOCKED | no |
| SEBI | yes | running (hourly) | not measurable (date only) | **PENDING** | LOCKED | no |
| Moneycontrol / Zee Business | UNSUPPORTED (HTTP 403) | — | — | — | — | — |
| Reuters | UNSUPPORTED (robots `Disallow: /`) | — | — | — | — | — |

## F–J. Latency, mapping, grouping, content, AI

- **Latency:** see D. The report command is `prajna news report --source <K> --day 2026-09-29`.
- **Mapping accuracy:** there is no human-judged false-positive rate yet. `prajna news review-sample --source <K>` writes a sample for you to judge, and the gate requires ≤ 2%.
- **Story grouping:** there is no human-judged accuracy yet. Evidence is stored for every grouping.
- **Content:** `TERMS_BLOCKED` for every source; no body has been fetched.
- **AI:** off. `boto3` is not installed, and no model id or credentials are configured.

## K–N. Integration

- **Stage 2:** `app/canon/news_pit.py` is additive. The Stage 2 gate and its criteria are unchanged.
- **Stage 3:** the `mnews_*` features are dry-run only. The approved Stage 3 registry is unchanged, so Stage 3 production readiness is unaffected.
- **API:** `/v1/news` (Upstox) is unchanged; the new endpoints are listed in B.
- **Frontend requirements:** every item separates `source_fact` / `observation` / `derived` / `ai_enrichment`. A stock page uses `/v1/instruments/{key}/news` and `/v1/stories?instrument_key=`, and the monitors use `/v1/news/sources|latency|freshness`. `frontend/` and `backend/app/api/` are untouched; the latter reads `news_article` directly and does not use `as_of`.

## O. Production locks (per source)

A database write needs every one of:
- the source's own flag `PRAJNA_NEWS_<SRC>_ENABLED`;
- the kill switch off;
- the source supported;
- terms APPROVED;
- the source PASSING `prajna acceptance news`;
- Stage 2 PASS;
- a write token.

Visibility to Stage 2/3/API additionally needs `PRAJNA_NEWS_MULTI_SOURCE_ENABLED` (PRODUCTION mode). Every refusal is recorded in `news_audit`.

## P. Remaining blockers

1. Your **terms review** for each source (NEWS-COMPLIANCE).
2. A **full market session** of dry-run evidence: 2026-09-29.
3. A **human mapping review** for each source (`review-sample`).
4. **Migration 0014 on production** (backup first). Until it is applied, the new `/v1/news/*` endpoints cannot run against production.
5. **Decision FEATURE-NEWS-V2** before any news feature enters Stage 3.
6. **AI:** add `boto3`, then set the model id and AWS credentials via the environment (from the V1 `.env`, never printed).
7. **A runtime** for a permanent collector (systemd or supervised); there is no cron entry.

## Q. Dry-run commands

```bash
cd backend
.venv/bin/prajna news sources                    # registry, terms, flags
.venv/bin/prajna news health                     # per-source health
.venv/bin/prajna news dry-run --source MEDIA --until 2026-09-29T15:45+05:30
.venv/bin/prajna news report --source ET_STOCKS_RSS --day 2026-09-29
.venv/bin/prajna news review-sample --source ET_STOCKS_RSS    # then judge var/news/review/*.json
.venv/bin/prajna acceptance news --run-tests
.venv/bin/prajna news kill on --reason "..."     # stop all polling
```

## R. Production enablement (per source; NOT done)

1. Approve the source's terms (`compliance="APPROVED"` in `app/news/sources/__init__.py`, recorded in NEWS-COMPLIANCE).
2. Run `prajna acceptance news --run-tests` and confirm the source shows PASS.
3. Enable SHADOW writes for that source only:
   ```bash
   export PRAJNA_SUPPLIED_TOKEN="$(grep '^PRAJNA_WRITE_TOKEN=' .env | cut -d= -f2-)"
   PRAJNA_NEWS_ET_ENABLED=true .venv/bin/prajna news poll --source ET_STOCKS_RSS --commit
   ```
4. For visibility to Stage 2/3/API, add `PRAJNA_NEWS_MULTI_SOURCE_ENABLED=true`. PRODUCTION mode writes through `app.news.store.poll_shadow(mode="PRODUCTION")`; a scheduled collector for it is not built yet (blocker 7).

## COMPONENT status

| COMPONENT | STATUS | BLOCKER | NEXT ACTION |
|---|---|---|---|
| Source adapters (8) | implemented, dry-run running | terms review | you review terms per source |
| Politeness / rate limits | implemented, restart-safe | — | re-check the POLITENESS criterion on 2026-09-29 |
| Normalisation (0014) | implemented and tested | migration not on production | back up, then apply 0014 |
| Story grouping | implemented and tested | no human accuracy check | review groupings from the 09-29 evidence |
| Entity mapping + aliases | implemented, fail-closed | no human false-positive rate | `review-sample` for each source |
| Assessment / breaking | implemented (rules) | no validation against outcomes | review on 09-29 evidence |
| Latency | implemented | no full session yet | report after 15:45 on 09-29 |
| Content fetch | implemented, blocked by terms | terms + `body_allowed` | per-source decision |
| AI enrichment | implemented, off | boto3, model, credentials | your go-ahead |
| Stage 2 point-in-time layer | implemented and tested | 0014 on production; no PRODUCTION rows | after enablement |
| Stage 3 news features | proposed, dry-run | FEATURE-NEWS-V2 | your decision |
| Read API | implemented and tested | 0014 on production | back up, then apply 0014 |
| Acceptance gate | implemented; NOT PASSED | evidence, terms, review | run after 09-29 |
| Production writes | LOCKED (per source) | all of the above | explicit per-source enablement |
