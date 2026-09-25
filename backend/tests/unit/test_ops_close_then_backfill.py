"""The close -> backfill chain and the backfill markers (ops runbooks).

The real scripts run against stubs: stub daily.sh/backfill.sh (the chain),
and a stub `.venv/bin/python` CLI plus stub pgrep/df (backfill.sh). No
network, no database. What is proven:
  - the backfill starts after a close that ran through (incl. per-instrument
    vendor failures and a non-trading-day SKIP), never after one that was
    stopped/aborted or did not run (token, too early);
  - one lock hold, sequential steps, the existing fractions (0.35 / 0.5);
  - the same-day rerun check (9 requests) is reported, never blocking;
  - backfill.sh keeps the approved stages/depths and logs
    BACKFILL_STARTED / BACKFILL_PROGRESS / BACKFILL_COMPLETED.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
RUNBOOKS = BACKEND / "ops" / "runbooks"
TODAY = _dt.datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def _exe(p: pathlib.Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def base(tmp_path):
    (tmp_path / "ops" / "runbooks").mkdir(parents=True)
    for name in ("close_then_backfill.sh", "backfill.sh"):
        shutil.copy(RUNBOOKS / name, tmp_path / "ops" / "runbooks" / name)
    (tmp_path / ".env").write_text("PRAJNA_WRITE_TOKEN=test-token\n")
    (tmp_path / "var" / "logs" / "daily").mkdir(parents=True)
    return tmp_path


def _chain(base, *, close_rc: int, intraday: dict | None, rerun_inserted: int = 0,
           backfill_rc: int = 0):
    stubs = base / "stubs"
    calls = base / "calls.log"
    j = f"var/logs/daily/close_{TODAY}_intraday.json"
    write_json = (f"cat > {j} <<'X'\n{json.dumps(intraday)}\nX\n" if intraday else "")
    _exe(stubs / "daily.sh", f'echo "daily $* fraction=$PRAJNA_UPSTOX_RATE_FRACTION" >> {calls}\n'
                             f"{write_json}exit {close_rc}\n")
    _exe(stubs / "backfill.sh", f'echo "backfill $* fraction=$PRAJNA_UPSTOX_RATE_FRACTION" '
                                f">> {calls}\nexit {backfill_rc}\n")
    _exe(stubs / "cli", f'echo "cli $* fraction=$PRAJNA_UPSTOX_RATE_FRACTION" >> {calls}\n'
                        f"echo '{json.dumps({'jobs': 9, 'complete': 9, 'inserted': rerun_inserted, 'failed': []})}'\n")
    env = {**os.environ, "PRAJNA_RUNBOOK_DIR": str(stubs), "PRAJNA_PY": sys.executable,
           "PRAJNA_CLI": str(stubs / "cli")}
    p = subprocess.run(["bash", str(base / "ops/runbooks/close_then_backfill.sh"),
                        "--until", "06:50"], cwd=base, env=env, capture_output=True,
                       text=True, timeout=60)
    return p, (calls.read_text() if calls.exists() else "")


OK = {"stopped": None, "aborted": 0, "not_attempted": 0, "complete": 10584, "failed": 0}


class TestCloseThenBackfill:
    def test_clean_close_then_rerun_check_then_backfill(self, base):
        p, calls = _chain(base, close_rc=0, intraday=OK)
        assert p.returncode == 0, p.stdout + p.stderr
        lines = calls.splitlines()
        assert lines[0] == "daily --login close fraction=0.35"
        assert lines[1].startswith("cli ingest candles --timeframe 1m --timeframe 15m "
                                   "--timeframe 1h --intraday --key NSE_EQ|INE002A01018")
        assert "--key NSE_INDEX|Nifty 50" in lines[1] and "fraction=0.35" in lines[1]
        assert lines[2] == "backfill --login --until 06:50 fraction=0.5"
        assert len(lines) == 3                                  # strictly sequential
        out = p.stdout
        for marker in ("CLOSE_STARTED", "CLOSE_COMPLETED rc=0 verdict=completed",
                       "CLOSE_RERUN_CHECK jobs=9 complete=9 inserted=0 failed=0 "
                       "idempotent=True"):
            assert marker in out
        assert out.index("CLOSE_COMPLETED") < out.index("CLOSE_RERUN_CHECK")

    def test_instrument_level_vendor_failures_still_start_the_backfill(self, base):
        p, calls = _chain(base, close_rc=1, intraday={**OK, "failed": 3})
        assert "verdict=completed_with_instrument_failures" in p.stdout
        assert "intraday: complete=10584 failed=3" in p.stdout
        assert "backfill --login --until 06:50 fraction=0.5" in calls

    @pytest.mark.parametrize("intraday", [
        {**OK, "stopped": "RateLimited: 429"},                  # quota abort
        {**OK, "aborted": 1},
        {**OK, "not_attempted": 500},
    ])
    def test_a_stopped_close_never_starts_the_backfill(self, base, intraday):
        p, calls = _chain(base, close_rc=1, intraday=intraday)
        assert p.returncode == 1
        assert "BACKFILL_SKIPPED reason=close_not_completed" in p.stdout
        assert "backfill" not in calls and "cli " not in calls

    @pytest.mark.parametrize("rc", [2, 3])                     # too early / token invalid
    def test_a_close_that_did_not_run_never_starts_the_backfill(self, base, rc):
        p, calls = _chain(base, close_rc=rc, intraday=None)
        assert p.returncode == rc and "BACKFILL_SKIPPED" in p.stdout
        assert "backfill" not in calls

    def test_non_trading_day_skip_goes_straight_to_the_backfill(self, base):
        p, calls = _chain(base, close_rc=0, intraday=None)       # daily.sh SKIP: exit 0
        assert "verdict=completed" in p.stdout and "CLOSE_RERUN_CHECK" not in p.stdout
        assert calls.splitlines()[-1] == "backfill --login --until 06:50 fraction=0.5"

    def test_rerun_check_is_reported_not_blocking(self, base):
        p, calls = _chain(base, close_rc=0, intraday=OK, rerun_inserted=4, backfill_rc=5)
        assert "inserted=4" in p.stdout and "idempotent=False" in p.stdout
        assert "backfill --login" in calls
        assert p.returncode == 5                                  # the backfill's outcome


def _backfill(base, *, stage_rc: dict[str, int] | None = None, other_job: bool = False):
    stage_rc = stage_rc or {}
    calls = base / "calls.log"
    bin_ = base / "bin"
    cases = "\n".join(f'  *"--timeframe {tf} "*) exit {rc} ;;' for tf, rc in stage_rc.items())
    _exe(base / ".venv" / "bin" / "python", f"""
