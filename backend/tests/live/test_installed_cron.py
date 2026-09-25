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


def test_installed_crontab_equals_the_repository_file():
    installed = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                               check=True).stdout
    assert installed == REPO.read_text()


def test_installed_schedule_is_safe():
    jobs = _jobs(subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                                check=True).stdout)
    slots = [" ".join(j.split()[:5]) for j in jobs]
    assert len(slots) == len(set(slots))                            # no duplicate slot
    assert not any("runbooks/backfill.sh" in j for j in jobs)       # backfill DEFERRED
    close = [j for j in jobs if "close_then_backfill.sh" in j]
    assert len(close) == 1 and "--no-backfill" in close[0]          # live close enabled
    assert close[0].split()[:5] == ["5", "16", "*", "*", "1-5"]
    # the jobs that take the candles lock never start at the same minute
    locked = [" ".join(j.split()[:2]) for j in jobs if "flock" in j]
    assert len(locked) == len(set(locked))
