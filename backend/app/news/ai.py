"""Optional AI enrichment of news items (Phase 9; decision NEWS-CONTENT).

AI output is ENRICHMENT, never a source fact: it is stored in its own table
(news_ai_enrichment) with model_id, model_version, prompt_version, input_sha256
and generated_at (= its knowable_at), and it never overwrites an item field.
It is validated against a closed schema; anything else is INVALID. A failure,
timeout or invalid answer is recorded and never stops ingestion.

Disabled unless PRAJNA_NEWS_AI_ENABLED is true AND a model id is configured.
Credentials come only from the standard AWS environment/credential chain of the
process (never from argv, never logged, never stored, never in the API).
The model call is injectable (tests use a fake; no network in tests).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.clock import now
from app.news.model import ItemObs

PROMPT_VERSION = "news-ai-v2"       # v2 (2026-10-22): closed event-type list, tolerant JSON
TIMEOUT_S = 90.0                   # one call, its backoff retries included
SCOPES = {"STOCK", "SECTOR", "INDEX", "MARKET", "MACRO", "GLOBAL", "UNKNOWN"}
IMPACTS = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}
DIRECTIONS = {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"}
EVENT_TYPES = (
    "results", "results_date", "board_meeting", "dividend", "bonus_split", "buyback",
    "fund_raising", "acquisition_merger", "order_win", "capacity_expansion", "product_launch",
    "management_change", "regulatory_action", "regulatory_approval", "legal_dispute",
    "credit_rating", "analyst_rating", "guidance_outlook", "shareholding_change",
    "insider_trade", "investor_meet", "ipo_listing", "corporate_action_other",
    "macro_economic", "government_policy", "monetary_policy", "commodity", "currency",
    "global_markets", "market_update", "sector_trend", "other")
PROMPT = """You annotate one Indian market news item for a research database.
Use ONLY the text given. Do not predict prices. If unsure, use UNKNOWN.
Answer with one JSON object and nothing else (no code fence, no text before or after),
with exactly these keys:
summary (<= 60 words), entities (list of names),
event_type (exactly one of: """ + ", ".join(EVENT_TYPES) + """),
market_scope (STOCK|SECTOR|INDEX|MARKET|MACRO|GLOBAL|UNKNOWN),
potential_impact (LOW|MEDIUM|HIGH|UNKNOWN),
impact_direction (POSITIVE|NEGATIVE|MIXED|NEUTRAL|UNKNOWN),
confidence (0..1), key_facts (list of short strings), risk_flags (list).

Title: {title}
Source: {publisher}
Description: {summary}"""

Model = Callable[[str, str], Awaitable[tuple[str, str | None]]]   # (text, model_version)


@dataclass(frozen=True, slots=True)
class AIResult:
    status: str                    # OK / ERROR / TIMEOUT / INVALID
    model_id: str
    model_version: str | None
    prompt_version: str
    input_sha256: str
    output: dict[str, Any] | None
    error: str | None
    generated_at: _dt.datetime


def prompt_for(item: ItemObs) -> str:
    return PROMPT.format(title=item.title, publisher=item.publisher,
                         summary=item.summary or "(none)")


def _json_object(text: str) -> Any:
    """The answer's JSON object, also when wrapped in a code fence or a sentence."""
    t = text.strip()
    try:
        return json.loads(t)
    except ValueError:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise
        return json.loads(t[i:j + 1])


def validate(text: str) -> dict[str, Any]:
    d = _json_object(text)
    if isinstance(d, dict):
        for k in ("market_scope", "potential_impact", "impact_direction"):
            if isinstance(d.get(k), str):
                d[k] = d[k].strip().upper()
        et = d.get("event_type")
        if isinstance(et, str):
            norm = et.strip().lower().replace(" ", "_").replace("-", "_")
            if norm not in EVENT_TYPES:
                d["event_type"], d["event_type_raw"] = "other", et
            else:
                d["event_type"] = norm
    need = {"summary", "entities", "event_type", "market_scope", "potential_impact",
            "impact_direction", "confidence", "key_facts", "risk_flags"}
    if not isinstance(d, dict) or set(d) - {"event_type_raw"} != need:
        raise ValueError(f"keys {sorted(d) if isinstance(d, dict) else type(d).__name__}")
    if (d["market_scope"] not in SCOPES or d["potential_impact"] not in IMPACTS
            or d["impact_direction"] not in DIRECTIONS):
        raise ValueError("enum value outside the schema")
    c = d["confidence"]
    if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0 <= c <= 1:
        raise ValueError("confidence outside 0..1")
    for k in ("entities", "key_facts", "risk_flags"):
        if not isinstance(d[k], list) or not all(isinstance(x, str) for x in d[k]):
            raise ValueError(f"{k} must be a list of strings")
    if not isinstance(d["summary"], str) or len(d["summary"].split()) > 80:
        raise ValueError("summary missing or too long")
    return d


async def enrich(item: ItemObs, model: Model, model_id: str, *,
                 timeout_s: float = TIMEOUT_S) -> AIResult:
    p = prompt_for(item)
    sha = hashlib.sha256(f"{PROMPT_VERSION}\x1f{model_id}\x1f{p}".encode()).hexdigest()

    def res(status, *, version=None, output=None, error=None):
        return AIResult(status, model_id, version, PROMPT_VERSION, sha, output, error, now())

    try:
        text, version = await asyncio.wait_for(model(model_id, p), timeout_s)
    except TimeoutError:
        return res("TIMEOUT", error=f"no answer within {timeout_s}s")
    except Exception as e:                        # a model failure never stops ingestion
        return res("ERROR", error=type(e).__name__)
    try:
        return res("OK", version=version, output=validate(text))
    except (ValueError, TypeError) as e:
        return res("INVALID", version=version, error=str(e)[:300])


