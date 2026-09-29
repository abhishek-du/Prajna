"""Market scope scope-v1 (pure) and its storage: primary + secondary, from the
item's own evidence; nothing is dropped; the scope row never replaces the event
category for readers (story index, news_pit)."""

from __future__ import annotations

import datetime as _dt

import httpx
import pytest
from sqlalchemy import text

from app.canon import news_pit as NP
from app.news import scope as SC
from app.news.store import poll_shadow
from tests.news.test_pilot import BODY, T0
from tests.news.test_store import KEY, TOKEN, unlocked  # noqa: F401 - fixture


def sc(title="x", category="OTHER", companies=(), mentions=(), kind="HEADLINE"):
    return SC.scope(title=title, category=category, companies=list(companies),
                    mentions=list(mentions), source_kind=kind)


@pytest.mark.parametrize("kw,primary", [
    ({"category": "REGULATORY"}, "REGULATORY"),
    ({"kind": "REGULATOR"}, "REGULATORY"),                               # SEBI's own feed
    ({"mentions": [("REGULATOR", "SEBI")]}, "REGULATORY"),
    ({"mentions": [("COURT", "NCLT_NCLAT")]}, "REGULATORY"),
    ({"companies": ["NSE_EQ|X"], "category": "RESULTS"}, "CORPORATE"),
    ({"companies": ["NSE_EQ|X"], "category": "MERGER_ACQUISITION"}, "CORPORATE"),
    ({"companies": ["NSE_EQ|X"]}, "COMPANY"),
    ({"companies": ["NSE_EQ|X"], "mentions": [("REGULATOR", "SEBI")]}, "COMPANY"),  # LODR
    ({"mentions": [("GEOPOLITICAL", "US_IRAN")]}, "GEOPOLITICAL"),
    ({"mentions": [("CURRENCY", "INR")]}, "CURRENCY"),
    ({"category": "COMMODITIES"}, "COMMODITY"),
    ({"mentions": [("CENTRAL_BANK", "RBI")]}, "MACRO"),
    ({"category": "FII_DII"}, "MACRO"),
    ({"title": "Wall St declines as yields stay elevated"}, "GLOBAL_MARKET"),
    ({"title": "Asian markets decline"}, "GLOBAL_MARKET"),
    ({"mentions": [("SECTOR", "PHARMA")]}, "SECTOR"),
    ({"mentions": [("INDEX", "NIFTY_50")]}, "MARKET_WIDE"),
    ({"category": "MARKET_WIDE"}, "MARKET_WIDE"),
    ({"title": "Ten recipes for the festive season"}, "IRRELEVANT"),
    ({"title": "Anthropic's IPO prospectus shows sweeping AI vision"}, "CORPORATE"),  # unlisted
    ({"category": "RESULTS"}, "CORPORATE"),
    ({"title": "Pre-market action: the trade setup for today's session"}, "MARKET_WIDE"),
    ({"title": "Adani Ports and Special Economic Zone Limited", "kind": "EXCHANGE"},
     "CORPORATE"),                                                    # an unresolved filer
])
def test_primary_scope(kw, primary):
    assert sc(**kw).primary == primary


def test_vocabulary_is_a_weak_last_resort():
    s = sc(title="Newgen Software bags Rs 53-cr contract from US health insurer")
    assert (s.primary, s.confidence, s.evidence["rule"]) == ("CORPORATE", 0.5, "vocabulary")
    # a real signal always wins over vocabulary
    assert sc(title="Rupee shares gains", mentions=[("CURRENCY", "INR")]).primary == "CURRENCY"


def test_every_applicable_scope_is_kept():
    s = sc(title="Rupee slips as crude jumps on Iran tensions; Nifty falls",
           mentions=[("CURRENCY", "INR"), ("COMMODITY", "CRUDE_OIL"),
                     ("GEOPOLITICAL", "US_IRAN"), ("INDEX", "NIFTY_50")])
    assert s.primary == "GEOPOLITICAL"
    assert s.secondary == ("CURRENCY", "COMMODITY", "MARKET_WIDE")
    assert s.version == "scope-v1" and s.method == "SCOPE_RULES"


def test_irrelevant_is_labelled_not_dropped_and_low_confidence():
    s = sc(title="Ten recipes")
    assert (s.primary, s.confidence, s.secondary) == ("IRRELEVANT", 0.3, ())
    assert s.evidence["rule"] == "no market signal"


def test_confidence_reflects_the_evidence():
    assert sc(companies=["NSE_EQ|X"]).confidence == 0.8
    assert sc(mentions=[("INDEX", "NIFTY_50")]).confidence == 0.6        # a title word only


@pytest.mark.db
@pytest.mark.integration
async def test_scope_is_stored_beside_the_category(db_session, unlocked, monkeypatch):  # noqa: F811
    await poll_shadow(db_session, KEY, token=TOKEN,
                      transport=httpx.MockTransport(lambda r: httpx.Response(200, content=BODY)))
    rows = (await db_session.execute(text("""select i.id,
        count(*) filter (where c.method = 'SCOPE_RULES'),
        count(*) filter (where c.method <> 'SCOPE_RULES')
        from news_item i join news_classification c on c.item_id = i.id group by 1"""))).all()
    assert rows and all(n_scope == 1 and n_cat == 1 for _, n_scope, n_cat in rows)
    # news_pit keeps them apart (rows are SHADOW: flip the poll mode in this transaction)
    await db_session.execute(text("alter table news_poll disable trigger tr_news_poll_append_only"))
    await db_session.execute(text("update news_poll set mode = 'PRODUCTION'"))
    got = await NP.items(db_session, T0 + _dt.timedelta(minutes=1))
    assert got and all(g["scope"] in SC.SCOPES and g["category"] not in SC.SCOPES[:1]
                       and g["dedup_decision"] for g in got)
    assert all(g["scope_version"] == "scope-v1" for g in got)
