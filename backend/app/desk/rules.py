"""The rule judge, dash-plan-v2 (pure). The v1 dashboard plan (app/dashboard/analysis) plus
the guards it lacked: circuit limits, over-extension, liquidity, cost-aware reward/risk,
news-driven moves, results today and bad data. Its output is evidence for the LLM and the
baseline the LLM's decision is compared with (conflicts are recorded)."""

from __future__ import annotations

import math
from typing import Any

from app.dashboard import analysis as A
from app.desk import config as K

RULE_VERSION = "dash-plan-v2"
TO_DECISION = {"BUY": "BUY", "HOLD / WAIT": "WATCH", "SELL / AVOID": "AVOID"}


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


ACTION = {"BUY": "BUY", "WATCH": "HOLD / WAIT", "AVOID": "AVOID"}


def stock_plan(close: float | None, feat: dict[str, Any], lv: dict[str, Any],
               ex: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """The dashboard stock page's plan, dash-plan-v2: the v1 levels plus the guards; the
    guards set the action, and their notes say why."""
    px = {**{k: feat.get(k) for k in ("close_to_sma_20", "close_to_sma_50",
                                      "close_to_sma_200", "rsi_14", "macd_histogram")},
          "close": close, "atr_pct": feat.get("atr_pct_14"), "ret_1d": ctx.get("ret_1d"),
          **{k: lv.get(k) for k in ("support_20", "resistance_20", "swing_low_60",
                                    "swing_high_60", "high_252", "low_252")}}
    j = judge(px, ex, ctx)
    plan = dict(j["plan"])
    v1 = plan.get("action")
    if j["decision"] != TO_DECISION.get(v1):
        label = "NEUTRAL" if j["decision"] == "WATCH" else plan.get("action")
        if j["decision"] == "WATCH":
            plan = A.trade_plan(close, {**feat}, lv, {**j["signal"], "label": label,
                                                      "version": A.SIGNAL_VERSION})
            if j["plan"].get("pullback_entry"):
                plan["when_buy"] = [f"wait for a pullback near {j['plan']['pullback_entry']:.2f}"
                                    " (20-day average + 1 ATR); do not chase", *plan["when_buy"]]
        plan["action"] = ACTION[j["decision"]]
        if j["decision"] == "AVOID":
            plan["when_buy"] = ["avoid new buying: " + "; ".join(j["notes"][:3])]
    plan.update(version=RULE_VERSION, v1_action=v1, guards=j["flags"], guard_notes=j["notes"],
                cost=j["cost"], extension_atr=j["extension_atr"])
    plan["basis"] = [*(plan.get("basis") or []), "dash-plan-v2 guards: circuit, extension, "
                     "liquidity, news move, results, data quality"]
    return plan


def judge(px: dict[str, Any], ex: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """px: close, atr_pct, close_to_sma_20/50/200, rsi_14, macd_histogram, ret_1d and the
    levels (support_20, resistance_20, swing_low_60, swing_high_60, high_252, low_252);
    ex: upper_circuit, lower_circuit, median_turnover; ctx: news_24h (count), results_today,
    bad_data (list). Returns {decision, flags, plan, signal, cost}."""
    close = _f(px.get("close"))
    feat = {k: px.get(k) for k in ("close_to_sma_20", "close_to_sma_50", "close_to_sma_200",
                                   "rsi_14", "macd_histogram", "atr_pct_14")}
    feat["atr_pct_14"] = px.get("atr_pct")
    sig = A.research_signal(feat)
    lv = {k: px.get(k) for k in ("support_20", "resistance_20", "swing_low_60",
                                 "swing_high_60", "high_252", "low_252")}
    plan = A.trade_plan(close, feat, lv, sig)
    decision = TO_DECISION.get(plan.get("action"), "WATCH")
    flags: list[str] = []
    notes: list[str] = []
    up, dn = _f(ex.get("upper_circuit")), _f(ex.get("lower_circuit"))
    if close and up and close >= up * (1 - K.CIRCUIT_NEAR):
        flags.append("CIRCUIT_UPPER")
        notes.append(f"price {close:.2f} is within {K.CIRCUIT_NEAR:.0%} of the upper circuit "
                     f"{up:.2f}: buy orders may not fill")
    if close and dn and close <= dn * (1 + K.CIRCUIT_NEAR):
        flags.append("CIRCUIT_LOWER")
        notes.append(f"price {close:.2f} is within {K.CIRCUIT_NEAR:.0%} of the lower circuit "
                     f"{dn:.2f}: sell orders may not fill")
    hi = _f(ex.get("day_high")) or _f(px.get("high"))
    if up and hi and hi >= up * 0.999 and "CIRCUIT_UPPER" not in flags:
        flags.append("CIRCUIT_TOUCHED")
        notes.append(f"the day's high {hi:.2f} touched the upper circuit {up:.2f}: a frenzy "
                     "move; liquidity vanishes at the limit")
    atrp, c20 = _f(px.get("atr_pct")), _f(px.get("close_to_sma_20"))
    ext_atr = None
    if close and atrp and c20 is not None and c20 > -1:
        sma20 = close / (1 + c20)
        ext_atr = (close - sma20) / (atrp * close)
        if ext_atr > K.EXTENDED_ATR:
            flags.append("EXTENDED")
            notes.append(f"price is {ext_atr:.1f} ATR above its 20-day average {sma20:.2f}: "
                         "chasing; wait for a pullback")
    tv = _f(ex.get("median_turnover"))
    if tv is not None and tv < K.MIN_TURNOVER_INR:
        flags.append("ILLIQUID")
        notes.append(f"median turnover Rs {tv / 1e7:.1f} cr < Rs {K.MIN_TURNOVER_INR / 1e7:.0f} cr")
    r1 = _f(px.get("ret_1d"))
    if r1 is not None and abs(r1) >= K.NEWS_MOVE and (ctx.get("news_24h") or 0) > 0:
        flags.append("NEWS_MOVE")
        notes.append(f"a {r1:+.1%} day with linked news: information, not noise")
    if ctx.get("results_today"):
        flags.append("RESULTS_TODAY")
        notes.append("results due: the move after results is unpredictable")
    if ctx.get("bad_data"):
        flags.append("BAD_DATA")
        notes.append("data quality: " + "; ".join(ctx["bad_data"]))
    # guards override the v1 action
    if any(f in flags for f in ("CIRCUIT_UPPER", "CIRCUIT_LOWER", "ILLIQUID")):
        decision = "AVOID"
    elif "EXTENDED" in flags and decision == "BUY":
        decision = "WATCH"
        if close and atrp and c20 is not None:
            sma20 = close / (1 + c20)
            plan["pullback_entry"] = round(sma20 + atrp * close, 2)
            notes.append(f"pullback entry near {plan['pullback_entry']:.2f} "
                         "(20-day average + 1 ATR)")
    cost = None
    e, sl, t1 = _f(plan.get("entry")), _f(plan.get("stop_loss")), _f(plan.get("t1"))
    if e and sl and t1 and e > sl:
        friction = e * (K.ROUND_TRIP_COST + 2 * K.HALF_SPREAD)
        cost = {"friction_inr_per_share": round(friction, 3),
                "gross_rrr_t1": round((t1 - e) / (e - sl), 2),
                "net_rrr_t1": round((t1 - e - friction) / (e - sl + friction), 2),
                "slippage_scenarios_bps": {str(b): round((t1 - e - friction - e * b / 1e4)
                                                         / (e - sl + friction + e * b / 1e4), 2)
                                           for b in (5, 10, 20)}}
    return {"version": RULE_VERSION, "decision": decision, "flags": flags, "notes": notes,
            "extension_atr": None if ext_atr is None else round(ext_atr, 2),
            "signal": {"label": sig["label"], "score": sig["score"],
                       "reasons": sig["reasons"]},
            "plan": {k: v for k, v in plan.items() if k not in ("disclaimer",)},
            "cost": cost}
