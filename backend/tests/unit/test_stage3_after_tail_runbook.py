"""stage3_snapshot.sh PRE_OPEN --after-tail (PREOPEN-TAIL, 2026-10-22): the command gets
--wait-preopen-ready; exit 4 (marker not verified) falls back to the full replay's
"replay exit 0" and runs once more without it. No database: a stub interpreter."""

from __future__ import annotations

import datetime as _dt
import os
import pathlib
import shutil
import subprocess
import sys

RUNBOOK = pathlib.Path(__file__).resolve().parents[2] / "ops" / "runbooks" / "stage3_snapshot.sh"
TODAY = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).date().isoformat()


def _setup(tmp_path, *, ready_rc: int, replay_line: str | None):
    rb = tmp_path / "ops" / "runbooks"
    rb.mkdir(parents=True)
    shutil.copy(RUNBOOK, rb / "stage3_snapshot.sh")
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    py.write_text(f"""#!/bin/sh
if [ "$1" = "-" ]; then exec {sys.executable} "$@"; fi
echo "$*" >> {calls}
case "$*" in
  *--wait-preopen-ready*) if [ {ready_rc} = 4 ]; then
      echo "NOT_READY: pre-open ticks not verified: no marker"; exit 4; fi ;;
esac
echo '[{{"run_id": "r1", "rows": 1, "inserted": 1, "already_present": 0, "seconds": 1}}]'
""")
    py.chmod(0o755)
    (tmp_path / ".env").write_text("PRAJNA_WRITE_TOKEN=x\n")
    (tmp_path / "var" / "logs").mkdir(parents=True)
    if replay_line:
        (tmp_path / "var" / "logs" / f"preopen_{TODAY}.log").write_text(replay_line + "\n")
    return rb / "stage3_snapshot.sh", calls


def _run(script):
    env = {**os.environ, "STAGE3_REPLAY_WAIT": "1"}
    return subprocess.run(["bash", str(script), "PRE_OPEN", "--after-tail",
                           "--token-from-dotenv"], capture_output=True, text=True,
                          timeout=60, env=env)


def test_ready_runs_once_with_the_wait_flag(tmp_path):
    script, calls = _setup(tmp_path, ready_rc=0, replay_line=None)
    out = _run(script)
    assert out.returncode == 0, out.stdout + out.stderr
    c = calls.read_text().splitlines()
    assert len(c) == 1 and "--wait-preopen-ready 09:14" in c[0]
    assert "STAGE3_DONE PRE_OPEN" in out.stdout and "FALLBACK" not in out.stdout


def test_not_ready_falls_back_to_the_full_replay(tmp_path):
    script, calls = _setup(tmp_path, ready_rc=4, replay_line="[x] replay exit 0")
    out = _run(script)
    assert out.returncode == 0, out.stdout + out.stderr
    c = calls.read_text().splitlines()
    assert len(c) == 2 and "--wait-preopen-ready" in c[0] and "--wait-preopen-ready" not in c[1]
    assert "STAGE3_FALLBACK PRE_OPEN" in out.stdout and "NOT_READY" in out.stdout
    assert "STAGE3_DONE PRE_OPEN" in out.stdout


def test_not_ready_and_failed_replay_writes_nothing(tmp_path):
    script, calls = _setup(tmp_path, ready_rc=4, replay_line="[x] replay exit 1")
    out = _run(script)
    assert out.returncode == 1
    assert len(calls.read_text().splitlines()) == 1
    assert "STAGE3_SKIP PRE_OPEN" in out.stdout
