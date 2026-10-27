"""Pure forensics: the path of a trade on 1-minute bars (MFE / MAE, the target after the
exit), the outcome class with the rule that assigned it, and the reasons a strategy's day
went the way it did. No database, no clock: every input is passed in."""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.lab import registry as RG

MARKET_TURN = 0.003          # Nifty moving >= 0.3 % against the trade counts as a turn
GAVE_BACK_R = 1.0            # up >= 1 R before a stop: the trade "gave it back"
GAVE_BACK_PCT = 0.01         # open->close trades: up >= 1 % before closing at a loss


@dataclass(frozen=True, slots=True)
class Bar:
    start: _dt.datetime
    end: _dt.datetime
    high: float
    low: float
    close: float


def excursion(bars: Sequence[Bar], side: int, entry_px: float, entry_at: _dt.datetime,
              exit_at: _dt.datetime, stop: float | None = None,
              target: float | None = None) -> dict[str, Any]:
    """Maximum favourable and adverse excursion inside [entry_at, exit_at] (in % of the
    entry and, with a stop, in R), and whether the target traded after the exit."""
    inside = [b for b in bars if b.start >= entry_at and b.end <= exit_at]
    after = [b for b in bars if b.start >= exit_at]
    out: dict[str, Any] = {"bars": len(inside), "mfe_pct": None, "mae_pct": None,
                           "mfe_r": None, "mae_r": None, "target_after_exit": None}
    if not inside or not entry_px:
        return out
    hi, lo = max(b.high for b in inside), min(b.low for b in inside)
    fav, adv = (hi - entry_px, entry_px - lo) if side > 0 else (entry_px - lo, hi - entry_px)
    out["mfe_pct"], out["mae_pct"] = max(fav, 0.0) / entry_px, max(adv, 0.0) / entry_px
    risk = abs(entry_px - stop) if stop is not None else 0.0
    if risk > 0:
        out["mfe_r"], out["mae_r"] = max(fav, 0.0) / risk, max(adv, 0.0) / risk
    if target is not None and after:
        out["target_after_exit"] = any(b.high >= target for b in after) if side > 0 \
            else any(b.low <= target for b in after)
    return out


def index_move(bars: Sequence[Bar], t0: _dt.datetime, t1: _dt.datetime) -> float | None:
    """The index return from the last bar closed by t0 to the last bar closed by t1."""
    a = [b for b in bars if b.end <= t0]
    z = [b for b in bars if b.end <= t1]
    if not a or not z or not a[-1].close:
        return None
    return z[-1].close / a[-1].close - 1


