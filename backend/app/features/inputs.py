"""Feature inputs, gathered ONLY through the Stage 2 point-in-time API
(app.canon.pit): every row is knowable strictly before the snapshot instant.

Two extra guards on top of pit's own check:
  * no daily bar of the snapshot's session (or later) is used: the session has
    not traded at a pre-session / pre-open instant;
  * each input carries its knowable_at; the maximum over everything a value used
    is recorded and must be < as_of (also a CHECK on feature_value).

Staleness: bar-based features describe the PREVIOUS session. When that
session's bar is not knowable at as_of (late or missing ingestion), they are
MISSING_INPUT; an older bar is never silently used in its place.

Price basis / corporate actions: stock bars come from pit.bars_adjusted, i.e.
split/bonus-adjusted with factors KNOWABLE before as_of; LOW-confidence rows
(vendor-adjusted history older than the corporate-action horizon, unknown
treatment, no recorded basis) and RECONSTRUCTED rows are refused, counted, and
never used. Index bars need no adjustment (no corporate actions) and come from
pit.bars.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.features.compute import Bar
from app.features.snapshots import Snapshot

DAILY_LOOKBACK_DAYS = 450          # >= 260 sessions: SMA 200 + beta 60 + slack


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class LookAhead(AssertionError):
    """An input knowable at/after as_of reached the feature layer (must never happen)."""


@dataclass
class Tracked:
    """A group of inputs with its provenance: content hash and latest knowable_at."""
    sha256: str
    max_knowable_at: _dt.datetime | None


def _track(rows: list[dict], as_of: _dt.datetime, what: str, keys: tuple[str, ...]) -> Tracked:
    kn = [r["knowable_at"] for r in rows if r.get("knowable_at") is not None]
    if any(k >= as_of for k in kn):
        raise LookAhead(f"{what}: an input with knowable_at >= as_of")
    return Tracked(_h([[r.get(k) for k in keys] for r in rows]), max(kn) if kn else None)


def _bars(rows: list[dict]) -> list[Bar]:
    return [Bar(r["market_date"], float(r["open"]), float(r["high"]), float(r["low"]),
                float(r["close"]), float(r["volume"])) for r in rows]


@dataclass
class InstrumentInputs:
    key: str
    daily: list[Bar]
    refused: dict[str, int]
    fundamentals: dict[str, Any]              # statement_type -> payload
    corporate_actions: list[dict[str, Any]]
    news_published: list[_dt.datetime]
    preopen_tick: dict[str, Any] | None
    tracked: dict[str, Tracked] = field(default_factory=dict)
    previous_session: _dt.date | None = None

    @property
    def stale(self) -> bool:
        """The previous session's bar is not knowable at as_of (late or missing):
        bar-based features would describe an older session, so they are refused."""
        return bool(self.daily) and self.daily[-1].day != self.previous_session

    def provenance(self, groups: tuple[str, ...]) -> tuple[str, _dt.datetime | None]:
        t = [self.tracked[g] for g in groups if g in self.tracked]
        kn = [x.max_knowable_at for x in t if x.max_knowable_at is not None]
        return _h([x.sha256 for x in t]), (max(kn) if kn else None)


async def instrument_inputs(s: AsyncSession, key: str, snap: Snapshot) -> InstrumentInputs:
    as_of, day = snap.as_of, snap.session_date
    start = day - _dt.timedelta(days=DAILY_LOOKBACK_DAYS)
    adj = await pit.bars_adjusted(s, key, "1d", as_of, start=start)
    rows = [r for r in adj["rows"] if r["market_date"] < day]
    tracked = {"daily_bars": _track(rows, as_of, f"{key} daily", (
        "market_date", "open", "high", "low", "close", "volume", "payload_sha256",
        "adjustment_status", "basis_confidence"))}
    funds = await pit.fundamentals(s, key, as_of)
    tracked["fundamentals"] = _track(funds, as_of, f"{key} fundamentals",
                                     ("statement_type", "knowable_at", "payload_sha256"))
    ca = await pit.corporate_actions(s, as_of, key)
    tracked["corporate_actions"] = _track(ca, as_of, f"{key} corporate actions",
                                          ("id", "action_type", "ex_date", "knowable_at"))
    news = await pit.news(s, as_of, key, since=as_of - _dt.timedelta(days=8))
    tracked["news"] = _track(news, as_of, f"{key} news", ("news_id", "published_at", "knowable_at"))
    tick = None
    if snap.kind == "PRE_OPEN":
        ticks = await pit.preopen(s, key, as_of, market_date=day)
        tick = ticks[-1] if ticks else None
        tracked["preopen"] = _track(ticks[-1:], as_of, f"{key} pre-open",
                                    ("tick_id", "event_ts", "iep", "ieq", "tbq", "tsq"))
    return InstrumentInputs(
        key=key, daily=_bars(rows), refused=dict(adj["refused"]),
        fundamentals={f["statement_type"]: f["payload"] for f in funds},
        corporate_actions=[{"id": c["id"], "action_type": c["action_type"],
                            "ex_date": c["ex_date"]} for c in ca],
        news_published=[n["published_at"] for n in news if n.get("published_at")],
        preopen_tick=tick, tracked=tracked, previous_session=snap.previous_session)


async def index_bars(s: AsyncSession, key: str, snap: Snapshot) -> tuple[list[Bar], Tracked]:
    start = snap.session_date - _dt.timedelta(days=DAILY_LOOKBACK_DAYS)
    rows = [r for r in await pit.bars(s, key, "1d", snap.as_of, start=start)
            if r["market_date"] < snap.session_date]
    return _bars(rows), _track(rows, snap.as_of, f"{key} daily",
                               ("market_date", "close", "high", "low", "volume", "payload_sha256"))


async def macro_rows(s: AsyncSession, snap: Snapshot) -> tuple[list[dict], Tracked]:
    rows = [r for r in await pit.macro(s, snap.as_of)
            if r["series_code"].split("|", 1)[0] in ("FII", "DII")]
    return rows, _track(rows, snap.as_of, "FII/DII", ("series_code", "observation_date", "value"))


async def global_closes(s: AsyncSession, key: str, snap: Snapshot) -> tuple[list[float], Tracked]:
    rows = await pit.global_bars(s, key, snap.as_of)     # confirmed labels only
    rows = rows[-2:]
    return [float(r["close"]) for r in rows], _track(rows, snap.as_of, f"{key} global",
                                                     ("label_date", "close", "finality"))
