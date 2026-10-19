"""Corporate-action factors and the revision classifier (phases 6-7), on the
real vendor evidence in tests/fixtures/vendor_evidence (sha256-pinned)."""

from __future__ import annotations

import collections
import datetime as _dt
import hashlib
import json
import pathlib
import re
from decimal import Decimal

import pytest

from app.contracts.ca_factor import adjust_price, cumulative, factor_for
from app.contracts.revision import Event, classify

EV = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "vendor_evidence"
D = Decimal
KEYS = ("open", "high", "low", "close", "volume", "open_interest")


def _load(name: str) -> dict:
    return {c[0][:10]: dict(zip(KEYS, c[1:7])) for c in
            json.loads((EV / f"{name}.json").read_text())["data"]["candles"]}


def test_fixture_integrity():
    rows = re.findall(r"\| (\S+\.json) \|.*\| `([0-9a-f]{64})` \|",
                      (EV / "README.md").read_text())
    assert len(rows) >= 26
    for name, sha in rows:
        assert hashlib.sha256((EV / name).read_bytes()).hexdigest() == sha, name


@pytest.mark.parametrize("kind,ratio,fvb,fva,expect", [
    ("BONUS", "1:1", None, None, D(2)),                  # CHAVDA, LICI, AHCL bonus
    ("BONUS", "1:2", None, None, D("1.5")),              # TRENT
    ("BONUS", "3:7", None, None, D(10) / D(7)),          # USASEEDS
    ("BONUS", "2:1", None, None, D(3)),                  # JAKHARIA, UEL
    ("SPLIT", "1:2", D(2), D(1), D(2)),                  # TDPOWERSYS (fv 2 -> 1)
    ("SPLIT", "2:10", D(10), D(2), D(5)),                # DHARIWAL, AHCL split
    ("SPLIT", "10:1", D(1), D(10), D("0.1")),            # reverse split (synthetic)
])
def test_exact_factors(kind, ratio, fvb, fva, expect):
    f = factor_for(kind, ratio=ratio, fv_before=fvb, fv_after=fva)
    assert f.status == "EXACT" and f.factor_price == expect and f.factor_volume == expect


def test_split_ratio_contradicting_face_values_is_uncertain():
    f = factor_for("SPLIT", ratio="2:10", fv_before=D(10), fv_after=D(5))
    assert f.status == "UNCERTAIN" and f.factor_price is None


def test_rights_and_dividends_are_never_price_factors():
    r = factor_for("RIGHTS", ratio="2:5", fv_before=None, fv_after=None,
                   details="Rights issue of equity shares of Rs. 2/- in the ratio of 2:5 "
                           "@ premium of Rs. 1.17/-")
    assert r.status == "UNSUPPORTED" and r.factor_price is None
    assert r.inputs["details_text_parse"] == {"face_value": "2", "ratio": "2:5",
                                              "premium": "1.17"}
    assert factor_for("DIVIDEND", ratio=None, fv_before=None, fv_after=None).status == \
        "UNSUPPORTED"


def test_same_day_split_and_bonus_multiply():                # AHCL 2026-04-24
    day = _dt.date(2026, 4, 24)
    assert cumulative([(day, D(5)), (day, D(2))]) == D(10)


def test_chavda_740_of_740_are_ca_adjustments():
    raw, live = _load("chavda_1d_archived_20260923"), _load("chavda_1d_live")
    ev = [Event(2338, _dt.date(2026, 9, 24), D(2))]
    got = collections.Counter(
        classify(raw[d], live[d], bar_date=_dt.date.fromisoformat(d),
                 fetch_date=_dt.date(2026, 9, 25), tick=D("0.05"), events=ev).classification
        for d in raw)
    assert got == {"CA_ADJUSTMENT": 740}
    # tick rounding, half-even: 86.45 / 2 -> 43.20 and 136.95 / 2 -> 68.50
    assert adjust_price(D("86.45"), D(2), D("0.05")) == D("43.20")
    assert adjust_price(D("136.95"), D(2), D("0.05")) == D("68.50")
    assert live["2023-09-25"]["low"] == 43.2 and live["2026-09-21"]["close"] == 68.5
    # volume x2, OI and timestamps untouched
    assert all(live[d]["volume"] == 2 * raw[d]["volume"] for d in raw)
    assert all(live[d]["open_interest"] == raw[d]["open_interest"] for d in raw)


