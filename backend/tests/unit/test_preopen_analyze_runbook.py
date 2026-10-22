"""preopen_day.sh refreshes planner statistics of the pre-open tables after a
SUCCESSFUL replay (97fe58e, 2026-10-13): only on replay exit 0, before the
"replay exit" line that stage3_snapshot.sh --after-replay waits for, bounded by
lock/statement/hard timeouts, and best effort - an ANALYZE failure is logged and
never changes the replay result or the script's exit. No database here: the block
is executed with a stub interpreter."""

from __future__ import annotations

import pathlib
import re
import subprocess

RUNBOOK = pathlib.Path(__file__).resolve().parents[2] / "ops" / "runbooks" / "preopen_day.sh"
STAGE3 = RUNBOOK.with_name("stage3_snapshot.sh")


def _block() -> str:
    text = RUNBOOK.read_text()
    # after the (fallback) full replay's REP=$? - inside its `if` since PREOPEN-TAIL
    m = re.search(r'^ *REP=\$\?\n(?:fi\n)?(if \[\[ \$REP -eq 0 \]\]; then\n.*?^fi\n)set -e\n'
                  r'say "replay exit \$\{REP\}"$', text, re.S | re.M)
    assert m, "the ANALYZE block must sit between REP=$? and the replay-exit line"
    return m.group(1)


def test_block_targets_exactly_the_preopen_tables_with_bounds():
    b = _block()
    assert re.findall(r'text\("(analyze [^"]+)"\)', b) == ["analyze preopen_tick, preopen_book"]
    assert "set local lock_timeout = '30s'" in b
    assert "set local statement_timeout = '240s'" in b
    assert 'timeout 300 "$P" -' in b
    assert "vacuum" not in b.lower()


def test_stage3_waits_on_a_marker_the_block_never_prints():
    assert 'grep -q "replay exit"' in STAGE3.read_text()
    printed = re.findall(r'say "([^"]*)"', _block()) + re.findall(r'print\(f"([^"]*)"', _block())
    assert printed and not any("replay exit" in p for p in printed)


def _run(tmp_path, rep: int, python_rc: int) -> subprocess.CompletedProcess:
    stub = tmp_path / "python"
    stub.write_text(f"#!/bin/sh\ncat >/dev/null\necho STUB_ANALYZE\nexit {python_rc}\n")
    stub.chmod(0o755)
    script = (f'P={stub}\nsay() {{ echo "$*"; }}\nset -euo pipefail\nset +e\n'
              f"REP={rep}\n{_block()}set -e\n"
              'say "replay exit ${REP}"\necho CONTINUED\n')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


def test_success_runs_analyze_before_the_replay_exit_line(tmp_path):
    out = _run(tmp_path, rep=0, python_rc=0)
    lines = out.stdout.split()
    assert out.returncode == 0
    assert out.stdout.splitlines() == ["STUB_ANALYZE", "analyze_preopen exit 0",
                                       "replay exit 0", "CONTINUED"], lines


def test_analyze_failure_is_logged_and_the_replay_result_is_unchanged(tmp_path):
    out = _run(tmp_path, rep=0, python_rc=1)
    assert out.returncode == 0
    assert out.stdout.splitlines() == ["STUB_ANALYZE", "analyze_preopen exit 1",
                                       "replay exit 0", "CONTINUED"]


def test_failed_replay_skips_analyze(tmp_path):
    out = _run(tmp_path, rep=1, python_rc=0)
    assert out.stdout.splitlines() == ["replay exit 1", "CONTINUED"]


def test_final_exit_still_comes_only_from_capture_replay_acceptance():
    assert RUNBOOK.read_text().rstrip().endswith("exit $(( CAP || REP || ACC ))")
