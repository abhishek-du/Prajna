"""features-v5 (decision FEATURES-V5, user 2026-10-21; docs/STAGE3_FEATURES_V5.md).

ACTIVE since 2026-10-21 (canary 12/12). The features-v4 document stays reproducible (its
hash is what stored v4 values and the Stage 4 v3 datasets refer to). Against the v4 list,
v5 adds exactly the new rows, drops the four ca_days_to_* rows and changes no v4 value;
every input is knowable before as_of (results events, analyst headlines, fundamentals)."""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import asdict

import pytest
from sqlalchemy import text

from app.canon import results_pit as RP
from app.core import clock
from app.core.clock import IST
from app.features import engine as E
from app.features import registry as R
from app.features import snapshots as SN
from app.features.compute import INSUFFICIENT_HISTORY, MISSING_INPUT, NOT_APPLICABLE
from app.features.compute import analyst as AN
from app.features.compute import context as CX
from app.features.compute import fund_own as FO
from app.features.compute import results as RS
from tests.stage3.test_engine import world  # noqa: F401  (fixture)
from tests.support import stage3_seed as W
from tests.support.stage2_seed import _run

D = _dt.date
UTC = _dt.UTC
V4_SHA = "6f998a76c49462c3244b5eecb2d783e75c6fff9d26365ae3540c8e88dbb201c3"
V5_SHA = "466790726ac24c7b50bac417cae8e438cc48859ac8d3d865dffe3fdf69b18387"


def at(y, m, d, hh=12):
    return _dt.datetime(y, m, d, hh, tzinfo=IST)


# ── registry ────────────────────────────────────────────────────────────────────
def test_v5_is_active_and_v4_stays_reproducible():
    import hashlib
    import json
    assert R.FEATURES_V5_ACTIVE is True
    assert R.VERSION == "features-v5" and R.REGISTRY_SHA256 == V5_SHA
    assert R.V5_IDS <= {f.id for f in R.FEATURES}
    assert hashlib.sha256(json.dumps(R.v4_document(), sort_keys=True,
                                     default=str).encode()).hexdigest() == V4_SHA
    assert R.features_v5(R.FEATURES_V4) == R.FEATURES


def test_v5_feature_list_and_diagram():
    v5 = R.features_v5(R.FEATURES_V4)
    ids = [f.id for f in v5]
    assert len(ids) == len(set(ids)) == 104 + len(R.FEATURES_V5_NEW)
    assert {f.id for f in v5 if f.status == "UNSUPPORTED"} == set(R.CA_TO_FEATURES)
    assert all(f.version == 1 and f.status == "IMPLEMENTED" for f in R.FEATURES_V5_NEW)
    diagram = R.diagram_v5(R.DIAGRAM_V4)
    assert diagram == R.DIAGRAM
    assert [d["item"] for d in diagram] == [d["item"] for d in R.DIAGRAM_V4]
    known = set(ids)
    assert all(f in known for d in diagram for f in d["features"])
    st = {d["item"]: R.diagram_status(d) for d in diagram}
    for item in ("Earnings dates", "Earnings surprises", "Analyst upgrades/downgrades",
                 "Market regime (bull/bear/sideways)", "Sector/market events"):
        assert st[item] == "PARTIAL", item           # implemented, with its limits named
    ob = next(d for d in diagram if d["item"] == "Order book imbalance")
    assert st["Order book imbalance"] == "UNSUPPORTED" and ob["reason"].startswith("OUT_OF_SCOPE")
    bad = [d["item"] for d in diagram
           if (R.diagram_status(d) in ("UNSUPPORTED", "UNKNOWN") and not d.get("reason"))
           or (R.diagram_status(d) == "PARTIAL" and not d.get("partial"))]
    assert not bad
    # every remaining UNSUPPORTED / UNKNOWN item is an approved OUT_OF_SCOPE
    assert all(d.get("reason", "").startswith("OUT_OF_SCOPE") for d in diagram
               if R.diagram_status(d) in ("UNSUPPORTED", "UNKNOWN"))


