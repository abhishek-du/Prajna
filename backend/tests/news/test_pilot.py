"""News pilot (NSE corporate announcements): parsing, timing, entity links,
classification, the polite client, dry-run evidence, and failure isolation.
Pure / file-system only: the network is blocked in tests (httpx.MockTransport)."""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import random

import httpx
import pytest

from app.core import clock
from app.core.clock import IST, UTC
from app.news import collector as C
from app.news import enrich as EN
from app.news import http as H
from app.news import report as RP
from app.news.model import ItemObs, canonical_url, normalise_title, title_hash
from app.news.sources import SOURCES
from app.news.sources import nse_announcements as NSE

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "nse_announcements" / "sample.xml"
BODY = FIX.read_bytes()
SRC = SOURCES["NSE_ANNOUNCEMENTS"]
T0 = _dt.datetime(2026, 9, 28, 15, 35, tzinfo=IST)
UNIVERSE = EN.Universe({
    "JMA": ("NSE_EQ|INE412C01023", "JULLUNDUR MOT AGENCY LTD"),
    "SHEETAL": ("NSE_EQ|INE04VX01019", "SHEETAL UNIVERSAL LIMITED"),
    "PARAS": ("NSE_EQ|INE045601023", "PARAS DEF AND SPCE TECH L"),
    "AMNPLST": ("NSE_EQ|INE275D01022", "AMINES & PLASTICIZERS LTD"),
    "PIRAMALFIN": ("NSE_EQ|INE202B01038", "PIRAMAL FINANCE LIMITED"),
    "IDBITSL": ("NSE_EQ|INE000X00001", "IDBI TRUSTEESHIP SERV LTD"),   # a trustee, listed
    "AXISBANK": ("NSE_EQ|INE238A01034", "AXIS BANK LIMITED"),
})


def obs(**kw) -> ItemObs:
    base = dict(source_article_id="x", title="Jullundur Motor Agency (Delhi) Limited", url=None,
                publisher="NSE", published_at=None, published_at_raw=None)
    return ItemObs(**{**base, **kw})


# ── adapter (pure) ───────────────────────────────────────────────────────────
class TestParse:
    def test_items_symbols_subjects_and_times(self):
        f = NSE.parse(BODY)
        assert f.ttl_minutes == 5
        by = {i.title: i for i in f.items}
        j = by["Jullundur Motor Agency (Delhi) Limited"]
        assert j.symbol_raw == "JMA" and j.category_raw == "Trading Window"
        assert j.published_at == _dt.datetime(2026, 9, 28, 10, 1, 17, tzinfo=UTC)   # IST 15:31:17
        assert j.published_at_raw == "28-Sep-2026 15:31:17" and j.publisher == "NSE"
        assert by["Axis Mutual Fund - Axis Gold ETF"].source_article_id.startswith("sha256:")
        assert by["Axis Mutual Fund - Axis Gold ETF"].symbol_raw is None
        xbrl = [i for i in f.items if "/xbrl/" in (i.url or "")]
        assert xbrl and xbrl[0].symbol_raw is None               # never guessed from xbrl names

    def test_malformed_duplicate_and_bad_timestamp_are_reported_not_fatal(self):
        f = NSE.parse(BODY)
        kinds = [i.kind for i in f.issues]
        assert kinds.count("MALFORMED_ITEM") == 1                # the item without a title
        assert kinds.count("DUPLICATE_IN_FEED") == 1             # the repeated debt notice
        assert kinds.count("BAD_TIMESTAMP") == 1
        bad = next(i for i in f.items if i.title == "Bad Date Limited")
        assert bad.published_at is None and bad.published_at_raw == "yesterday-ish"

    @pytest.mark.parametrize("body", [
        b"<html>blocked</html>", b"not xml at all", b"",
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
        b"<rss><channel><title>&b;</title></channel></rss>"])
    def test_non_rss_is_a_decode_error(self, body):
        with pytest.raises(NSE.FeedDecodeError):
            NSE.parse(body)

    def test_normalisation(self):
        assert canonical_url("HTTP://WWW.X.com/a/b/amp/?utm_source=t&id=3#frag") == \
            "https://www.x.com/a/b?id=3"
        assert normalise_title("  Infosys  Q2: profit UP 5%! ") == "infosys q2 profit up 5"
        assert title_hash("A-B") == title_hash("a b")


