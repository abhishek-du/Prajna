"""Watchlist and Telegram alerts (user 2026-10-22). PAPER RESEARCH ONLY: an alert is a
message; nothing here places, modifies or cancels an order.

The watchlist is var/dashboard/watchlist.json (symbols), edited from the dashboard.
In market hours, after every live cycle, each watched stock's live price is compared with
the levels of its plan from the PREVIOUS session's forward record (signals_log), so the
levels do not move during the day:

  BUY plan        ENTRY_ZONE (price at or below the entry), STOP, T1, T2
  HOLD / WAIT     BREAKOUT (price above the buy-only-above trigger)
  SELL / AVOID    DOWNSIDE_1, VIEW_STOP
  any             HIGH-impact AI-tagged news linked to the stock

Each (day, stock, event) is sent once (var/dashboard/alerts/<day>.json).
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import subprocess
from typing import Any

BASE = pathlib.Path(__file__).resolve().parents[2] / "var" / "dashboard"
WATCH = BASE / "watchlist.json"
SENT = BASE / "alerts"


def watchlist() -> list[str]:
    try:
        return sorted(set(json.loads(WATCH.read_text())))
    except (OSError, ValueError):
        return []


def set_watch(symbol: str, on: bool) -> list[str]:
    w = set(watchlist())
    (w.add if on else w.discard)(symbol.upper())
    BASE.mkdir(parents=True, exist_ok=True)
    tmp = WATCH.with_suffix(".part")
    tmp.write_text(json.dumps(sorted(w)))
    tmp.replace(WATCH)
    return sorted(w)


def events(plan: dict[str, Any] | None, price: float | None) -> list[tuple[str, str]]:
    """(event, text) for a live price against a plan's levels."""
    if not plan or price is None:
        return []
    a, out = plan.get("action"), []
    f = lambda x: f"{x:,.2f}"  # noqa: E731
    if a == "BUY":
        if plan.get("stop_loss") and price <= plan["stop_loss"]:
            out.append(("STOP", f"at/below stop-loss {f(plan['stop_loss'])}"))
        elif plan.get("t2") and price >= plan["t2"]:
            out.append(("T2", f"target T2 {f(plan['t2'])} reached"))
        elif plan.get("t1") and price >= plan["t1"]:
            out.append(("T1", f"target T1 {f(plan['t1'])} reached"))
        elif plan.get("entry") and price <= plan["entry"]:
            out.append(("ENTRY_ZONE", f"in the entry zone (entry {f(plan['entry'])}, "
                                      f"stop {f(plan['stop_loss'])})"))
    elif a == "HOLD / WAIT" and plan.get("buy_trigger") and price > plan["buy_trigger"]:
        out.append(("BREAKOUT", f"above the buy-only-above level {f(plan['buy_trigger'])}"))
    elif a == "SELL / AVOID":
        if plan.get("stop_loss") and price >= plan["stop_loss"]:
            out.append(("VIEW_STOP", f"above the SELL view's stop {f(plan['stop_loss'])}"))
        elif plan.get("t1") and price <= plan["t1"]:
            out.append(("DOWNSIDE_1", f"downside level {f(plan['t1'])} reached"))
    return out


def _sent(day: _dt.date) -> set[str]:
    try:
        return set(json.loads((SENT / f"{day}.json").read_text()))
    except (OSError, ValueError):
        return set()


def _mark(day: _dt.date, keys: set[str]) -> None:
    SENT.mkdir(parents=True, exist_ok=True)
    (SENT / f"{day}.json").write_text(json.dumps(sorted(keys)))


def due(day: _dt.date, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(id, text) not yet sent today; marks them as sent."""
    done = _sent(day)
    new = [(i, t) for i, t in candidates if i not in done]
    if new:
        _mark(day, done | {i for i, _ in new})
    return new


def log_path(day: _dt.date) -> pathlib.Path:
    return SENT / f"{day}.log.jsonl"


def send(notify: str, day: _dt.date, items: list[tuple[str, str]]) -> int:
    if not items:
        return 0
    text = "Prajna watchlist alert (paper research, not advice)\n" + "\n".join(
        f"- {t}" for _, t in items)
    try:
        ok = subprocess.run([notify], input=text[:3900], text=True, timeout=60,  # noqa: S603
                            capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    SENT.mkdir(parents=True, exist_ok=True)
    with log_path(day).open("a") as fh:
        for i, t in items:
            fh.write(json.dumps({"id": i, "text": t, "sent": ok,
                                 "at": _dt.datetime.now(_dt.UTC).isoformat()}) + "\n")
    return len(items)


def history(day: _dt.date) -> list[dict[str, Any]]:
    p = log_path(day)
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
