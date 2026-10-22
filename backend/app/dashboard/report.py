"""Daily "Market News & Impact" report (user 2026-10-22), generated after the close and
before the open from the dashboard's own facts: Indian indices, breadth, sectors, movers,
global markets, commodities / FX, FII-DII flows, today's results and today's media
headlines with their AI enrichment. Bedrock writes it; it is told to use ONLY these facts,
to separate what was reported from what might follow, and never to recommend a trade.
Validated against a closed schema, stored in var/dashboard/reports/<day>_<HHMM>.json and
sent to Telegram. Missing inputs (Kospi, US 10-year, dollar index: not available from
Upstox) are listed as missing, never invented. Paper research; no order is ever placed."""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
from typing import Any

from app.core.clock import IST, now

PROMPT_VERSION = "dash-report-v3"
DIR = pathlib.Path(__file__).resolve().parents[2] / "var" / "dashboard" / "reports"
NOT_AVAILABLE = ["KOSPI", "US 10-year Treasury yield", "US dollar index (DXY)"]
PROMPT = """You write the daily "Market News & Impact Report" for a private Indian-market
research dashboard. Use ONLY the facts in the JSON below.
- Market numbers (indices, breadth, sectors, movers, global, commodities, FX, FII/DII) come
  from the data fields: state them as facts.
- Anything taken from "headlines" must name its source, e.g. "(reported by Mint)".
- Separate what was REPORTED (text) from its POTENTIAL impact (impact).
- "themes" groups the headlines by topic. Write one item for EVERY theme that has
  headlines or data: Indian market - indices and breadth, sector moves, crude and
  commodities (use the Brent / WTI data), rupee, RBI / rates / bonds, results and earnings
  (use results_today and the results headlines), FII-DII flows; global market - US, Asia,
  Europe, geopolitics and energy.
- Mention data that is in "not_available" only as unavailable, never with a number.
- Do not recommend buying or selling and do not give price targets.
Answer with one JSON object and nothing else, exactly these keys:
  title (string),
  indian_market (list of {{"headline": str, "text": str (<= 70 words),
                 "impact": str (<= 40 words)}}, 4-7 items),
  global_market (list of the same shape, 2-5 items),
  variables_to_monitor (list of short strings),
  overall (string, <= 100 words).

FACTS:
{facts}"""


def validate(text: str) -> dict[str, Any]:
    t = text.strip()
    d = json.loads(t[t.find("{"): t.rfind("}") + 1])
    keys = {"title", "indian_market", "global_market", "variables_to_monitor", "overall"}
    if set(d) != keys:
        raise ValueError(f"keys {sorted(d)}")
    for sec in ("indian_market", "global_market"):
        if not isinstance(d[sec], list):
            raise ValueError(sec)
        for x in d[sec]:
            if not isinstance(x, dict) or set(x) != {"headline", "text", "impact"} \
                    or not all(isinstance(v, str) for v in x.values()):
                raise ValueError(f"{sec} item")
    if not isinstance(d["variables_to_monitor"], list) or not isinstance(d["overall"], str):
        raise ValueError("variables / overall")
    low = json.dumps(d).lower()
    if any(w in low for w in ("target price", "price target", "we recommend", "you should buy",
                              "you should sell", "strong buy")):
        raise ValueError("a recommendation or a price target")
    return d


def facts(view: dict[str, Any], glob: list[dict[str, Any]], news: dict[str, Any],
          sectors: list[dict[str, Any]], flows: list[dict[str, Any]],
          results: list[dict[str, Any]]) -> dict[str, Any]:
    def pct(x):
        return None if x is None else round(100 * x, 2)
    stocks = [r for r in view["stocks"] if r["day_change"] is not None]
    large = [r for r in stocks if r.get("cap_bucket") == "LARGE"]
    large.sort(key=lambda r: r["day_change"])
    def rank(n):
        ai = n.get("ai") or {}
        return ({"HIGH": 0, "MEDIUM": 1}.get(ai.get("potential_impact"), 2),
                {"MARKET": 0, "MACRO": 0, "GLOBAL": 0, "SECTOR": 1}.get(ai.get("market_scope"), 2))
    heads = sorted(news["items"], key=rank)[:80]
    return {
        "date": now().astimezone(IST).date().isoformat(),
        "india_indices": [{"name": i["name"], "level": i["close"],
                           "change_pct": pct(i["day_change"]),
                           "as_of": i.get("price_at") or i.get("close_date")}
                          for i in view["indices"]],
        "global": [{"name": g["name"], "level": g["ltp"], "change_pct": pct(g.get("change")),
                    **({"change_bps": g["change_bps"]} if g.get("change_bps") is not None
                       else {}), "as_of": g.get("at") or g.get("date")} for g in glob],
        "breadth": view["breadth"], "market_regime": (view.get("regime") or {}).get("label"),
        "sectors_up": [{"sector": x["sector"], "median_change_pct": pct(x["day"])}
                       for x in sectors if x["stocks"] >= 8][:6],
        "sectors_down": [{"sector": x["sector"], "median_change_pct": pct(x["day"])}
                         for x in sectors if x["stocks"] >= 8][-6:],
        "large_cap_gainers": [{"symbol": r["symbol"], "change_pct": pct(r["day_change"])}
                              for r in large[::-1][:6]],
        "large_cap_losers": [{"symbol": r["symbol"], "change_pct": pct(r["day_change"])}
                             for r in large[:6]],
        "fii_dii_cash_net_crore": flows[:3],
        "results_today": results[:40],
        "headlines": [{"title": n["title"], "source": n["publisher"],
                       "ai_direction": (n.get("ai") or {}).get("impact_direction"),
                       "ai_impact": (n.get("ai") or {}).get("potential_impact"),
                       "ai_summary": ((n.get("ai") or {}).get("summary") or "")[:220]}
                      for n in heads],
        "themes": themes(news["items"]),
        "not_available": NOT_AVAILABLE,
    }


