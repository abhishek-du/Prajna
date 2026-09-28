"""Locks of the news collector.

  DRY_RUN     allowed unless the kill switch (var/run/news.kill) is engaged or
              the source is UNSUPPORTED / has no adapter; it writes files only.
  SHADOW      database writes, invisible to Stage 2/3/API (rows of SHADOW polls
              are never projected). Every one of:
                source_flag          the source's OWN flag, PRAJNA_NEWS_<SRC>_ENABLED
                                     (default false; no switch enables every source)
                kill_switch_off, source_supported
                compliance_approved  terms review APPROVED for this source
                                     (decision NEWS-COMPLIANCE)
                source_acceptance    this source PASSES the news acceptance gate
                                     (var/acceptance/news.json): dry-run evidence,
                                     latency, mapping - no unresolved critical issue
                stage2_pass          the Stage 2 report PASS, <= 7 days, with tests
                write_token
  PRODUCTION  all of SHADOW, plus PRAJNA_NEWS_MULTI_SOURCE_ENABLED: rows become
              visible to Stage 2/3/API. Stage 3's own locks are untouched.
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
from app.features.locks import LockRefused, LockReport, stage2_status
from app.news.collector import BASE, KILL_FILE
from app.news.sources import SOURCES

NEWS_REPORT = BASE / "var" / "acceptance" / "news.json"
WRITE_MODES = ("SHADOW", "PRODUCTION")


def kill_engaged() -> bool:
    return KILL_FILE.exists()


def set_kill(on: bool, reason: str = "") -> None:
    KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if on:
        KILL_FILE.write_text(json.dumps({"engaged_at": now().isoformat(), "reason": reason}))
    elif KILL_FILE.exists():
        KILL_FILE.unlink()


def source_acceptance(source_key: str, path=None) -> tuple[bool, str]:
    """This source's verdict in the latest news acceptance report."""
    p = path or NEWS_REPORT
    if not p.exists():
        return False, "no news acceptance report (run: prajna acceptance news)"
    try:
        rep = json.loads(p.read_text())
        st = rep["sources"][source_key]["status"]
    except (KeyError, ValueError, TypeError):
        return False, f"{source_key} not in the news acceptance report"
    return st == "PASS", f"{source_key} acceptance {st} ({rep.get('generated_at')})"


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
    if mode not in WRITE_MODES:
        r.add("mode_known", False, f"unknown mode {mode}")
        return r
    if src is not None:
        on = bool(src.flag) and bool(getattr(st, src.flag, False))
        r.add("source_flag", on, f"{src.flag}=true" if on else
              f"{src.flag or 'no per-source flag'} is false (default)")
        r.add("compliance_approved", src.compliance == "APPROVED",
              f"compliance {src.compliance} (decision NEWS-COMPLIANCE)")
        ok, why = source_acceptance(source_key)
        r.add("source_acceptance", ok, why)
    ok2, d2 = stage2_status()
    r.add("stage2_pass", ok2, d2)
    if mode == "PRODUCTION":
        r.add("multi_source_enabled", st.PRAJNA_NEWS_MULTI_SOURCE_ENABLED,
              "PRAJNA_NEWS_MULTI_SOURCE_ENABLED=true" if st.PRAJNA_NEWS_MULTI_SOURCE_ENABLED
              else "PRAJNA_NEWS_MULTI_SOURCE_ENABLED is false (default)")
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
