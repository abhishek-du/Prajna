"""Stage 3 execution locks. Everything that WRITES features is refused unless
every condition holds; each refusal names every unmet condition and is audited.

  RUN       (write one snapshot's features)
    stage3_enabled        PRAJNA_STAGE3_ENABLED is true           (default false)
    kill_switch_off       var/run/stage3.kill does not exist
    stage1_complete       the Stage 1 gate, evaluated NOW, is COMPLETE (never a cached file)
    stage2_pass           the latest Stage 2 report is PASS, <= 7 days old, with its test
                          criterion (P) PASS
    decisions_approved    every Stage 3 decision is APPROVED (FEATURE-PARAMS: approved
                          by the user 2026-09-28)
    registry_consistent   every IMPLEMENTED feature has a group, inputs and a definition
    write_token           the write token is authorised
  BACKFILL  (write features for past sessions): all of RUN, plus
    backfill_enabled      PRAJNA_STAGE3_BACKFILL_ENABLED is true  (default false)

Dry-run (compute and print, read-only) needs none of these. Stage 3 has no
vendor call and never starts a Stage 1 warm-up or backfill.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.clock import now
from app.core.config import get_settings
from app.db.models import Stage3Event
from app.features.decisions import DECISIONS
from app.features.registry import FEATURES

BASE = pathlib.Path(__file__).resolve().parents[2]
KILL_FILE = BASE / "var" / "run" / "stage3.kill"
STAGE2_REPORT = BASE / "var" / "acceptance" / "stage2.json"
STAGE2_MAX_AGE = _dt.timedelta(days=7)
MODES = ("RUN", "BACKFILL")


class LockRefused(PermissionError):
    """A Stage 3 write was refused; `report` names every unmet condition."""

    def __init__(self, report: LockReport):
        super().__init__("Stage 3 execution is locked: " + "; ".join(
            f"{c['name']}: {c['detail']}" for c in report.conditions if not c["ok"]))
        self.report = report


@dataclass
class LockReport:
    mode: str
    conditions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.conditions) and all(c["ok"] for c in self.conditions)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.conditions.append({"name": name, "ok": bool(ok), "detail": detail})

    def summary(self) -> dict[str, Any]:
        return {"mode": self.mode, "unlocked": self.ok,
                "failing": [c["name"] for c in self.conditions if not c["ok"]]}


def kill_switch_engaged() -> bool:
    return KILL_FILE.exists()


def set_kill_switch(on: bool, reason: str = "") -> None:
    KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if on:
        KILL_FILE.write_text(json.dumps({"engaged_at": now().isoformat(), "reason": reason}))
    elif KILL_FILE.exists():
        KILL_FILE.unlink()


def stage2_status(path: pathlib.Path = STAGE2_REPORT, *,
                  at: _dt.datetime | None = None) -> tuple[bool, str]:
    at = at or now()
    if not path.exists():
        return False, "no Stage 2 report (run: prajna acceptance stage2 --run-tests)"
    try:
        rep = json.loads(path.read_text())
        gen = _dt.datetime.fromisoformat(rep["generated_at"])
    except Exception as e:                                 # an unreadable report is not a PASS
        return False, f"Stage 2 report unreadable ({type(e).__name__})"
    p = next((c for c in rep.get("criteria", []) if c.get("id") == "P"), None)
    if rep.get("overall") != "PASS":
        return False, f"Stage 2 overall {rep.get('overall')}"
    if not p or p.get("status") != "PASS":
        return False, "Stage 2 test criterion P is not PASS (report generated without tests?)"
    if at - gen > STAGE2_MAX_AGE:
        return False, f"Stage 2 report is {(at - gen).days} days old (max 7)"
    return True, f"PASS, generated {gen.isoformat()}"


async def stage1_status(s: AsyncSession) -> tuple[bool, str]:
    from app.acceptance import stage1 as S1  # evaluated now, read-only
    rep = await S1.evaluate(s)
    ok = rep["overall"] == "COMPLETE"
    detail = f"overall {rep['overall']}"
    if not ok:
        detail += f" (waiting: {rep.get('waiting_for_evidence')}, failing: {rep.get('failing')})"
    return ok, detail


def registry_status() -> tuple[bool, str]:
    bad = [f.id for f in FEATURES if f.status == "IMPLEMENTED"
           and not (f.group and f.inputs and f.definition)]
    return (not bad, "consistent" if not bad else f"incomplete specs: {bad}")


async def check(s: AsyncSession, *, mode: str, token: str | None) -> LockReport:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    st = get_settings()
    r = LockReport(mode)
    r.add("stage3_enabled", st.PRAJNA_STAGE3_ENABLED,
          "PRAJNA_STAGE3_ENABLED=true" if st.PRAJNA_STAGE3_ENABLED
          else "PRAJNA_STAGE3_ENABLED is false (default; production execution not approved)")
    if mode == "BACKFILL":
        r.add("backfill_enabled", st.PRAJNA_STAGE3_BACKFILL_ENABLED,
              "PRAJNA_STAGE3_BACKFILL_ENABLED=true" if st.PRAJNA_STAGE3_BACKFILL_ENABLED
              else "PRAJNA_STAGE3_BACKFILL_ENABLED is false "
                   "(default; feature backfill not approved)")
    r.add("kill_switch_off", not kill_switch_engaged(),
          "not engaged" if not kill_switch_engaged() else f"engaged ({KILL_FILE})")
    ok1, d1 = await stage1_status(s)
    r.add("stage1_complete", ok1, d1)
    ok2, d2 = stage2_status()
    r.add("stage2_pass", ok2, d2)
    pending = [k for k, v in DECISIONS.items() if v["status"] != "APPROVED"]
    r.add("decisions_approved", not pending, "all approved" if not pending
          else f"PENDING: {', '.join(pending)}")
    okr, dr = registry_status()
    r.add("registry_consistent", okr, dr)
    try:
        authorize_write(token)
        r.add("write_token", True, "authorised")
    except Exception as e:
        r.add("write_token", False, f"{type(e).__name__}")
    return r


async def record_event(s: AsyncSession, event: str, mode: str, operator: str,
                       detail: dict[str, Any], run_id=None) -> None:
    await s.execute(insert(Stage3Event).values(event=event, mode=mode, operator=operator[:64],
                                               detail=json.loads(json.dumps(detail, default=str)),
                                               run_id=run_id))


async def require(s: AsyncSession, *, mode: str, token: str | None,
                  operator: str = "cli") -> LockReport:
    """Raise LockRefused (after auditing it) unless every condition holds."""
    report = await check(s, mode=mode, token=token)
    if not report.ok:
        await s.rollback()                        # nothing of the caller's is committed
        await record_event(s, "REFUSED", mode, operator, {"conditions": report.conditions})
        await s.commit()
        raise LockRefused(report)
    return report