# ── results calendar (pure) ──────────────────────────────────────────────────────
def ev(kind, *, meeting=None, period=None, verdict=None, ea=None, kn=None, nid=1):
    kn = kn or at(2026, 10, 1)
    return RP.ResultsEvent(kind, "K", meeting, period, verdict, ea or kn, kn, nid)


COV = at(2026, 9, 29)
AS_OF = at(2026, 10, 21, 8)
DAY = D(2026, 10, 21)


def test_next_meeting_uses_the_latest_intimation_per_period():
    evs = [ev("INTIMATION", meeting=D(2026, 10, 24), period=D(2026, 9, 30), nid=1),
           ev("INTIMATION", meeting=D(2026, 10, 30), period=D(2026, 9, 30), nid=2,
              kn=at(2026, 10, 10)),                       # postponed: replaces the 24th
           ev("INTIMATION", meeting=D(2026, 10, 21), period=None, nid=3)]
    assert RS.scheduled_meetings(evs) == [D(2026, 10, 21), D(2026, 10, 30)]
    assert RS.days_to_next(evs, DAY, COV, AS_OF) == (0.0, None)
    assert RS.today(evs, DAY, COV, AS_OF) == (1.0, None)
    assert RS.days_to_next(evs[:2], DAY, COV, AS_OF) == (9.0, None)
    assert RS.today(evs[:2], DAY, COV, AS_OF) == (0.0, None)
    assert RS.days_to_next([], DAY, COV, AS_OF) == (None, NOT_APPLICABLE)
    assert RS.days_to_next(evs, DAY, None, AS_OF) == (None, MISSING_INPUT)
    assert RS.today(evs, DAY, AS_OF, AS_OF) == (None, MISSING_INPUT)   # coverage not before


def test_days_since_and_verdict():
    out = [ev("OUTCOME", ea=at(2026, 10, 17, 18), nid=4)]
    assert RS.days_since(out, DAY, COV, AS_OF) == (4.0, None)
    assert RS.days_since([], DAY, COV, AS_OF) == (None, MISSING_INPUT)      # < 120 days
    assert RS.days_since([], DAY, at(2026, 5, 1), AS_OF) == (None, NOT_APPLICABLE)
    v = [ev("ESTIMATE_NEWS", verdict="BEAT", ea=at(2026, 10, 10), nid=5),
         ev("ESTIMATE_NEWS", verdict="MISS", ea=at(2026, 10, 15), nid=6),
         ev("ESTIMATE_NEWS", verdict="BEAT", ea=at(2026, 6, 1), nid=7)]      # > 90 days
    assert RS.street_verdict(v, COV, AS_OF) == (-1.0, None)
    assert RS.street_verdict(v[2:], COV, AS_OF) == (None, NOT_APPLICABLE)
    assert RS.street_verdict(v, None, AS_OF) == (None, MISSING_INPUT)


# ── analyst / sentiment (pure) ─────────────────────────────────────────────────
@pytest.mark.parametrize(("title", "want"), [
    ("Kotak Mahindra Bank shares rise 2% as HSBC upgrades stock to buy", "UP"),
    ("KEC Int'l: Why Kotak upgraded stock to 'Add' despite 60% fall in a year", "UP"),
    ("Morgan Stanley raises Lenskart target price to Rs 718; bull case implies 41% upside", "UP"),
    ("Bajaj Finance share price target raised by JPMorgan after Q2 update", "UP"),
    ("HCLTech shares jump 5% on EPS upgrades after Q2 results", "UP"),
    ("JSW Infra shares get downgraded by HSBC, who prefers this port operator instead", "DOWN"),
    ("Bernstein cuts PB Fintech share price target by 53%", "DOWN"),
    ("HDB Financial shares fall 4% after Q2 results as brokerages cut targets", "DOWN"),
    ("NABARD-backed fund raises ₹450 crore at first close, targets ₹1,500 crore", None),
    ("Capri Global plans to raise up to ₹4,000 crore as it targets ₹1 lakh crore in assets",
     None),
    ("Ashoka Buildcon wins contract to upgrade traction power systems", None),
    ("AMFI Rejig: Lenskart among 6 stocks set for largecap upgrade", None),
    ("Analyst upgrades stock to buy but cuts target price", None),           # mixed
    ("TCS Q2 results: profit rises 5%", None)])
