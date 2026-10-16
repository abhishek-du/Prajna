"""Stage 7 step 2: load a session's bars, simulate (sim.py) and record the run (0022).

- Bars: the canonical 1d bar of the session (raw prices: what an order would have
  traded at) and the previous trading session's volume (the participation cap).
- Idempotent per (strategy, session): the same inputs again -> ALREADY_PRESENT, nothing
  written; different inputs -> refused (a stored paper day is never overwritten).
- Writes need the write token (authorize_write at the write path). Every row is
  mode 'PAPER' (and the database refuses anything else).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import uuid
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.clock import now
from app.core.errors import PrajnaError
from app.paper import sim

STRATEGY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class PaperRefused(PrajnaError):
    """A paper run that would contradict a stored one, or invalid input."""


def _d(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(x, 4)))


def targets_sha(targets: list[str]) -> str:
    return hashlib.sha256(json.dumps(targets).encode()).hexdigest()


async def load_bars(s: AsyncSession, session_date: _dt.date,
                    keys: list[str]) -> tuple[dict[str, sim.Bar], _dt.datetime | None]:
    """The session's 1d bars and the previous session's volume, for the given keys."""
    prev = (await s.execute(text("""select max(session_date) from trading_session
        where is_trading_day and session_date < :d"""), {"d": session_date})).scalar()
    rows = (await s.execute(text("""
        select b.instrument_key, b.open, b.high, b.low, b.close, b.knowable_at,
               p.volume as prev_volume
        from canon_market_bar b
        left join canon_market_bar p on p.instrument_key = b.instrument_key
             and p.timeframe = '1d' and p.market_date = :p
        where b.timeframe = '1d' and b.market_date = :d
          and b.instrument_key = any(:k)"""),
        {"d": session_date, "p": prev, "k": keys})).all()
    bars = {r.instrument_key: sim.Bar(*(None if v is None else float(v) for v in
                                        (r.open, r.high, r.low, r.close, r.prev_volume)))
            for r in rows}
    return bars, max((r.knowable_at for r in rows), default=None)


async def simulate_session(s: AsyncSession, strategy: str, session_date: _dt.date,
                           targets: list[str], cfg: sim.Config | None = None, *,
                           commit: bool = False, token: str | None = None,
                           code_git_sha: str = "unknown") -> dict[str, Any]:
    if not STRATEGY_RE.match(strategy):
        raise PaperRefused(f"strategy name {strategy!r}: [A-Za-z0-9_.-]{{1,64}}")
    if not targets:
        raise PaperRefused("no targets")
    cfg = cfg or sim.Config()
    fp = authorize_write(token) if commit else None          # before anything is read
    bars, knowable = await load_bars(s, session_date, targets)
    if not bars:
        raise PaperRefused(f"no stored 1d bar on {session_date} for any target "
                           "(the daily bar is stored the next morning)")
    res = sim.simulate(targets, bars, cfg)
    out = {"strategy": strategy, "session_date": str(session_date), "commit": commit,
           "targets_sha256": targets_sha(targets), "bars_found": len(bars),
           **{k: v for k, v in res.items() if k != "fills"}, "fills": res["fills"]}
    old = (await s.execute(text("""select run_id, inputs_sha256 from paper_run
        where strategy = :s and session_date = :d"""),
        {"s": strategy, "d": session_date})).first()
    if old is not None:
        if old.inputs_sha256 != res["sha256"]:
            raise PaperRefused(f"{strategy} {session_date} is stored with other inputs "
                               f"(run {old.run_id}); a paper day is never overwritten")
        return {**out, "status": "ALREADY_PRESENT", "run_id": str(old.run_id)}
    if not commit:
        return {**out, "status": "DRY_RUN"}
    rid = uuid.uuid4()
    cfg_json = {**asdict(cfg), "rates": asdict(cfg.rates)}
    await s.execute(text("""insert into paper_run (run_id, strategy, session_date, mode,
        targets_sha256, inputs_sha256, config, bars_knowable_max, code_git_sha,
        authz_token_sha256, created_at) values (:r, :s, :d, :m, :t, :i, cast(:c as jsonb),
        :k, :g, :a, :n)"""),
        {"r": rid, "s": strategy, "d": session_date, "m": sim.MODE,
         "t": out["targets_sha256"], "i": res["sha256"], "c": json.dumps(cfg_json),
         "k": knowable, "g": code_git_sha, "a": fp, "n": now()})
    await s.execute(text("""insert into paper_order (run_id, seq, instrument_key, product,
        order_value_inr, mode) values (:r, :q, :k, 'MIS', :v, :m)"""),
        [{"r": rid, "q": i, "k": k, "v": _d(cfg.order_value_inr), "m": sim.MODE}
         for i, k in enumerate(targets)])
    await s.execute(text("""insert into paper_fill (run_id, instrument_key, status, reason,
        qty, buy_px, sell_px, buy_value_inr, sell_value_inr, charges, pnl_inr, mode)
        values (:r, :k, :st, :re, :q, :bp, :sp, :bv, :sv, cast(:c as jsonb), :p, :m)"""),
        [{"r": rid, "k": f["key"], "st": f["status"], "re": f["reason"], "q": f["qty"],
          "bp": _d(f["buy_px"]), "sp": _d(f["sell_px"]), "bv": _d(f["buy_value"]),
          "sv": _d(f["sell_value"]), "c": json.dumps(f["charges"]), "p": _d(f["pnl_inr"]),
          "m": f["mode"]} for f in res["fills"]])
    await s.execute(text("""insert into paper_day (run_id, session_date, targets, filled,
        not_filled, start_cash_inr, end_cash_inr, pnl_inr, charges_inr, turnover_inr, mode)
        values (:r, :d, :t, :f, cast(:nf as jsonb), :sc, :ec, :p, :ch, :tu, :m)"""),
        {"r": rid, "d": session_date, "t": res["targets"], "f": res["filled"],
         "nf": json.dumps(res["not_filled"]), "sc": _d(res["start_cash"]),
         "ec": _d(res["end_cash"]), "p": _d(res["pnl_inr"]), "ch": _d(res["charges_inr"]),
         "tu": _d(res["turnover_inr"]), "m": sim.MODE})
    await s.commit()
    return {**out, "status": "WRITTEN", "run_id": str(rid)}
