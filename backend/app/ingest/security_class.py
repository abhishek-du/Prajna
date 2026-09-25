"""Security classification: STOCK / FUND_UNIT / RIGHTS_ENTITLEMENT / OTHER (phase 3).

Independent signals, each with its raw value and a vote (measured on the
real 2026-09-25 universe, 3,532 NSE_EQ instruments):

  isin      ISIN structure: IN + issuer type + issuer(4) + security code(2)
            + serial(2) + check. Issuer F -> FUND (351/351 fund units);
            code 20 -> RE (both -RE instruments); code 23 -> INVIT (21/21
            series-IV trusts); issuer E or 9 otherwise -> COMPANY (9 = DVR
            shares, e.g. JISLDVREQS). This CLASSIFIES; eligibility for
            the S1 universe is unchanged and never ISIN-based.
  series    vendor series: IV -> INVIT; every other series says nothing
            (ETFs trade in series EQ too)
  financials vendor fundamentals: sector or key ratios / shareholding ->
            FINANCIALS (a company or a trust files statements); a profile
            with none of them -> NO_FINANCIALS (fund schemes, entitlements);
            no profile -> no vote
  suffix    trading symbol ends in -RE -> RE
  name      scheme naming ("<AMC> - <SCHEME>") or the word ETF -> FUND;
            supportive only: its absence never contradicts (10 listed AMC
            companies such as HDFCAMC must not look like funds)

Decisions (>= 2 agreeing signals, no contradicting vote):
  STOCK               isin COMPANY + financials FINANCIALS
  FUND_UNIT           isin FUND + (financials NO_FINANCIALS or name FUND)
  RIGHTS_ENTITLEMENT  isin RE + suffix RE
  OTHER/INVIT_UNIT    isin INVIT + series INVIT
  OTHER/INDEX|GLOBAL  segment + vendor instrument type
A contradiction is REVIEW; fewer than two signals UNCLASSIFIED (e.g. a new
listing whose fundamentals have not been fetched yet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.identity import GLOBAL_SEGMENTS
from app.contracts.provenance import AnomalyKind, AnomalySeverity
from app.core.clock import now
from app.db.models import InstrumentSecurityClass
from app.ingest.runner import IngestRunner

METHOD_VERSION = "secclass-v1"
SOURCE, STREAM = "PRAJNA_DERIVED", "derive.security_class"
_FUND_NAME = re.compile(r"\bETF\b|^[A-Z0-9&_]+(AMC|AML|MF)\s*-\s*\S")


def isin_vote(isin: str | None) -> str | None:
    if not isin or len(isin) != 12 or not isin.startswith("IN"):
        return None
    issuer, code = isin[2], isin[7:9]
    if issuer == "F":
        return "FUND"
    if issuer in ("E", "9"):
        return {"20": "RE", "23": "INVIT"}.get(code, "COMPANY")
    return None


def financials_vote(has_profile: bool, sector: str | None, has_ratios: bool) -> str | None:
    if sector or has_ratios:
        return "FINANCIALS"
    return "NO_FINANCIALS" if has_profile else None


@dataclass(frozen=True, slots=True)
class Decision:
    security_class: str | None
    subclass: str | None
    status: str
    reason: str
    signals: dict[str, Any]


def classify(inst: dict[str, Any]) -> Decision:
    """Pure. inst: segment, isin, instrument_type, trading_symbol, name, sector,
    has_profile, has_ratios."""
    seg = inst.get("segment")
    if seg == "NSE_INDEX" or seg in GLOBAL_SEGMENTS:
        sub = "INDEX" if seg == "NSE_INDEX" else "GLOBAL"
        sig = {"segment": {"value": seg, "vote": sub},
               "instrument_type": {"value": inst.get("instrument_type"), "vote": sub}}
        return Decision("OTHER", sub, "CLASSIFIED", f"segment {seg}", sig)
    sig = {
        "isin": {"value": inst.get("isin"), "vote": isin_vote(inst.get("isin"))},
        "series": {"value": inst.get("instrument_type"),
                   "vote": "INVIT" if inst.get("instrument_type") == "IV" else None},
        "financials": {"value": {"sector": inst.get("sector"),
                                 "profile": bool(inst.get("has_profile")),
                                 "ratios_or_holdings": bool(inst.get("has_ratios"))},
                       "vote": financials_vote(bool(inst.get("has_profile")), inst.get("sector"),
                                               bool(inst.get("has_ratios")))},
        "suffix": {"value": inst.get("trading_symbol"),
                   "vote": "RE" if (inst.get("trading_symbol") or "").endswith("-RE") else None},
        "name": {"value": inst.get("name"),
                 "vote": "FUND" if _FUND_NAME.search(inst.get("name") or "") else None},
    }
    v = {k: s["vote"] for k, s in sig.items()}
    kinds = {x for x in (v["isin"], v["series"], v["suffix"], v["name"]) if x}
    fin = v["financials"]

    def decide(cls, sub, agree: list[str], reason: str) -> Decision:
        return Decision(cls, sub, "CLASSIFIED", f"{reason} (signals: {', '.join(agree)})", sig)

    if v["isin"] == "COMPANY" and kinds == {"COMPANY"} and fin == "FINANCIALS":
        return decide("STOCK", None, ["isin", "financials"], "company equity with financials")
    if v["isin"] == "FUND" and kinds == {"FUND"} and "FINANCIALS" != fin \
            and (fin == "NO_FINANCIALS" or v["name"] == "FUND"):
        agree = ["isin"] + (["financials"] if fin == "NO_FINANCIALS" else []) + \
            (["name"] if v["name"] == "FUND" else [])
        return decide("FUND_UNIT", None, agree, "fund scheme unit")
    if v["isin"] == "RE" and v["suffix"] == "RE" and kinds == {"RE"}:
        return decide("RIGHTS_ENTITLEMENT", None, ["isin", "suffix"], "rights entitlement")
    if v["isin"] == "INVIT" and v["series"] == "INVIT" and kinds == {"INVIT"}:
        return decide("OTHER", "INVIT_UNIT", ["isin", "series"],
                      "infrastructure investment trust unit (not an operating company)")
    if len(kinds) > 1 or (fin == "FINANCIALS" and kinds & {"FUND"}) or \
            (fin == "NO_FINANCIALS" and kinds == {"COMPANY"}):
        return Decision(None, None, "REVIEW", f"signals disagree: {v}", sig)
    return Decision(None, None, "UNCLASSIFIED", f"insufficient evidence: {v}", sig)


async def classify_securities(s: AsyncSession, *, commit: bool, token: str | None,
                              operator: str = "cli") -> dict[str, Any]:
    runner = IngestRunner(s, source=SOURCE, stream=STREAM,
                          vendor_endpoint="derived: instrument + fundamental_snapshot",
                          request_params={"method_version": METHOD_VERSION}, operator=operator)
    ctx = await runner.open(commit=commit, token=token)
    try:
        rows = (await s.execute(text("""
            select i.instrument_id, i.instrument_key, i.segment, i.isin, i.instrument_type,
                   i.trading_symbol, i.name, p.sector, p.id is not null as has_profile,
                   exists (select 1 from fundamental_snapshot f
                           where f.instrument_key = i.instrument_key
                             and f.statement_type in ('key_ratios', 'shareholding')) has_ratios
            from instrument i
            left join lateral (
                select f.id, nullif(f.payload->>'sector', '') as sector from fundamental_snapshot f
                where f.instrument_key = i.instrument_key and f.statement_type = 'profile'
                order by f.knowable_at desc limit 1) p on true
            where i.valid_to = 'infinity'"""))).mappings().all()
        prior = {r.instrument_id: (r.security_class, r.status) for r in (await s.execute(text(
            "select instrument_id, security_class, status from instrument_security_class")))}
        at = now()
        out, counts, changed = [], {}, []
        for r in rows:
            d = classify(dict(r))
            key = f"{d.security_class or '-'}/{d.subclass or '-'}/{d.status}"
            counts[key] = counts.get(key, 0) + 1
            if prior.get(r["instrument_id"]) not in (None, (d.security_class, d.status)):
                changed.append(r["instrument_key"])
            out.append({"instrument_id": r["instrument_id"], "instrument_key": r["instrument_key"],
                        "security_class": d.security_class, "subclass": d.subclass,
                        "status": d.status, "signals": d.signals, "reason": d.reason[:500],
                        "method_version": METHOD_VERSION, "classified_at": at,
                        "run_id": ctx.run_id})
        review = sorted(o["instrument_key"] for o in out if o["status"] == "REVIEW")
        if review:
            ctx.checks.add(AnomalySeverity.WARN, AnomalyKind.LIFECYCLE, "security_class",
                           reason="classification signals disagree: REVIEW", count=len(review),
                           keys=review[:200])
        if changed:
            ctx.checks.add(AnomalySeverity.WARN, AnomalyKind.LIFECYCLE, "security_class",
                           reason="classification changed", count=len(changed),
                           keys=changed[:200])
        if commit and out:
            for i in range(0, len(out), 1000):
                stmt = pg_insert(InstrumentSecurityClass).values(out[i:i + 1000])
                await s.execute(stmt.on_conflict_do_update(
                    index_elements=["instrument_id"],
                    set_={c: stmt.excluded[c] for c in (
                        "instrument_key", "security_class", "subclass", "status", "signals",
                        "reason", "method_version", "classified_at", "run_id")}))
        summary = {"instruments": len(out), "counts": dict(sorted(counts.items())),
                   "review": review, "changed": len(changed)}
        await runner.finalize(rows_written=len(out) if commit else 0, outcome=summary)
        return {"run_id": str(ctx.run_id), "committed": commit, **summary}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        raise
