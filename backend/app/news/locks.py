"""Locks of the news collector.

  DRY_RUN   allowed unless the kill switch (var/run/news.kill) is engaged or the
            source is UNSUPPORTED; it writes files only.
  SHADOW    database writes (news_* tables, invisible to Stage 2/3 and the API).
            Every one of: PRAJNA_NEWS_CRAWLER_ENABLED (default false); kill switch
            off; the source is implemented and not UNSUPPORTED; its compliance
            review APPROVED (decision NEWS-COMPLIANCE); a write token.
  PRODUCTION  not available: nothing reads news_* for Stage 2/3/API yet. It will
            additionally need PRAJNA_NEWS_MULTI_SOURCE_ENABLED, Stage 1 COMPLETE,
            Stage 2 PASS and dry-run evidence.
A refusal names every unmet condition and is recorded in news_audit.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.clock import now
from app.core.config import get_settings
from app.db.models import NewsAudit
from app.features.locks import LockRefused, LockReport
from app.news.collector import KILL_FILE
from app.news.sources import SOURCES


def kill_engaged() -> bool:
    return KILL_FILE.exists()


def set_kill(on: bool, reason: str = "") -> None:
    KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if on:
        KILL_FILE.write_text(json.dumps({"engaged_at": now().isoformat(), "reason": reason}))
    elif KILL_FILE.exists():
        KILL_FILE.unlink()


def check(source_key: str, *, mode: str, token: str | None) -> LockReport:
    st = get_settings()
    src = SOURCES.get(source_key)
    r = LockReport(mode)
    r.add("known_source", src is not None, "registered" if src else f"unknown source {source_key}")
    r.add("kill_switch_off", not kill_engaged(),
          "not engaged" if not kill_engaged() else f"engaged ({KILL_FILE})")
    if src is not None:
        r.add("source_supported", src.status != "UNSUPPORTED" and src.parse is not None,
              f"status {src.status}" + ("" if src.parse else ", no adapter implemented"))
    if mode == "DRY_RUN":
        return r
    if mode != "SHADOW":
        r.add("mode_available", False, f"{mode} is not available (no consumer reads news_* yet)")
        return r
    r.add("crawler_enabled", st.PRAJNA_NEWS_CRAWLER_ENABLED,
          "PRAJNA_NEWS_CRAWLER_ENABLED=true" if st.PRAJNA_NEWS_CRAWLER_ENABLED
          else "PRAJNA_NEWS_CRAWLER_ENABLED is false (default)")
    if src is not None:
        r.add("compliance_approved", src.compliance == "APPROVED",
              f"compliance {src.compliance} (decision NEWS-COMPLIANCE)")
    try:
        authorize_write(token)
        r.add("write_token", True, "authorised")
    except Exception as e:
        r.add("write_token", False, type(e).__name__)
    return r


async def audit(s: AsyncSession, event: str, source: str | None, operator: str,
                detail: dict[str, Any]) -> None:
    await s.execute(insert(NewsAudit).values(
        event=event, source=source, operator=operator[:64],
        detail=json.loads(json.dumps(detail, default=str))))


async def require(s: AsyncSession, source_key: str, *, mode: str, token: str | None,
                  operator: str = "cli") -> LockReport:
    r = check(source_key, mode=mode, token=token)
    if not r.ok:
        await s.rollback()
        await audit(s, "REFUSED", source_key, operator, {"mode": mode,
                                                         "conditions": r.conditions})
        await s.commit()
        raise LockRefused(r)
    return r