# ── enrichment ───────────────────────────────────────────────────────────────
class TestEntities:
    def test_exact_symbol_needs_the_filer_name_to_agree(self):
        ln = EN.resolve(obs(symbol_raw="JMA"), UNIVERSE, EN.Aliases())
        assert (ln.method, ln.instrument_key, ln.confidence) == ("EXACT_SYMBOL",
                                                                  "NSE_EQ|INE412C01023", 1.0)

    def test_uploader_symbol_of_another_company_is_not_trusted(self):
        """A trustee (IDBITSL) files for Piramal Finance: the name decides."""
        ln = EN.resolve(obs(title="Piramal Finance Limited", symbol_raw="IDBITSL"), UNIVERSE,
                        EN.Aliases())
        assert ln.method == "COMPANY_NAME" and ln.instrument_key == "NSE_EQ|INE202B01038"
        assert "IDBITSL" in ln.reason

    def test_unknown_symbol_falls_back_to_the_name(self):
        ln = EN.resolve(obs(title="Amines & Plasticizers Limited", symbol_raw="OMKAR"),
                        UNIVERSE, EN.Aliases())
        assert ln.method == "COMPANY_NAME" and ln.instrument_key == "NSE_EQ|INE275D01022"

    def test_abbreviated_vendor_names_agree_but_different_companies_do_not(self):
        assert EN.names_agree("Paras Defence and Space Technologies Limited",
                              "PARAS DEF AND SPCE TECH L")
        assert not EN.names_agree("Axis Mutual Fund - Axis Gold ETF", "AXIS BANK LIMITED")
        assert not EN.names_agree("Piramal Finance Limited", "PIRAMAL PHARMA LIMITED")
        assert not EN.names_agree("Reliance", "RELIANCE INDUSTRIES LTD")
        strict = [  # measured on the 2026-09-28 feed
            ("Jullundur Motor Agency (Delhi) Limited", "JULLUNDUR MOT AGENCY LTD", True),
            ("Hindustan Petroleum Corporation Limited", "HINDUSTAN PETROLEUM CORP", True),
            ("The Bombay Burmah Trading Corporation Limited", "BOMBAY BURMAH TRADING COR", True),
            ("Khfm Hospitality And Facility Management Services Limited",
             "KHFM HOS FAC MANA SER LTD", True),
            ("SUNDARAM HOME FINANCE LIMITED", "SUNDARAM FINANCE LTD", False),
            ("Arvind SmartSpaces Limited", "ARVIND LIMITED", False),
            ("Emami Realty Limited", "EMAMI LTD", False),
            ("Kotak Mahindra Mutual Fund - Kotak Nifty MNC ETF", "KOTAK NIFTY ETF", False)]
        for filer, name, want in strict:
            assert EN.names_agree(filer, name, strict=True) is want, (filer, name)

    def test_fund_schemes_are_not_mapped_by_name(self):
        u = EN.Universe({"KOTAKNIFTY": ("k", "KOTAK NIFTY ETF")})
        ln = EN.resolve(obs(title="Kotak Mahindra Mutual Fund - Kotak Nifty MNC ETF"), u,
                        EN.Aliases())
        assert ln.method == "UNRESOLVED" and "fund" in ln.reason

    def test_unknown_and_ambiguous_stay_unresolved(self):
        assert EN.resolve(obs(title="Unknown Widgets Limited"), UNIVERSE,
                          EN.Aliases()).method == "UNRESOLVED"
        u = EN.Universe({"AB1": ("k1", "ACME BRAKES LTD"), "AB2": ("k2", "ACME BRAKES LIMITED")})
        ln = EN.resolve(obs(title="Acme Brakes Limited"), u, EN.Aliases())
        assert ln.method == "UNRESOLVED" and "several" in ln.reason

    def test_alias_is_learned_only_from_exact_links(self):
        a = EN.Aliases()
        odd = EN.Universe({"ODD": ("k", "ODDLY NAMED HOLDINGS LTD")})
        filer = "Oddly Named Holdings Ltd."
        assert EN.resolve(obs(title=filer, symbol_raw="ODD"), odd, a).method == "EXACT_SYMBOL"
        assert a.lookup(filer) == ("ODD", None)

    def test_database_down_means_unresolved_not_failure(self):
        ln = EN.resolve(obs(symbol_raw="JMA"), None, EN.Aliases())
        assert ln.method == "UNRESOLVED" and "unavailable" in ln.reason


