"""Content retrieval (never a bypass, never fatal) and AI enrichment (versioned,
validated, never a source fact). No network: httpx.MockTransport / fake models."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.news import ai as AI
from app.news import content as CT
from app.news.model import ItemObs
from app.news.sources import SOURCES

ET = SOURCES["ET_STOCKS_RSS"]
URL = "https://economictimes.indiatimes.com/markets/stocks/news/x/articleshow/1.cms"
ARTICLE = "<html><article>" + "".join(f"<p>{'Paragraph text about the company. ' * 3}{i}</p>"
                                      for i in range(8)) + "</article></html>"


def allowed(src=ET, **kw):
    fields = {k: getattr(src, k) for k in src.__slots__}
    return type(src)(**{**fields, "compliance": "APPROVED", "body_allowed": True, **kw})


def site(robots=(200, "User-agent: *\nAllow: /\n"), page=(200, ARTICLE)):
    calls = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        code, body = robots if req.url.path == "/robots.txt" else page
        return httpx.Response(code, text=body)
    t = httpx.MockTransport(h)
    t.calls = calls
    return t


class TestContent:
    async def test_terms_not_approved_means_no_request_at_all(self):
        t = site()
        r = await CT.fetch_content(URL, ET, CT.RobotsCache(), transport=t)
        assert r.status == "TERMS_BLOCKED" and t.calls == [] and r.body is None
        r = await CT.fetch_content(URL, allowed(body_allowed=False), CT.RobotsCache(),
                                   transport=t)
        assert r.status == "TERMS_BLOCKED" and t.calls == []

    async def test_available_body_is_extracted_and_hashed(self):
        r = await CT.fetch_content(URL, allowed(), CT.RobotsCache(), transport=site())
        assert r.status == "AVAILABLE" and r.robots_allowed and len(r.body) >= CT.MIN_TEXT
        assert r.content_sha256 and "<p>" not in r.body

    @pytest.mark.parametrize("robots", [(200, "User-agent: *\nDisallow: /markets/\n"),
                                        (500, ""), (403, "")])
    async def test_robots_disallow_or_unreadable_blocks_the_page_fetch(self, robots):
        t = site(robots=robots)
        r = await CT.fetch_content(URL, allowed(), CT.RobotsCache(), transport=t)
        assert r.status == "ROBOTS_BLOCKED" and t.calls == ["/robots.txt"]

    @pytest.mark.parametrize("page,status", [
        ((403, "denied"), "HTTP_BLOCKED"), ((401, ""), "HTTP_BLOCKED"),
        ((402, ""), "PAYWALL"), ((200, "<p>Subscribe to continue reading this story</p>"),
                                 "PAYWALL"),
        ((200, "<p>short</p>"), "NOT_AVAILABLE"), ((500, ""), "ERROR")])
    async def test_blocks_and_failures_are_statuses_not_exceptions(self, page, status):
        r = await CT.fetch_content(URL, allowed(), CT.RobotsCache(), transport=site(page=page))
        assert r.status == status and r.body is None

    async def test_network_error_is_an_error_status(self):
        def boom(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            raise httpx.ConnectError("down")
        r = await CT.fetch_content(URL, allowed(), CT.RobotsCache(),
                                   transport=httpx.MockTransport(boom))
        assert r.status == "ERROR"


ITEM = ItemObs("x", "Paras bags Rs 26 cr DRDO order", None, "Business Standard", None, None,
               summary="Paras Defence received an order worth Rs 26.59 crore from DRDO.")
GOOD = {"summary": "Paras Defence got a Rs 26.59 crore DRDO order.", "entities": ["Paras Defence",
        "DRDO"], "event_type": "order_win", "market_scope": "STOCK",
        "potential_impact": "MEDIUM", "impact_direction": "UNKNOWN", "confidence": 0.7,
        "key_facts": ["Rs 26.59 crore"], "risk_flags": []}


def model(answer=None, *, exc=None, delay=0.0):
    async def call(model_id, prompt):
        await asyncio.sleep(delay)
        if exc:
            raise exc
        return (answer if isinstance(answer, str) else json.dumps(answer)), "v1"
    return call


class TestAI:
    async def test_valid_output_is_versioned_enrichment(self):
        r = await AI.enrich(ITEM, model(GOOD), "test-model")
        assert r.status == "OK" and r.output == GOOD and r.model_id == "test-model"
        assert r.prompt_version == AI.PROMPT_VERSION and len(r.input_sha256) == 64
        assert r.model_version == "v1" and r.generated_at

    def test_same_input_same_hash_and_prompt_never_asks_for_prediction(self):
        p = AI.prompt_for(ITEM)
        assert "Do not predict prices" in p and ITEM.title in p

    @pytest.mark.parametrize("bad", [
        "not json", json.dumps({**GOOD, "market_scope": "MOON"}),
        json.dumps({**GOOD, "confidence": 2}), json.dumps({k: v for k, v in GOOD.items()
                                                           if k != "summary"}),
        json.dumps({**GOOD, "price_target": 999}), json.dumps([GOOD])])
    async def test_invalid_output_is_rejected(self, bad):
        r = await AI.enrich(ITEM, model(bad), "m")
        assert r.status == "INVALID" and r.output is None and r.error

    async def test_failure_and_timeout_never_raise(self):
        assert (await AI.enrich(ITEM, model(exc=RuntimeError("throttled")), "m")).status == "ERROR"
        r = await AI.enrich(ITEM, model(GOOD, delay=1), "m", timeout_s=0.01)
        assert r.status == "TIMEOUT" and r.output is None

    def test_ai_is_off_by_default(self):
        from app.core.config import Settings
        f = Settings.model_fields
        assert f["PRAJNA_NEWS_AI_ENABLED"].default is False
        assert f["PRAJNA_NEWS_AI_MODEL_ID"].default is None