def bedrock_model(region: str | None = None, max_tokens: int = 600) -> Model:  # pragma: no cover
    """A Bedrock Converse call through boto3's standard credential chain."""
    import boto3  # imported only when AI is enabled
    from botocore.config import Config

    # Bedrock throttles bursts (2026-10-22: ~1/3 of the calls of a 4-concurrent run got
    # ThrottlingException): botocore's adaptive mode backs off and retries within the call.
    client = boto3.client("bedrock-runtime", region_name=region, config=Config(
        retries={"mode": "adaptive", "max_attempts": 8}, connect_timeout=10, read_timeout=40))

    async def call(model_id: str, prompt: str) -> tuple[str, str | None]:
        def _run():
            r = client.converse(modelId=model_id, messages=[
                {"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
            text = r["output"]["message"]["content"][0]["text"]
            return text, r.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get(
                "x-amzn-bedrock-model-version")
        return await asyncio.to_thread(_run)
    return call


# ── the enrichment job (NEWS-CONTENT; enabled by the user 2026-10-22) ─────────────────
# Point in time: an enrichment is knowable when it was generated (knowable_at =
# generated_at, the moment the answer was received), never at the item's own time. A
# feature that reads it filters knowable_at < as_of like every other input.
WINDOW_H = 48                      # items first knowable within this many hours
RUN_LIMIT = 400                    # model calls per run at most
CONCURRENCY = 2                    # 4 drew ThrottlingException on ~1/3 of the calls
DAILY_MAX = 4000                   # stored enrichments per IST day at most (cost guard)
FINAL = ("OK", "INVALID")          # stored; ERROR / TIMEOUT are retried by a later run


def item_obs(r) -> ItemObs:
    return ItemObs(source_article_id=r.source_article_id, title=r.title, url=r.url,
                   publisher=r.publisher, published_at=r.published_at,
                   published_at_raw=r.published_at_raw, summary=r.summary)


async def enrich_pending(s, model: Model, model_id: str, *, token: str | None,
                         limit: int = RUN_LIMIT, window_h: int = WINDOW_H,
                         concurrency: int = CONCURRENCY, daily_max: int = DAILY_MAX,
                         timeout_s: float = TIMEOUT_S) -> dict[str, Any]:
    """Enrich the items of the last `window_h` hours that have no OK/INVALID enrichment
    for (model_id, PROMPT_VERSION), newest first. One commit per run. A transient
    failure (ERROR, TIMEOUT) is counted, not stored, and retried by the next run."""
    from collections import Counter

    from sqlalchemy import text

    from app.core.authz import authorize_write
    from app.core.clock import IST

    authorize_write(token)
    day0 = _dt.datetime.combine(now().astimezone(IST).date(), _dt.time(), tzinfo=IST)
    done_today = (await s.execute(text("""select count(*) from news_ai_enrichment
        where generated_at >= :d0"""), {"d0": day0})).scalar()
    budget = max(0, min(limit, daily_max - done_today))
    rows = (await s.execute(text("""
        select i.id, i.source_article_id, i.title, i.url, i.publisher, i.published_at,
               i.published_at_raw, i.summary
        from news_item i
        where i.knowable_at > cast(:at as timestamptz) - make_interval(hours => :h)
          and i.knowable_at <= cast(:at as timestamptz)
          and not exists (select 1 from news_ai_enrichment e where e.item_id = i.id
                          and e.model_id = :m and e.prompt_version = :pv)
        order by i.knowable_at desc, i.id desc limit :n"""),
        {"h": window_h, "m": model_id, "pv": PROMPT_VERSION, "n": budget, "at": now()})).all()
    sem = asyncio.Semaphore(concurrency)

    async def one(r):
        async with sem:
            return r.id, await enrich(item_obs(r), model, model_id, timeout_s=timeout_s)

    results = await asyncio.gather(*(one(r) for r in rows))
    status = Counter(res.status for _, res in results)
    stored = 0
    for item_id, res in results:
        if res.status not in FINAL:
            continue
        n = (await s.execute(text("""insert into news_ai_enrichment (item_id, status,
            model_id, model_version, prompt_version, input_sha256, output, error,
            generated_at, knowable_at) values (:i, :st, :m, :v, :pv, :sha,
            cast(:o as jsonb), :e, :g, :g)
            on conflict on constraint uq_news_ai do nothing"""),
            {"i": item_id, "st": res.status, "m": res.model_id, "v": res.model_version,
             "pv": res.prompt_version, "sha": res.input_sha256,
             "o": None if res.output is None else json.dumps(res.output),
             "e": res.error, "g": res.generated_at})).rowcount
        stored += n or 0
    await s.commit()
    errors = sorted({res.error for _, res in results
                     if res.status in ("ERROR", "TIMEOUT") and res.error})[:5]
    return {"model_id": model_id, "prompt_version": PROMPT_VERSION, "window_h": window_h,
            "done_today_before": done_today, "budget": budget, "candidates": len(rows),
            "status": dict(status), "stored": stored, "errors": errors}
