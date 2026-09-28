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
        "ref": "user 2026-09-28 ('All feasible')"},
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
        "status": "PENDING",
        "decision": "Per-source terms-of-use review (not a legal opinion by Claude). Until "
                    "APPROVED for a source, only DRY_RUN is allowed for it",
        "ref": "docs/NEWS_MULTI_SOURCE_DESIGN.md section 9"},
}
