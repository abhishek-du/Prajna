"""Media adapters (ET, Business Standard, BusinessLine, Livemint, CNBC-TV18):
parsing real feed samples, headline entity links (precision over recall),
keyword classification, and multi-link items. Pure; no network, no database."""

from __future__ import annotations

import datetime as _dt
import pathlib

import pytest

from app.core.clock import IST, UTC
from app.news import collector as C
from app.news import enrich as EN
from app.news import http as H
from app.news.model import ItemObs
from app.news.sources import SOURCES
from app.news.sources.rss import FeedDecodeError, clean, news_sitemap_parser, rss_parser

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "news_media"
MEDIA = ("ET_STOCKS_RSS", "BS_MARKETS_RSS", "BL_MARKETS_RSS", "MINT_MARKETS_RSS",
         "CNBCTV18_NEWS_SITEMAP")
UNI = EN.Universe({
    "HDFCBANK": ("k:hdfcbank", "HDFC BANK LTD"), "HDFCLIFE": ("k:hdfclife", "HDFC LIFE INS CO LTD"),
    "INFY": ("k:infy", "INFOSYS LIMITED"), "LUPIN": ("k:lupin", "LUPIN LIMITED"),
    "ADANIENT": ("k:adanient", "ADANI ENTERPRISES LIMITED"),
    "KALPATARU": ("k:kalpataru", "KALPATARU LIMITED"),
    "KPIL": ("k:kpil", "KALPATARU PROJECT INT LTD"),
    "INDIANB": ("k:indianb", "INDIAN BANK"), "PARAS": ("k:paras", "PARAS DEF AND SPCE TECH L"),
    "AXISBANK": ("k:axis", "AXIS BANK LIMITED"), "ASIANPAINT": ("k:asian", "ASIAN PAINTS LIMITED"),
})
IDX = EN.HeadlineIndex(UNI)


def body(k: str) -> bytes:
    return (FIX / f"{k}.xml").read_bytes()


def links(title: str) -> list[str]:
    return [ln.instrument_key for ln in EN.resolve_headline(
        ItemObs("x", title, None, "p", None, None), UNI, IDX) if ln.instrument_key]


