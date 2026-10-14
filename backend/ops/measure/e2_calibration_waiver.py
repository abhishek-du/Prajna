"""E2 calibration waiver W (Amendment 2 rev 2, §6.5; approved by the user 2026-10-14):
accept correction C-a although its second pre-set criterion (the two-sided Wilson
interval contains 2.5%) failed - ONLY when every failure is on the CONSERVATIVE side.

  .venv/bin/python ops/measure/e2_calibration_waiver.py --approved-by user --reason "..."

Reads var/stage4/experiments/e2/null_calibration_studentized.json (never edited) and
writes null_calibration_studentized_waiver.json (never overwritten) only if:
  1  the source has >= 1,000 worlds, ci_method studentized, and criterion 1 holds:
     k20 ACCEPTED-EXPLORATORY Wilson upper bound <= 2.5% in every world type
  2  every world type where criterion 2 failed failed BELOW: Wilson upper < 2.5% (too
     conservative), never above
The waiver records the source sha256, the code sha it calibrated (the runner checks it
against the current code), the reason, the approver and the time. No E2 data is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.clock import IST, now  # noqa: E402

OUT = ROOT / "var/stage4/experiments/e2"
SOURCE, WAIVER = OUT / "null_calibration_studentized.json", \
    OUT / "null_calibration_studentized_waiver.json"
K20, BOUND = "k20", 0.025


def evaluate(src: dict) -> tuple[bool, list[str], list[str]]:
    """(waivable, problems, conservative failures) of a studentized calibration."""
    problems, conservative = [], []
    if src.get("worlds", 0) < 1000:
        problems.append(f"{src.get('worlds')} worlds < 1000")
    if src.get("ci_method") != "studentized":
        problems.append(f"ci_method {src.get('ci_method')!r} is not studentized")
    for kind, w in sorted(src.get("by_world", {}).items()):
        k = w[K20]
        if k["accepted"]["wilson95"][1] > BOUND:
            problems.append(f"{kind}: accepted upper {k['accepted']['wilson95'][1]} > {BOUND}")
        lo, hi = k["ci_excludes_0"]["wilson95"]
        if lo > BOUND:
            problems.append(f"{kind}: two-sided rate too HIGH ({lo}..{hi}): anti-conservative")
        elif hi < BOUND:
            conservative.append(f"{kind}: two-sided {k['ci_excludes_0']['rate']} "
                                f"({lo}..{hi}) < {BOUND}: conservative")
    if not src.get("by_world"):
        problems.append("no world results")
    return not problems, problems, conservative


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-by", required=True)
    ap.add_argument("--reason", required=True)
    a = ap.parse_args()
    body = SOURCE.read_bytes()
    src = json.loads(body)
    ok, problems, conservative = evaluate(src)
    if not ok:
        raise SystemExit(f"REFUSED: not waivable: {problems}")
    if WAIVER.exists():
        raise SystemExit(f"REFUSED: {WAIVER.name} exists; not overwritten")
    out = {"worlds": src["worlds"], "ci_method": src["ci_method"],
           "code_sha256": src["code_sha256"], "adequate": True,
           "waiver": {"option": "W", "criterion_waived": "2 (two-sided Wilson interval "
                      "contains 2.5%), conservative side only",
                      "conservative_failures": conservative, "reason": a.reason,
                      "approved_by": a.approved_by,
                      "at": now().astimezone(IST).isoformat()},
           "source_file": SOURCE.name,
           "source_sha256": hashlib.sha256(body).hexdigest(),
           "source_adequate": src["adequate"], "source_criterion": src["criterion"]}
    text = json.dumps(out, indent=1, sort_keys=True)
    WAIVER.write_text(text)
    print(json.dumps({**out, "written": str(WAIVER),
                      "sha256": hashlib.sha256(text.encode()).hexdigest()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
