"""ops/runbooks/backfill_supervisor.sh: every decision of a tick, run in a temporary
tree with a fake backfill.sh (no database, no vendor, no real backups)."""

from __future__ import annotations

import fcntl
import hashlib
import os
import pathlib
import shutil
import subprocess
import time

SRC = pathlib.Path(__file__).resolve().parents[2] / "ops" / "runbooks" / "backfill_supervisor.sh"


def tree(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "repo"
    (root / "ops" / "runbooks").mkdir(parents=True)
    shutil.copy(SRC, root / "ops" / "runbooks" / "backfill_supervisor.sh")
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "backfill.sh").write_text(
        "#!/usr/bin/env bash\necho \"$@\" > \"$(pwd)/var/run/fake_args\"\n")
    (fake / "backfill.sh").chmod(0o755)
    (fake / "telegram.sh").write_text(              # records each message it is given
        "#!/usr/bin/env bash\n"
        "printf '%s\\n---\\n' \"$1\" >> \"$(dirname \"$0\")/../telegram_sent.txt\"\n")
    (fake / "telegram.sh").chmod(0o755)
    (root / "var" / "logs" / "backfill").mkdir(parents=True)
    (root / "var" / "run").mkdir(parents=True)
    (root / "var" / "backups").mkdir(parents=True)
    return root


def tick(root, *, free=150, hhmm="2345", trading="true", archive=None, cmd="tick", **extra):
    env = {**os.environ, "PRAJNA_RUNBOOK_DIR": str(root.parent / "fake"),
           "PRAJNA_TELEGRAM_CMD": str(root.parent / "fake" / "telegram.sh"),
           "PRAJNA_TEST_PROGRESS": "1h: 10/100 instruments",
           "PRAJNA_TEST_FREE_GB": str(free), "PRAJNA_TEST_NOW_HHMM": hhmm,
           "PRAJNA_TEST_TRADING_DAY": trading, "PRAJNA_TEST_HEALTH": "",
           "PRAJNA_BACKUP_ARCHIVE_DIR": str(archive or root.parent / "no_archive"), **extra}
    r = subprocess.run(["bash", str(root / "ops/runbooks/backfill_supervisor.sh"), cmd],
                       cwd=root, env=env, capture_output=True, text=True, timeout=60)
    return r.stdout


def last_run(root, status, selected="1h,15m"):
    extra = (f"[x] selected stages ({selected}) complete; others not run\n"
             if status == "selected_stages_complete" else "")
    (root / "var/logs/backfill/backfill_2026-10-15_2330.log").write_text(
        f"{extra}[x] BACKFILL_COMPLETED rc=0 status={status}\n")


def started(root):
    for _ in range(50):
        if (root / "var/run/fake_args").exists():
            return (root / "var/run/fake_args").read_text().strip()
        time.sleep(0.1)
    return None


def test_pause_and_done_markers_stop_everything(tmp_path):
    root = tree(tmp_path)
    (root / "var/run/backfill.paused").touch()
    assert "SUPERVISOR_PAUSED" in tick(root)
    (root / "var/run/backfill.paused").unlink()
    (root / "var/run/backfill.done").touch()
    assert "SUPERVISOR_DONE" in tick(root) and started(root) is None


def test_only_all_stages_complete_ends_the_backfill(tmp_path):
    root = tree(tmp_path)
    last_run(root, "selected_stages_complete")          # tonight's 1h-only run
    out = tick(root)                                    # phase 1 just finished
    assert "SUPERVISOR_PHASE1_DONE" in out and "SUPERVISOR_STARTED stages=1h,1m,15m" in out
    assert started(root) == "--login --stages 1h,1m,15m --until 06:25"
    assert not (root / "var/run/backfill.done").exists()
    last_run(root, "all_stages_complete")
    assert "SUPERVISOR_DONE all stages complete" in tick(root)
    assert (root / "var/run/backfill.done").exists()


def test_no_start_in_trading_hours_but_weekends_run(tmp_path):
    root = tree(tmp_path)
    assert "SUPERVISOR_WINDOW_CLOSED" in tick(root, hhmm="1000", trading="true")
    assert "SUPERVISOR_STARTED" in tick(root, hhmm="1000", trading="false")


def test_disk_below_the_guard_alerts_and_does_not_start(tmp_path):
    root = tree(tmp_path)
    out = tick(root, free=55)
    assert "SUPERVISOR_ALERT disk_below_guard" in out and started(root) is None


