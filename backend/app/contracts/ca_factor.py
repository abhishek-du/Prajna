"""Corporate-action adjustment factors (hardening phase 7). Pure.

A factor F divides prices and multiplies volumes of bars BEFORE the ex-date:
    adj_price = raw_price / F        adj_volume = raw_volume * F

Rules (ratio semantics verified on the real data, 2026-09-25):
  SPLIT      F = old_face_value / new_face_value. The vendor ratio is
             "new:old" (73/73 splits: ratio_from = new fv, ratio_to = old fv);
             both must agree or the factor is UNCERTAIN. A reverse split
             (new fv > old fv) gives F < 1 by the same formula.
             Verified: DHARIWAL "2:10" -> F 5; the vendor left it unadjusted
             and its raw series jumps 4.905x at the ex-date.
  BONUS a:b  a new shares for every b held: F = (a + b) / b.
             Verified on the unadjusted events: JAKHARIA 2:1 -> 3 (jump 2.86),
             UEL 2:1 -> 3 (3.16), IDEALTECHO 1:1 -> 2 (1.80); CHAVDA 1:1 -> 2
             (740/740 vendor bars = half-even(raw / 2, tick), volume x 2).
  RIGHTS     UNSUPPORTED: the structured Premium field is 0.0 on 60/60 rights
             events while the free-text Details state a premium (e.g. "Rs. 1.17"),
             so the issue price is not provable from structured data; the text
             is recorded as evidence only, never applied.
  DIVIDEND   never a price factor (a separate total-return series, if ever)
  others     UNSUPPORTED (mergers/demergers are not in the vendor feed)
Several events: factors multiply in ex-date order (same-day events: both).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

METHOD_VERSION = "cafactor-v1"
_RIGHTS_TEXT = re.compile(r"Rs\.?\s*([\d.]+)/?-?.*?ratio of\s*(\d+)\s*:\s*(\d+).*?premium of\s*"
                          r"Rs\.?\s*([\d.]+)", re.I | re.S)


@dataclass(frozen=True, slots=True)
class Factor:
    status: str                        # EXACT / UNCERTAIN / UNSUPPORTED
    method: str                        # SPLIT_FV / BONUS_RATIO / RIGHTS_TERP / NONE
    factor_price: Decimal | None
    factor_volume: Decimal | None
    reason: str
    inputs: dict[str, Any] = field(default_factory=dict)


def _ratio(s: str | None) -> tuple[Decimal, Decimal] | None:
    if not s or ":" not in s:
        return None
    a, b = (x.strip() for x in s.split(":", 1))
    try:
        a_, b_ = Decimal(a), Decimal(b)
    except Exception:
        return None
    return (a_, b_) if a_ > 0 and b_ > 0 else None


def factor_for(action_type: str, *, ratio: str | None, fv_before: Decimal | None,
               fv_after: Decimal | None, details: str | None = None) -> Factor:
    r = _ratio(ratio)
    if action_type == "SPLIT":
        inputs = {"ratio": ratio, "face_value_before": str(fv_before),
                  "face_value_after": str(fv_after)}
        if not fv_before or not fv_after:
            return Factor("UNCERTAIN", "SPLIT_FV", None, None, "face values missing", inputs)
        f = Decimal(fv_before) / Decimal(fv_after)
        if r and (r[0] != Decimal(fv_after) or r[1] != Decimal(fv_before)):
            return Factor("UNCERTAIN", "SPLIT_FV", None, None,
                          "ratio new:old disagrees with the face values", inputs)
        return Factor("EXACT", "SPLIT_FV", f, f, "old face value / new face value", inputs)
    if action_type == "BONUS":
        inputs = {"ratio": ratio}
        if r is None:
            return Factor("UNCERTAIN", "BONUS_RATIO", None, None, "unparseable ratio", inputs)
        a, b = r
        f = (a + b) / b
        return Factor("EXACT", "BONUS_RATIO", f, f, f"(a+b)/b for {a}:{b}", inputs)
    if action_type == "RIGHTS":
        m = _RIGHTS_TEXT.search(details or "")
        text = None if m is None else {"face_value": m.group(1), "ratio": f"{m.group(2)}:"
                                       f"{m.group(3)}", "premium": m.group(4)}
        return Factor("UNSUPPORTED", "RIGHTS_TERP", None, None,
                      "structured Premium is 0.0 on every vendor rights event; the issue "
                      "price exists only in free text and is not provable",
                      {"ratio": ratio, "details_text_parse": text})
    return Factor("UNSUPPORTED", "NONE", None, None,
                  "dividends are not price factors" if action_type == "DIVIDEND"
                  else f"{action_type}: no factor rule")


def adjust_price(raw: Decimal, f: Decimal, tick: Decimal) -> Decimal:
    """The vendor's observed convention: round half-even to the tick."""
    return (Decimal(raw) / f / tick).quantize(Decimal(1), rounding=ROUND_HALF_EVEN) * tick


def cumulative(factors: list[tuple[Any, Decimal]]) -> Decimal:
    """Product of the factors, applied in ex-date order (same-day: all)."""
    out = Decimal(1)
    for _, f in sorted(factors, key=lambda x: x[0]):
        out *= f
    return out
