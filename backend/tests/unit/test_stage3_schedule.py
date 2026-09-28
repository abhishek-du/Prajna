"""Decision SCHEDULE (APPROVED 2026-09-28, PRE_OPEN option B): the Stage 3 cron
lines are prepared in ops/cron/prajna.cron but stay commented until the first
production run is authorised, and they fit the installed schedule unchanged."""

from __future__ import annotations

import pathlib

CRON = pathlib.Path(__file__).resolve().parents[2] / "ops" / "cron" / "prajna.cron"
PREFIX = "# APPROVED_NOT_INSTALLED: "


def _active(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")
            and "=" not in ln.split()[0]]


def test_no_stage3_job_is_active():
    assert not [ln for ln in _active(CRON.read_text()) if "stage3" in ln]


def test_the_approved_lines_are_pre_session_and_pre_open_option_b():
    text = CRON.read_text()
    approved = [ln[len(PREFIX):] for ln in text.splitlines() if ln.startswith(PREFIX)]
    assert len(approved) == 2
    ps, po = approved
    assert ps.split()[:5] == ["0", "9", "*", "*", "1-5"] and "sleep 30" in ps
    assert "stage3_snapshot.sh PRE_SESSION" in ps and "--after-replay" not in ps
    assert po.split()[:5] == ["22", "9", "*", "*", "1-5"]
    assert "stage3_snapshot.sh PRE_OPEN --after-replay" in po            # option B
    assert "PENDING_APPROVAL:" not in text                               # no option-A line left
    for ln in approved:                                                  # token: env only
        assert "--token-from-dotenv" in ln and "--token " not in ln
    slots = [" ".join(ln.split()[:5]) for ln in _active(text)]
    assert not {" ".join(ln.split()[:5]) for ln in approved} & set(slots)  # installs cleanly
