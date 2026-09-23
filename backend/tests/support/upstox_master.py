"""A synthetic Upstox instrument master in the vendor's shape.

Not a recording. Row shapes follow the live NSE.json.gz (segment,
instrument_type, instrument_key, isin, trading_symbol, ...); the mix covers
every rule the selection must apply.
"""

from __future__ import annotations

import gzip
import json


def row(key: str, segment: str, itype: str | None, isin: str | None = None,
        sym: str | None = None, **extra) -> dict:
    r = {"segment": segment, "instrument_key": key, "exchange": segment.split("_")[0],
         "trading_symbol": sym or key.split("|")[1], "name": sym or key, "lot_size": 1,
         "tick_size": 0.05, "exchange_token": "1", **extra}
    if itype is not None:
        r["instrument_type"] = itype
    if isin is not None:
        r["isin"] = isin
    return r


RELIANCE = row("NSE_EQ|INE002A01018", "NSE_EQ", "EQ", "INE002A01018", "RELIANCE")
NIFTYBEES = row("NSE_EQ|INF204KB14I2", "NSE_EQ", "EQ", "INF204KB14I2", "NIFTYBEES")
IN9_EQ = row("NSE_EQ|IN9155A01020", "NSE_EQ", "EQ", "IN9155A01020", "TATAMTRDVR")
SME = row("NSE_EQ|INE0AAA01011", "NSE_EQ", "SM", "INE0AAA01011", "SMEONE")
BE = row("NSE_EQ|INE0BBB01011", "NSE_EQ", "BE", "INE0BBB01011", "BEONE")
BZ = row("NSE_EQ|INE0CCC01011", "NSE_EQ", "BZ", "INE0CCC01011", "BZONE")
ST = row("NSE_EQ|INE0DDD01011", "NSE_EQ", "ST", "INE0DDD01011", "STONE")
IV = row("NSE_EQ|INE0EEE01011", "NSE_EQ", "IV", "INE0EEE01011", "IVONE")

GSEC = row("NSE_EQ|IN0020230011", "NSE_EQ", "SG", "IN0020230011", "GS2033")
DEBT = row("NSE_EQ|INE0FFF07011", "NSE_EQ", "N0", "INE0FFF07011", "NCD1")
TBILL = row("NSE_EQ|IN002024X011", "NSE_EQ", "TB", "IN002024X011", "TBILL")
GOLDB = row("NSE_EQ|IN0020220078", "NSE_EQ", "GB", "IN0020220078", "SGBJAN")
NO_SERIES = row("NSE_EQ|INE0GGG01011", "NSE_EQ", None, "INE0GGG01011", "NOSERIES")
INDEX = row("NSE_INDEX|Nifty 50", "NSE_INDEX", "INDEX", None, "NIFTY")
FUT = row("NSE_FO|35001", "NSE_FO", "FUT", None, "RELIANCE26SEPFUT")

ELIGIBLE = [RELIANCE, NIFTYBEES, IN9_EQ, SME, BE, BZ, ST, IV]
INELIGIBLE = [GSEC, DEBT, TBILL, GOLDB, NO_SERIES, INDEX, FUT]
ALL = ELIGIBLE + INELIGIBLE


def master_bytes(rows: list, *, gz: bool = True) -> bytes:
    raw = json.dumps(rows, separators=(",", ":")).encode()
    return gzip.compress(raw, mtime=0) if gz else raw
