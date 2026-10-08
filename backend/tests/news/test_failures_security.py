"""Failure and hostile-input matrix of the news pipeline (pure: client, parsers,
process). Each case ends in a recorded outcome or issue - never a crash, never
a guess, never unsafe text or links passed on."""

from __future__ import annotations

import datetime as _dt
import random

import httpx
import pytest

from app.core import clock
from app.news import collector as C
from app.news import http as H
from app.news import sanitise as SAN
from app.news.model import ItemObs
from app.news.sources import SOURCES
from app.news.sources.rss import rss_parser
from tests.news.test_pilot import T0, UNIVERSE

ET = SOURCES["ET_STOCKS_RSS"]


def rss(*items: str, ttl: str = "") -> bytes:
    return (f"<rss version=\"2.0\"><channel><title>t</title>{ttl}" + "".join(items)
            + "</channel></rss>").encode()


def it(title="Nifty ends higher", link="https://economictimes.indiatimes.com/a/1.cms",
       pub="Tue, 29 Sep 2026 10:00:00 +0530", desc="d"):
    link_xml = f"<link>{link}</link>" if link is not None else ""
    pub_xml = f"<pubDate>{pub}</pubDate>" if pub is not None else ""
    return (f"<item><title>{title}</title>{link_xml}<description>{desc}</description>"
            f"{pub_xml}</item>")


def run(body: bytes | None = None, status=200, exc: Exception | None = None, seen=None):
    def handler(req):
        if exc is not None:
            raise exc
        return httpx.Response(status, content=body or b"")
    clock.freeze(T0)
    try:
        import asyncio
        st = H.SourceState()
        f = asyncio.run(H.fetch(ET.url, st, transport=httpx.MockTransport(handler)))
        o = C.process(ET, f, seen if seen is not None else {}, universe=UNIVERSE,
                      aliases=C.EN.Aliases(), first_success=False)
        return f, o, st
    finally:
        clock.unfreeze()


class TestTransportFailures:
    @pytest.mark.parametrize("exc", [
        httpx.ConnectError("[Errno -2] Name or service not known"),       # DNS
        httpx.ConnectTimeout("timed out"), httpx.ReadTimeout("timed out"),
        httpx.RemoteProtocolError("peer closed connection without response"),
    ])
    def test_network_errors_are_recorded_and_back_off(self, exc):
        f, o, st = run(exc=exc)
        assert f.outcome == "ERROR" and type(exc).__name__ in f.error
        assert o.new == [] and st.failures == 1
        assert H.next_delay(120, st, random.Random(0)) >= 120 * 0.8

    @pytest.mark.parametrize("status,outcome", [(500, "ERROR"), (502, "ERROR"),
                                                (503, "RATE_LIMITED"), (429, "RATE_LIMITED"),
                                                (403, "BLOCKED"), (401, "AUTH_FAILED"),
                                                (404, "ERROR")])
    def test_http_statuses(self, status, outcome):
        f, o, _ = run(status=status)
        assert f.outcome == outcome and o.new == []

    def test_oversized_payload_is_not_read_or_parsed(self, monkeypatch):
        monkeypatch.setattr(H, "MAX_BYTES", 1000)
        f, o, st = run(rss(*[it(title=f"x{i}", link=f"https://e.com/{i}") for i in range(50)]))
        assert f.outcome == "ERROR" and "payload over 1000 bytes" in f.error
        assert f.body == b"" and o.new == [] and st.failures == 1 and st.etag is None


class TestMalformedFeeds:
    @pytest.mark.parametrize("body", [
        b"", b"not xml", b"<rss><channel>", b"<html>blocked</html>",
        b"<rss version='2.0'><channel><item><title>x</title>"])
    def test_malformed_or_truncated(self, body):
        _, o, _ = run(body)
        assert o.fetch.outcome == "MALFORMED" and o.new == []

    def test_empty_feed_is_ok_with_nothing_new(self):
        _, o, _ = run(rss())
        assert o.fetch.outcome == "OK" and o.seen == 0 and o.new == []

    def test_duplicate_items_in_one_feed_are_stored_once(self):
        _, o, _ = run(rss(it(), it()))
        assert len(o.new) == 1 and [i["kind"] for i in o.issues] == ["DUPLICATE_IN_FEED"]

    @pytest.mark.parametrize("pub,kind", [("29 Sep 2026 10:00:00", "BAD_TIMESTAMP"),  # no zone
                                          ("yesterday", "BAD_TIMESTAMP")])
    def test_bad_or_zoneless_dates_are_never_guessed(self, pub, kind):
        _, o, _ = run(rss(it(pub=pub)))
        assert o.new[0].item.published_at is None and kind in [i["kind"] for i in o.issues]

    def test_missing_date_has_no_latency(self):
        _, o, _ = run(rss(it(pub=None)))
        assert o.new[0].item.published_at is None and o.new[0].latency_s is None

    def test_future_date_is_kept_as_the_publishers_claim(self):
        _, o, _ = run(rss(it(pub="Tue, 29 Sep 2026 23:59:00 +0530")))
        d = o.new[0]
        assert d.item.published_at > d.discovered_at and d.discovered_at == T0  # knowable = seen

    def test_an_item_missing_from_the_feed_is_not_deleted(self):
        seen: dict = {}
        run(rss(it(), it(title="Second", link="https://e.com/2")), seen=seen)
        _, o, _ = run(rss(it()), seen=seen)                      # "Second" disappeared
        assert o.new == [] and o.changed == [] and len(seen) == 2

    def test_an_edit_is_a_change_not_a_new_item(self):
        seen: dict = {}
        run(rss(it()), seen=seen)
        _, o, _ = run(rss(it(title="Nifty ends higher; banks lead")), seen=seen)
        assert o.new == [] and [c for _, c in o.changed] == [["title"]]


