"""Prajna's own point-in-time valuation and the analyst-free earnings surprise
(features-v5; F3 / F5a of docs/STAGE1_FUNDAMENTALS_RND.md). Pure.

The vendor's key ratios (pe, pb) are a snapshot refreshed about monthly; these use the
previous session's close with the fundamentals history known at as_of
(app.fundamentals.ratios: merged snapshots, standalone share count, TTM of 4 consecutive
quarters, seasonal random walk).

  pe_ttm                 close / TTM EPS (TTM EPS <= 0: DIVISION_UNDEFINED)
  earnings_yield_ttm     TTM EPS / close (defined for losses)
  pb_own                 close x shares / book (latest FY assets - liabilities)
  eps_surprise_srw       (NP(q) - NP(q-4)) / |NP(q-4)|, q = the latest known quarter
  eps_surprise_srw_price (NP(q) - NP(q-4)) per share / close
A split or bonus with its ex-date after the fiscal year the share count comes from changes
the count; the vendor gives no count, so the share-based values are MISSING_INPUT then
(never a guessed factor). eps_surprise_srw needs no share count.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from app.features.compute import (
    DIVISION_UNDEFINED,
    INSUFFICIENT_HISTORY,
    MISSING_INPUT,
    Result,
    miss,
    ok,
)
from app.fundamentals import ratios as R

IDS = ("pe_ttm", "earnings_yield_ttm", "pb_own", "eps_surprise_srw", "eps_surprise_srw_price")
SHARE_CHANGING = ("SPLIT", "BONUS")


def own(snaps: dict[str, list[tuple[_dt.datetime, Any]]], close: float | None,
        actions: list[dict[str, Any]], session: _dt.date) -> dict[str, Result]:
    f = R.build(snaps)
    if f is None:
        return dict.fromkeys(IDS, miss(MISSING_INPUT))
    r = R.ratios(f, close if close and close > 0 else None)
    out: dict[str, Result] = {}
    fy = r["shares_from_fy"]
    changed = fy is not None and any(
        a.get("action_type") in SHARE_CHANGING and a.get("ex_date")
        and fy < a["ex_date"] <= session for a in actions)
    shares_ok = r["shares"] is not None and not changed
    no_price = miss(MISSING_INPUT) if not close or close <= 0 else None

    if not shares_ok:
        out["pe_ttm"] = out["earnings_yield_ttm"] = miss(MISSING_INPUT)
    elif r["ttm_net_profit_cr"] is None:        # fewer than 4 consecutive known quarters
        out["pe_ttm"] = out["earnings_yield_ttm"] = miss(
            INSUFFICIENT_HISTORY if f.quarterly_np else MISSING_INPUT)
    elif no_price:
        out["pe_ttm"] = out["earnings_yield_ttm"] = no_price
    else:
        out["earnings_yield_ttm"] = ok(r["earnings_yield"])
        out["pe_ttm"] = ok(r["pe"]) if r["pe"] is not None else miss(DIVISION_UNDEFINED)

    if not shares_ok or r["book_cr"] is None:
        out["pb_own"] = miss(MISSING_INPUT)
    elif no_price:
        out["pb_own"] = no_price
    else:
        out["pb_own"] = ok(r["pb"]) if r["pb"] is not None else miss(DIVISION_UNDEFINED)

    if r["surprise_quarter"] is None:
        out["eps_surprise_srw"] = out["eps_surprise_srw_price"] = miss(MISSING_INPUT)
        return out
    base_known = r["surprise_growth"] is not None or _base_is_zero(f)
    if not base_known:
        out["eps_surprise_srw"] = out["eps_surprise_srw_price"] = miss(INSUFFICIENT_HISTORY)
        return out
    out["eps_surprise_srw"] = (ok(r["surprise_growth"]) if r["surprise_growth"] is not None
                               else miss(DIVISION_UNDEFINED))
    if not shares_ok:
        out["eps_surprise_srw_price"] = miss(MISSING_INPUT)
    elif no_price:
        out["eps_surprise_srw_price"] = no_price
    else:
        out["eps_surprise_srw_price"] = ok(r["surprise_per_price"])
    return out


def _base_is_zero(f: R.Fundamentals) -> bool:
    last = max(f.quarterly_np)
    return f.quarterly_np.get(R._quarters_back(last, 4)) == 0
