"""NSE trading-session contract.

Populated in M2; the contract is fixed here so M1 can reference session_date
and the pre-open window without guessing.

Two things V1 got wrong that this shape prevents:

1. Its holiday list was a flat text file with 8 dates for 2026 (NSE typically
   has ~14) that self-declared 2027 "INCOMPLETE". When 2026-09-14 produced no
   candles, nothing could tell whether that was a holiday or an outage. A
   session is therefore an explicit ROW with a source and a knowable_at, not an
   absence of one.

2. NSE is not always closed at the weekend and not always open 09:15-15:30.
   2026-02-01 (Sunday) was a full Budget-day session and 2026-11-08 (Sunday)
   is Diwali Muhurat, 18:00-19:00 IST. V1's Muhurat bar was anchored to 09:15,
   ~8 hours before trading began. Session times are per-row, never assumed.
"""

from __future__ import annotations

import datetime as _dt
import enum
from dataclasses import dataclass

from app.core.clock import REGULAR_CLOSE, REGULAR_OPEN, REGULAR_PREOPEN_END, REGULAR_PREOPEN_START


class SessionType(str, enum.Enum):
    NORMAL = "NORMAL"
    MUHURAT = "MUHURAT"
    SPECIAL = "SPECIAL"       # e.g. Budget-day weekend session
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"


@dataclass(frozen=True, slots=True)
class TradingSession:
    session_date: _dt.date
    is_trading_day: bool
    session_type: SessionType
    preopen_start_ist: _dt.time | None
    preopen_end_ist: _dt.time | None
    open_ist: _dt.time | None
    close_ist: _dt.time | None

    @property
    def has_preopen(self) -> bool:
        """Muhurat has no pre-open call auction; a normal session does."""
        return self.is_trading_day and self.preopen_start_ist is not None


def regular_session(day: _dt.date) -> TradingSession:
    """A standard NSE equity session. Used as a template, never as an assumption
    about a specific date — the calendar row is always the authority."""
    return TradingSession(
        session_date=day,
        is_trading_day=True,
        session_type=SessionType.NORMAL,
        preopen_start_ist=REGULAR_PREOPEN_START,
        preopen_end_ist=REGULAR_PREOPEN_END,
        open_ist=REGULAR_OPEN,
        close_ist=REGULAR_CLOSE,
    )