def test_analyst_action(title, want):
    assert AN.action(title) == want


def test_analyst_counts_and_sentiment():
    h = [(AS_OF - _dt.timedelta(days=2), "HSBC upgrades X to buy"),
         (AS_OF - _dt.timedelta(days=10), "Jefferies cuts X target price"),
         (AS_OF - _dt.timedelta(days=40), "Citi upgrades X")]                # outside 30 days
    assert AN.counts(h, AS_OF, True) == ((1.0, None), (1.0, None))
    assert AN.counts([], AS_OF, True) == ((0.0, None), (0.0, None))       # a real zero
    assert AN.counts(h, AS_OF, False) == ((None, MISSING_INPUT),) * 2
    rows = [{"knowable_at": AS_OF - _dt.timedelta(hours=2), "impact_direction": "POSITIVE"},
            {"knowable_at": AS_OF - _dt.timedelta(hours=30), "impact_direction": "NEGATIVE"},
            {"knowable_at": AS_OF - _dt.timedelta(hours=40), "impact_direction": "NEUTRAL"},
            {"knowable_at": AS_OF - _dt.timedelta(hours=5), "impact_direction": "UNKNOWN"}]
    assert AN.sentiment(rows, AS_OF, 24) == (1.0, None)
    assert AN.sentiment(rows, AS_OF, 72) == (0.0, None)                     # (1 - 1 + 0) / 3
    assert AN.sentiment(rows[3:], AS_OF, 24) == (None, NOT_APPLICABLE)


# ── own ratios and the seasonal random walk (pure) ──────────────────────────────
def q_payload(values):
    return {"income_statement": [{"category": "net_profit", "history": [
        {"period": p, "value": v} for p, v in values.items()]}]}


def y_payload(pat, eps):
    return {"full_statement": [
        {"particular": "Profit After Tax", "history": [{"period": "Mar 2026", "value": pat}]},
        {"particular": "EPS - Basic", "history": [{"period": "Mar 2026", "value": eps}]}]}


T1, T2 = at(2026, 9, 24), at(2026, 10, 20)


def snaps(with_sep=True):
    q = [(T1, q_payload({"Jun 2026": 130, "Mar 2026": 120, "Dec 2025": 110, "Sep 2025": 100}))]
    if with_sep:
        q.append((T2, q_payload({"Sep 2026": 150, "Jun 2026": 131, "Mar 2026": 120,
                                 "Dec 2025": 110})))
    return {"income:consolidated:quarterly": q,
            "income:standalone:yearly": [(T1, y_payload(400, 4.0))],
            "income:consolidated:yearly": [(T1, y_payload(520, 6.0))],
            "balance_sheet:consolidated": [(T1, {"history": [
                {"period": "Mar 2026", "total_asset": 9000, "total_liability": 4000}]})]}


def test_own_ratios_and_surprise():
    r = FO.own(snaps(), 200.0, [], D(2026, 10, 21))
    eps = (150 + 131 + 120 + 110) * 1e7 / 1e9
    assert r["pe_ttm"][0] == pytest.approx(200 / eps, rel=1e-9)
    assert r["earnings_yield_ttm"][0] == pytest.approx(eps / 200, rel=1e-9)
    assert r["pb_own"][0] == pytest.approx(200 * 1e9 / (5000 * 1e7), rel=1e-9)
    assert r["eps_surprise_srw"] == (0.5, None)                 # (150 - 100) / 100
    assert r["eps_surprise_srw_price"][0] == pytest.approx(50 * 1e7 / 1e9 / 200, rel=1e-9)
    early = FO.own(snaps(with_sep=False), 200.0, [], D(2026, 10, 1))
    assert early["eps_surprise_srw"] == (None, INSUFFICIENT_HISTORY)   # Jun 2025 never seen
    assert FO.own({}, 200.0, [], D(2026, 10, 1))["pe_ttm"] == (None, MISSING_INPUT)