THEMES = {"crude_commodities": ("crude", "brent", "oil price", "opec", "gold", "rubber", "metal"),
          "rupee_fx": ("rupee", "usd/inr", "dollar index", "forex"),
          "rbi_rates_bonds": ("rbi", "repo", "bond", "yield", "inflation", "mpc minutes"),
          "results_earnings": ("q2", "results", "profit", "earnings", "revenue"),
          "geopolitics_energy": ("iran", "israel", "middle east", "west asia", "geopolitic",
                                 "war", "sanction"),
          "us_markets": ("wall street", "s&p", "nasdaq", "dow jones", "fed "),
          "asia_markets": ("asian market", "nikkei", "hang seng", "kospi", "china")}


def themes(items: list[dict[str, Any]], per: int = 8) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for n in items:
        low = f" {n['title']} {(n.get('ai') or {}).get('summary') or ''} ".lower()
        for th, kws in THEMES.items():
            if any(k in low for k in kws) and len(out.setdefault(th, [])) < per:
                out[th].append({"title": n["title"], "source": n["publisher"]})
    return {k: v for k, v in out.items() if v}


async def generate(fx: dict[str, Any], model, model_id: str, *, timeout_s: float = 120.0
                   ) -> dict[str, Any]:
    at = now().astimezone(IST)
    rec: dict[str, Any] = {"generated_at": at.isoformat(), "date": at.date().isoformat(),
                           "model_id": model_id, "prompt_version": PROMPT_VERSION,
                           "inputs": {k: (len(v) if isinstance(v, list) else None)
                                      for k, v in fx.items()},
                           "not_available": fx.get("not_available", NOT_AVAILABLE),
                           # shown under the AI text from the data itself, so nothing the
                           # model leaves out is lost
                           "themes": fx.get("themes"), "results_today": fx.get("results_today"),
                           "global": fx.get("global"), "india_indices": fx.get("india_indices")}
    prompt = PROMPT.format(facts=json.dumps(fx, default=str))
    try:
        text, version = await asyncio.wait_for(model(model_id, prompt), timeout_s)
        rec.update(status="OK", model_version=version, report=validate(text))
    except TimeoutError:
        rec.update(status="TIMEOUT", report=None)
    except (ValueError, TypeError) as e:
        rec.update(status="INVALID", report=None, error=str(e)[:200])
    except Exception as e:                        # shown on the page, never raised
        rec.update(status="ERROR", report=None, error=type(e).__name__)
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{at:%Y-%m-%d_%H%M}.json").write_text(json.dumps(rec, indent=1, default=str))
    return rec


def latest(n: int = 10) -> list[dict[str, Any]]:
    files = sorted(DIR.glob("*.json"), reverse=True)[:n] if DIR.exists() else []
    return [json.loads(f.read_text()) for f in files]


def telegram_text(rec: dict[str, Any]) -> str:
    r = rec.get("report") or {}
    lines = [f"Prajna market report {rec['date']} ({rec['generated_at'][11:16]} IST)",
             r.get("title", "")]
    for sec, name in (("indian_market", "INDIA"), ("global_market", "GLOBAL")):
        if r.get(sec):
            lines.append(f"\n{name}")
            lines += [f"- {x['headline']}: {x['impact']}" for x in r[sec]]
    if r.get("overall"):
        lines.append(f"\n{r['overall']}")
    lines.append("\nResearch summary from news; not a trading recommendation.")
    return "\n".join(lines)[:3900]


def send_telegram(rec: dict[str, Any], notify: str) -> bool:
    if rec.get("status") != "OK":
        return False
    try:
        return subprocess.run([notify], input=telegram_text(rec), text=True, timeout=60,  # noqa: S603 - our own runbook
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