def test_an_event_after_the_fetch_explains_nothing():
    raw, live = _load("chavda_1d_archived_20260923"), _load("chavda_1d_live")
    v = classify(raw["2026-09-22"], live["2026-09-22"], bar_date=_dt.date(2026, 9, 22),
                 fetch_date=_dt.date(2026, 9, 23), tick=D("0.05"),
                 events=[Event(2338, _dt.date(2026, 9, 24), D(2))])
    assert v.classification == "UNEXPLAINED" and v.fails


def test_same_day_split_plus_bonus_revision():               # AHCL: F = 5 * 2
    stored = {"open": 400.0, "high": 410.5, "low": 395.25, "close": 402.0, "volume": 1000,
              "open_interest": 0}
    new = {k: float(adjust_price(D(str(stored[k])), D(10), D("0.05")))
           for k in ("open", "high", "low", "close")}
    new.update(volume=10000, open_interest=0)
    v = classify(stored, new, bar_date=_dt.date(2026, 4, 23), fetch_date=_dt.date(2026, 5, 1),
                 tick=D("0.05"), events=[Event(1, _dt.date(2026, 4, 24), D(5)),
                                         Event(2, _dt.date(2026, 4, 24), D(2))])
    assert v.classification == "CA_ADJUSTMENT" and v.explained_by["factor"] == "10"
    assert sorted(v.explained_by["ca_ids"]) == [1, 2]


@pytest.mark.parametrize("change,klass", [
    ({"close": 100.05}, "ROUNDING"),                         # one tick
    ({"close": 101.0}, "UNEXPLAINED"),                       # a real value change
    ({"volume": 999}, "UNEXPLAINED"),                        # volume only
    ({"open_interest": 5}, "UNEXPLAINED"),
])
def test_other_revisions(change, klass):
    stored = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000,
              "open_interest": 0}
    v = classify(stored, {**stored, **change}, bar_date=_dt.date(2026, 9, 1),
                 fetch_date=_dt.date(2026, 9, 2), tick=D("0.05"), events=[])
    assert v.classification == klass


def test_settlement_only_on_the_last_bar():
    stored = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000,
              "open_interest": 0}
    new = {**stored, "close": 100.3, "volume": 1100}
    kw = dict(bar_date=_dt.date(2026, 9, 1), fetch_date=_dt.date(2026, 9, 1),
              tick=D("0.05"), events=[])
    assert classify(stored, new, last_bar_of_session=True, **kw).classification == "SETTLEMENT"
    assert classify(stored, new, last_bar_of_session=False, **kw).classification == \
        "UNEXPLAINED"


def test_global_label_changes_are_global_revisions():
    first, later = _load("N225_global_archived_20260925_1341"), _load("N225_global_live")
    v = classify(first["2026-09-24"], later["2026-09-24"], bar_date=_dt.date(2026, 9, 24),
                 fetch_date=_dt.date(2026, 9, 25), tick=None, events=[], is_global=True)
    assert first["2026-09-24"]["open"] != later["2026-09-24"]["open"]   # the proven revision
    assert v.classification == "GLOBAL_REVISION" and not v.fails


