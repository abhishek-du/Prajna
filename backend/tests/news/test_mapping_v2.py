"""headline-entity-v2 / alias-v2: the guards added after the 2026-09-29 mapping
review. Each case is a real headline whose link was judged WRONG (or a
counter-example that must stay linked). A rejected link becomes UNRESOLVED
with its reason - an association is never invented."""

from __future__ import annotations

import pytest

from app.news import enrich as EN
from app.news import entities as X
from app.news.model import ItemObs

UNI = EN.Universe({
    "KALPATARU": ("K1", "KALPATARU LIMITED"), "KPIL": ("K2", "KALPATARU PROJECT INT LTD"),
    "SURAJLTD": ("S1", "SURAJ LIMITED"), "SURAJEST": ("S2", "SURAJ ESTATE DEVELOPERS L"),
    "ALANKIT": ("A1", "ALANKIT LIMITED"), "PREMIER": ("P1", "PREMIER LIMITED"),
    "COASTCORP": ("C1", "COASTAL CORPORATION LTD"), "M&M": ("M1", "MAHINDRA & MAHINDRA LTD"),
    "M&MFIN": ("M2", "M&M FIN. SERVICES LTD"), "TMCV": ("T1", "TATA MOTORS LIMITED"),
    "TMPV": ("T2", "TATA MOTORS PASS VEH LTD"), "CARERATING": ("CR", "CARE RATINGS LIMITED"),
    "ANGELONE": ("AO", "ANGEL ONE LIMITED"), "ICICIBANK": ("IB", "ICICI BANK LTD."),
    "ICICIAMC": ("IA", "ICICI PRUDENTIAL AMC LTD"), "BHEL": ("BH", "BHEL"),
    "CYIENT": ("CY", "CYIENT LIMITED"), "CYIENTDLM": ("CD", "CYIENT DLM LIMITED"),
    "TCS": ("TC", "TATA CONSULTANCY SERV LT"), "TITAN": ("TI", "TITAN COMPANY LIMITED"),
    "HDFCBANK": ("HB", "HDFC BANK LTD"), "CRISIL": ("CS", "CRISIL LTD"),
    "URBANCO": ("UC", "URBAN COMPANY LIMITED"), "BIRLACORPN": ("BC", "BIRLA CORPORATION LTD"),
    "SBIN": ("SB", "STATE BANK OF INDIA"), "JMFINANCIL": ("JM", "JM FINANCIAL LIMITED"),
    "INFY": ("IN", "INFOSYS LIMITED"), "VOLTAS": ("VO", "VOLTAS LTD"),
})
IX = EN.HeadlineIndex(UNI)


def keys(title):
    it = ItemObs("x", title, None, "P", None, None)
    links = [ln for ln in EN.resolve_headline(it, UNI, IX) if ln.instrument_key]
    return sorted({ln.instrument_key for ln in links} | {
        ln.instrument_key for ln in X.alias_links(it, UNI)})


@pytest.mark.parametrize("title", [
    "Kalpataru Projects International secures 'major' EPC order in UAE",       # CNBC-08
    "Suraj Estate subsidiary completes over Rs 82 crore acquisition",           # CNBC-19
    "Adjudication Order in the matter of Alankit Assignments Limited",          # SEBI-05
    "Man City found guilty of Premier League charges, set to appeal",           # CNBC-21
    "India's Asian Games gold and the promise waiting in coastal Karnataka",    # CNBC-39
    "Mahindra & Mahindra Financial Services raises Rs 1250 cr via NCDs",        # BS-42
    "Tata Motors launches Aeris at Rs 5.29 lakh",                               # CNBC-04
    "Tata Motors Passenger Vehicles Ltd Slides 1.91%",                          # BS-25
    "CARE Ratings reaffirms ratings of Everest Kanto Cylinder at 'A-/A2+'",      # BS-44
    "Angel One sees 25% upside in this newly listed stock",                     # MINT-10
    "S Naren of ICICI Prudential AMC explains the three factors plaguing markets",  # CNBC-48
    "Gold may rise to $5,000/oz in H1 2027 after consolidation: ICICI Bank",    # BL-05
    "Ellenbarrie Industrial Gases secures contract worth Rs 480 cr from BHEL",  # BS-14
    "Ellenbarrie wins Rs 481 crore BHEL order for giant oxygen plant",          # CNBC-32
    # the holdout sample (judged after the first fixes)
    "Aditya Birla Sun Life AMC launches BSE Total Market Index Fund, ETF",
    "Atishay receives LoI from Punjab Urban Planning & Development Authority",
    "PM Awas Yojana Urban 2.0: Over 18 lakh houses sanctioned so far",
    "Which SBI Card Can Help If I Have a Low Credit Score?",
    "SBI Conclave 2026: RBI DG sees case for rupee recovery",
])
def test_judged_wrong_links_are_not_made(title):
    assert keys(title) == []


def test_the_rejection_is_recorded_as_the_unresolved_reason():
    it = ItemObs("x", "Man City found guilty of Premier League charges", None, "P", None, None)
    (ln,) = EN.resolve_headline(it, UNI, IX)
    assert ln.method == "UNRESOLVED" and ln.reason.startswith("premier: ")
    assert ln.version == "headline-entity-v2"


@pytest.mark.parametrize("title,expected", [
    ("Cyient among 4 stocks showing White Marubozu Pattern", ["CY"]),          # one-word name
    ("Analysts recommend buying Cyient DLM", ["CD"]),                          # the longer name
    ("From TCS, Titan to Tata Tele - Tata Group stocks fall", ["TC", "TI"]),   # 'from', no order
    ("Kalpataru Ltd shares rise 3% on new launch", ["K1"]),
    ("HDFC Bank CEO transition nears; Jefferies sees rerating scope", ["HB"]),
    ("Top 5 Breakout stocks to buy: KPI Green, Crisil, Manyavar", ["CS"]),     # a listed rater
    ("Power Mech bags order from Telangana genco; BHEL shares rise", ["BH"]),
    ("Stocks to buy: JM Financial expects soft Q2 season; targets for Infosys", ["IN"]),
    ("Equirus likes LG Electronics, Blue Star, Voltas", ["VO"]),
    ("Why Voltas Shares Fell Today", ["VO"]),                     # title case, generic words
])
def test_genuine_links_stay(title, expected):
    assert keys(title) == expected