class TestClassification:
    @pytest.mark.parametrize("subject,cat", [
        ("Bagging/Receiving of orders/contracts", "ORDER_CONTRACT"),
        ("Financial Result Updates", "RESULTS"),
        ("Change in Directors/KMP/SMP/Auditor/RTA", "MANAGEMENT_CHANGE"),
        ("Corporate Insolvency Resolution Process", "BANKRUPTCY"),
        ("Confirmation of Redemption/Payment of Interest and Principal", "DEBT"),
        ("Acquisition (including agreement to acquire)-XBRL", "MERGER_ACQUISITION"),
        ("Credit Rating", "RATING_CHANGE"), ("Record Date Updates", "CORPORATE_ACTION")])
    def test_exchange_subjects(self, subject, cat):
        c = EN.classify(obs(category_raw=subject))
        assert (c.category, c.confidence, c.method) == (cat, 1.0, "EXCHANGE_SUBJECT")

    def test_unmapped_is_other_with_low_confidence(self):
        assert EN.classify(obs(category_raw="Trading Window")) == \
            EN.Classification("OTHER", 0.5, "EXCHANGE_SUBJECT", EN.CLASSIFY_VERSION)


# ── polite client ────────────────────────────────────────────────────────────
def transport(*responses):
    """A MockTransport replaying responses in order; records the requests."""
    seq, seen = list(responses), []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        r = seq.pop(0)
        return r() if callable(r) else r
    t = httpx.MockTransport(handler)
    t.requests = seen
    return t


OK = httpx.Response(200, content=BODY, headers={"etag": 'W/"1"', "last-modified": "Mon, 28 Sep "
                                                "2026 10:01:48 GMT"})


class TestClient:
    async def test_conditional_get_and_304(self):
        st = H.SourceState()
        t = transport(OK, httpx.Response(304))
        assert (await H.fetch("https://x/feed", st, transport=t)).outcome == "OK"
        r = await H.fetch("https://x/feed", st, transport=t)
        assert r.outcome == "NOT_MODIFIED" and r.body == b""
        assert t.requests[1].headers["if-none-match"] == 'W/"1"'
        assert "if-modified-since" in t.requests[1].headers
        assert t.requests[0].headers["user-agent"].startswith("PrajnaResearch/")

    async def test_403_stops_the_source_for_good(self):
        st = H.SourceState()
        t = transport(httpx.Response(403))
        assert (await H.fetch("https://x/feed", st, transport=t)).outcome == "BLOCKED"
        again = await H.fetch("https://x/feed", st, transport=t)
        assert again.outcome == "BLOCKED" and len(t.requests) == 1      # not retried
        assert H.health(st, last_ok=None, stale_after_s=60) == "BLOCKED"

    async def test_rate_limit_honours_retry_after(self):
        clock.freeze(T0)
        try:
            st = H.SourceState()
            limited = httpx.Response(429, headers={"retry-after": "900"})
            r = await H.fetch("https://x/feed", st, transport=transport(limited))
            assert r.outcome == "RATE_LIMITED" and r.retry_after_s == 900
            assert H.next_delay(60, st, random.Random(1)) >= 900 * 0.8
            assert H.health(st, last_ok=T0, stale_after_s=3600) == "RATE_LIMITED"
        finally:
            clock.unfreeze()

    async def test_backoff_grows_and_is_capped(self):
        st = H.SourceState()
        for _ in range(3):
            await H.fetch("https://x/feed", st, transport=transport(httpx.Response(500)))
        rng = random.Random(0)
        assert st.failures == 3
        assert 4 * 60 * 0.8 <= H.next_delay(60, st, rng) <= 4 * 60 * 1.2
        st.failures = 40
        assert H.next_delay(60, st, rng) <= H.BACKOFF_CAP_S * 1.2

    async def test_network_error_is_an_error_not_a_crash(self):
        def boom(req):
            raise httpx.ConnectError("down")
        st = H.SourceState()
        r = await H.fetch("https://x/feed", st, transport=httpx.MockTransport(boom))
        assert r.outcome == "ERROR" and st.failures == 1

    def test_interval_never_below_the_feed_ttl(self):
        st = H.SourceState(ttl_s=300)
        assert H.next_delay(15, st, random.Random(0)) >= 300 * 0.8

    def test_cadence_by_session(self):
        assert C.interval_for(SRC, T0.replace(hour=11)) == 300           # market hours
        assert C.interval_for(SRC, T0.replace(hour=20)) == 900
        assert C.interval_for(SRC, _dt.datetime(2026, 9, 27, 11, tzinfo=IST)) == 1800


