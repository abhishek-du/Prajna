"""News intelligence layers (pure): non-company mentions, reviewed aliases
(fail-closed), story grouping (point in time, with evidence), and the
rule-based assessment (potential relevance, never a prediction)."""

from __future__ import annotations

import datetime as _dt

import pytest

from app.core.clock import IST
from app.news import assess as A
from app.news import collector as C
from app.news import enrich as EN
from app.news import entities as X
from app.news import http as H
from app.news import stories as ST
from app.news.model import ItemObs, title_hash
from app.news.sources import SOURCES

UNI = EN.Universe({
    "SBIN": ("k:sbin", "STATE BANK OF INDIA"),
    "SBILIFE": ("k:sbilife", "SBI LIFE INSURANCE CO LTD"),
    "LT": ("k:lt", "LARSEN & TOUBRO LTD."), "LTF": ("k:ltf", "L&T FINANCE LIMITED"),
    "M&M": ("k:mm", "MAHINDRA & MAHINDRA LTD"), "M&MFIN": ("k:mmfin", "M&M FIN. SERV. LTD"),
    "BEL": ("k:bel", "BHARAT ELECTRONICS LTD"), "AEGISLOG": ("k:aegis", "AEGIS LOGISTICS LTD"),
})
T0 = _dt.datetime(2026, 9, 28, 10, 0, tzinfo=IST)


def item(title, sid="x", pub=None):
    return ItemObs(sid, title, None, "p", pub, None)


def keys(links):
    return [ln.instrument_key for ln in links]


class TestMentions:
    @pytest.mark.parametrize("title,expected", [
        ("Sensex tumbles 1,100 points as crude surges; rupee weakens",
         {("INDEX", "SENSEX"), ("COMMODITY", "CRUDE_OIL"), ("CURRENCY", "INR")}),
        ("RBI keeps repo rate unchanged; Nifty Bank rises",
         {("INDEX", "NIFTY_BANK"), ("CENTRAL_BANK", "RBI")}),
        ("Supreme Court notice to RBI, NPCI on UPI MDR",
         {("COURT", "SUPREME_COURT"), ("CENTRAL_BANK", "RBI")}),
        ("US 10-year Treasury yield tops 5% as Fed signals hikes",
         {("BOND_YIELD", "US_10Y"), ("CENTRAL_BANK", "US_FED")}),
        ("Oil jumps as US-Iran talks stall", {("COMMODITY", "CRUDE_OIL"),
                                              ("GEOPOLITICAL", "US_IRAN")})])
    def test_entities(self, title, expected):
        got = {(m.entity_type, m.entity_id) for m in X.mentions(item(title))}
        assert expected <= got
        assert all(m.evidence and m.version == X.MENTION_VERSION for m in X.mentions(item(title)))

    def test_nifty_bank_is_not_the_banking_sector_or_nifty_50(self):
        got = {(m.entity_type, m.entity_id) for m in X.mentions(item("Nifty Bank rises 1%"))}
        assert ("SECTOR", "BANKING") not in got and ("INDEX", "NIFTY_50") not in got


class TestAliases:
    @pytest.mark.parametrize("title,expected", [
        ("Adani Enterprises, BEL, L&T among top losers", ["k:bel", "k:lt"]),
        ("SBI hikes lending rates", ["k:sbin"]),
        ("M&M launches new SUV", ["k:mm"]),
        # fail-closed: the next word makes it another listed company
        ("SBI Life falls on IRDAI draft", []), ("L&T Finance raises Rs 500 cr", []),
        ("M&M Financial Services Q2 update", []),
        # never inside words or lower-case
        ("Asbi and ltd sbi words", [])])
    def test_reviewed_aliases(self, title, expected):
        assert keys(X.alias_links(item(title), UNI)) == expected

    def test_alias_needs_the_symbol_in_the_universe(self):
        assert X.alias_links(item("ONGC shares rise"), UNI) == []
        assert X.alias_links(item("SBI up"), None) == []


