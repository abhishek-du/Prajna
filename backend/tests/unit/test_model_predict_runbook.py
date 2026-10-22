"""model_predict.sh (E5 forward test): after a successful predict, one MODEL_HEARTBEAT line
of counts (never performance) goes to Telegram; a missing forward day or a closed session
without outcomes raises an ISSUE alert instead. No database: stub CLI and interpreter."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import shutil
import subprocess
import sys

RUNBOOK = pathlib.Path(__file__).resolve().parents[2] / "ops" / "runbooks" / "model_predict.sh"
TODAY = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).date().isoformat()


def _run(tmp_path, status: dict):
    rb = tmp_path / "ops" / "runbooks"
    rb.mkdir(parents=True)
    shutil.copy(RUNBOOK, rb / "model_predict.sh")
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n')
    py.chmod(0o755)
    (tmp_path / ".env").write_text("PRAJNA_WRITE_TOKEN=x\n")
    (tmp_path / "status.json").write_text(json.dumps(status))
    cli = tmp_path / "cli.sh"
    cli.write_text(f"""#!/bin/sh
case "$*" in
  *"models predict"*) echo '{{"inserted": 500, "universe": 500, "history_sessions": 9,
    "history_expected": 9, "history_missing": [], "picks": [1], "results_today_excluded": 0}}' ;;
  *"models status"*) cat {tmp_path / "status.json"} ;;
esac
""")
    cli.chmod(0o755)
    (tmp_path / "var" / "logs" / "daily").mkdir(parents=True)
    (tmp_path / "var" / "logs" / "daily" / f"stage3_{TODAY}.log").write_text(
        f"STAGE3_DONE PRE_SESSION {TODAY}\n")
    sent = tmp_path / "telegram.txt"
    notify = tmp_path / "notify.sh"
    notify.write_text(f'#!/bin/sh\necho "$*" >> {sent}\n')
    notify.chmod(0o755)
    env = {**os.environ, "PRAJNA_CLI": str(cli), "PRAJNA_TELEGRAM_CMD": str(notify),
           "PRAJNA_TEST_TRADING_DAY": "true"}
    out = subprocess.run(["bash", str(rb / "model_predict.sh")], capture_output=True,
                         text=True, timeout=60, env=env)
    return out, (sent.read_text() if sent.exists() else "")


def _status(pending=(), missing=()):
    return {"sessions_predicted": 2, "forward_sessions_needed": 40,
            "missing_sessions": list(missing), "last": {"rows": 500, "picks": 10},
            "outcomes": {"sessions_ready": 1 - len(pending), "sessions_closed": 1,
                         "pending": list(pending)},
            "performance": "not shown before the single look (pre-registration)"}


def test_heartbeat_counts_only(tmp_path):
    out, sent = _run(tmp_path, _status())
    assert out.returncode == 0, out.stdout + out.stderr
    assert "MODEL_PREDICT rc=0 inserted=500" in out.stdout and "history=9/9" in out.stdout
    assert "MODEL_HEARTBEAT day 2/40 rows=500 picks=10 missing_days=0" in out.stdout
    assert sent.startswith("Prajna E5 forward test: day 2/40") and "ISSUE" not in sent
    assert "outcomes_ready=1/1 pending=-" in sent


def test_pending_outcomes_or_a_missing_day_is_an_issue(tmp_path):
    out, sent = _run(tmp_path, _status(pending=["2026-10-22"]))
    assert out.returncode == 0 and "Prajna model ISSUE: heartbeat" in sent
    assert "pending=2026-10-22" in sent
    _, sent2 = _run(tmp_path / "b", _status(missing=["2026-10-23"]))
    assert "Prajna model ISSUE: heartbeat" in sent2 and "missing_days=1" in sent2