args="$*"
echo "py $args" >> {calls}
case "$args" in
  *"upstox token-status"*) echo '"valid": true' ;;
  *"db sql"*"covered_from"*) printf 'count count\\n----- -----\\n12 3528\\n' ;;
  *"db sql"*) printf 'max\\n---\\n2026-09-24\\n' ;;
  *"ingest candles"*)
    echo '{{}}'
    case "$args " in
{cases}
    esac ;;
esac
exit 0
""")
    _exe(bin_ / "pgrep", f"exit {0 if other_job else 1}\n")
    _exe(bin_ / "df", "printf 'Avail\\n500G\\n'\n")
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}",
           "PRAJNA_UPSTOX_RATE_FRACTION": "0.5"}
    p = subprocess.run(["bash", str(base / "ops/runbooks/backfill.sh"), "--until", "23:59"],
                       cwd=base, env=env, capture_output=True, text=True, timeout=60)
    return p, (calls.read_text() if calls.exists() else "")


class TestBackfillMarkers:
    def test_approved_stages_depths_and_markers(self, base):
        p, calls = _backfill(base)
        assert p.returncode == 0, p.stdout + p.stderr
        six = (_dt.date.fromisoformat(TODAY) - _dt.timedelta(days=183)).isoformat()
        ingests = [ln for ln in calls.splitlines() if "ingest candles" in ln]
        assert [ln.split("--timeframe ")[1].split(" --to")[0] for ln in ingests] == [
            "1h --from 2022-01-01", f"1m --from {six}", "15m --from 2022-01-01"]
        assert all("--all-instruments --commit" in ln for ln in ingests)
        out = p.stdout
        assert "BACKFILL_STARTED until=23:59 fraction=0.5" in out
        assert out.count("BACKFILL_PROGRESS") == 6                # before + after each stage
        assert "BACKFILL_PROGRESS tf=1h from=2022-01-01 covered=12/3528" in out
        assert "BACKFILL_COMPLETED rc=0 status=all_stages_complete" in out

    def test_a_failed_stage_stops_resumably_and_says_so(self, base):
        p, calls = _backfill(base, stage_rc={"1m": 1})
        assert p.returncode == 1
        assert "BACKFILL_COMPLETED rc=1 status=stage_1m_not_complete" in p.stdout
        assert "--timeframe 15m" not in calls                   # later stages not started

    def test_never_competes_with_another_candles_job(self, base):
        p, calls = _backfill(base, other_job=True)
        assert p.returncode == 0 and "ingest candles" not in calls
        assert "BACKFILL_COMPLETED rc=0 status=another_candles_job_running" in p.stdout