def test_a_split_after_the_share_fy_makes_share_values_missing():
    split = [{"action_type": "SPLIT", "ex_date": D(2026, 8, 1)}]
    r = FO.own(snaps(), 200.0, split, D(2026, 10, 21))
    assert r["pe_ttm"] == r["pb_own"] == r["eps_surprise_srw_price"] == (None, MISSING_INPUT)
    assert r["eps_surprise_srw"] == (0.5, None)                 # needs no share count
    later = [{"action_type": "SPLIT", "ex_date": D(2026, 11, 1)}]          # after the session
    assert FO.own(snaps(), 200.0, later, D(2026, 10, 21))["pe_ttm"][1] is None


def test_regime_and_percentile():
    up = [100 + i for i in range(250)]
    assert CX.regime_trend(up) == (1.0, None)
    assert CX.regime_trend(list(reversed(up))) == (-1.0, None)
    dip = [*up[:-1], 100.0]                                    # close below SMA200, SMA50 above
    assert CX.regime_trend(dip) == (0.0, None)
    assert CX.regime_trend(up[:150]) == (None, INSUFFICIENT_HISTORY)
    assert CX.percentile_rank(up, 252) == (None, INSUFFICIENT_HISTORY)
    assert CX.percentile_rank([float(i) for i in range(252)], 252) == (1.0, None)


# ── point-in-time readers (test database) ───────────────────────────────────────
async def _poll(s, source, mode="PRODUCTION", t=None):
    rid = await _run(s, "news.poll", source=source)
    return (await s.execute(text("""insert into news_poll (source, mode, run_id, started_at,
        finished_at, outcome) values (:src, :m, :r, :t, :t, 'OK') returning id"""),
        {"src": source, "m": mode, "r": rid, "t": t or at(2026, 9, 29)})).scalar()


async def _item(s, pid, *, source, title, summary=None, category=None, knowable,
                links=(), backlog=False):
    nid = (await s.execute(text("""insert into news_item (source, source_article_id, url,
        canonical_url, title, title_norm_hash, summary, publisher, category_raw, published_at,
        discovered_at, knowable_at, backlog, content_available, first_poll_id, content_sha256,
        payload_sha256, content_fetch_status) values (:src, :u, :u, :u, :ti, 'h', :su, 'p',
        :c, :k, :k, :k, :b, false, :p, 'c', 'p', 'NOT_AVAILABLE') returning id"""),
        {"src": source, "u": f"https://x/{uuid.uuid4()}", "ti": title, "su": summary,
         "c": category, "k": knowable, "b": backlog, "p": pid})).scalar()
    for key, conf, lk in links:
        await s.execute(text("""insert into news_entity_link (item_id, instrument_key, method,
            confidence, matched_text, reason, version, mapped_at, knowable_at) values
            (:i, :k, 'COMPANY_NAME', :c, 'x', 'x', 'v', :t, :t)"""),
            {"i": nid, "k": key, "c": conf, "t": lk or knowable})
    return nid


INTIM = ("A LIMITED has informed the Exchange about Board Meeting to be held on 30-Oct-2026 to "
         "consider and approve the Quarterly Unaudited Financial results of the Company for "
         "the period ended September 2026.")


