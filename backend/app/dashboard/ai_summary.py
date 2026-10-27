"""Per-stock AI summary for the dashboard (user 2026-10-22: "AI powered").

On demand, cached per stock per IST day (var/dashboard/ai/<day>/<symbol>.json), so one
stock costs at most one model call a day. The model (Bedrock, PRAJNA_NEWS_AI_MODEL_ID)
is given ONLY the facts the dashboard computed - returns, trend, the research signal's
reasons, ratios, forensic flags, recent headlines - and must not predict a price or say
buy / sell. Its answer is validated against a closed schema; anything else is not shown.
A description of the facts, never advice; no order is ever placed."""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any

from app.core.clock import IST, now

PROMPT_VERSION = "dash-stock-ai-v1"
CACHE = pathlib.Path(__file__).resolve().parents[2] / "var" / "dashboard" / "ai"
PROMPT = """You write a short, neutral research note about one Indian listed stock for a
private research dashboard. Use ONLY the facts in the JSON below; if something is not in
it, do not mention it. Do NOT predict a price or a target, do NOT say buy, sell or hold,
and do NOT give advice. Answer with one JSON object and nothing else, with exactly these
keys: summary (<= 90 words), positives (list of short strings), risks (list of short
strings), watch (list of short strings: what would change the picture).

FACTS:
{facts}"""
KEYS = {"summary", "positives", "risks", "watch"}


def validate(text: str) -> dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[1] if "\n" in t else t
    d = json.loads(t[t.find("{"): t.rfind("}") + 1])
    if set(d) != KEYS or not isinstance(d["summary"], str):
        raise ValueError("keys")
    for k in ("positives", "risks", "watch"):
        if not isinstance(d[k], list) or not all(isinstance(x, str) for x in d[k]):
            raise ValueError(k)
    if len(d["summary"].split()) > 120:
        raise ValueError("summary too long")
    low = json.dumps(d).lower()
    if any(w in low for w in ("target price", "price target", " buy ", " sell ",
                              "strong buy", "we recommend")):
        raise ValueError("advice or a price target")
    return d


def facts(st: dict[str, Any]) -> dict[str, Any]:
    f = st.get("features") or {}
    return {"symbol": st["symbol"], "name": st["name"], "sector": st["sector"],
            "last_close": st["close"], "close_date": st["close_date"],
            "returns": {k: round(v, 4) for k, v in (st.get("returns") or {}).items()},
            "trend": st["trend"], "research_signal": {
                "label": st["signal"]["label"],
                "reasons": [r["why"] for r in st["signal"]["reasons"]]},
            "volatility_20d": f.get("volatility_20"), "beta_60": f.get("beta_60"),
            "ratios": st.get("ratios"), "forensic": {
                k: st["forensic"][k] for k in ("red_flags", "green_flags")},
            "next_results_in_days": f.get("results_days_to_next"),
            "recent_headlines": [{"title": n["title"], "ai_direction": (n.get("ai") or {})
                                  .get("impact_direction")} for n in st.get("news", [])[:10]],
            "recent_candle_patterns": [{"date": c["date"], "patterns": c["patterns"]}
                                       for c in st.get("candles", [])[-5:] if c["patterns"]]}


def cache_path(symbol: str) -> pathlib.Path:
    day = now().astimezone(IST).date().isoformat()
    safe = "".join(ch for ch in symbol if ch.isalnum() or ch in "-_&")
    return CACHE / day / f"{safe}.json"


def cached(symbol: str) -> dict[str, Any] | None:
    p = cache_path(symbol)
    return json.loads(p.read_text()) if p.exists() else None


async def generate(st: dict[str, Any], model, model_id: str, *,
                   timeout_s: float = 90.0) -> dict[str, Any]:
    """One model call for this stock today (cached); returns the stored record."""
    hit = cached(st["symbol"])
    if hit and str(hit.get("facts_close_date")) == str(st.get("close_date")):
        return hit                     # a note on older facts is regenerated (2026-10-27)
    prompt = PROMPT.format(facts=json.dumps(facts(st), default=str, indent=0))
    rec: dict[str, Any] = {"symbol": st["symbol"], "model_id": model_id,
                           "prompt_version": PROMPT_VERSION, "facts_close_date": st["close_date"]}
    try:
        text, version = await asyncio.wait_for(model(model_id, prompt), timeout_s)
        rec.update(status="OK", model_version=version, output=validate(text))
    except TimeoutError:
        rec.update(status="TIMEOUT", output=None)
    except (ValueError, TypeError) as e:
        rec.update(status="INVALID", output=None, error=str(e)[:200])
    except Exception as e:                        # a model failure is shown, never raised
        rec.update(status="ERROR", output=None, error=type(e).__name__)
    rec["generated_at"] = now().isoformat()
    if rec["status"] in ("OK", "INVALID"):
        p = cache_path(st["symbol"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, indent=1))
    return rec
