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


def test_canonical_repository_cron_has_stage3_prepared_but_not_installed():
    """Stage 3 schedule is approved in docs and prepared in repo cron, but NOT installed.
    The lines MUST be commented with 'APPROVED_NOT_INSTALLED:' until production is authorized."""
    repo_text = REPO.read_text()
    s3_lines = _stage3_lines(repo_text)
    assert len(s3_lines) == 2, f"Expected 2 prepared Stage 3 entries in repo, got {len(s3_lines)}"
    assert all(ln.startswith("# APPROVED_NOT_INSTALLED:") for ln in s3_lines), (
        "Stage 3 entries in ops/cron/prajna.cron must remain prefixed with "
        "'APPROVED_NOT_INSTALLED:' until production authorization"
    )
    # verify approved schedule slots (Option B: 09:00:30 and 09:22:00)
    assert any("0 9 * * 1-5" in ln and "PRE_SESSION" in ln for ln in s3_lines)
    assert any("22 9 * * 1-5" in ln and "PRE_OPEN" in ln and "--after-replay" in ln for ln in s3_lines)


def test_installed_crontab_has_zero_stage3_jobs():
    """Host crontab MUST NOT contain active or installed Stage 3 jobs."""
    installed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                               check=True).stdout
    active_jobs = _jobs(installed)
    assert not any("stage3" in j for j in active_jobs), "Found active Stage 3 job in crontab!"
    assert "stage3_snapshot.sh" not in installed, "Stage 3 script referenced in installed crontab!"


def test_installed_schedule_is_safe():
    installed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                               check=True).stdout
    jobs = _jobs(installed)
    slots = [" ".join(j.split()[:5]) for j in jobs]
    assert len(slots) == len(set(slots))                            # no duplicate slot
    assert not any("runbooks/backfill.sh" in j for j in jobs)       # backfill DEFERRED
    assert not any("stage3" in j for j in jobs)                     # Stage 3 uninstalled
    close = [j for j in jobs if "close_then_backfill.sh" in j]
    assert len(close) == 1 and "--no-backfill" in close[0]          # live close enabled
    assert close[0].split()[:5] == ["5", "16", "*", "*", "1-5"]
    # the jobs that take the candles lock never start at the same minute
    locked = [" ".join(j.split()[:2]) for j in jobs if "flock" in j]
    assert len(locked) == len(set(locked))