@pytest.mark.db
@pytest.mark.integration
async def test_results_events_and_headlines_are_point_in_time(db_session):
    s = db_session
    prod, shadow = await _poll(s, "NSE_ANNOUNCEMENTS"), await _poll(s, "NSE_ANNOUNCEMENTS",
                                                                    "SHADOW")
    t0 = at(2026, 10, 20, 18)
    A, B = W.A, W.B
    await _item(s, prod, source="NSE_ANNOUNCEMENTS", title="A", summary=INTIM,
                category="Board Meeting Intimation", knowable=t0, links=((A, 0.9, None),))
    await _item(s, prod, source="NSE_ANNOUNCEMENTS", title="A", summary=INTIM.replace(
        "30-Oct", "31-Oct"), category="Board Meeting Intimation", knowable=t0,
        links=((A, 0.9, at(2026, 10, 21, 9)),))                   # the link: after as_of
    await _item(s, shadow, source="NSE_ANNOUNCEMENTS", title="A", summary=INTIM.replace(
        "30-Oct", "29-Oct"), category="Board Meeting Intimation", knowable=t0,
        links=((A, 0.9, None),))                                  # SHADOW: never visible
    await _item(s, prod, source="NSE_ANNOUNCEMENTS", title="A", summary=INTIM.replace(
        "30-Oct", "27-Oct"), category="Board Meeting Intimation", knowable=t0,
        links=((A, 0.85, None),))                     # an announcement needs >= 0.9
    await _item(s, prod, source="NSE_ANNOUNCEMENTS", title="A", summary=INTIM.replace(
        "30-Oct", "28-Oct"), category="Board Meeting Intimation",
        knowable=at(2026, 10, 21, 9), links=((A, 0.9, None),))    # the item: after as_of
    news = await _poll(s, "ET_STOCKS_RSS")
    await _item(s, news, source="ET_STOCKS_RSS", title="HSBC upgrades AAA to buy",
                knowable=t0, links=((A, 0.95, None),))
    await _item(s, news, source="ET_STOCKS_RSS", title="Citi upgrades AAA and BBB",
                knowable=t0, links=((A, 0.95, None), (B, 0.95, None)))   # two names
    await _item(s, news, source="ET_STOCKS_RSS", title="Kotak upgrades AAA, the backlog",
                knowable=t0, links=((A, 0.95, None),), backlog=True)
    await _item(s, news, source="ET_STOCKS_RSS", title="Nomura cuts AAA target price",
                knowable=t0, links=((A, 0.8, None),))            # a news link: 0.80 counts
    await _item(s, news, source="ET_STOCKS_RSS", title="Macquarie upgrades AAA",
                knowable=t0, links=((A, 0.7, None),))            # below 0.80: not linked
    as_of = at(2026, 10, 21, 8)
    evs = await RP.events(s, as_of)
    assert [(e.kind, e.meeting_date) for e in evs[A]] == [("INTIMATION", D(2026, 10, 30))]
    assert all(e.knowable_at < as_of for e in evs[A])
    assert await RP.coverage_from(s, as_of) == at(2026, 9, 29)
    heads = await RP.linked_headlines(s, as_of, AN.WINDOW, AN.PREFILTER)
    assert [t for _, t, _ in heads[A]] == ["HSBC upgrades AAA to buy",
                                           "Nomura cuts AAA target price"] and B not in heads
    later = await RP.events(s, at(2026, 10, 21, 10))
    assert sorted(e.meeting_date for e in later[A]) == [D(2026, 10, 28), D(2026, 10, 30),
                                                        D(2026, 10, 31)]


@pytest.mark.db
@pytest.mark.integration
async def test_engine_v5_adds_rows_and_changes_no_v4_value(world, monkeypatch):  # noqa: F811
    clock.freeze(W.NOW)
    snap = await SN.resolve(world, W.SESSION, "PRE_SESSION")
    keys = [W.A, W.B, W.NIFTY]
    monkeypatch.setattr(E, "FEATURES", R.FEATURES_V4)
    before = await E.compute_snapshot(world, snap, keys)
    monkeypatch.setattr(E, "FEATURES", R.FEATURES)
    after = await E.compute_snapshot(world, snap, keys)
    b = {(r.instrument_key, r.feature_id): asdict(r) for r in before.rows}
    a = {(r.instrument_key, r.feature_id): asdict(r) for r in after.rows}
    assert {f for _, f in set(b) - set(a)} == set(R.CA_TO_FEATURES)
    added = set(a) - set(b)
    assert {f for _, f in added} == R.V5_IDS
    assert all(a[k] == b[k] for k in a if k in b)                       # v4 values unchanged
    assert all(r.input_max_knowable_at is None or r.input_max_knowable_at < snap.as_of
               for r in after.rows)
    v = {k: (a[k]["value"], a[k]["reason"]) for k in added}
    assert v[(W.A, "results_days_to_next")] == (None, MISSING_INPUT)    # no announcements
    assert v[(W.NIFTY, "results_today")] == (None, NOT_APPLICABLE)       # an index
    assert v[(W.NIFTY, "market_regime_trend")][1] in (None, INSUFFICIENT_HISTORY)
    assert v[(W.A, "dist_high_252")] == (None, INSUFFICIENT_HISTORY)      # ~80 sessions seeded
    assert v[(W.A, "analyst_upgrades_30d")] == (None, MISSING_INPUT)