def member(key, title, src, t, *, companies=(), category="OTHER", url=None, strict=False,
           knowable=None, entities=()):
    return ST.Member(key, "", src, ST.words(title), url, title_hash(title), frozenset(companies),
                     frozenset(entities), category, t, knowable or t, strict)


class TestStories:
    def test_same_event_across_publishers_is_grouped_with_evidence(self):
        ix = ST.StoryIndex()
        mkt = {"entities": ["INDEX:SENSEX"], "category": "MARKET_WIDE"}
        a = member("ET|1", "Why did stock market crash today? Sensex tumbles 1,124 points", "ET",
                   T0, **mkt)
        a.story_id = ix.new_id()
        ix.add(a)
        b = member("CNBC|9", "Stock Market Crash: Key factors behind Sensex tumbles 1,100 points",
                   "CNBC", T0 + _dt.timedelta(minutes=20), **mkt)
        got = ix.assign(b, b.knowable_at)
        assert got.story_id == a.story_id and got.method == "SIMILAR"
        assert got.evidence["with"] == "ET|1"
        assert got.evidence["shared_entities"] == ["INDEX:SENSEX"]
        # the same wording WITHOUT the shared entity/category is not enough on its own
        c = member("BL|1", "Stock Market Crash: Key factors behind Sensex tumbles 1,100 points",
                   "BL", T0 + _dt.timedelta(minutes=20))
        assert ix.assign(c, c.knowable_at).method == "FOUNDER"

    def test_same_company_and_event_with_different_wording(self):
        ix = ST.StoryIndex()
        a = member("BS|1", "Board of Aegis Logistics approves fund raising up to Rs 6,000 cr", "BS",
                   T0, companies=["k:aegis"], category="FUNDRAISING")
        a.story_id = ix.new_id()
        ix.add(a)
        b = member("BS|2", "Aegis Logistics board approves Rs 6,000 crore fund raising proposal",
                   "BS", T0 + _dt.timedelta(minutes=5), companies=["k:aegis"],
                   category="FUNDRAISING")
        assert ix.assign(b, b.knowable_at).story_id == a.story_id

    def test_unrelated_titles_found_new_stories(self):
        ix = ST.StoryIndex()
        a = member("ET|1", "Infosys wins large deal in Europe", "ET", T0, companies=["k:infy"])
        a.story_id = ix.new_id()
        ix.add(a)
        b = member("ET|2", "Rupee falls 28 paise against US dollar", "ET", T0)
        assert ix.assign(b, T0).method == "FOUNDER"

    def test_regulator_orders_about_different_parties_are_never_merged(self):
        """Measured 2026-09-28: SEBI 'Remittance Order ... RC No. 9209' vs '... 9207'."""
        ix = ST.StoryIndex()
        a = member("SEBI|a", "Remittance Order dated September 24, 2026 issued under RC No. 9209",
                   "SEBI", T0, strict=True)
        a.story_id = ix.new_id()
        ix.add(a)
        b = member("SEBI|b", "Remittance Order dated September 24, 2026 issued under RC No. 9207",
                   "SEBI", T0, strict=True)
        assert ix.assign(b, T0).method == "FOUNDER"

    def test_point_in_time_a_member_not_yet_knowable_is_not_a_candidate(self):
        ix = ST.StoryIndex()
        late = member("ET|1", "Sensex tumbles 1,124 points as crude surges", "ET", T0,
                      knowable=T0 + _dt.timedelta(minutes=10))
        late.story_id = ix.new_id()
        ix.add(late)
        b = member("CNBC|1", "Sensex tumbles 1,124 points as crude surges", "CNBC", T0)
        assert ix.assign(b, T0 + _dt.timedelta(minutes=5)).method == "FOUNDER"
        assert ix.assign(b, T0 + _dt.timedelta(minutes=11)).method == "SAME_TITLE"


