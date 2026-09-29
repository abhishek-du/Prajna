"""The news collection runbook: argument checks happen before anything runs, the
token comes from the environment (never argv), and one collector at a time."""

from __future__ import annotations

import pathlib
import subprocess

import pytest

RUNBOOK = pathlib.Path(__file__).resolve().parents[2] / "ops" / "runbooks" / "news_collect.sh"


@pytest.mark.parametrize("args", [
    [], ["--mode", "DRY_RUN", "--sources", "ALL", "--until", "15:45"],
    ["--mode", "SHADOW", "--until", "15:45"], ["--mode", "SHADOW", "--sources", "ALL"],
    ["--mode", "SHADOW", "--sources", "ALL", "--until", "3pm"], ["--token", "x"],
])
def test_bad_arguments_exit_2_before_anything_runs(args):
    p = subprocess.run(["bash", str(RUNBOOK), *args], capture_output=True, text=True, timeout=30)
    assert p.returncode == 2 and "usage:" in p.stderr


def test_runbook_contract():
    s = RUNBOOK.read_text()
    assert "flock -n 9" in s and "var/run/news_collect.lock" in s
    assert "export PRAJNA_SUPPLIED_TOKEN" in s and "--token " not in s.split("set -uo")[1]
    assert "news collect --source" in s                    # only the lock-checked command
    for m in ("START", "DONE", "REFUSED", "FAILED", "SKIP"):
        assert f"NEWS_COLLECT_{m}" in s
