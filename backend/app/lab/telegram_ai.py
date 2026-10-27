"""AI-written Telegram messages for the Buy List (user 2026-10-27): the morning list and the
end-of-day check (did the picks make money). Nova Pro writes the text, in Hinglish with
emojis, from the facts only (it is told not to add a number or a stock); if the model fails
or answers badly a fixed template is sent instead. Every message ends with the disclaimer.

    .venv/bin/python -m app.lab.telegram_ai MORNING|EOD [YYYY-MM-DD]
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
import sys
from typing import Any

from sqlalchemy import text

DISCLAIMER = "⚠️ Paper research only - not investment advice. No order is placed."
MAX_CHARS = 3500

MORNING_PROMPT = """You write a Telegram message for an Indian stock-market research desk.
Language: Hinglish (Hindi in Latin script mixed with English), friendly and crisp, with
emojis (🟢 📈 🎯 🛑 ⏰ 📰 ⚠️ etc.). Use ONLY the facts in the JSON below: never add a stock,
a price, a percentage or a claim that is not there. Keep numbers exactly as given (rounded
to 1-2 decimals is fine).

Structure:
1. A title line with the date: "☀️ Aaj ki Intraday Buy List - <date>".
2. One or two lines on the market mood (regime.state and regime.note) and events.
3. The picks, one block each (at most 12, in the given order): symbol and sector; where the
   picks come from (DESK = AI desk, RULES = rule formula, agree = both, strongest);
   🛑 stop, 🎯 T1 / T2 with their % from the previous close (intraday levels: they move with
   the 09:15 open - stop 0.5 ATR below it, T1 0.75 ATR above, T2 1 ATR above);
   "aaj ki typical range" = typical_up_pct (how far it usually moves in a day); one short
   reason (desk_why or the rule flags) if given.
4. One line of discipline: stop pehle se lagao, T1 par profit book, 15:15 se pehle exit.
Plain text only (no markdown tables), under 3000 characters.

FACTS:
{facts}"""

EOD_PROMPT = """You write the end-of-day Telegram report of an Indian stock research desk's
intraday Buy List. Language: Hinglish with emojis (✅ ❌ 🎯 🛑 📊 💰 etc.). Use ONLY the
facts in the JSON: never invent a stock, a number or a reason.

Structure:
1. Title: "🌙 Buy List ka Nateeja - <date>".
2. The score card from summary: kitne picks fayde mein (profitable of graded), T1 hit,
   stopped, 15:15 par band; average net % per pick; total net Rs on Rs 1 lakh per pick.
3. Top 3 winners and top 3 losers from grades (symbol, status, net %, open-to-high %).
4. One honest takeaway line (for example: "agree" picks - desk and rules dono BUY - vs the
   rest if both exist; or that one day proves nothing).
Plain text only, under 3000 characters.