class TestParsers:
    @pytest.mark.parametrize("key", MEDIA)
    def test_every_adapter_parses_its_real_sample(self, key):
        f = SOURCES[key].parse(body(key))
        assert len(f.items) == 6 and not f.issues
        for i in f.items:
            assert i.title and i.url and i.published_at and i.published_at.tzinfo == UTC
            assert i.source_article_id

    def test_rfc822_times_and_ids(self):
        f = SOURCES["BS_MARKETS_RSS"].parse(body("BS_MARKETS_RSS"))
        i = next(x for x in f.items if x.title.startswith("Aegis Logistics"))
        assert i.published_at == _dt.datetime(2026, 9, 28, 15, 50, 2, tzinfo=IST)
        assert i.source_updated_at == _dt.datetime(2026, 9, 28, 15, 50, 17, tzinfo=IST)
        assert i.publisher == "Business Standard" and "Capital Market News" in i.category_raw

    def test_non_url_guid_is_namespaced_and_ttl_is_read(self):
        f = SOURCES["BL_MARKETS_RSS"].parse(body("BL_MARKETS_RSS"))
        assert f.ttl_minutes == 60
        assert all(i.source_article_id.startswith("BusinessLine:article-") for i in f.items)

    def test_news_sitemap(self):
        f = SOURCES["CNBCTV18_NEWS_SITEMAP"].parse(body("CNBCTV18_NEWS_SITEMAP"))
        i = f.items[0]
        assert i.title.startswith("Sensex closes over 1,000 points lower")
        assert i.published_at == _dt.datetime(2026, 9, 28, 15, 42, 35, tzinfo=IST)
        assert i.source_updated_at == _dt.datetime(2026, 9, 28, 15, 56, 1, tzinfo=IST)
        assert "crude prices" in i.category_raw and i.summary is None

    def test_malformed_items_and_bad_dates_are_reported(self):
        rss = (b'<rss version="2.0"><channel><item><link>https://x/a</link></item>'
               b"<item><title>T</title><link>https://x/b</link><pubDate>someday</pubDate></item>"
               b"<item><title>T2</title><link>https://x/b</link></item>"
               b"<item><title>T3</title><link>https://x/c</link>"
               b"<pubDate>Mon, 28 Sep 2026 10:00:00</pubDate></item></channel></rss>")
        f = rss_parser("X")(rss)
        assert [i.kind for i in f.issues] == ["MALFORMED_ITEM", "BAD_TIMESTAMP",
                                              "DUPLICATE_IN_FEED", "BAD_TIMESTAMP"]
        assert f.items[1].published_at is None           # a zone-less time is not guessed

    @pytest.mark.parametrize("parser,bad", [
        (rss_parser("X"), b"<urlset/>"), (news_sitemap_parser("X"), b"<rss/>"),
        (rss_parser("X"), b"<html>Access denied</html>"),
        (rss_parser("X"), b'<!DOCTYPE rss [<!ENTITY a "x">]><rss><channel/></rss>')])
    def test_wrong_or_hostile_documents_are_refused(self, parser, bad):
        with pytest.raises(FeedDecodeError):
            parser(bad)

    def test_description_is_stripped_and_short(self):
        assert clean("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
        assert len(clean("x" * 2000)) == 500


class TestHeadlineEntities:
    def test_names_in_headlines(self):
        assert links("Why HDFC Bank shares fall 2% as banking stocks decline") == ["k:hdfcbank"]
        assert links("Axis Bank, Asian Paints, Infosys in focus") == ["k:axis", "k:asian",
                                                                      "k:infy"]
        assert links("Lupin receives tentative approval from US FDA") == ["k:lupin"]

    def test_a_shared_first_word_is_not_guessed(self):
        """Measured 2026-09-28: 'Kalpataru Projects' was linked to Kalpataru Ltd."""
        assert links("Kalpataru Projects shares rise 2.5% despite market sell-off") == []

    def test_generic_names_and_truncated_vendor_names_are_not_matched(self):
        assert links("Indian bank stocks fall as crude rises") == []          # INDIAN BANK
        assert links("Paras Defence bags DRDO order") == []    # vendor name is abbreviated

    def test_no_company_is_one_unresolved_link(self):
        ls = EN.resolve_headline(ItemObs("x", "Sensex tumbles 1,100 points", None, "p", None,
                                         None), UNI, IDX)
        assert [ln.method for ln in ls] == ["UNRESOLVED"] and ls[0].reason

    def test_database_down(self):
        ls = EN.resolve_headline(ItemObs("x", "Infosys up", None, "p", None, None), None, None)
        assert ls[0].method == "UNRESOLVED" and "unavailable" in ls[0].reason


class TestKeywords:
    @pytest.mark.parametrize("title,cat", [
        ("Sensex closes over 1,000 points lower: 5 reasons", "MARKET_WIDE"),
        ("Gold, silver ETFs tumble up to 4% as precious metals melt", "COMMODITIES"),
        ("Pioneer Fil-Med, Tonbo Imaging among 3 firms to get Sebi nod for IPOs", "FUNDRAISING"),
        ("Aegis Logistics board approves Rs 6,000 crore fund raising proposal", "FUNDRAISING"),
        ("Paras receives order worth Rs 26.59 cr from DRDO", "ORDER_CONTRACT"),
        ("FII outflows in 2 years leave decade-long investment near nil", "FII_DII"),
        ("Rategain announces change in CFO", "OTHER")])
    def test_rules(self, title, cat):
        c = EN.classify_keywords(ItemObs("x", title, None, "p", None, None))
        assert c.category == cat and c.method == "KEYWORD_RULES"
        assert c.confidence == (0.3 if cat == "OTHER" else 0.6)     # a heuristic, not truth


class TestMultiLink:
    def test_media_items_carry_every_link_and_the_best_one(self):
        rss = (b'<rss version="2.0"><channel><item><title>Axis Bank, Asian Paints fall</title>'
               b"<link>https://x/a</link><pubDate>Mon, 28 Sep 2026 10:00:00 +0530</pubDate>"
               b"</item></channel></rss>")
        src = SOURCES["ET_STOCKS_RSS"]
        at = _dt.datetime(2026, 9, 28, 10, 5, tzinfo=IST)
        o = C.process(src, H.FetchResult("OK", at, at, 200, rss), {}, universe=UNI,
                      aliases=EN.Aliases(), first_success=False)
        d = o.new[0]
        assert [ln.instrument_key for ln in d.links] == ["k:axis", "k:asian"]
        assert d.link.confidence == 0.8 and d.classification.method == "KEYWORD_RULES"
        assert d.latency_s == 300.0 and d.discovered_at == at
