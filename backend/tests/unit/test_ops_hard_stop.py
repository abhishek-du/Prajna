"""Hard stops and the candles lock with REAL processes (hardening phase 4).

The runbooks wrap every long step in `timeout -k 120 --signal=INT <secs>`:
SIGINT first (the ingest aborts cleanly, its run is marked), SIGKILL 120 s
later if the process ignores it. These tests run the same construction with
short times against real python processes, and the real flock(1).

Measured on the live close (2026-09-25): the ingest python process has no
child processes and is alone in timeout's process group, so killing the
command kills everything intended. (A background grandchild of a command is
NOT killed by timeout -k: known limitation, not applicable to the ingest.)
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time

import pytest

PY = sys.executable


def _run(args, timeout=30):
    t0 = time.monotonic()
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, time.monotonic() - t0


def test_sigint_is_honoured_by_a_cooperative_process():
    rc, dt = _run(["timeout", "-k", "5", "--signal=INT", "1", PY, "-c",
                   "import time\ntry:\n    time.sleep(30)\nexcept KeyboardInterrupt:\n"
                   "    raise SystemExit(130)"])
    assert rc == 124 and dt < 4                       # stopped at the first signal


def test_a_process_ignoring_sigint_is_killed_by_the_escalation():
    rc, dt = _run(["timeout", "-k", "2", "--signal=INT", "1", PY, "-c",
                   "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                   "time.sleep(60)"])
    assert rc == 137 and 2.5 < dt < 8                 # SIGKILL after 1 s + 2 s


def test_a_process_ignoring_sigterm_is_killed_too():
    rc, dt = _run(["timeout", "-k", "2", "--signal=TERM", "1", PY, "-c",
                   "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                   "time.sleep(60)"])
    assert rc == 137 and dt < 8


def test_no_kill_escalation_would_hang(tmp_path):
    """Why -k matters: without it a SIGINT-ignoring process outlives the limit."""
    p = subprocess.Popen(["timeout", "--signal=INT", "1", PY, "-c",
                          "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                          "time.sleep(60)"])
    time.sleep(3)
    try:
        assert p.poll() is None                       # still running past its limit
    finally:
        p.kill()
        subprocess.run(["pkill", "-KILL", "-P", str(p.pid)], check=False)
        p.wait()


@pytest.fixture
def held_lock(tmp_path):
    path = tmp_path / "candles.lock"
    f = open(path, "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    yield path, f
    f.close()


def test_lock_already_held_nothing_runs(held_lock, tmp_path):
    path, f = held_lock
    marker = tmp_path / "ran"
    rc, _ = _run(["flock", "-n", str(path), "touch", str(marker)])
    assert rc == 1 and not marker.exists()            # -n: gives up at once
    rc, dt = _run(["flock", "-w", "1", str(path), "touch", str(marker)])
    assert rc == 1 and dt >= 1 and not marker.exists()  # -w: waits, then gives up
    fcntl.flock(f, fcntl.LOCK_UN)
    rc, _ = _run(["flock", "-n", str(path), "touch", str(marker)])
    assert rc == 0 and marker.exists()                # released: runs


def test_the_lock_is_released_when_its_holder_dies(tmp_path):
    """No stale lock after a crash: flock(2) is released with the (last)
    process holding the descriptor - here SIGKILLed mid-hold."""
    path = tmp_path / "candles.lock"
    holder = subprocess.Popen([PY, "-c", "import fcntl, sys, time\n"
                               f"f = open({str(path)!r}, 'w')\n"
                               "fcntl.flock(f, fcntl.LOCK_EX)\nprint('held', flush=True)\n"
                               "time.sleep(60)"], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    rc, _ = _run(["flock", "-n", str(path), "true"])
    assert rc == 1
    os.kill(holder.pid, 9)
    holder.wait()
    rc, _ = _run(["flock", "-w", "5", str(path), "true"])
    assert rc == 0
