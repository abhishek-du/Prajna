"""ops/runbooks/ca_refresh.sh (daily CA refresh D1) against stubs: a stub CLI, a stub
maintenance.sh and a stub Telegram notifier; the target set comes from
PRAJNA_TARGETS_JSON. No network, no database. Plus the pure parts of
ops/measure/ca_targets.py (event classification, weekday buckets)."""

from __future__ import annotations

import collections
import importlib.util
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def _exe(p: pathlib.Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def base(tmp_path):
    (tmp_path / "ops" / "runbooks").mkdir(parents=True)
    shutil.copy(BACKEND / "ops/runbooks/ca_refresh.sh", tmp_path / "ops/runbooks/ca_refresh.sh")
    (tmp_path / ".env").write_text("PRAJNA_WRITE_TOKEN=test-token\n")
    return tmp_path


def run(base, mode, isins, *, inserted=0, ca_rc=0, candles_fail=(), heal="false"):
    stubs, calls = base / "stubs", base / "calls.log"
    calls.unlink(missing_ok=True)
    fail = " ".join(f"'{k}'" for k in candles_fail)
    _exe(stubs / "cli", f'''echo "cli $*" >> {calls}
if [[ "$2" == corporate-actions ]]; then
  echo '{{"inserted": {inserted}, "failed": 0, "complete": 1}}'; exit {ca_rc}; fi
for k in {fail}; do [[ "$*" == *"--key $k "* ]] && exit 1; done
echo '{{"complete": 1}}'
''')
    _exe(stubs / "maint", f'echo "maint $*" >> {calls}\n')
    _exe(stubs / "tg", f'echo "tg $1" >> {calls}\n')
    t = {"mode": mode, "isins": isins, "keys": [f"NSE_EQ|{x}" for x in isins], "reasons": {}}
    env = {**os.environ, "PRAJNA_CLI": str(stubs / "cli"), "PRAJNA_PY": sys.executable,
           "PRAJNA_TARGETS_JSON": json.dumps(t), "PRAJNA_TELEGRAM_CMD": str(stubs / "tg"),
           "PRAJNA_MAINT_CMD": str(stubs / "maint"), "PRAJNA_CA_SELF_HEAL": heal}
    p = subprocess.run(["bash", str(base / "ops/runbooks/ca_refresh.sh"), mode], cwd=base,
                       env=env, capture_output=True, text=True, timeout=300)
    return p, (calls.read_text() if calls.exists() else "")


def test_targeted_sweeps_only_the_targets_and_derives_after_an_insert(base):
    p, calls = run(base, "targeted", ["INE0OPS01011", "INE669C01036"], inserted=1)
    assert p.returncode == 0, p.stdout + p.stderr
    assert ("cli ingest corporate-actions --isin INE0OPS01011 --isin INE669C01036 --commit"
            in calls)
    assert "maint derive" in calls
    assert "CA_REFRESH mode=targeted targeted=2 inserted=1 failed=0 rc=0" in p.stdout


def test_nothing_inserted_means_no_derive_and_no_target_means_no_call(base):
    _, calls = run(base, "targeted", ["INE0OPS01011"], inserted=0)
    assert "maint" not in calls
    p, calls = run(base, "targeted", [])
    assert "CA_REFRESH mode=targeted targeted=0" in p.stdout and "corporate-actions" not in calls


def test_rolling_resumes_within_20_hours(base):
    _, calls = run(base, "rolling", ["INE002A01018"])
    assert "--resume-hours 20 --isin INE002A01018 --commit" in calls


def test_an_ingest_failure_is_an_alert(base):
    p, calls = run(base, "targeted", ["INE0OPS01011"], ca_rc=1)
    assert p.returncode == 1 and "tg Prajna CA refresh ISSUE: mode=targeted" in calls


def test_selfheal_disabled_alerts_and_writes_nothing(base):
    p, calls = run(base, "selfheal", ["INE0OPS01011"], heal="false")
    assert p.returncode == 1 and "SELF_HEAL_DISABLED" in p.stdout
    assert "tg Prajna CA refresh ISSUE: mode=selfheal 1D FAILED" in calls
    assert "cli" not in calls


def test_selfheal_is_bounded_to_the_failing_key(base):
    p, calls = run(base, "selfheal", ["INE0OPS01011"], heal="true")
    assert p.returncode == 0, p.stdout + p.stderr
    lines = [x for x in calls.splitlines() if x.startswith(("cli", "maint"))]
    assert lines[0] == "cli ingest corporate-actions --isin INE0OPS01011 --commit"
    assert lines[1].startswith("cli ingest candles --timeframe 1d --from ")
    assert "--key NSE_EQ|INE0OPS01011 --commit" in lines[1] and "--all-instruments" not in calls
    assert lines[2] == "maint derive"
    assert "healed=1 still_failing=0" in p.stdout and "self-heal fixed 1 key" in calls


def test_selfheal_reports_a_key_that_still_fails(base):
    p, calls = run(base, "selfheal", ["INE0OPS01011", "INE669C01036"], heal="true",
                   candles_fail=("NSE_EQ|INE669C01036",))
    assert p.returncode == 1 and "healed=1 still_failing=1" in p.stdout
    assert "still failing after self-heal" in calls and "NSE_EQ|INE669C01036" in calls


def test_selfheal_refuses_a_mass_failure(base):
    many = [f"INE{i:09d}" for i in range(11)]
    p, calls = run(base, "selfheal", many, heal="true")
    assert p.returncode == 1 and "not self-healing" in p.stdout and "cli" not in calls


def _targets_module():
    spec = importlib.util.spec_from_file_location("ca_targets",
                                                  BACKEND / "ops/measure/ca_targets.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_event_classification():
    m = _targets_module()
    assert m.is_ca_event("Bonus", "Tech Mahindra Limited", None)
    assert m.is_ca_event("Outcome of Board Meeting", None, "approved sub-division of shares")
    assert m.is_ca_event(None, None, "Stock Split from Rs.10/- to Rs.2/-")
    assert not m.is_ca_event("Record Date", None, "Record date for the purpose of Dividend")
    assert not m.is_ca_event("Shareholders meeting", None, "Consolidated Scrutinizer report")


def test_buckets_cover_every_isin_once_a_week():
    m = _targets_module()
    c = collections.Counter(m.bucket(f"INE{i:09d}") for i in range(5000))
    assert set(c) == {0, 1, 2, 3, 4} and min(c.values()) > 850