def test_storage_rule_archives_oldest_verified_and_keeps_the_newest_two(tmp_path):
    root = tree(tmp_path)
    archive = tmp_path / "archive"
    archive.mkdir()
    names = []
    for i in range(4):
        f = root / "var/backups" / f"prajna_2026101{i}T1000_x.dump"
        f.write_bytes(os.urandom(64) + bytes([i]))
        (root / "var/backups" / (f.name + ".sha256")).write_text(
            hashlib.sha256(f.read_bytes()).hexdigest())
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
        names.append(f.name)
    digests = {n: hashlib.sha256((root / "var/backups" / n).read_bytes()).hexdigest()
               for n in names}
    out = tick(root, free=66, archive=archive)          # needs two moves (+5 GB each, test)
    assert out.count("SUPERVISOR_ARCHIVED") == 2
    for n in names[:2]:
        assert not (root / "var/backups" / n).exists()
        assert hashlib.sha256((archive / n).read_bytes()).hexdigest() == digests[n]
        assert (archive / (n + ".sha256")).exists()
    for n in names[2:]:                                  # the newest two never move
        assert (root / "var/backups" / n).exists()


def test_storage_rule_never_moves_the_newest_two_even_when_short(tmp_path):
    root = tree(tmp_path)
    archive = tmp_path / "archive"
    archive.mkdir()
    for i in range(2):
        (root / "var/backups" / f"b{i}.dump").write_bytes(b"x" * 10)
    tick(root, free=61, archive=archive)
    assert sorted(p.name for p in (root / "var/backups").iterdir()) == ["b0.dump", "b1.dump"]


def test_missing_archive_is_an_alert_not_a_move(tmp_path):
    root = tree(tmp_path)
    (root / "var/backups" / "a.dump").write_bytes(b"x")
    out = tick(root, free=70)
    assert "SUPERVISOR_ALERT storage_archive_unavailable" in out
    assert (root / "var/backups" / "a.dump").exists()


def test_a_busy_candles_lock_waits(tmp_path):
    root = tree(tmp_path)
    lock = root / "var/run/candles.lock"
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        assert "SUPERVISOR_WAITING_LOCK" in tick(root)
    assert started(root) is None


def test_known_and_unknown_stops(tmp_path):
    root = tree(tmp_path)
    last_run(root, "stage_15m_not_complete")
    assert "SUPERVISOR_ALERT vendor_stop:stage_15m_not_complete" in tick(root)
    (root / "var/run/fake_args").unlink(missing_ok=True)
    last_run(root, "something_new")
    assert "SUPERVISOR_ALERT unknown_stop:something_new" in tick(root)


def test_status_is_one_json_line(tmp_path):
    import json
    root = tree(tmp_path)
    s = json.loads(tick(root, cmd="status").strip().splitlines()[-1])
    assert s["done"] is False and s["free_gb"] == 150 and s["stages"] == "1h,15m"
    assert s["process"] == "none"


def test_phase1_is_1h_and_15m_at_the_fast_fraction(tmp_path):
    root = tree(tmp_path)
    out = tick(root, PRAJNA_TEST_OTHER_JOB="false", PRAJNA_TEST_DOW="4")
    assert "SUPERVISOR_STARTED stages=1h,15m fraction=0.9 until=06:25" in out
    assert started(root) == "--login --stages 1h,15m --until 06:25"


def test_shared_fraction_when_another_upstox_job_runs(tmp_path):
    root = tree(tmp_path)
    out = tick(root, PRAJNA_TEST_OTHER_JOB="true", PRAJNA_TEST_DOW="4")
    assert "fraction=0.5" in out


def test_saturday_weekly_sweep_window(tmp_path):
    root = tree(tmp_path)
    out = tick(root, hhmm="0800", trading="false", PRAJNA_TEST_OTHER_JOB="false",
               PRAJNA_TEST_DOW="6")
    assert "fraction=0.9 until=09:50" in out
    root2 = tree(tmp_path / "b")
    out = tick(root2, hhmm="1030", trading="false", PRAJNA_TEST_OTHER_JOB="false",
               PRAJNA_TEST_DOW="6")
    assert "fraction=0.5 until=13:00" in out


def test_a_1h_only_run_does_not_end_phase_1(tmp_path):
    root = tree(tmp_path)
    last_run(root, "selected_stages_complete", selected="1h")   # tonight's waiter
    out = tick(root, PRAJNA_TEST_OTHER_JOB="false", PRAJNA_TEST_DOW="4")
    assert "SUPERVISOR_PHASE1_DONE" not in out and "stages=1h,15m" in out
    assert not (root / "var/run/backfill.phase1_done").exists()


def _sent(root):
    f = root.parent / "telegram_sent.txt"
    return f.read_text() if f.exists() else ""


def test_alerts_are_sent_to_telegram_once_per_hour(tmp_path):
    root = tree(tmp_path)
    tick(root, free=55)
    tick(root, free=55)
    assert _sent(root).count("Prajna backfill ISSUE: SUPERVISOR_ALERT disk_below_guard") == 1


