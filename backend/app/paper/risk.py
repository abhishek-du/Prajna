"""Stage 6, generic part: strategy-independent limits applied to a TargetList before it is
simulated. PURE. Every target gets a decision; a rejection names its rule.

Rules, in order (the first that fails rejects the target):
  halted_drawdown     the strategy's paper drawdown >= max_drawdown_halt: nothing trades
  halted_daily_loss   the previous paper day lost >= daily_loss_halt of capital
  min_price           previous close < min_price
  min_turnover        median daily turnover < min_turnover_inr (unknown -> rejected)
  sector_cap          more than max_names_per_sector approved names in one sector
                      (an unknown sector counts as its own sector, "UNKNOWN")
  max_positions       more than max_positions approved names
Strategy-dependent risk (stops, targets, volatility sizing) is NOT here: it waits for the
exit design (E4b).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.paper.targets import TargetList


@dataclass(frozen=True)
class Limits:
    max_positions: int = 10
    max_names_per_sector: int = 3
    min_price: float = 50.0
    min_turnover_inr: float = 5e7                 # Rs 5 crore median daily turnover
    max_drawdown_halt: float = 0.10               # of capital
    daily_loss_halt: float = 0.03                 # of capital

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class State:
    """The strategy's paper record before this session (from paper_day)."""
    capital_inr: float
    drawdown_inr: float = 0.0                    # peak cumulative P&L - current, >= 0
    last_day_pnl_inr: float = 0.0


def apply(tl: TargetList, ctx: dict[str, dict[str, Any]], state: State,
          limits: Limits | None = None) -> tuple[TargetList, list[dict[str, Any]]]:
    lim = limits or Limits()
    halt = None
    if state.drawdown_inr >= lim.max_drawdown_halt * state.capital_inr:
        halt = "halted_drawdown"
    elif -state.last_day_pnl_inr >= lim.daily_loss_halt * state.capital_inr:
        halt = "halted_daily_loss"
    approved: list[str] = []
    per_sector: dict[str, int] = {}
    decisions = []
    for t in tl.entries:
        c = ctx.get(t.key, {})
        sector = c.get("sector") or "UNKNOWN"
        pc, to = c.get("prev_close"), c.get("turnover")
        if halt:
            why = halt
        elif pc is None or pc < lim.min_price:
            why = "min_price"
        elif to is None or to < lim.min_turnover_inr:
            why = "min_turnover"
        elif per_sector.get(sector, 0) >= lim.max_names_per_sector:
            why = "sector_cap"
        elif len(approved) >= lim.max_positions:
            why = "max_positions"
        else:
            why = None
            approved.append(t.key)
            per_sector[sector] = per_sector.get(sector, 0) + 1
        decisions.append({"rank": t.rank, "key": t.key,
                          "decision": "REJECTED" if why else "APPROVED", "reason": why})
    return tl.with_entries(approved), decisions