class TestAssessment:
    def kw(self, title, category, companies=(), mentions=(), **kw):
        return A.assess(title, category, companies=list(companies), mentions=list(mentions),
                        backlog=kw.get("backlog", False), published_at=kw.get("pub"),
                        discovered_at=kw.get("disc", T0), confirmed_by=kw.get("confirmed"))

    def test_large_order_is_high_potential_but_direction_is_only_from_words(self):
        a = self.kw("Company receives Rs 5,000 crore order", "ORDER_CONTRACT", ["k:x"])
        assert (a.market_scope, a.potential_impact) == ("STOCK", "HIGH")
        assert a.evidence["impact_rule"] == "sized event >= Rs 1,000 crore"
        assert a.impact_direction == "UNKNOWN"          # "receives" is not a claim of a rise
        assert self.kw("Paras bags order worth Rs 26 cr", "ORDER_CONTRACT",
                       ["k:p"]).potential_impact == "MEDIUM"

    def test_scope_direction_and_groups(self):
        a = self.kw("Sensex tumbles 1,100 points", "MARKET_WIDE",
                    mentions=[("INDEX", "SENSEX")])
        assert (a.market_scope, a.impact_direction, a.event_group) == ("MARKET", "NEGATIVE",
                                                                       "MARKET")
        m = self.kw("RBI keeps repo rate unchanged", "INTEREST_RATE",
                    mentions=[("CENTRAL_BANK", "RBI")])
        assert (m.market_scope, m.impact_direction, m.potential_impact) == ("MACRO", "NEUTRAL",
                                                                           "HIGH")
        assert self.kw("Stocks drop up to 38% in 3 days", "OTHER").impact_direction == "NEGATIVE"
        assert self.kw("X rises then falls", "OTHER").impact_direction == "MIXED"
        assert self.kw("An interview", "OTHER").potential_impact == "UNKNOWN"

    def test_breaking_is_observable_only(self):
        pub = T0 - _dt.timedelta(minutes=7)
        live = self.kw("Company X Q2 net profit jumps 40%", "RESULTS", ["k:x"], pub=pub)
        assert live.is_breaking and "15 min" in live.breaking_reason
        assert not self.kw("Company X Q2 net profit jumps 40%", "RESULTS", ["k:x"], pub=pub,
                           backlog=True).is_breaking              # backlog is never breaking
        old = self.kw("Company X Q2 net profit jumps 40%", "RESULTS", ["k:x"],
                      pub=T0 - _dt.timedelta(hours=2))
        assert not old.is_breaking
        assert self.kw("Some update", "OTHER", confirmed=["ET"]).is_breaking


class TestWiring:
    def test_discoveries_carry_mentions_story_and_assessment(self):
        rss = (b'<rss version="2.0"><channel>'
               b"<item><title>Sensex tumbles 1,124 points as crude surges</title>"
               b"<link>https://x/a</link><pubDate>Mon, 28 Sep 2026 09:50:00 +0530</pubDate></item>"
               b"</channel></rss>")
        rss2 = rss.replace(b"https://x/a", b"https://y/b")
        ix = ST.StoryIndex()
        at = T0
        o1 = C.process(SOURCES["ET_STOCKS_RSS"], H.FetchResult("OK", at, at, 200, rss), {},
                       universe=UNI, aliases=EN.Aliases(), first_success=False, stories=ix)
        at2 = T0 + _dt.timedelta(minutes=4)
        o2 = C.process(SOURCES["MINT_MARKETS_RSS"], H.FetchResult("OK", at2, at2, 200, rss2), {},
                       universe=UNI, aliases=EN.Aliases(), first_success=False, stories=ix)
        d1, d2 = o1.new[0], o2.new[0]
        assert {m.entity_id for m in d1.mentions} >= {"SENSEX", "CRUDE_OIL"}
        assert d2.story_id == d1.story_id and d2.story.method == "SAME_TITLE"
        assert d2.assessment.is_breaking and "confirmed" in d2.assessment.breaking_reason
        assert d1.latency_class == "LIVE_DISCOVERY" and d1.latency_s == 600.0
