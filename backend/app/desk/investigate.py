"""The investigator agent (Nova Pro) and its validator. The LLM reads one dossier and
returns a closed JSON verdict: why the stock moved, six viewpoint scores, a decision, levels
and the thesis, risks and invalidation, citing evidence ids. By the user's decision
(2026-10-27) the LLM's decision is final: it may override the rule judge; every override is
recorded as a conflict. The validator enforces the schema, the citations and price sanity;
an invalid answer gets one retry, then the verdict is INVALID (no watchlist entry)."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.desk import config as K
from app.desk import dossier as DS

Model = Callable[[str, str], Awaitable[tuple[str, str | None]]]

PROMPT = """You are the head of research at an Indian equity intraday/swing desk. Investigate
ONE NSE stock like a detective, from every point of view, using ONLY the dossier below.
Never invent facts; every claim must cite evidence ids from the dossier (px, lvl, attr,
exec, ctx, fund, rule, news:<n>, res:<n>, ca:<n>).

Work through, in order:
1. WHY it moved on the last bar: market vs sector vs stock-specific (attr), the news,
   results or corporate actions and their timing (hours_before_last_close), volume.
   Was the move information (news, results) or noise? Is it already priced in?
2. Technical structure: trend, momentum, extension from averages (rule.extension_atr),
   support/resistance (lvl), volatility (px.atr_pct).
3. Catalyst quality: is the news a real, material, durable catalyst or hype?
4. Fundamentals (fund): valuation vs sector, growth; treat fund.sanity_flags as unreliable.
5. Market context (ctx): regime, calendar events, FII/DII.
6. Execution: liquidity (exec.median_turnover in Rs), circuit limits, costs, gap risk.
7. The rule judge (rule): its decision, flags and notes. You may disagree; if you do, say
   why in "rule_disagreement".
Then decide. Best practice: risk at most what the stop allows; the stop sits outside
noise (at least ~0.5-1 ATR) at a level that proves the idea wrong; reward/risk to T1 at
least 1.5 net of costs; do not chase a stock locked at a circuit or far above its averages
unless the evidence justifies it; "no trade" (WATCH/AVOID) is a valid answer.

Return ONLY one JSON object, no prose outside it:
{{"why_moved": {{"summary": str, "driver": "MARKET"|"SECTOR"|"STOCK_NEWS"|"RESULTS"|"CORPORATE_ACTION"|"TECHNICAL"|"NO_CLEAR_REASON", "evidence_ids": [str]}},
 "pov": {{"technical": 0-100, "catalyst": 0-100, "fundamental": 0-100, "market": 0-100, "execution": 0-100, "risk": 0-100}},
 "score": 0-100,
 "decision": "STRONG_BUY"|"BUY"|"WATCH"|"AVOID"|"SELL",
 "horizon": "INTRADAY"|"SWING_1_5D",
 "entry_lo": number|null, "entry_hi": number|null, "stop": number|null, "t1": number|null, "t2": number|null,
 "levels_basis": {{"entry": str, "stop": str, "targets": str}},
 "thesis": str, "risks": [str], "invalidation": str, "rule_disagreement": str|null,
 "evidence_ids": [str]}}
Scores: 100 = very favourable for a long position (for "risk", 100 = low risk). For BUY or
STRONG_BUY all five levels are required with stop < entry_lo <= entry_hi < t1 <= t2.
For WATCH give the levels you would wait for, or nulls. For AVOID/SELL levels may be null.

