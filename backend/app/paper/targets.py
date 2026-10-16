"""The Stage 5 -> Stage 7 contract: a session's target list (docs/STAGE7_8_PAPER_DESIGN.md).

Any strategy (a baseline here, the E4 runner or a model later) hands the paper job one
TargetList. It is validated before anything is simulated:
  - strategy name [A-Za-z0-9_.-]{1,64}; keys unique; ranks 1..n in order
  - entry / exit rules the simulator implements (today: OPEN -> CLOSE, MIS)
  - decided before the entry: decision_at (tz-aware) <= 09:15 IST of the session
The JSON form is canonical (sorted keys), so its sha256 identifies the list.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.clock import IST

STRATEGY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
ENTRY_RULES = ("OPEN",)            # market order at the official open
EXIT_RULES = ("CLOSE",)            # square off at the official close (MIS)
OPEN_IST = _dt.time(9, 15)


class TargetListError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    key: str
    rank: int
    score: float | None = None


@dataclass(frozen=True)
class TargetList:
    strategy: str
    session_date: _dt.date
    decision_at: _dt.datetime
    entries: tuple[Target, ...]
    source: str
    entry_rule: str = "OPEN"
    exit_rule: str = "CLOSE"
    meta: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> TargetList:
        if not STRATEGY_RE.match(self.strategy):
            raise TargetListError(f"strategy name {self.strategy!r}")
        if self.entry_rule not in ENTRY_RULES or self.exit_rule not in EXIT_RULES:
            raise TargetListError(f"rules {self.entry_rule}->{self.exit_rule} not simulated "
                                  f"(supported: {ENTRY_RULES} -> {EXIT_RULES})")
        if self.decision_at.tzinfo is None:
            raise TargetListError("decision_at must be timezone-aware")
        entry = _dt.datetime.combine(self.session_date, OPEN_IST, tzinfo=IST)
        if self.decision_at > entry:
            raise TargetListError(f"decided at {self.decision_at.isoformat()}, after the "
                                  f"entry {entry.isoformat()}: look-ahead")
        keys = [t.key for t in self.entries]
        if len(set(keys)) != len(keys):
            raise TargetListError("duplicate keys")
        if [t.rank for t in self.entries] != list(range(1, len(keys) + 1)):
            raise TargetListError("ranks must be 1..n in order")
        return self

    @property
    def keys(self) -> list[str]:
        return [t.key for t in self.entries]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["session_date"] = self.session_date.isoformat()
        d["decision_at"] = self.decision_at.isoformat()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TargetList:
        return cls(strategy=d["strategy"],
                   session_date=_dt.date.fromisoformat(d["session_date"]),
                   decision_at=_dt.datetime.fromisoformat(d["decision_at"]),
                   entries=tuple(Target(**t) for t in d["entries"]), source=d["source"],
                   entry_rule=d.get("entry_rule", "OPEN"), exit_rule=d.get("exit_rule", "CLOSE"),
                   meta=d.get("meta", {})).validate()

    def with_entries(self, keys: list[str]) -> TargetList:
        """The same list restricted to keys (order kept, ranks renumbered)."""
        by = {t.key: t for t in self.entries}
        return TargetList(self.strategy, self.session_date, self.decision_at,
                          tuple(Target(k, i + 1, by[k].score) for i, k in enumerate(keys)),
                          self.source, self.entry_rule, self.exit_rule, self.meta)
