"""Decision register of the multi-source news subsystem."""

from __future__ import annotations

DECISIONS: dict[str, dict[str, str]] = {
    "NEWS-SOURCES": {
        "status": "APPROVED",
        "decision": "Constraint #1 (Upstox-only) is amended FOR NEWS ONLY: the feasible "
                    "external sources may be polled - NSE corporate announcements RSS, "
                    "Economic Times, Business Standard, BusinessLine, Livemint, CNBC-TV18. "
                    "Moneycontrol and Zee Business (HTTP 403, bot protection) and Reuters "
                    "(robots.txt Disallow /) are UNSUPPORTED; nothing bypasses a block",
        "ref": "user 2026-09-28 ('All feasible'); extended the same day: 'add Indian "
               "Express and SEBI press release feeds' (robots.txt allows both; probed)"},
    "NEWS-CONTENT": {
        "status": "APPROVED",
        "decision": "Store metadata, URL, the feed's short description, and the article body "
                    "where a source's pages are publicly accessible and allowed by robots.txt "
                    "(never behind a paywall, login or bot protection); an AI description may "
                    "be generated (AWS Bedrock) as a versioned enrichment, never as fact. "
                    "Body collection and AI descriptions are separate, not yet built steps",
        "ref": "user 2026-09-28 ('meta data url short description body data full news if "
               "possible and ai description using bedrock')"},
    "NEWS-PILOT": {
        "status": "APPROVED",
        "decision": "Pilot adapter: NSE corporate announcements RSS",
        "ref": "user 2026-09-28"},
    "NEWS-KNOWABLE": {
        "status": "APPROVED",
        "decision": "knowable_at = Prajna's first observation (discovered_at) for every "
                    "source; published_at is informational. Existing Upstox rows are not "
                    "modified",
        "ref": "user request 2026-09-28 (Phase 1: 'Never set knowable_at to published_at')"},
    "NEWS-CADENCE": {
        "status": "PROPOSED",
        "decision": "Per-source intervals from the source's own constraints (NSE RSS ttl = 5 "
                    "min is honoured); revised after dry-run measurements",
        "ref": "docs/NEWS_MULTI_SOURCE_DESIGN.md section 5"},
    "NEWS-COMPLIANCE": {
        "status": "APPROVED",
        "decision": "Terms review decided by the user (not a legal opinion by Claude): the 8 "
                    "adapters NSE_ANNOUNCEMENTS, SEBI_RSS, ET_STOCKS_RSS, BS_MARKETS_RSS, "
                    "BL_MARKETS_RSS, MINT_MARKETS_RSS, CNBCTV18_NEWS_SITEMAP and "
                    "INDIANEXPRESS_BUSINESS_RSS are APPROVED for production storage of "
                    "headline, feed summary, URL and timestamps ONLY. Article bodies are not "
                    "approved (body_allowed stays False; content stays TERMS_BLOCKED). "
                    "Moneycontrol, Zee Business and Reuters stay REJECTED (403 / robots). "
                    "Approval does not bypass the other locks (per-source flag, acceptance "
                    "gate incl. the human mapping review, Stage 2, token)",
        "ref": "user 2026-09-29 ('all', for headline + summary + URL + timestamps, no bodies)"},
    "FEATURE-NEWS-V2": {
        "status": "APPROVED",
        "decision": "Multi-source news features join the Stage 3 registry as a new version, "
                    "ACTIVATED only after a production canary day shows correct PIT, "
                    "de-duplication and coverage; until activation they are computed in "
                    "dry-run only",
        "ref": "user 2026-09-29 ('After canary evidence')",
        "activation": {
            "status": "ACTIVATED", "registry": "features-v2", "effective": "2026-10-09 PRE_SESSION",
            "evidence": "canary PASS on 12 real scheduled snapshots (2026-09-30, 10-01, 10-05, "
                        "10-06, "
                        "10-07, 10-08; PRE_SESSION and PRE_OPEN): coverage NORMAL, 0 inputs "
                        "knowable at/after as_of, market-wide and per-company counts equal to an "
                        "independent SQL recount, real zeros vs MISSING, deterministic, non-news "
                        "features identical; audit/evidence/news_stage3_canary_*.json",
            "activated_at": "2026-10-08 (after the 2026-10-08 PRE_OPEN run: a session boundary)"},
    },
}