DOSSIER:
{dossier}"""  # noqa: E501 - the JSON schema lines are kept whole for the model


def prompt_for(packet: dict[str, Any]) -> str:
    return PROMPT.format(dossier=json.dumps(packet, default=str, ensure_ascii=False,
                                            separators=(",", ":")))


def _num(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def validate(raw: dict[str, Any], packet: dict[str, Any]) -> tuple[str, str | None]:
    """('OK', None) or ('INVALID', why)."""
    ids = DS.evidence_ids(packet)
    if not isinstance(raw, dict):
        return "INVALID", "not a JSON object"
    if raw.get("decision") not in K.DECISIONS:
        return "INVALID", f"decision {raw.get('decision')!r}"
    if raw.get("horizon") not in K.HORIZONS:
        return "INVALID", f"horizon {raw.get('horizon')!r}"
    sc = _num(raw.get("score"))
    if sc is None or not 0 <= sc <= 100:
        return "INVALID", f"score {raw.get('score')!r}"
    pov = raw.get("pov")
    if not isinstance(pov, dict) or any(not (_num(pov.get(p)) is not None and
                                             0 <= _num(pov.get(p)) <= 100) for p in K.POVS):
        return "INVALID", "pov scores"
    cited = set(raw.get("evidence_ids") or []) | set(
        ((raw.get("why_moved") or {}).get("evidence_ids")) or [])
    if not cited:
        return "INVALID", "no evidence cited"
    unknown = cited - ids
    if unknown:
        return "INVALID", f"unknown evidence ids {sorted(unknown)[:5]}"
    if not (raw.get("thesis") and raw.get("invalidation")):
        return "INVALID", "thesis and invalidation are required"
    lv = {k: _num(raw.get(k)) for k in ("entry_lo", "entry_hi", "stop", "t1", "t2")}
    if raw["decision"] in K.BUY_DECISIONS:
        if None in lv.values():
            return "INVALID", "BUY needs entry_lo, entry_hi, stop, t1, t2"
        if not lv["stop"] < lv["entry_lo"] <= lv["entry_hi"] < lv["t1"] <= lv["t2"]:
            return "INVALID", "levels not ordered stop < entry_lo <= entry_hi < t1 <= t2"
        px = packet["evidence"]["px"]
        close, atrp = _num(px.get("close")), _num(px.get("atr_pct"))
        if close and atrp:
            mid = (lv["entry_lo"] + lv["entry_hi"]) / 2
            d = (mid - lv["stop"]) / (atrp * close)
            if not K.STOP_MIN_ATR <= d <= K.STOP_MAX_ATR:
                return "INVALID", f"stop {d:.2f} ATR from the entry (allowed " \
                                  f"{K.STOP_MIN_ATR}-{K.STOP_MAX_ATR})"
            if not 0.5 * close <= mid <= 1.5 * close:
                return "INVALID", "entry far from the price"
    return "OK", None


def conflicts(raw: dict[str, Any], rule: dict[str, Any]) -> list[str]:
    """Where the LLM's (final) decision overrides the rule judge."""
    out = []
    dec, rdec, flags = raw.get("decision"), rule.get("decision"), set(rule.get("flags") or [])
    buy = dec in K.BUY_DECISIONS
    if buy:
        for f in ("CIRCUIT_UPPER", "ILLIQUID", "EXTENDED", "RESULTS_TODAY", "BAD_DATA"):
            if f in flags:
                out.append(f"LLM_BUY_vs_RULE_{f}")
        if rdec == "AVOID":
            out.append("LLM_BUY_vs_RULE_AVOID")
    elif dec in ("AVOID", "SELL") and rdec == "BUY":
        out.append("LLM_AVOID_vs_RULE_BUY")
    return out


async def investigate(model: Model, packet: dict[str, Any], *,
                      model_id: str = K.MODEL_ID) -> dict[str, Any]:
    """One stock: up to K.ATTEMPTS calls. Returns the verdict fields (never raises)."""
    from app.news.ai import _json_object
    prompt = prompt_for(packet)
    psha = hashlib.sha256(prompt.encode()).hexdigest()
    rule = packet["evidence"]["rule"]
    last = {"status": "ERROR", "invalid_reason": "no attempt", "response_raw": None}
    t0 = time.monotonic()
    for attempt in range(K.ATTEMPTS):
        p = prompt if attempt == 0 else (prompt + "\n\nYour previous answer was invalid ("
                                         + str(last.get("invalid_reason")) + "). Return a "
                                         "corrected JSON object only.")
        try:
            text, _ver = await model(model_id, p)
        except Exception as e:
            last = {"status": "ERROR", "invalid_reason": f"{type(e).__name__}: {e}"[:300],
                    "response_raw": None}
            continue
        try:
            raw = _json_object(text)
        except Exception as e:
            last = {"status": "INVALID", "invalid_reason": f"not JSON: {e}"[:200],
                    "response_raw": text}
            continue
        st, why = validate(raw, packet)
        last = {"status": st, "invalid_reason": why, "response_raw": text, "raw": raw}
        if st == "OK":
            break
    out = {"prompt_sha256": psha, "model_id": model_id,
           "latency_ms": int((time.monotonic() - t0) * 1000), "rule_decision": rule["decision"],
           "rule_flags": list(rule.get("flags") or []), "rule_plan": rule, **{
               k: last.get(k) for k in ("status", "invalid_reason", "response_raw")}}
    raw = last.get("raw") if last["status"] == "OK" else None
    if raw:
        out.update({
            "decision": raw["decision"], "horizon": raw["horizon"],
            "score": round(_num(raw["score"])),
            "pov": {p: round(_num(raw["pov"][p])) for p in K.POVS},
            **{k: _num(raw.get(k)) for k in ("entry_lo", "entry_hi", "stop", "t1", "t2")},
            "levels_basis": raw.get("levels_basis"), "why_moved": raw.get("why_moved"),
            "thesis": raw.get("thesis"), "risks": raw.get("risks") or [],
            "invalidation": raw.get("invalidation"),
            "rule_disagreement": raw.get("rule_disagreement"),
            "evidence_ids": sorted(set(raw.get("evidence_ids") or []) | set(
                (raw.get("why_moved") or {}).get("evidence_ids") or [])),
            "conflicts": conflicts(raw, rule)})
    else:
        out.update({"evidence_ids": [], "conflicts": []})
    return out
