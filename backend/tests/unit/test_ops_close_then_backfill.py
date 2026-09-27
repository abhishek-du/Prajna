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
# backfill.sh budgets against the real clock: its hard stop is always 3 h ahead
# of now (a fixed "23:59" left a zero budget when the suite ran just before
# midnight and every stage was skipped)
UNTIL = (_dt.datetime.now(ZoneInfo("Asia/Kolkata")) + _dt.timedelta(hours=3)).strftime("%H:%M")


@pytest.fixture(autouse=True)
def _clock_now():
    """TODAY / UNTIL as of THIS test: the scripts under test read the real clock,
    and a suite running across midnight must not compare against yesterday."""
    global TODAY, UNTIL
    now = _dt.datetime.now(ZoneInfo("Asia/Kolkata"))
    TODAY = now.date().isoformat()
    UNTIL = (now + _dt.timedelta(hours=3)).strftime("%H:%M")


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
           backfill_rc: int = 0, now_hhmm: str = "2330", extra: tuple = ()):
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
           "PRAJNA_CLI": str(stubs / "cli"), "PRAJNA_TEST_NOW_HHMM": now_hhmm}
    p = subprocess.run(["bash", str(base / "ops/runbooks/close_then_backfill.sh"),
                        "--until", "06:50", *extra], cwd=base, env=env, capture_output=True,
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
        for marker in ("CLOSE_STARTED",
                       "CLOSE_COMPLETED rc=0 verdict=completed failure_class=SUCCESS",
                       "CLOSE_RERUN_CHECK jobs=9 complete=9 inserted=0 failed=0 "
                       "idempotent=True"):
            assert marker in out
        assert out.index("CLOSE_COMPLETED") < out.index("CLOSE_RERUN_CHECK")

    def test_instrument_level_vendor_failures_still_start_the_backfill(self, base):
        p, calls = _chain(base, close_rc=1, intraday={**OK, "failed": 3})
        assert "verdict=completed_with_instrument_failures" in p.stdout
        assert "failure_class=SINGLE_INSTRUMENT_VENDOR_FAILURE" in p.stdout
        assert "complete=10584 failed=3" in p.stdout
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


def _backfill(base, *, stage_rc: dict[str, int] | None = None, other_job: bool = False,
              now_hhmm: str = "2330", trading: str = "True", auth_failures: int = 0):
    stage_rc = stage_rc or {}
    counter = base / "ingest_calls"
    calls = base / "calls.log"
    bin_ = base / "bin"
    cases = "\n".join(f'  *"--timeframe {tf} "*) exit {rc} ;;' for tf, rc in stage_rc.items())
    _exe(base / ".venv" / "bin" / "python", f"""
if [ "$1" = "-c" ]; then exec {sys.executable} "$@"; fi     # JSON parsing: real python
args="$*"
echo "py $args" >> {calls}
case "$args" in
  *"upstox token-status"*) echo '"valid": true' ;;
  *"upstox login"*) echo "LOGIN" >> {calls} ;;
  *"select is_trading_day from"*) printf 'is_trading_day\\n---\\n{trading}\\n' ;;
  *"db sql"*"covered_from"*) printf 'count count\\n----- -----\\n12 3528\\n' ;;
  *"db sql"*) printf 'max\\n---\\n2026-09-24\\n' ;;
  *"ingest candles"*)
    n=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 )); echo $n > {counter}
    if [ "$n" -le {auth_failures} ]; then
      echo '{{"stopped": "VendorAuthError: 401 UDAPI100050"}}'; exit 1
    fi
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
           "PRAJNA_UPSTOX_RATE_FRACTION": "0.5", "PRAJNA_TEST_NOW_HHMM": now_hhmm}
    p = subprocess.run(["bash", str(base / "ops/runbooks/backfill.sh"), "--login",
                        "--until", UNTIL],
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
        assert f"BACKFILL_STARTED until={UNTIL} fraction=0.5" in out
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


class TestPhase4Hardening:
    @pytest.mark.parametrize("intraday,rc,cls", [
        ({**OK, "stopped": "RateLimited: 429 UDAPI10005", "not_attempted": 900}, 1,
         "QUOTA_FAILURE"),
        ({**OK, "stopped": "VendorAuthError: 401 UDAPI100050", "aborted": 1}, 1,
         "TOKEN_FAILURE"),
        (None, 3, "TOKEN_FAILURE"),                         # daily.sh: token invalid
        (None, 2, "TOO_EARLY"),
        ({**OK, "stopped": "OSError: disk"}, 1, "ABORTED"),
    ])
    def test_failure_classes_are_distinct_and_never_start_the_backfill(self, base, intraday,
                                                                         rc, cls):
        p, calls = _chain(base, close_rc=rc, intraday=intraday)
        assert f"failure_class={cls}" in p.stdout and "verdict=not_completed" in p.stdout
        assert "backfill" not in calls

    def test_data_absent_is_counted_not_a_failure(self, base):
        p, _calls = _chain(base, close_rc=0, intraday={**OK, "coverage": {"EMPTY": 408}})
        assert "failure_class=SUCCESS" in p.stdout and "data_absent=408" in p.stdout

    def test_no_backfill_runs_close_and_rerun_check_only(self, base):
        p, calls = _chain(base, close_rc=0, intraday=OK, extra=("--no-backfill",))
        assert p.returncode == 0
        assert "CLOSE_RERUN_CHECK" in p.stdout
        assert "BACKFILL_DEFERRED reason=DEFERRED_FOR_STAGE_1" in p.stdout
        assert "backfill" not in calls

    @pytest.mark.parametrize("hhmm,starts", [
        ("0649", True), ("0650", False), ("0651", False), ("1000", False),
        ("1559", False), ("1600", True), ("1601", True), ("2330", True)])
    def test_overrun_guard_never_hands_over_in_market_hours(self, base, hhmm, starts):
        p, calls = _chain(base, close_rc=0, intraday=OK, now_hhmm=hhmm)
        assert ("backfill --login" in calls) is starts
        if not starts:
            assert "BACKFILL_SKIPPED reason=overrun_guard" in p.stdout


class TestBackfillHardening:
    def test_refuses_to_start_in_trading_hours_on_a_trading_day(self, base):
        p, calls = _backfill(base, now_hhmm="1000", trading="True")
        assert p.returncode == 0 and "ingest candles" not in calls
        assert "BACKFILL_COMPLETED rc=0 status=refused_trading_hours" in p.stdout

    def test_weekend_daytime_is_allowed(self, base):
        p, calls = _backfill(base, now_hhmm="1000", trading="False")
        assert "ingest candles" in calls
        assert "status=all_stages_complete" in p.stdout

    def test_exactly_one_relogin_after_token_expiry_then_resume(self, base):
        p, calls = _backfill(base, auth_failures=1)
        assert calls.count("LOGIN") == 1
        assert "BACKFILL_RELOGIN" in p.stdout
        assert "status=all_stages_complete" in p.stdout
        assert sum("--timeframe 1h" in ln for ln in calls.splitlines()) == 2   # retried once

    def test_a_second_auth_failure_stops_without_a_second_login(self, base):
        p, calls = _backfill(base, auth_failures=2)
        assert calls.count("LOGIN") == 1
        assert p.returncode != 0 and "status=stage_1h_not_complete" in p.stdout


class TestStaticGuards:
    def test_long_steps_have_a_kill_escalation(self):
        daily = (RUNBOOKS / "daily.sh").read_text()
        backfill = (RUNBOOKS / "backfill.sh").read_text()
        assert "run intraday timeout -k 120 --signal=INT" in daily
        assert 'timeout -k 120 --signal=INT "${left}"' in backfill

    def test_repo_cron_invariants(self):
        lines = [ln for ln in (BACKEND / "ops" / "cron" / "prajna.cron").read_text().splitlines()
                 if ln.strip() and not ln.startswith("#") and not ln.split()[0].isupper()
                 and "=" not in ln.split()[0]]
        jobs = [ln for ln in lines]
        schedules = [" ".join(ln.split()[:5]) for ln in jobs]
        assert len(schedules) == len(set(schedules))                 # no duplicate slots
        assert not any("runbooks/backfill.sh" in ln for ln in jobs)  # backfill DEFERRED
        close = [ln for ln in jobs if "close_then_backfill.sh" in ln]
        assert len(close) == 1 and "--no-backfill" in close[0]
        assert close[0].split()[:2] == ["5", "16"]
        # every candle-writing job holds the one candles lock
        for ln in jobs:
            if any(k in ln for k in ("close_then_backfill", "daily.sh --login morning",
                                     "daily.sh --login refresh")):
                assert "flock" in ln and "$LK" in ln, ln
        refresh = [ln for ln in jobs if "--login refresh" in ln][0]
        maint = [ln for ln in jobs if "maintenance.sh all" in ln][0]
        morning = [ln for ln in jobs if "--login morning" in ln][0]
        hm = lambda ln: (int(ln.split()[1]), int(ln.split()[0]))         # noqa: E731
        assert hm(refresh) < hm(maint) < hm(morning)                  # 06:30 < 06:40 < 07:00
        deferred = (BACKEND / "ops" / "cron" / "prajna.cron").read_text()
        assert deferred.count("# DEFERRED_FOR_STAGE_1:") == 2         # capability kept

    def test_news_poll_runs_in_market_hours_without_login_or_candles_lock(self):
        text = (BACKEND / "ops" / "cron" / "prajna.cron").read_text()
        news = [ln for ln in text.splitlines() if "news_poll.sh" in ln and not ln.startswith("#")]
        assert news, "market-hours news polling is scheduled"
        weekend = [ln for ln in news if ln.split()[4] == "0,6"]
        for ln in news:
            minute, hour, _, _, dow = ln.split()[:5]
            assert dow in ("1-5", "0,6") and "$LK" not in ln and "news.lock" in ln
            if dow == "1-5":
                hours = [int(h) for h in hour.replace("-", ",").split(",")]
                assert min(hours) >= 9 and max(hours) <= 15
                if hour == "9":
                    assert minute == "30"        # after the 08:55-09:20 pre-open capture
        # weekends are swept too: acceptance N needs a sweep within 36 h, and no
        # weekday job runs Sat/Sun (Fri 23:36 close -> Mon 07:00 was ~55 h)
        assert weekend, "weekend news sweep scheduled"
        hours = sorted(int(h) for ln in weekend for h in ln.split()[1].split(","))
        gaps = [b - a for a, b in zip(hours, hours[1:])] + [24 - hours[-1] + hours[0]]
        assert max(gaps) <= 24                    # never more than a day between weekend sweeps
        body = (RUNBOOKS / "news_poll.sh").read_text()
        assert "--login" not in body and "PRAJNA_SUPPLIED_TOKEN" in body
        assert "timeout -k 60 --signal=INT" in body and "--token" not in body


    def test_timing_monitor_is_scheduled_guarded_and_read_only(self):
        text = (BACKEND / "ops" / "cron" / "prajna.cron").read_text()
        mon = [ln for ln in text.splitlines() if "timing_monitor.sh" in ln
               and not ln.startswith("#")]
        assert [ln.split()[:5] for ln in mon] == [["21", "9", "*", "*", "1-5"],
                                                   ["10", "16", "*", "*", "1-5"]]
        assert all("$LK" not in ln for ln in mon)          # never the candles lock
        body = (RUNBOOKS / "timing_monitor.sh").read_text()
        assert 'pgrep -f "ops/measure/candle_timin[g].py"' in body     # one poller only
        assert "--login" not in body and "PRAJNA_SUPPLIED_TOKEN" not in body
        assert "--token" not in body and "--commit" not in body         # read-only
        assert "timeout -k 60 --signal=INT" in body
        assert "TIMING_LATE_REVISION_DETECTED" in body and "analyze_timing.py" in body


class TestInterruptedClose:
    """A close killed by its hard stop (or any interruption) leaves no, an
    empty, or a truncated intraday report: never 'completed', never a backfill."""

    @pytest.mark.parametrize("report", [None, "", "{\"complete\": 12"])
    def test_interrupted_or_timed_out_close_is_aborted(self, base, report):
        stubs = base / "stubs"
        _chain(base, close_rc=0, intraday=None)          # create the stubs
        j = base / f"var/logs/daily/close_{TODAY}_intraday.json"
        body = "" if report is None else f"printf '%s' '{report}' > {j}\n"
        _exe(stubs / "daily.sh", f"{body}exit 1\n")      # daily.sh: a step FAILED
        env = {**os.environ, "PRAJNA_RUNBOOK_DIR": str(stubs), "PRAJNA_PY": sys.executable,
               "PRAJNA_CLI": str(stubs / "cli"), "PRAJNA_TEST_NOW_HHMM": "2330"}
        p = subprocess.run(["bash", str(base / "ops/runbooks/close_then_backfill.sh")],
                           cwd=base, env=env, capture_output=True, text=True, timeout=60)
        assert "verdict=not_completed failure_class=ABORTED" in p.stdout, p.stdout
        assert "BACKFILL_SKIPPED reason=close_not_completed" in p.stdout
        assert p.returncode == 1


class TestBackfillBoundaries:
    @pytest.mark.parametrize("hhmm,starts", [
        ("0649", True), ("0650", False), ("0651", False), ("1559", False),
        ("1600", True), ("1601", True)])
    def test_trading_day_boundaries(self, base, hhmm, starts):
        p, calls = _backfill(base, now_hhmm=hhmm, trading="True")
        assert ("ingest candles" in calls) is starts, p.stdout
        if not starts:
            assert "status=refused_trading_hours" in p.stdout

    @pytest.mark.parametrize("hhmm", ["0650", "1000", "1559"])
    def test_weekend_or_holiday_daytime_is_allowed(self, base, hhmm):
        p, calls = _backfill(base, now_hhmm=hhmm, trading="False")
        assert "ingest candles" in calls and "status=all_stages_complete" in p.stdout

    def test_repeated_auth_failures_never_loop(self, base):
        p, calls = _backfill(base, auth_failures=10)
        assert calls.count("LOGIN") == 1
        assert sum("ingest candles" in ln for ln in calls.splitlines()) == 2
        assert p.returncode != 0