FACTS:
{facts}"""


def _r(x: Any, n: int = 4) -> Any:
    return round(x, n) if isinstance(x, float) else x


def morning_facts(brief: dict[str, Any]) -> dict[str, Any]:
    c = brief.get("candidates") or {}
    items = c.get("BUYLIST") or []
    keep = ("symbol", "sector", "prev_close", "typical_up_pct", "entry_lo", "entry_hi", "stop",
            "t1", "t2", "t1_pct", "t2_pct", "stop_pct", "levels_from", "agree", "desk_score",
            "rule_score", "rule_flags", "desk_why")
    return {"date": str(brief.get("session_date") or brief.get("session")),
            "regime": {k: (brief.get("regime") or {}).get(k) for k in ("state", "rule", "note")},
            "events": brief.get("events"), "e5_picks": [x.get("trading_symbol")
                                                       for x in c.get("E5") or []],
            "picks": [{k: _r(x.get(k)) for k in keep} for x in items[:12]],
            "total_picks": len(items)}


def eod_facts(day: _dt.date, grade: dict[str, Any]) -> dict[str, Any]:
    g = [x for x in grade["happened"]["grades"] if x.get("status") not in (None, "NO_DATA")]
    g.sort(key=lambda x: -x["net_pct"])
    keep = ("symbol", "status", "net_pct", "net_inr", "open_to_high_pct", "open_to_close_pct",
            "levels_from", "agree")
    sm = grade["happened"]["summary"]
    return {"date": str(day), "summary": {k: _r(v) for k, v in sm.items()},
            "winners": [{k: _r(x.get(k)) for k in keep} for x in g[:3]],
            "losers": [{k: _r(x.get(k)) for k in keep} for x in g[::-1][:3]]}


def template_morning(f: dict[str, Any]) -> str:
    lines = [f"☀️ Aaj ki Intraday Buy List - {f['date']}",
             f"📊 Market mood: {f['regime'].get('state')} - {f['regime'].get('note') or ''}"]
    for i, p in enumerate(f["picks"], 1):
        rng = f" | typical day ±{p['typical_up_pct']:.1%}" if p.get("typical_up_pct") else ""
        src = p["levels_from"] + (" + RULES" if p.get("agree") else "")
        lines.append(f"{i}. 🟢 {p['symbol']} ({p.get('sector') or ''}) [{src}]\n"
                     f"   Entry {p['entry_lo']}-{p['entry_hi']} | 🛑 {p['stop']} | "
                     f"🎯 {p['t1']} / {p['t2']}{rng}")
    lines.append("⏰ Stop pehle se lagao, T1 par profit book karo, 15:15 se pehle exit.")
    return "\n".join(lines)


def template_eod(f: dict[str, Any]) -> str:
    s = f["summary"]
    lines = [f"🌙 Buy List ka Nateeja - {f['date']}",
             f"📊 {s.get('profitable')}/{s.get('graded')} fayde mein | 🎯 T1 {s.get('t1_hit')} | "
             f"🛑 Stop {s.get('stopped')} | ⏰ 15:15 {s.get('eod')}",
             f"💰 Average {s.get('avg_net_pct', 0):+.2%} per pick, total Rs "
             f"{s.get('total_net_inr', 0):,.0f} (Rs 1 lakh per pick, after costs)"]
    lines += [f"✅ {w['symbol']} {w['status']} {w['net_pct']:+.2%}" for w in f["winners"]]
    lines += [f"❌ {w['symbol']} {w['status']} {w['net_pct']:+.2%}" for w in f["losers"]]
    return "\n".join(lines)


def _sane(txt: str, allowed: set[str]) -> bool:
    """Short enough, and every all-caps stock-like word is a given symbol or a common word."""
    if not txt or len(txt) > MAX_CHARS:
        return False
    common = {"T1", "T2", "RULES", "DESK", "AI", "NSE", "BUY", "EOD", "STOP", "RSI", "ATR",
              "FOMC", "RBI", "EVENT_WAIT", "TREND_UP", "TREND_DOWN", "RANGE", "MIXED", "SHOCK",
              "IST", "MIS", "NIFTY", "VIX", "FII", "DII", "OK", "P1", "E5", "PE", "GDP", "US",
              "FED", "NOTE", "LIST", "STRONG_BUY", "WATCH", "AVOID", "SELL", "INR", "RS"}
    words = set(re.findall(r"\b[A-Z][A-Z0-9&-]{2,}\b", txt))
    return not (words - allowed - common - {w.upper() for w in allowed})


async def write(kind: str, facts: dict[str, Any], model=None) -> str:
    """The message text: the model's when it is sane, else the template."""
    allowed = {p["symbol"] for p in facts.get("picks") or []} | {
        x["symbol"] for x in (facts.get("winners") or []) + (facts.get("losers") or [])} | set(
        facts.get("e5_picks") or [])
    allowed = {a for a in allowed if a}
    tmpl = template_morning(facts) if kind == "MORNING" else template_eod(facts)
    if model is not None:
        prompt = (MORNING_PROMPT if kind == "MORNING" else EOD_PROMPT).format(
            facts=json.dumps(facts, default=str, ensure_ascii=False))
        try:
            from app.desk import config as K
            txt, _ = await asyncio.wait_for(model(K.MODEL_ID, prompt), 60)
            txt = txt.strip().strip("`").strip()
            if _sane(txt, allowed):
                return f"{txt}\n\n{DISCLAIMER}"
        except Exception as e:
            import logging
            logging.getLogger("lab.telegram").warning("AI message failed: %s", e)
    return f"{tmpl}\n\n{DISCLAIMER}"


async def compose(kind: str, day: _dt.date, model=None) -> str:
    from app.db.engine import get_sessionmaker
    async with get_sessionmaker()() as s:
        if kind == "MORNING":
            r = (await s.execute(text("""select b.session_date, b.regime, b.events, b.candidates
                from daily_brief b join lab_run r using (run_id) where b.session_date = :d
                order by r.created_at desc limit 1"""), {"d": day})).mappings().first()
            await s.rollback()
            if r is None or not (r["candidates"] or {}).get("BUYLIST"):
                return ""
            return await write(kind, morning_facts(dict(r)), model)
        r = (await s.execute(text("""select f.happened, f.thought from day_forensic f
            join lab_run r using (run_id) where f.session_date = :d and f.strategy = '_BUYLIST'
            order by r.created_at desc limit 1"""), {"d": day})).mappings().first()
        await s.rollback()
        if r is None:
            return ""
        return await write(kind, eod_facts(day, dict(r)), model)


async def _main(kind: str, day: _dt.date) -> str:
    from app.core.config import get_settings
    from app.news.ai import bedrock_model
    try:
        model = bedrock_model(get_settings().PRAJNA_NEWS_AI_REGION, max_tokens=1500)
    except Exception:
        model = None
    return await compose(kind, day, model)


if __name__ == "__main__":
    from app.core.clock import IST, now
    k = (sys.argv[1] if len(sys.argv) > 1 else "MORNING").upper()
    d = _dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else now().astimezone(IST).date()
    print(asyncio.run(_main(k, d)))
