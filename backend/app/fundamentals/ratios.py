"""Point-in-time ratios (F3) and the analyst-free earnings surprise (F5a) from the
Upstox fundamentals snapshots (docs/STAGE1_FUNDAMENTALS_RND.md; approved 2026-10-19).
PURE: payloads and a price in, numbers out; the caller passes only snapshots with
knowable_at < as_of, so every number here is knowable at as_of.

  history     every snapshot of a statement contributes its periods; for a period seen
              in several snapshots the LATEST known snapshot wins (a restatement known
              by as_of is used; one published later is not)
  shares      FY profit after tax (crore) x 1e7 / FY basic EPS: the vendor gives no share
              count. STANDALONE figures are used when present (consolidated PAT includes
              minority interest, which overstates the count: RELIANCE 16.0 bn vs 13.5 bn);
              the basis and FY are recorded
  TTM         the sum of the 4 latest CONSECUTIVE quarters of net profit
  P/E, EY     price / TTM EPS; earnings yield = TTM EPS / price (defined for losses too)
  P/B         price x shares / book; book = total assets - total liabilities (latest FY)
  surprise    F5a seasonal random walk (Foster, Olsen & Shevlin 1984): the expectation of
              quarter q is quarter q - 4; surprise = NP(q) - NP(q - 4), scaled by
              |NP(q - 4)| (growth form) and by price (per-share form)
Consolidated statements are preferred; standalone is the fallback (recorded).
"""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any

VERSION = "fund-ratios-v1"
_LABEL = re.compile(r"^([A-Za-z]{3})[a-z]*\s+(\d{4})$")
_MON = {m: i for i, m in enumerate(calendar.month_abbr) if m}


def period_end(label: str | None) -> _dt.date | None:
    """'Jun 2026' -> 2026-06-30."""
    m = _LABEL.match((label or "").strip())
    if not m or m.group(1).title() not in _MON:
        return None
    y, mo = int(m.group(2)), _MON[m.group(1).title()]
    return _dt.date(y, mo, calendar.monthrange(y, mo)[1])


def _quarters_back(d: _dt.date, n: int) -> _dt.date:
    m = d.month - 3 * n
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return _dt.date(y, m, calendar.monthrange(y, m)[1])


def merge(snapshots: list[tuple[_dt.datetime, Any]], pick) -> dict[_dt.date, float]:
    """{period_end: value} over snapshots ordered by knowable_at; later ones win.
    `pick(payload)` yields (label, value)."""
    out: dict[_dt.date, float] = {}
    for _, p in sorted(snapshots, key=lambda x: x[0]):
        for label, v in pick(p):
            pe = period_end(label)
            if pe is not None and v is not None:
                out[pe] = float(v)
    return out


def _category(p: Any, key: str, cat: str):
    for x in (p or {}).get(key) or [] if isinstance(p, dict) else []:
        if x.get("category") == cat:
            for h in x.get("history") or []:
                yield h.get("period"), h.get("value")


def _particular(p: Any, name: str):
    for x in (p or {}).get("full_statement") or [] if isinstance(p, dict) else []:
        if (x.get("particular") or "").strip().lower() == name.lower():
            for h in x.get("history") or []:
                yield h.get("period"), h.get("value")


def _book(p: Any):
    for h in (p or {}).get("history") or [] if isinstance(p, dict) else []:
        a, li = h.get("total_asset"), h.get("total_liability")
        yield h.get("period"), (a - li) if a is not None and li is not None else None


@dataclass(frozen=True, slots=True)
class Fundamentals:
    """Merged histories of one instrument as known at as_of (one statement type)."""
    basis: str                                   # consolidated | standalone
    quarterly_np: dict[_dt.date, float]          # crore
    fy_pat: dict[_dt.date, float]
    fy_eps: dict[_dt.date, float]
    fy_book: dict[_dt.date, float]
    share_pat: dict[_dt.date, float]             # the pair used for the share count
    share_eps: dict[_dt.date, float]
    share_basis: str


def build(snaps: dict[str, list[tuple[_dt.datetime, Any]]]) -> Fundamentals | None:
    """snaps: statement_type -> [(knowable_at, payload)], already filtered to as_of."""
    def pat_eps(basis: str) -> tuple[dict, dict]:
        y = snaps.get(f"income:{basis}:yearly", [])
        return (merge(y, lambda p: _particular(p, "Profit After Tax")),
                merge(y, lambda p: _particular(p, "EPS - Basic")))

    sp, se = pat_eps("standalone")
    share_basis = "standalone"
    for basis in ("consolidated", "standalone"):
        q = merge(snaps.get(f"income:{basis}:quarterly", []),
                  lambda p: _category(p, "income_statement", "net_profit"))
        pat, eps = pat_eps(basis)
        if not q and not pat:
            continue
        if not (set(sp) & set(se)):
            sp, se, share_basis = pat, eps, basis
        return Fundamentals(basis, q, pat, eps,
                            merge(snaps.get(f"balance_sheet:{basis}", []), _book),
                            sp, se, share_basis)
    return None


def ttm(q: dict[_dt.date, float]) -> tuple[float | None, _dt.date | None]:
    """Sum of the 4 latest consecutive quarters, and the latest quarter end."""
    if not q:
        return None, None
    last = max(q)
    need = [_quarters_back(last, i) for i in range(4)]
    return (sum(q[d] for d in need), last) if all(d in q for d in need) else (None, last)


def shares(f: Fundamentals) -> tuple[float | None, _dt.date | None]:
    for fy in sorted(set(f.share_pat) & set(f.share_eps), reverse=True):
        pat, eps = f.share_pat[fy], f.share_eps[fy]
        if eps and pat and (pat > 0) == (eps > 0):
            return pat * 1e7 / eps, fy
    return None, None


def ratios(f: Fundamentals, price: float | None) -> dict[str, Any]:
    n, fy = shares(f)
    t, last_q = ttm(f.quarterly_np)
    book_fy = max(f.fy_book) if f.fy_book else None
    out: dict[str, Any] = {"version": VERSION, "basis": f.basis, "latest_quarter": last_q,
                           "shares_from_fy": fy, "shares_basis": f.share_basis, "shares": n,
                           "ttm_net_profit_cr": t,
                           "book_fy": book_fy,
                           "book_cr": f.fy_book.get(book_fy) if book_fy else None,
                           "ttm_eps": None, "pe": None, "earnings_yield": None, "pb": None}
    if n and t is not None:
        eps = t * 1e7 / n
        out["ttm_eps"] = eps
        if price and price > 0:
            out["earnings_yield"] = eps / price
            out["pe"] = price / eps if eps > 0 else None      # P/E undefined for losses
    if n and price and price > 0 and out["book_cr"] and out["book_cr"] > 0:
        out["pb"] = price * n / (out["book_cr"] * 1e7)
    out.update(surprise(f, price, n))
    return out


def surprise(f: Fundamentals, price: float | None, n: float | None) -> dict[str, Any]:
    """F5a: the latest quarter against the same quarter a year earlier."""
    q = f.quarterly_np
    if not q:
        return {"surprise_quarter": None, "surprise_growth": None, "surprise_per_price": None}
    last = max(q)
    base = q.get(_quarters_back(last, 4))
    out: dict[str, Any] = {"surprise_quarter": last, "surprise_growth": None,
                           "surprise_per_price": None}
    if base is None:
        return out
    diff = q[last] - base
    if base != 0:
        out["surprise_growth"] = diff / abs(base)
    if n and price and price > 0:
        out["surprise_per_price"] = diff * 1e7 / n / price
    return out