def classify(t: dict[str, Any]) -> tuple[str, str]:
    """(outcome_class, the rule that fired). `t` carries exit_reason, net_inr, side,
    target_after_exit, mfe_r, mfe_pct, news_after (list) and index_move (entry->exit)."""
    reason, net = t.get("exit_reason"), t.get("net_inr")
    against = None if t.get("index_move") is None else -t["side"] * t["index_move"]
    if reason in (None, "NOT_FILLED"):
        return "NOT_FILLED", "no fill: the order could not be simulated"
    if reason == "NO_EXIT_BAR":
        return "NO_DATA", "no exit bar: the path could not be priced"
    if reason == "TARGET":
        return "TARGET_HIT", "exit reason TARGET"
    if reason == "STOP_GAP":
        return "GAP_THROUGH_STOP", "exit reason STOP_GAP: a bar opened beyond the stop"
    if reason == "STOP":
        if t.get("news_after"):
            return "NEWS_SHOCK", "stopped, and a linked news item became knowable in the trade"
        if t.get("target_after_exit"):
            return "STOPPED_IN_NOISE", "stopped, then the target traded later the same day"
        if against is not None and against >= MARKET_TURN:
            return "MARKET_TURNED", f"stopped while Nifty moved >= {MARKET_TURN:.1%} against"
        if (t.get("mfe_r") or 0) >= GAVE_BACK_R:
            return "GAVE_BACK", f"stopped after being up >= {GAVE_BACK_R:g} R"
        return "STOPPED", "exit reason STOP"
    win = net is not None and net > 0
    if reason in ("TIME_NOT_WORKING", "EOD"):
        return ("TIME_EXIT_WIN", f"exit reason {reason}, net > 0") if win \
            else ("TIME_EXIT_LOSS", f"exit reason {reason}, net <= 0")
    if reason == "CLOSE":            # open -> close paper / E5 trades
        if win:
            return "CLOSE_WIN", "sold at the close for a net gain"
        if t.get("news_after"):
            return "NEWS_SHOCK", "closed at a loss; a linked news item arrived in the session"
        if against is not None and against >= MARKET_TURN:
            return ("MARKET_AGAINST",
                    f"closed at a loss while Nifty moved >= {MARKET_TURN:.1%} against")
        if (t.get("mfe_pct") or 0) >= GAVE_BACK_PCT:
            return "GAVE_BACK", f"closed at a loss after being up >= {GAVE_BACK_PCT:.0%}"
        return "CLOSE_LOSS", "sold at the close for a net loss"
    if reason == "OPEN_POSITION":
        return ("OPEN_GAIN", "still open, marked above entry") if win \
            else ("OPEN_LOSS", "still open, marked at or below entry")
    return "OTHER", f"exit reason {reason}"


LABELS = {
    "TARGET_HIT": ("target reached", "target mil gaya"),
    "GAP_THROUGH_STOP": ("price jumped through the stop", "daam stop ke paar kood gaya"),
    "NEWS_SHOCK": ("news arrived during the trade", "trade ke dauran news aayi"),
    "STOPPED_IN_NOISE": ("stop was inside the day's noise (target hit later)",
                         "stop shor ke andar tha (baad mein target aaya)"),
    "MARKET_TURNED": ("the market turned against the trade", "market trade ke ulta mud gaya"),
    "MARKET_AGAINST": ("the market moved against the trade", "market trade ke ulta chala"),
    "GAVE_BACK": ("was in profit, then gave it back", "profit mein tha, phir wapas gaya"),
    "STOPPED": ("stop-loss hit", "stop-loss laga"),
    "TIME_EXIT_WIN": ("time exit with a gain", "time par nikle, fayde mein"),
    "TIME_EXIT_LOSS": ("time exit with a loss", "time par nikle, nuksaan mein"),
    "CLOSE_WIN": ("closed in profit", "close par fayde mein"),
    "CLOSE_LOSS": ("closed at a loss", "close par nuksaan mein"),
    "OPEN_GAIN": ("open, in profit", "khula hai, fayde mein"),
    "OPEN_LOSS": ("open, at a loss", "khula hai, nuksaan mein"),
    "NOT_FILLED": ("not filled", "order nahi bhara"),
    "NO_DATA": ("no data to price", "data nahi"),
    "OTHER": ("other", "anya"),
}
SKIP_TEXT = {
    "SKIP_RRR": "reward/risk too low", "CHECKLIST_LT4": "checklist under 4 of 6",
    "CAP_OPEN_RISK": "open-risk cap", "CAP_SECTOR": "sector cap", "CAP_LIQUIDITY": "liquidity cap",
    "HALT_DAILY": "daily loss halt", "MOVE_GT_3PCT": "moved > 3 % (news-like)",
    "NO_INTRADAY_BARS": "no intraday bars", "VOL_TOO_HIGH": "ATR% above 3 %",
    "SR_BLOCKED": "resistance in the way", "NO_SR_ZONE": "no support zone near",
    "HALT_FIRST_STOP": "no entries after the first stop", "SWITCHED_OFF": "switched off by admin",
}


def _why(code: str, en: str, hi: str) -> dict[str, str]:
    return {"code": code, "en": en, "hi": hi}


