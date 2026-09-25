"""ops/runbooks/global_refresh.sh (phase 5): markers, hard stop, no token in
argv, and the finality summary never counting the CLI's row-count footer."""

from __future__ import annotations

import pathlib
import re
import subprocess

RB = pathlib.Path(__file__).resolve().parents[2] / "ops" / "runbooks" / "global_refresh.sh"


def test_markers_hard_stop_and_env_token():
    body = RB.read_text()
    for m in ("GLOBAL_REFRESH_STARTED", "GLOBAL_REFRESH_", "GLOBAL_REVISION_DETECTED",
              "GLOBAL_VENDOR_ABSENT", "GLOBAL_FINALITY", "PARTIAL"):
        assert m in body, m
    assert "timeout -k 60 --signal=INT 900" in body
    assert "PRAJNA_SUPPLIED_TOKEN" in body and "--token" not in body and "--login" not in body


def test_finality_summary_ignores_the_row_count_footer():
    awk = re.search(r"awk '([^']*)'", [ln for ln in RB.read_text().splitlines()
                                        if ln.startswith("fin=")][0]).group(1)
    table = ("finality          count\n----------------  -----\nCONFIRMED         48\n"
             "REVISED           1\n\n5 row(s)\n")
    lines = "\n".join(table.splitlines()[2:9]) + "\n"          # the script's sed -n '3,9p'
    out = subprocess.run(["awk", awk], input=lines, capture_output=True, text=True).stdout
    assert out == "CONFIRMED=48 REVISED=1 "
