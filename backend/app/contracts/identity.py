"""Instrument identity, keyed on Upstox.

V2 IS UPSTOX-ONLY (constraint #1). The authority for identity is Upstox's
`instrument_key`, which is ISIN-based:

    NSE_EQ|INE002A01018        equity, keyed by ISIN
    NSE_INDEX|Nifty 50         index, keyed by name (indices have no ISIN)

There are NO Kite instrument tokens in this system. `exchange_token` below is
the NSE exchange token that Upstox publishes in its own master — an NSE
identifier, not a broker one.

Why identity is temporal (SCD2): V1 overwrote `kite_instruments` every day, so
a symbol rename silently rewrote the meaning of every historical row that
referenced it, and two live ISIN collisions (CRESTO/SILLYMONKS,
KDGREEN/MANBRO) had no way to coexist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Verified live from assets.upstox.com/.../NSE.json.gz on 2026-09-22.
SEGMENT_NSE_EQ = "NSE_EQ"
SEGMENT_NSE_INDEX = "NSE_INDEX"
SEGMENT_NSE_FO = "NSE_FO"

# `instrument_type` in the Upstox master carries the NSE SERIES. Counts observed
# in NSE_EQ (9,730 rows): EQ 2668, SM 467, BE 235, GS 132, ST 103, BZ 27, IV 21,
# plus SG 4325 and N*/TB/GB which are government securities and debt.
TRADEABLE_EQUITY_SERIES = frozenset({"EQ", "BE", "SM", "BZ", "ST", "IV"})

_ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
_KEY_RE = re.compile(r"^(?P<segment>[A-Z_]+)\|(?P<token>.+)$")


@dataclass(frozen=True, slots=True)
class InstrumentKey:
    segment: str
    token: str

    @property
    def raw(self) -> str:
        return f"{self.segment}|{self.token}"

    @property
    def is_isin_keyed(self) -> bool:
        return bool(_ISIN_RE.match(self.token))


def parse_instrument_key(key: str) -> InstrumentKey:
    m = _KEY_RE.match((key or "").strip())
    if not m:
        raise ValueError(f"malformed Upstox instrument_key: {key!r}")
    return InstrumentKey(m.group("segment"), m.group("token"))


def is_valid_isin(value: str | None) -> bool:
    """STRUCTURAL check only: IN + 10 alphanumerics.

    This deliberately does NOT judge asset class, because the ISIN prefix is not
    a reliable proxy for one. Measured against the live Upstox NSE master on
    2026-09-22, among instruments whose instrument_type is a tradeable equity
    series:

        INE -> EQ 2316, SM 467, BE 235, ST 103, BZ 26, IV 21
        INF -> EQ  351        <-- ETFs. NIFTYBEES is INF204KB14I2.
        IN9 -> EQ    1, BZ  1

    So an "INE-only" rule would silently drop 351 tradeable ETFs, including the
    market-regime proxy V1 itself depended on. That is precisely the silent-drop
    class of failure V2 exists to prevent, so the rule is not applied.

    THE AUTHORITY FOR ASSET CLASS IS `segment` + `instrument_type`, from the
    vendor's own master. Never the ISIN prefix. See is_tradeable_equity().

    (Separately: V1's `instrument_key_for()` had an operator-precedence bug,
    `not a or not b and not c`, which made its ISIN guard evaluate in a way its
    author did not intend. Written here as one explicit regex so that class of
    mistake cannot recur.)
    """
    return bool(value) and bool(_ISIN_RE.match(value.strip().upper()))


def is_tradeable_equity(segment: str, instrument_type: str | None) -> bool:
    """Pre-open / equity-strategy eligibility.

    Deliberately excludes SG (government securities), N*/TB/GB (debt) and the
    derivative segments. This is an INSTRUMENT-CLASS decision, not a liquidity
    decision — liquidity filtering belongs to Stage 5 strategy logic, never to
    ingestion (constraint #4).
    """
    return segment == SEGMENT_NSE_EQ and (instrument_type or "").upper() in TRADEABLE_EQUITY_SERIES