def day_why(strategy: str, trades: Sequence[dict[str, Any]], *, regime_pre: str | None,
            day_type: str | None, skips: dict[str, int] | None = None,
            placebo_net: float | None = None, enabled: bool | None = True) -> list[dict]:
    """The reasons a strategy's day went the way it did, from facts only. Each reason has a
    code and an English and Hinglish sentence."""
    meta = RG.BY_NAME.get(strategy)
    out: list[dict] = []
    real = [t for t in trades if not t.get("is_placebo") and t.get("exit_reason") != "NOT_FILLED"]
    if enabled is False:
        out.append(_why("SWITCHED_OFF", "Switched off by the admin: no trades.",
                        "Admin ne band kiya tha: koi trade nahi."))
        return out
    if not real:
        top = sorted((skips or {}).items(), key=lambda kv: -kv[1])[:3]
        if top:
            txt = ", ".join(f"{SKIP_TEXT.get(k, k)} ({n})" for k, n in top)
            out.append(_why("NO_TRADE_FILTERED", f"No trade: candidates were rejected by {txt}.",
                            f"Koi trade nahi: candidates in rules se ruke: {txt}."))
        else:
            out.append(_why("NO_SIGNAL", "No trade: no stock met the entry conditions.",
                            "Koi trade nahi: kisi stock ne entry ki shartein poori nahi ki."))
    if meta is not None and meta.tool in RG.FIT_DAY and day_type:
        fit = day_type in RG.FIT_DAY[meta.tool]
        kind = "trend" if meta.tool == "TREND" else "range"
        if real and not fit and day_type != "UNCLEAR":
            out.append(_why("REGIME_MISFIT",
                            f"A {kind} tool traded on a {day_type} day: the market did not "
                            "suit it.",
                            f"{kind.title()} wali strategy {day_type} din par chali: market "
                            "uske hisaab ka nahi tha."))
        elif real and fit:
            out.append(_why("REGIME_FIT", f"The day ({day_type}) suited this {kind} tool.",
                            f"Din ({day_type}) is {kind} strategy ke hisaab ka tha."))
    if meta is not None and meta.tool in RG.FIT_STATE and regime_pre:
        if regime_pre in ("MIXED", "SHOCK", "EVENT_WAIT") and real:
            out.append(_why("REGIME_CAUTION",
                            f"The morning regime was {regime_pre}: the planned size for P3 "
                            "is reduced or zero.",
                            f"Subah ka mood {regime_pre} tha: P3 mein is din size kam ya "
                            "zero hota."))
    if real:
        cls = Counter(t["outcome_class"] for t in real)
        wins = sum(1 for t in real if (t.get("net_inr") or 0) > 0)
        net = sum(float(t.get("net_inr") or 0) for t in real)
        out.append(_why("RESULT", f"{len(real)} trades, {wins} won, net ₹{net:,.0f}.",
                        f"{len(real)} trades, {wins} jeete, net ₹{net:,.0f}."))
        losing = [(c, n) for c, n in cls.most_common()
                  if c not in ("TARGET_HIT", "TIME_EXIT_WIN", "CLOSE_WIN", "OPEN_GAIN")]
        if losing:
            c, n = losing[0]
            en, hi = LABELS.get(c, (c, c))
            out.append(_why(f"MAIN_{c}", f"Main loss driver: {en} ({n} of {len(real)}).",
                            f"Nuksaan ki mukhya wajah: {hi} ({len(real)} mein se {n})."))
        if placebo_net is not None:
            better = net > placebo_net
            out.append(_why("VS_PLACEBO",
                            f"Against its random-stock placebo (₹{placebo_net:,.0f}): "
                            f"{'better' if better else 'not better'}.",
                            f"Random-stock placebo (₹{placebo_net:,.0f}) se "
                            f"{'behtar' if better else 'behtar nahi'}."))
    return out
