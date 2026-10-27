"""The Telegram text after a desk run: the decision mix, the watchlist changes and the top
new BUY calls with their levels. Reads the run's JSON output (the CLI's stdout file).

    .venv/bin/python -m app.desk.summary var/logs/desk/evening_<stamp>.json
"""

from __future__ import annotations

import json
import sys
from typing import Any


def render(res: dict[str, Any]) -> str:
    if res.get("status") != "WRITTEN":
        return ""
    c = res.get("counts") or {}
    ev = res.get("watchlist_events") or []
    lines = [f"Prajna Research Desk {res['mode']} {res['session']} (paper; not advice)",
             f"Investigated {c.get('investigated')}: " + ", ".join(
                 f"{k} {v}" for k, v in sorted((c.get("mix") or {}).items())),
             f"Overrides of the rules: {c.get('conflicts', 0)}"]
    adds = [e for e in ev if e["event"] == "ADD"]
    rems = [e for e in ev if e["event"] == "REMOVE"]
    if adds:
        lines.append("Added to the watchlist: " + ", ".join(
            f"{e.get('symbol')} ({e['decision']} {e['score']})" for e in adds[:15]))
    if rems:
        lines.append("Removed: " + ", ".join(f"{e.get('symbol')} ({e['reason']})"
                                              for e in rems[:15]))
    if not adds and not rems:
        lines.append("No watchlist change.")
    lines.append("Details: http://127.0.0.1:8600/#/desk")
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        print(render(json.loads(open(sys.argv[1]).read())))
    except (OSError, ValueError, IndexError):
        print("")
