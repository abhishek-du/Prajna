"""Stage 2 data-availability states per (instrument, timeframe, session). Pure.

Per trading session, in this order:
  DATA              >= 1 stored bar (bars counted; quarantined counted too)
  QUARANTINED       no stored bar, but the vendor's bar(s) were quarantined (Q1)
  EMPTY             a COMPLETE ingest window (or a COMPLETE intraday run of that
                    day) covered the session and the vendor returned no bar
  VENDOR_ERROR      the latest attempt at a window covering it FAILED
  MISSING           inside the stream checkpoint, yet no COMPLETE window
                    covers it: an inconsistency (a quality gate fails on it)
  PENDING_BACKFILL  none of the above: the approved backfill has not reached it

Consecutive sessions in the same state collapse into one range. Nothing is
filled: no zero, no forward fill, no interpolation.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Window:
    from_date: _dt.date
    to_date: _dt.date
    status: str                     # COMPLETE / FAILED / ABORTED
    started_at: _dt.datetime


@dataclass(frozen=True, slots=True)
class Range:
    from_date: _dt.date
    to_date: _dt.date
    state: str
    sessions: int
    bars: int
    quarantined: int


def session_state(d: _dt.date, *, bars: int, quarantined: int, windows: list[Window],
                  checkpoint: tuple[_dt.date, _dt.date] | None) -> str:
    if bars > 0:
        return "DATA"
    if quarantined > 0:
        return "QUARANTINED"
    covering = [w for w in windows if w.from_date <= d <= w.to_date]
    if any(w.status == "COMPLETE" for w in covering):
        return "EMPTY"
    attempts = [w for w in covering if w.status in ("FAILED", "ABORTED")]
    if attempts and max(attempts, key=lambda w: w.started_at).status == "FAILED":
        return "VENDOR_ERROR"
    if checkpoint and checkpoint[0] <= d <= checkpoint[1]:
        return "MISSING"
    return "PENDING_BACKFILL"


def ranges(sessions: list[_dt.date], *, bars: dict[_dt.date, int],
           quarantined: dict[_dt.date, int], windows: list[Window],
           checkpoint: tuple[_dt.date, _dt.date] | None) -> list[Range]:
    out: list[Range] = []
    cur: list = []                  # [from, to, state, sessions, bars, quarantined]
    for d in sorted(sessions):
        b, q = bars.get(d, 0), quarantined.get(d, 0)
        st = session_state(d, bars=b, quarantined=q, windows=windows, checkpoint=checkpoint)
        if cur and cur[2] == st:
            cur[1], cur[3], cur[4], cur[5] = d, cur[3] + 1, cur[4] + b, cur[5] + q
        else:
            if cur:
                out.append(Range(*cur))
            cur = [d, d, st, 1, b, q]
    if cur:
        out.append(Range(*cur))
    return out