# ── timing and dry-run evidence ──────────────────────────────────────────────
def fres(body=BODY, at=T0, outcome="OK"):
    return H.FetchResult(outcome, at, at, http_status=200 if outcome == "OK" else 304, body=body)


class TestTiming:
    def test_first_response_is_backlog_and_knowable_is_discovery(self):
        seen: dict = {}
        o = C.process(SRC, fres(), seen, universe=UNIVERSE, aliases=EN.Aliases(),
                      first_success=True)
        assert o.new and all(d.backlog and d.discovered_at == T0 for d in o.new)
        assert all(d.latency_s is None for d in o.new)     # backlog: no latency claimed

    def test_new_item_later_has_latency_and_is_knowable_at_discovery_not_publication(self):
        seen: dict = {}
        C.process(SRC, fres(), seen, universe=UNIVERSE, aliases=EN.Aliases(), first_success=True)
        extra = BODY.replace(b"</channel>", b"<item><title>Sheetal Universal Limited</title>"
                             b"<link>https://nsearchives.nseindia.com/corporate/SHEETAL_28092026"
                             b"153500_x.pdf</link><description>d |SUBJECT: Updates</description>"
                             b"<pubDate>28-Sep-2026 15:35:00</pubDate></item></channel>")
        t1 = T0 + _dt.timedelta(minutes=5, seconds=7)
        o = C.process(SRC, fres(extra, t1), seen, universe=UNIVERSE, aliases=EN.Aliases(),
                      first_success=False)
        assert len(o.new) == 1
        d = o.new[0]
        assert d.discovered_at == t1 and not d.backlog
        assert d.item.published_at == T0.astimezone(UTC)     # 15:35:00 IST
        assert d.latency_s == 307.0

    def test_unchanged_item_is_not_new_and_an_edit_is_an_observation(self):
        seen: dict = {}
        C.process(SRC, fres(), seen, universe=UNIVERSE, aliases=EN.Aliases(), first_success=True)
        again = C.process(SRC, fres(at=T0 + _dt.timedelta(minutes=5)), seen, universe=UNIVERSE,
                          aliases=EN.Aliases(), first_success=False)
        assert again.new == [] and again.changed == []
        edited = BODY.replace(b"Jullundur Motor Agency (Delhi) Limited has informed",
                              b"Jullundur Motor Agency (Delhi) Limited has now informed")
        o = C.process(SRC, fres(edited, T0 + _dt.timedelta(minutes=10)), seen, universe=UNIVERSE,
                      aliases=EN.Aliases(), first_success=False)
        assert [ch for _, ch in o.changed] == [["summary"]] and o.new == []

    def test_malformed_body_is_recorded_not_raised(self):
        o = C.process(SRC, fres(b"<html>captcha</html>"), {}, universe=UNIVERSE,
                      aliases=EN.Aliases(), first_success=True)
        assert o.fetch.outcome == "MALFORMED" and o.new == []