class TestHostileText:
    def test_html_and_encoded_script_are_removed(self):
        _, o, _ = run(rss(it(
            title="&lt;script&gt;alert(1)&lt;/script&gt;Rupee &lt;b&gt;falls&lt;/b&gt;")))
        t = o.new[0].item.title
        assert "<" not in t and ">" not in t and "Rupee" in t and "falls" in t

    def test_control_characters_cannot_inject_log_lines(self):
        s = SAN.text('Nifty\n{"event": "fake", "level": "error"}\x1b[31m\r\u2028up', 200)
        assert "\n" not in s and "\x1b" not in s and "\r" not in s and "\u2028" not in s

    def test_very_long_titles_are_capped(self):
        _, o, _ = run(rss(it(title="A" * 5000)))
        assert len(o.new[0].item.title) == SAN.TITLE_MAX and o.new[0].item.title.endswith("…")

    def test_unicode_is_kept(self):
        _, o, _ = run(rss(it(title="रुपया 96 के पार 📉 — Rupee crosses 96")))
        assert o.new[0].item.title == "रुपया 96 के पार 📉 — Rupee crosses 96"

    @pytest.mark.parametrize("link", ["javascript:alert(1)", "data:text/html,x", "/relative/path",
                                      "https://", "https://e.com/a b", "ftp://e.com/x",
                                      "https://e.com/" + "a" * 3000])
    def test_unsafe_links_are_dropped_with_an_issue(self, link):
        _, o, _ = run(rss(it(link=link)))
        assert o.new[0].item.url is None
        assert "BAD_URL" in [i["kind"] for i in o.issues]

    def test_a_title_of_only_markup_is_not_an_item(self):
        _, o, _ = run(rss(it(title="&lt;b&gt;&lt;/b&gt;")))
        assert o.new == [] and "MALFORMED_ITEM" in [i["kind"] for i in o.issues]

    def test_nse_titles_are_sanitised_too(self):
        raw = ItemObs("id", "X Ltd\n<script>", "javascript:x", "NSE", None, None)
        safe, iss = SAN.item(raw)
        assert safe.title == "X Ltd" and safe.url is None and iss[0][0] == "BAD_URL"


def test_rss_parser_still_parses_a_normal_feed():
    f = rss_parser("ET")(rss(it(), ttl="<ttl>5</ttl>"))
    assert f.ttl_minutes == 5 and f.items[0].published_at == _dt.datetime(
        2026, 9, 29, 4, 30, tzinfo=_dt.UTC)


class TestFlappingFeeds:
    def test_a_field_missing_from_one_response_is_not_an_edit(self):
        seen: dict = {}
        run(rss(it()), seen=seen)
        _, o, _ = run(rss(it(pub=None)), seen=seen)             # the time disappears
        assert o.changed == []
        _, o, _ = run(rss(it()), seen=seen)                     # ...and comes back
        assert o.changed == []

    def test_a_new_value_is_still_an_edit_and_keeps_the_known_time(self):
        seen: dict = {}
        run(rss(it()), seen=seen)
        _, o, _ = run(rss(it(title="Nifty ends higher; banks lead", pub=None)), seen=seen)
        (item, changed), = o.changed
        assert changed == ["title"]
        assert item.published_at is not None                    # not recorded as removed


class TestXmlRepair:
    """Regression (2026-10-06): Business Standard emitted a bare '&' ("T&D sector") in
    <media:title>; the whole feed was MALFORMED for most of the day (57 polls)."""

    def test_a_bare_ampersand_is_repaired_and_recorded(self):
        _, o, _ = run(rss(it(title="GEC-III boosts outlook for T&D sector")))
        assert o.fetch.outcome == "OK" and o.new[0].item.title == \
            "GEC-III boosts outlook for T&D sector"
        assert "REPAIRED_XML" in [i["kind"] for i in o.issues]

    def test_valid_entities_are_untouched_and_no_repair_is_recorded(self):
        _, o, _ = run(rss(it(title="M&amp;M &#38; L&#x26;T &lt;b&gt;")))
        assert o.new[0].item.title == "M&M & L&T" and "REPAIRED_XML" not in [
            i["kind"] for i in o.issues]

    @pytest.mark.parametrize("body", [
        b"<rss version='2.0'><channel><item><title>x &amp; y</title>",       # truncated
        b"<rss version='2.0'><channel><item><title>a < b</title></item></channel></rss>",
        b'<!DOCTYPE r [<!ENTITY a "x">]><rss><channel/></rss>',            # DTD refused
    ])
    def test_only_the_ampersand_is_repaired(self, body):
        _, o, _ = run(body)
        assert o.fetch.outcome == "MALFORMED"

    def test_nse_uses_the_same_repair(self):
        from app.news.sources import nse_announcements as NSE
        body = (b"<rss version='2.0'><channel><item><title>A&B Ltd</title><link>"
                b"https://nsearchives.nseindia.com/corporate/AB_29092026101010_x.pdf</link>"
                b"<pubDate>29-Sep-2026 10:10:10</pubDate></item></channel></rss>")
        f = NSE.parse(body)
        assert f.items[0].title == "A&B Ltd" and f.issues[0].kind == "REPAIRED_XML"