def test_a_start_is_announced(tmp_path):
    root = tree(tmp_path)
    tick(root, PRAJNA_TEST_OTHER_JOB="false", PRAJNA_TEST_DOW="4")
    assert "Prajna backfill: SUPERVISOR_STARTED stages=1h,15m fraction=0.9" in _sent(root)


def test_hourly_update_carries_state_and_progress(tmp_path):
    root = tree(tmp_path)
    tick(root, cmd="hourly")
    msg = _sent(root)
    assert "Prajna backfill hourly update" in msg and "1h: 10/100 instruments" in msg
    assert '"stages":"1h,15m"' in msg and "alerts in the last hour: none" in msg


def test_no_start_around_the_0630_refresh_on_any_day(tmp_path):
    """2026-10-16: a run holding the lock at 06:30 made the refresh (login) time out."""
    for i, (hhmm, dow) in enumerate((("0625", "6"), ("0640", "7"), ("0630", "2"))):
        root = tree(tmp_path / str(i))
        out = tick(root, hhmm=hhmm, trading="false", PRAJNA_TEST_DOW=dow)
        assert "SUPERVISOR_WINDOW_CLOSED refresh" in out and started(root) is None
    root = tree(tmp_path / "sat_night")
    out = tick(root, hhmm="0100", trading="false", PRAJNA_TEST_OTHER_JOB="false",
               PRAJNA_TEST_DOW="6")
    assert "until=06:25" in out                       # not 09:50 across the refresh


def test_hourly_health_problems_are_alerted(tmp_path):
    root = tree(tmp_path)
    tick(root, cmd="hourly", PRAJNA_TEST_HEALTH="stage2_not_pass Stage 2 overall NOT PASSED\n"
                                                "news_refused latest refused")
    msg = _sent(root)
    assert "Prajna backfill ISSUE: SUPERVISOR_ALERT health_stage2_not_pass" in msg
    assert "SUPERVISOR_ALERT health_news_refused" in msg
    assert "alerts in the last hour: [" in msg        # the summary lists them too


def _close(root, text):
    import datetime as dt
    import zoneinfo
    day = dt.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).date()
    (root / "var/logs/daily").mkdir(parents=True, exist_ok=True)
    (root / f"var/logs/daily/close_then_backfill_{day}.log").write_text(text)


def test_on_a_trading_day_the_close_goes_first(tmp_path):
    """2026-10-16: the 16:00 tick started the backfill before the 16:05 close."""
    root = tree(tmp_path)
    out = tick(root, hhmm="1600", trading="true", PRAJNA_TEST_DOW="5")
    assert "SUPERVISOR_WAITING_CLOSE" in out and started(root) is None
    _close(root, "[x] CLOSE_STARTED day=d fraction=0.9\n")
    assert "SUPERVISOR_WAITING_CLOSE" in tick(root, hhmm="1930", trading="true")
    _close(root, "[x] CLOSE_STARTED\n[x] CLOSE_COMPLETED rc=0 verdict=complete\n")
    out = tick(root, hhmm="1935", trading="true", PRAJNA_TEST_OTHER_JOB="false",
               PRAJNA_TEST_DOW="5")
    assert "SUPERVISOR_STARTED" in out and started(root) is not None


def test_without_a_close_the_backfill_starts_at_2330_with_an_alert(tmp_path):
    root = tree(tmp_path)
    out = tick(root, hhmm="2330", trading="true", PRAJNA_TEST_OTHER_JOB="false",
               PRAJNA_TEST_DOW="5")
    assert "SUPERVISOR_ALERT close_missing" in out and "SUPERVISOR_STARTED" in out
    assert "close_missing" in _sent(root)


def test_non_trading_days_do_not_wait_for_a_close(tmp_path):
    root = tree(tmp_path)
    out = tick(root, hhmm="1600", trading="false", PRAJNA_TEST_DOW="6",
               PRAJNA_TEST_OTHER_JOB="false")
    assert "SUPERVISOR_STARTED" in out


def test_an_operator_stage_override_file_chooses_the_stages(tmp_path):
    """2026-10-17: a fail-closed 1h stream kept the fixed 1h,15m order from reaching 15m."""
    root = tree(tmp_path)
    (root / "var/run/backfill.stages").write_text("15m\n")
    out = tick(root, hhmm="1310", trading="false", PRAJNA_TEST_DOW="6",
               PRAJNA_TEST_OTHER_JOB="false")
    assert "SUPERVISOR_STARTED stages=15m" in out
    assert started(root).startswith("--login --stages 15m ")
    root2 = tree(tmp_path / "bad")
    (root2 / "var/run/backfill.stages").write_text("15m; rm -rf /\n")   # not a stage list
    assert "stages=1h,15m" in tick(root2, hhmm="1310", trading="false", PRAJNA_TEST_DOW="6",
                                    PRAJNA_TEST_OTHER_JOB="false")
