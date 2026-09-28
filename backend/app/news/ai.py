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

PROMPT_VERSION = "news-ai-v1"
TIMEOUT_S = 20.0
SCOPES = {"STOCK", "SECTOR", "INDEX", "MARKET", "MACRO", "GLOBAL", "UNKNOWN"}
IMPACTS = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}
DIRECTIONS = {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"}
PROMPT = """You annotate one Indian market news item for a research database.
Use ONLY the text given. Do not predict prices. If unsure, use UNKNOWN.
Answer with one JSON object and nothing else, with exactly these keys:
summary (<= 60 words), entities (list of names), event_type (short label),
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


def validate(text: str) -> dict[str, Any]:
    d = json.loads(text)
    need = {"summary", "entities", "event_type", "market_scope", "potential_impact",
            "impact_direction", "confidence", "key_facts", "risk_flags"}
    if not isinstance(d, dict) or set(d) != need:
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


def bedrock_model(region: str | None = None) -> Model:            # pragma: no cover - network
    """A Bedrock Converse call through boto3's standard credential chain."""
    import boto3  # imported only when AI is enabled

    client = boto3.client("bedrock-runtime", region_name=region)

    async def call(model_id: str, prompt: str) -> tuple[str, str | None]:
        def _run():
            r = client.converse(modelId=model_id, messages=[
                {"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 600, "temperature": 0})
            text = r["output"]["message"]["content"][0]["text"]
            return text, r.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get(
                "x-amzn-bedrock-model-version")
        return await asyncio.to_thread(_run)
    return call
