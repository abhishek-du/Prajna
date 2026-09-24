"""Stage 2.4: the deterministic NSE-only filter. Pure.

Every current instrument gets a decision and a reason; nothing is removed
from Stage 1 or the raw archive. The rule set is hashed (rules_sha256) so a
changed rule is visible on every row it decided.

  NSE_EQ with a tradeable series (S1: EQ/BE/SM/BZ/ST/IV) and a valid ISIN  -> included
  NSE_INDEX in the approved list (NIFTY 50, Nifty Bank, India VIX)          -> included
  GLOBAL_INDEX / GLOBAL_INDICATOR -> excluded from the NSE universe; exposed
                                     as macro context in canon_global_bar
  anything else (BSE, derivatives, other series, malformed)                -> excluded
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.contracts.identity import (
    GLOBAL_SEGMENTS,
    SEGMENT_NSE_EQ,
    SEGMENT_NSE_INDEX,
    TRADEABLE_EQUITY_SERIES,
    is_valid_isin,
)
from app.ingest.instruments import REQUIRED_INDEX_KEYS

RULES = {
    "version": "stage2-universe-v1",
    "nse_eq_series": sorted(TRADEABLE_EQUITY_SERIES),
    "nse_indices": sorted(REQUIRED_INDEX_KEYS),
    "global_segments": sorted(GLOBAL_SEGMENTS),
    "requires": "NSE_EQ: valid ISIN and trading_symbol",
}
RULES_SHA256 = hashlib.sha256(json.dumps(RULES, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Decision:
    included: bool
    reason: str


def decide(inst: dict[str, Any]) -> Decision:
    seg, series, key = inst.get("segment"), inst.get("instrument_type"), inst["instrument_key"]
    if seg == SEGMENT_NSE_EQ:
        if (series or "").upper() not in TRADEABLE_EQUITY_SERIES:
            return Decision(False, f"NSE_EQ series {series!r} not in the S1 universe")
        if not is_valid_isin(inst.get("isin")) or not inst.get("trading_symbol"):
            return Decision(False, "malformed: NSE_EQ without a valid ISIN or symbol")
        return Decision(True, f"NSE_EQ series {series}")
    if seg == SEGMENT_NSE_INDEX:
        if key in REQUIRED_INDEX_KEYS:
            return Decision(True, "approved NSE index")
        return Decision(False, "NSE_INDEX not in the approved index list")
    if seg in GLOBAL_SEGMENTS:
        return Decision(False, "not NSE: global instrument (macro context, canon_global_bar)")
    return Decision(False, f"segment {seg!r} is outside the NSE universe")


def content_sha256(row: dict[str, Any]) -> str:
    """Hash of everything a canon_instrument row asserts (not its run_id)."""
    keep = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()
            if k not in ("run_id", "content_sha256")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()