# ── revision-v3: the vendor's reciprocal-4dp convention (OLIL, 2026-10-15) ──────────
# OLIL (NSE_EQ|INE0OPS01011, tick 0.05) BONUS 1:2 (corporate_action 4109, F = 1.5, ex
# 2026-10-15). The seven bars the vendor re-served at the 14:01 IST replay of 2026-10-15
# (ingest_run ed2ac553-394e-4285-bf41-998653a3da64; the first five also at 07:03 in
# eeb6eba5-36a5-4fea-bcbb-08a42b7e43b0): stored vs re-served OHLC and volume.
OLIL = [  # (stored O, H, L, C, V), (re-served O, H, L, C, V)
    (("445.50", "454.50", "440.00", "441.35", 33200),
     ("297.0", "303.0", "293.35", "294.25", 49798)),
    (("440.00", "441.50", "439.95", "440.65", 12400),
     ("293.35", "294.35", "293.3", "293.8", 18599)),
    (("448.00", "450.00", "443.00", "449.55", 46000),
     ("298.7", "300.0", "295.35", "299.7", 68997)),
    (("449.55", "455.00", "449.55", "455.00", 38400),
     ("299.7", "303.35", "299.7", "303.35", 57597)),
    (("451.00", "471.20", "451.00", "457.00", 14800),
     ("300.7", "314.15", "300.7", "304.7", 22199)),
    (("438.05", "447.00", "438.05", "443.65", 11600),
     ("292.05", "298.0", "292.05", "295.8", 17399)),
    (("423.10", "455.00", "423.05", "440.65", 29600),
     ("282.1", "303.35", "282.05", "293.8", 44398)),
]
OLIL_EVENT = Event(4109, _dt.date(2026, 10, 15), D("1.5"))
OLIL_KW = dict(bar_date=_dt.date(2026, 10, 13), fetch_date=_dt.date(2026, 10, 15),
               tick=D("0.05"), events=[OLIL_EVENT])


def _bar(t):
    return dict(zip(("open", "high", "low", "close", "volume"), t, strict=True),
                open_interest=0)


def test_vendor_multiplier_is_the_reciprocal_to_four_decimals():
    from app.contracts.ca_factor import vendor_multiplier
    assert vendor_multiplier(D("1.5")) == D("0.6667")
    assert vendor_multiplier(D(2)) == D("0.5") and vendor_multiplier(D(10)) == D("0.1")


def test_every_real_olil_bar_is_the_reciprocal_convention():
    for stored, new in OLIL:
        v = classify(_bar(stored), _bar(new), **OLIL_KW)
        assert v.classification == "CA_ADJUSTMENT", (stored, new)
        assert v.explained_by["rounding"] == "reciprocal-4dp"
        assert v.explained_by["ca_ids"] == [4109]


def test_the_exact_convention_does_not_explain_olil():
    from app.contracts.ca_factor import CONVENTIONS
    price, vol = CONVENTIONS["exact"]
    prices = sum(price(D(st[i]), D("1.5"), D("0.05")) == D(nw[i]) for st, nw in OLIL
                 for i in range(4))
    vols = sum(vol(D(st[4]), D("1.5")) == D(nw[4]) for st, nw in OLIL)
    assert (prices, vols) == (20, 0)


def test_exact_is_still_first_and_unchanged():                       # CHAVDA convention
    s = {"open": 86.45, "high": 136.95, "low": 86.45, "close": 136.95, "volume": 100,
         "open_interest": 0}
    n = {"open": 43.20, "high": 68.50, "low": 43.20, "close": 68.50, "volume": 200,
         "open_interest": 0}
    v = classify(s, n, bar_date=_dt.date(2026, 9, 1), fetch_date=_dt.date(2026, 9, 3),
                 tick=D("0.05"), events=[Event(1, _dt.date(2026, 9, 2), D(2))])
    assert v.classification == "CA_ADJUSTMENT" and v.explained_by["rounding"] == "exact"


def test_a_convention_must_explain_prices_and_volume_together():
    stored, new = OLIL[1]
    # reciprocal prices with the exact volume (18,600): neither convention as a whole
    assert classify(_bar(stored), {**_bar(new), "volume": 18600},
                    **OLIL_KW).classification == "UNEXPLAINED"
    # the reciprocal volume with a price that is one tick off
    assert classify(_bar(stored), {**_bar(new), "close": "293.75"},
                    **OLIL_KW).classification == "UNEXPLAINED"


