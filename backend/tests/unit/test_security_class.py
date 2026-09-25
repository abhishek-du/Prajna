"""Security classification (phase 3), on the real edge cases measured
2026-09-25 in the 3,532-instrument NSE_EQ universe."""

from __future__ import annotations

import pytest

from app.ingest.security_class import classify, isin_vote


def _i(isin, sym, name, series="EQ", sector=None, profile=True, ratios=False, seg="NSE_EQ"):
    return {"segment": seg, "isin": isin, "trading_symbol": sym, "name": name,
            "instrument_type": series, "sector": sector, "has_profile": profile,
            "has_ratios": ratios}


@pytest.mark.parametrize("isin,vote", [
    ("INE002A01018", "COMPANY"), ("IN9175A01010", "COMPANY"),     # DVR shares
    ("INF769K01JP9", "FUND"), ("INE0BZQ20011", "RE"), ("INE281A20018", "RE"),
    ("INE183W23014", "INVIT"), (None, None), ("US0378331005", None), ("INE1", None)])
def test_isin_votes(isin, vote):
    assert isin_vote(isin) == vote


@pytest.mark.parametrize("inst,cls,sub", [
    (_i("INE002A01018", "RELIANCE", "RELIANCE INDUSTRIES LTD", sector="Refineries",
        ratios=True), "STOCK", None),
    (_i("IN9175A01010", "JISLDVREQS", "JAIN DVR EQUITY SHARES", sector="Miscellaneous"),
     "STOCK", None),
    # a listed asset-management COMPANY is a stock, not a fund
    (_i("INE127D01025", "HDFCAMC", "HDFC AMC LIMITED", sector="Finance", ratios=True),
     "STOCK", None),
    (_i("INF769K01JP9", "GOLDETF", "MIRAEAMC - MAGOLDETF"), "FUND_UNIT", None),
    # ETF without the scheme naming: ISIN + no-financials still agree
    (_i("INF204KB14I2", "BANKBETF", "BFAM - BANKBETF"), "FUND_UNIT", None),
    # no profile yet, but ISIN + name agree
    (_i("INF204KB14I2", "QNIFTY", "QUANTUM NIFTY 50 ETF", profile=False), "FUND_UNIT", None),
    (_i("INE0BZQ20011", "RCDL-RE", "RAJGOR CAST DERIVATI LTD", series="ST"),
     "RIGHTS_ENTITLEMENT", None),
    (_i("INE183W23014", "IRBINVIT", "IRB INVIT FUND", series="IV", sector="Investment",
        ratios=True), "OTHER", "INVIT_UNIT"),
    (_i(None, "NIFTY", "Nifty 50", series="INDEX", seg="NSE_INDEX"), "OTHER", "INDEX"),
])
def test_classified(inst, cls, sub):
    d = classify(inst)
    assert (d.security_class, d.subclass, d.status) == (cls, sub, "CLASSIFIED"), d.reason
    assert all("vote" in v for v in d.signals.values())          # every signal explained


@pytest.mark.parametrize("inst,why", [
    # a fund ISIN with company financials: contradiction
    (_i("INF769K01JP9", "ODD", "SOMETHING", sector="Finance", ratios=True), "REVIEW"),
    # company ISIN named like a fund scheme
    (_i("INE002A01018", "ODD", "XYZAMC - SCHEME", sector="Finance"), "REVIEW"),
    # company ISIN whose vendor profile has no financials at all
    (_i("INE002A01018", "ODD", "ODD LTD"), "REVIEW"),
    # RE code without the -RE symbol: only one RE signal
    (_i("INE0BZQ20011", "RCDLX", "RAJGOR"), "UNCLASSIFIED"),
])
def test_ambiguous_is_never_silently_classified(inst, why):
    d = classify(inst)
    assert d.status == why and d.security_class is None


def test_new_listing_without_fundamentals_is_unclassified():
    d = classify(_i("INE0GAN01010", "NEWCO", "NEW CO LTD", profile=False))
    assert d.status == "UNCLASSIFIED" and d.security_class is None
    assert "insufficient evidence" in d.reason