class TestDryRun:
    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        clock.freeze(T0)

        async def uni():
            return UNIVERSE
        monkeypatch.setattr(C, "load_universe", uni)
        monkeypatch.setattr(C, "KILL_FILE", tmp_path / "news.kill")
        yield tmp_path
        clock.unfreeze()

    async def test_writes_evidence_files_only(self, env):
        sleeps = []

        async def sleep(s):
            sleeps.append(s)
        out = await C.dry_run("NSE_ANNOUNCEMENTS", polls=2, root=env, sleep=sleep,
                              transport=transport(OK, httpx.Response(304)),
                              rng=random.Random(0))
        assert [p["outcome"] for p in out] == ["OK", "NOT_MODIFIED"]
        assert sleeps and sleeps[0] >= 300 * 0.8                  # ttl 5 min honoured
        d = env / "NSE_ANNOUNCEMENTS"
        st = json.loads((d / "state.json").read_text())
        assert st["polls"] == 2 and st["http"]["ttl_s"] == 300 and st["http"]["etag"]
        events = [json.loads(x) for x in (d / "events_2026-09-28.jsonl").read_text().splitlines()]
        items = [e for e in events if e["type"] == "item"]
        assert items and all(e["knowable_at"] == e["discovered_at"] for e in items)
        assert all(e["knowable_at"] != e["published_at"] for e in items)
        assert list((d / "raw").rglob("*.xml.gz"))                  # raw bytes archived
        rep = RP.summarise(d, "2026-09-28")
        assert rep["polls"] == 2 and rep["backlog_items"] == rep["items"]
        assert rep["mapping"]["EXACT_SYMBOL"] >= 2
        assert rep["duplicates"]["same_link_repeated_in_feed"] == 1

    async def test_restart_does_not_rediscover(self, env):
        async def sleep(s):
            pass
        await C.dry_run("NSE_ANNOUNCEMENTS", polls=1, root=env, sleep=sleep,
                        transport=transport(OK))
        out = await C.dry_run("NSE_ANNOUNCEMENTS", polls=1, root=env, sleep=sleep,
                              transport=transport(httpx.Response(200, content=BODY)))
        assert out[0]["items_new"] == 0 and out[0]["backlog"] is False

    async def test_a_restart_waits_out_the_interval_since_the_last_poll(self, env):
        slept = []

        async def sleep(s):
            slept.append(s)
        await C.dry_run("NSE_ANNOUNCEMENTS", polls=1, root=env, sleep=sleep,
                        transport=transport(OK))
        assert slept == []                                        # first ever poll: no wait
        clock.freeze(T0 + _dt.timedelta(seconds=17))              # "restarted" 17 s later
        await C.dry_run("NSE_ANNOUNCEMENTS", polls=1, root=env, sleep=sleep,
                        transport=transport(httpx.Response(304)))
        assert slept and slept[0] >= 300 - 17 - 0.01              # ttl 5 min honoured

    async def test_until_is_never_overshot(self, env):
        """Regression (2026-09-29): with --until 15:45 the collector still polled at
        15:46-15:48 and hourly sources ran on for up to an hour."""
        until = T0 + _dt.timedelta(minutes=12)

        async def sleep(s):                                       # time passes while asleep
            clock.freeze(clock.now() + _dt.timedelta(seconds=s))
        t = transport(OK, *[httpx.Response(304)] * 10)
        out = await C.dry_run("NSE_ANNOUNCEMENTS", until=until, root=env, sleep=sleep,
                              transport=t, rng=random.Random(0))
        assert len(out) >= 2
        assert all(_dt.datetime.fromisoformat(p["started_at"]) < until for p in out)
        assert clock.now() < until                                # never slept past it

    async def test_a_deadline_already_passed_makes_no_request(self, env):
        t = transport(OK)
        assert await C.dry_run("NSE_ANNOUNCEMENTS", until=T0, root=env, transport=t) == []
        assert t.requests == []

    async def test_kill_switch_stops_before_any_request(self, env):
        (env / "news.kill").write_text("{}")
        t = transport(OK)
        assert await C.dry_run("NSE_ANNOUNCEMENTS", polls=3, root=env, transport=t) == []
        assert t.requests == []

    async def test_blocked_source_stops_the_loop(self, env):
        async def sleep(s):
            pass
        out = await C.dry_run("NSE_ANNOUNCEMENTS", polls=5, root=env, sleep=sleep,
                              transport=transport(httpx.Response(403)))
        assert [p["outcome"] for p in out] == ["BLOCKED"]

    async def test_database_unreachable_does_not_stop_collection(self, env, monkeypatch):
        async def none():
            return None
        monkeypatch.setattr(C, "load_universe", none)
        out = await C.dry_run("NSE_ANNOUNCEMENTS", polls=1, root=env, transport=transport(OK))
        assert out[0]["outcome"] == "OK" and out[0]["items_new"] > 0
        rep = RP.summarise(env / "NSE_ANNOUNCEMENTS")
        assert set(rep["mapping"]) == {"UNRESOLVED"}

    async def test_unsupported_sources_have_no_adapter(self, env):
        for k in ("MONEYCONTROL", "ZEE_BUSINESS", "REUTERS"):
            with pytest.raises(ValueError):
                await C.dry_run(k, root=env)