def test_ceiling_with_the_exact_volume_is_not_a_convention():
    """revision-v2 accepted ceiling(stored / F) prices; v3 drops it. For OLIL's prices
    ceiling and reciprocal-4dp coincide, so the volume decides: ceiling prices with
    volume stored * F (which v2 would have accepted) are UNEXPLAINED in v3."""
    stored, new = OLIL[1]                       # close: half-even 293.75, ceiling 293.80
    assert classify(_bar(stored), {**_bar(new), "volume": 18600},
                    **OLIL_KW).classification == "UNEXPLAINED"


# ── revision-v4: intraday volume slack, one unit per constituent minute (2026-10-19) ──
# OLIL 1h bars the vendor re-served on 2026-10-17 (ingest_anomaly DUPLICATE_KEY, both
# UNEXPLAINED under v3): prices are exactly reciprocal-4dp, volume is off by a few units
# because the vendor adjusts volume below the bar level before summing.
OLIL_1H = [  # (stored O, H, L, C, V), (re-served O, H, L, C, V), bar date
    (("426.0000", "433.9000", "422.0500", "424.0500", 47600),
     ("284.0", "289.3", "281.4", "282.7", 71397), _dt.date(2026, 9, 24)),
    (("421.0500", "438.0000", "420.0000", "438.0000", 58000),
     ("280.7", "292.0", "280.0", "292.0", 86995), _dt.date(2026, 9, 28)),
]


def _kw1h(bar_date, minutes=60):
    return dict(bar_date=bar_date, fetch_date=_dt.date(2026, 10, 17), tick=D("0.05"),
                events=[OLIL_EVENT], minutes=minutes)


def test_real_olil_1h_bars_are_explained_with_bounded_volume_slack():
    for stored, new, day in OLIL_1H:
        v = classify(_bar(stored), _bar(new), **_kw1h(day))
        assert v.classification == "CA_ADJUSTMENT", (stored, new)
        assert v.explained_by["ca_ids"] == [4109]
        assert 0 < int(v.explained_by["volume_slack"]) <= v.explained_by["slack_max"] == 60


def test_the_same_bars_fail_closed_without_minutes():      # v3 behaviour: daily stays exact
    for stored, new, day in OLIL_1H:
        assert classify(_bar(stored), _bar(new), **_kw1h(day, minutes=0)).fails


def test_volume_beyond_one_unit_per_minute_fails_closed():
    stored, new, day = OLIL_1H[0]      # prices fit reciprocal-4dp only: volume 71,396
    assert not classify(_bar(stored), {**_bar(new), "volume": 71396 - 60},
                        **_kw1h(day)).fails
    assert classify(_bar(stored), {**_bar(new), "volume": 71396 - 61},
                    **_kw1h(day)).fails
    assert classify(_bar(stored), {**_bar(new), "volume": 71396 + 61},
                    **_kw1h(day)).fails
    assert classify(_bar(stored), {**_bar(new), "volume": 71396 + 15},     # 15m bar
                    **_kw1h(day, minutes=15)).classification == "CA_ADJUSTMENT"
    assert classify(_bar(stored), {**_bar(new), "volume": 71396 + 16},
                    **_kw1h(day, minutes=15)).fails


def test_slack_never_excuses_a_price_or_a_missing_event():
    stored, new, day = OLIL_1H[0]
    assert classify(_bar(stored), {**_bar(new), "close": "282.75"}, **_kw1h(day)).fails
    assert classify(_bar(stored), _bar(new),
                    **{**_kw1h(day), "events": []}).fails                 # no recorded CA
    late = Event(4109, _dt.date(2026, 10, 18), D("1.5"))                  # ex after fetch
    assert classify(_bar(stored), _bar(new), **{**_kw1h(day), "events": [late]}).fails
    assert classify(_bar(stored), {**_bar(new), "open_interest": 5}, **_kw1h(day)).fails


def test_an_unchanged_volume_still_needs_no_slack():
    stored, new, day = OLIL_1H[0]
    v = classify(_bar(stored), {**_bar(new), "volume": 71396}, **_kw1h(day))
    assert v.classification == "CA_ADJUSTMENT" and "volume_slack" not in v.explained_by
