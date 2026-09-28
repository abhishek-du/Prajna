"""Fundamental features (diagram group 3), from vendor snapshots as knowable
at the snapshot instant. Vendor payloads are shape-checked; an unexpected shape
yields MALFORMED_INPUT, never an exception and never a guess.

  pe, pb, roe_pct, roce_pct, ev_ebitda      company value from `key_ratios`
  pe_to_sector, pb_to_sector                company / sector value
  revenue_yoy, pat_yoy, eps_yoy             yearly statement: latest period vs the one before
  revenue_yoy_q, pat_yoy_q                  quarterly: latest quarter vs the same quarter a
                                            year earlier.
                                            The vendor's "quarterly" statement usually carries
                                            ANNUAL (March) periods, identical to the yearly one
                                            (2026-09-28: ~99% of instruments); such a payload is
                                            MALFORMED_INPUT, never reused as quarterly growth
  liabilities_to_assets                     (Current + Non-Current Liabilities) / Total Assets,
                                            latest year (the vendor balance sheet has no debt line:
                                            this is total liabilities, not debt)
Earnings surprises: UNSUPPORTED (no consensus estimates exist in any source).
"""

from __future__ import annotations

import re
from datetime import date
from itertools import pairwise
from typing import Any

from app.features.compute import (
    DIVISION_UNDEFINED,
    INSUFFICIENT_HISTORY,
    MALFORMED_INPUT,
    MISSING_INPUT,
    Result,
    miss,
    ok,
)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_number(v: Any) -> float | None:
    """'19.14' / '8.94%' / '1,234.5' / 19.14 -> float; anything else -> None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace(",", "").rstrip("%").strip()
    if not re.fullmatch(r"[-+]?\d+(\.\d+)?", s):
        return None
    return float(s)


def parse_period(label: Any) -> date | None:
    """'Mar 2026' -> 2026-03-01."""
    if not isinstance(label, str):
        return None
    m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\s+(\d{4})", label.strip())
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    return date(int(m.group(2)), _MONTHS[m.group(1).lower()], 1)


def key_ratio(payload: Any, name: str, *, sector: bool = False) -> Result:
    if payload is None:
        return miss(MISSING_INPUT)
    if not isinstance(payload, list):
        return miss(MALFORMED_INPUT)
    for r in payload:
        if isinstance(r, dict) and r.get("name") == name:
            v = parse_number(r.get("sector_value" if sector else "company_value"))
            return ok(v) if v is not None else miss(MALFORMED_INPUT)
    return miss(MISSING_INPUT)


def ratio_to_sector(payload: Any, name: str) -> Result:
    c, why = key_ratio(payload, name)
    if c is None:
        return (None, why)
    s, why = key_ratio(payload, name, sector=True)
    if s is None:
        return (None, why)
    return ok(c / s) if s > 0 else miss(DIVISION_UNDEFINED)


def _line(payload: Any, particular: str) -> dict[date, float] | None:
    """{period: value} for one statement line; None when the payload is malformed."""
    if not isinstance(payload, dict):
        return None
    full = payload.get("full_statement")
    if not isinstance(full, list):
        return None
    for line in full:
        if isinstance(line, dict) and line.get("particular") == particular:
            hist = line.get("history")
            if not isinstance(hist, list):
                return None
            out = {}
            for h in hist:
                if not isinstance(h, dict):
                    return None
                p, v = parse_period(h.get("period")), parse_number(h.get("value"))
                if p is not None and v is not None:
                    out[p] = v
            return out
    return {}


def growth(payload: Any, particular: str, *, quarterly: bool = False) -> Result:
    if payload is None:
        return miss(MISSING_INPUT)
    line = _line(payload, particular)
    if line is None:
        return miss(MALFORMED_INPUT)
    if not line:
        return miss(MISSING_INPUT)
    periods = sorted(line)
    latest = periods[-1]
    if quarterly:
        months = [p.year * 12 + p.month for p in periods]
        if len(months) >= 2 and min(b - a for a, b in pairwise(months)) >= 12:
            return miss(MALFORMED_INPUT)          # annual periods labelled quarterly
        prev = date(latest.year - 1, latest.month, 1)
        if prev not in line:
            return miss(INSUFFICIENT_HISTORY)
    else:
        if len(periods) < 2:
            return miss(INSUFFICIENT_HISTORY)
        prev = periods[-2]
    base = line[prev]
    if base <= 0:            # growth from a loss / zero base is undefined, not a number
        return miss(DIVISION_UNDEFINED)
    return ok(line[latest] / base - 1)


def liabilities_to_assets(payload: Any) -> Result:
    if payload is None:
        return miss(MISSING_INPUT)
    cur, non = _line(payload, "Current Liabilities"), _line(payload, "Non-Current Liabilities")
    tot = _line(payload, "Total Assets")
    if cur is None or non is None or tot is None:
        return miss(MALFORMED_INPUT)
    if not tot:
        return miss(MISSING_INPUT)
    latest = max(tot)
    if latest not in cur or latest not in non:
        return miss(MISSING_INPUT)
    return ok((cur[latest] + non[latest]) / tot[latest]) if tot[latest] > 0 \
        else miss(DIVISION_UNDEFINED)
