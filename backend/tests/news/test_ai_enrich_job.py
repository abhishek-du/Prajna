"""The news AI enrichment job (NEWS-CONTENT, enabled 2026-10-22): recent items without an
enrichment get one, knowable_at = generated_at (PIT), OK/INVALID stored once, transient
failures retried, the daily cap and the window respected. A fake model: no network."""

from __future__ import annotations

import datetime as _dt
import json

import httpx
import pytest
from sqlalchemy import text

from app.core.clock import now
from app.news import ai as AI
from app.news.store import poll_shadow
from tests.news.test_content_ai import GOOD
from tests.news.test_store import KEY, TOKEN, unlocked  # noqa: F401 - fixture

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def _items(s, ages_h):
    empty = b'<rss version="2.0"><channel><title>NSE</title></channel></rss>'
    pid = (await poll_shadow(s, KEY, token=TOKEN, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=empty))))["poll_id"]
    ids = []
    for n, age in enumerate(ages_h):
        t = now() - _dt.timedelta(hours=age)
        ids.append((await s.execute(text("""insert into news_item (source, source_article_id,
            url, canonical_url, title, title_norm_hash, summary, publisher, discovered_at,
            knowable_at, backlog, content_available, first_poll_id, content_sha256,
            payload_sha256, content_fetch_status) values (:k, :u, :u, :u, :ti, 'h', 'text',
            'NSE', :t, :t, false, false, :p, 'c', 'p', 'NOT_AVAILABLE') returning id"""),
            {"k": KEY, "u": f"https://n/{n}.pdf", "ti": f"Item {n}", "t": t,
             "p": pid})).scalar())
    return ids


def fake(answers):
    """answers: title -> dict (OK), str (INVALID) or Exception (ERROR)."""
    calls = []

    async def call(model_id, prompt):
        title = prompt.split("Title: ", 1)[1].split("\n", 1)[0]
        calls.append(title)
        a = answers.get(title, GOOD)
        if isinstance(a, Exception):
            raise a
        return (a if isinstance(a, str) else json.dumps(a)), "v-test"
    call.calls = calls
    return call


async def test_enriches_recent_items_once_with_pit_knowable_at(db_session, unlocked):  # noqa: F811
    s = db_session
    ids = await _items(s, [1, 2, 3, 60])                       # the last is outside 48 h
    m = fake({"Item 1": "not json", "Item 2": RuntimeError("throttled")})
    t0 = now()
    out = await AI.enrich_pending(s, m, "test-model", token=TOKEN)
    assert out["candidates"] == 3 and out["status"] == {"OK": 1, "INVALID": 1, "ERROR": 1}
    assert out["stored"] == 2 and out["errors"] == ["RuntimeError"]
    rows = (await s.execute(text("""select item_id, status, generated_at, knowable_at,
        model_version, prompt_version from news_ai_enrichment order by item_id"""))).all()
    assert [(r.item_id, r.status) for r in rows] == [(ids[0], "OK"), (ids[1], "INVALID")]
    assert all(r.knowable_at == r.generated_at >= t0 for r in rows)
    assert {(r.model_version, r.prompt_version) for r in rows} == {("v-test", AI.PROMPT_VERSION)}

    again = fake({})
    out2 = await AI.enrich_pending(s, again, "test-model", token=TOKEN)
    assert again.calls == ["Item 2"] and out2["stored"] == 1     # only the transient failure
    other = fake({})
    out3 = await AI.enrich_pending(s, other, "another-model", token=TOKEN)
    assert out3["candidates"] == 3                               # per model id


async def test_daily_cap_and_limit(db_session, unlocked):  # noqa: F811
    s = db_session
    await _items(s, [1, 2, 3])
    m = fake({})
    out = await AI.enrich_pending(s, m, "test-model", token=TOKEN, limit=2)
    assert out["candidates"] == 2 and len(m.calls) == 2
    capped = await AI.enrich_pending(s, fake({}), "test-model", token=TOKEN, daily_max=2)
    assert capped["budget"] == 0 and capped["candidates"] == 0


async def test_write_token_required(db_session):
    from app.core.errors import AuthorizationError
    with pytest.raises(AuthorizationError):
        await AI.enrich_pending(db_session, fake({}), "m", token="wrong")
