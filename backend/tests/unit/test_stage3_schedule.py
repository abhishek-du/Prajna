"""Decision SCHEDULE (APPROVED 2026-09-28, PRE_OPEN option B), INSTALLED 2026-09-29 at
go-live: ops/cron/prajna.cron holds exactly the two approved Stage 3 jobs as active
lines, nothing else Stage 3, no backfill, and no token on any command line."""

from __future__ import annotations

import pathlib

CRON = pathlib.Path(__file__).resolve().parents[2] / "ops" / "cron" / "prajna.cron"


def _active(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")
            and "=" not in ln.split()[0]]


def _stage3(text: str) -> list[str]:
    return [ln for ln in _active(text) if "stage3" in ln]


def test_exactly_the_two_approved_stage3_jobs_are_active():
    ps, po = _stage3(CRON.read_text())                        # exactly two, in this order
    assert ps.split()[:5] == ["0", "9", "*", "*", "1-5"] and "sleep 30" in ps   # 09:00:30
    assert "stage3_snapshot.sh PRE_SESSION --token-from-dotenv" in ps
    assert "--after-replay" not in ps
    assert po.split()[:5] == ["22", "9", "*", "*", "1-5"]                       # 09:22
    assert "stage3_snapshot.sh PRE_OPEN --after-replay --token-from-dotenv" in po  # option B


def test_no_other_stage3_job_no_backfill_no_leftover_marker():
    text = CRON.read_text()
    active = _active(text)
    assert not [ln for ln in active if "stage3" in ln and "stage3_snapshot.sh" not in ln]
    assert not any("stage3 backfill" in ln or "runbooks/backfill.sh" in ln for ln in active)
    assert "APPROVED_NOT_INSTALLED:" not in text and "PENDING_APPROVAL:" not in text


def test_no_token_on_any_command_line_and_no_slot_collision():
    active = _active(CRON.read_text())
    assert not any("--token " in ln or "PRAJNA_WRITE_TOKEN" in ln or "PRAJNA_SUPPLIED_TOKEN=" in ln
                   for ln in active)
    slots = [" ".join(ln.split()[:5]) for ln in active]
    assert len(slots) == len(set(slots))


def test_the_stage2_report_stage3_depends_on_is_refreshed_daily():
    """Stage 3's lock refuses a Stage 2 report older than 7 days (locks.STAGE2_MAX_AGE);
    a daily job (user decision 2026-09-29) regenerates it WITH tests (criterion P)
    and never rewrites docs/."""
    from app.features.locks import STAGE2_MAX_AGE
    jobs = [ln for ln in _active(CRON.read_text()) if "acceptance stage2" in ln]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.split()[:5] == ["30", "5", "*", "*", "*"]                  # every day
    assert "--run-tests" in job and "--md ''" in job
    assert STAGE2_MAX_AGE.days == 7
