"""The INSTALLED crontab (hardening phase 4). Live: reads this machine's
crontab; run with `-m live`. The repo file is the single source of truth."""

from __future__ import annotations

import pathlib
import subprocess

import pytest

pytestmark = pytest.mark.live
REPO = pathlib.Path(__file__).resolve().parents[2] / "ops" / "cron" / "prajna.cron"


def _jobs(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
            and "=" not in ln.split()[0]]


def _stage3_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if "stage3_snapshot.sh" in ln]


def test_installed_jobs_match_canonical_repository_jobs():
    """All active cron jobs on this host must match the repository file exactly."""
    installed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                               check=True).stdout
    repo_text = REPO.read_text()
    assert _jobs(installed) == _jobs(repo_text)


APPROVED_STAGE3 = (
    ("0 9 * * 1-5", "stage3_snapshot.sh PRE_SESSION --token-from-dotenv"),
    ("22 9 * * 1-5", "stage3_snapshot.sh PRE_OPEN --after-replay --token-from-dotenv"),
)


def test_installed_crontab_has_exactly_the_approved_stage3_jobs():
    """Go-live 2026-09-29: the two approved Stage 3 jobs (decision SCHEDULE, PRE_OPEN
    option B) are installed, each exactly once, and no other Stage 3 job."""
    installed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                               check=True).stdout
    s3 = [j for j in _jobs(installed) if "stage3" in j]
    assert len(s3) == 2, f"expected exactly 2 installed Stage 3 jobs, got {len(s3)}"
    for (slot, cmd), job in zip(APPROVED_STAGE3, s3, strict=True):
        assert " ".join(job.split()[:5]) == slot and cmd in job
    assert "sleep 30" in s3[0]                                      # 09:00:30
    assert not any("stage3 backfill" in j for j in _jobs(installed))


def test_no_token_is_embedded_in_the_installed_crontab():
    installed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                               check=True).stdout
    assert "PRAJNA_WRITE_TOKEN" not in installed and "PRAJNA_SUPPLIED_TOKEN=" not in installed
    assert not any("--token " in j for j in _jobs(installed))


def test_installed_schedule_is_safe():
    installed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                               check=True).stdout
    jobs = _jobs(installed)
    slots = [" ".join(j.split()[:5]) for j in jobs]
    assert len(slots) == len(set(slots))                            # no duplicate slot
    assert not any("runbooks/backfill.sh" in j for j in jobs)       # backfill DEFERRED
    assert [j for j in jobs if "stage3" in j] == [                  # exactly the approved two
        j for j in jobs if "stage3_snapshot.sh" in j]
    close = [j for j in jobs if "close_then_backfill.sh" in j]
    assert len(close) == 1 and "--no-backfill" in close[0]          # live close enabled
    assert close[0].split()[:5] == ["5", "16", "*", "*", "1-5"]
    # the jobs that take the candles lock never start at the same minute
    locked = [" ".join(j.split()[:2]) for j in jobs if "flock" in j]
    assert len(locked) == len(set(locked))
