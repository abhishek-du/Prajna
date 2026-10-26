"""Stage 4 v2 P2: the LLM reviewer in shadow (docs/STAGE4_P2_REVIEWER_PREREGISTRATION.md).

For every P1 shadow trade (real and placebo) the reviewer reads an evidence packet that
contains only what was knowable at the trade's signal time, and answers PASS, SHRINK or
VETO with closed-list reason codes and the ids of the evidence it relies on. It may only
reduce risk: it never creates a trade, enlarges one or moves a stop.

  blind      the packet never contains the outcome (exit, P&L, exit reason)
  PIT        news, enrichments, results events, corporate actions and entity links all have
             knowable_at <= signal_at; the regime snapshots are from checkpoints <= signal_at
  closed     verdict in {PASS, SHRINK, VETO}; reason codes from REASONS; every cited id must
             be in the packet; SHRINK / VETO need >= 1 reason and >= 1 evidence id
  failsafe   an invalid answer, an error or a timeout is recorded and counts as PASS
             (shadow rule: a failure never means "trade bigger")
  pinned     the model id, the prompt version and the prompt sha are frozen with the
             reviewer; temperature 0; every prompt and raw answer is stored

PAPER/SHADOW ONLY: nothing here talks to a broker. Measured at the P1 looks only.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.clock import IST, now
from app.core.errors import PrajnaError
from app.news import ai as NAI
from app.shadow import job as J
from app.shadow import spec as SP

REVIEWER_VERSION = "p2-reviewer-v1"
PROMPT_VERSION = "p2-prompt-v1"
MODEL_ID = "amazon.nova-pro-v1:0"          # pinned (the live news-AI model, same key)
FORWARD_FROM: _dt.date | None = _dt.date(2026, 10, 27)   # frozen 2026-10-26 (= P1 start)
NEWS_WINDOW_H = 48
MAX_NEWS = 15
TIMEOUT_S = 90.0
ATTEMPTS = 2
RUN_LIMIT = 400
VERDICTS = ("PASS", "SHRINK", "VETO")
REASONS = ("UNSEEN_MATERIAL_NEWS", "RESULTS_OR_BOARD_MEETING", "CORPORATE_ACTION",
           "GOVERNANCE_FLAG", "CIRCUIT_RISK", "STALE_OR_CONFLICTING_DATA",
           "STRATEGY_PRECONDITION_FAILED", "MACRO_EVENT_WINDOW", "OTHER")
OUTCOME_KEYS = ("exit_at", "exit_raw", "exit_px", "exit_reason", "gross_inr", "net_inr",
                "net_r", "by_slippage", "charges", "entry_px")

HYPOTHESIS = {
    SP.S1: ("Opening-range breakout with volume, Nifty and breadth agreement: a trend-day "
            "continuation trade. It should not be taken when the move is driven by a "
            "company-specific event the strategy cannot see (results, a board meeting, a "
            "corporate action, a regulatory action), or into a binary macro event."),
    SP.S2: ("Mean reversion of an intraday stretch below (above) the Bollinger band back "
            "to its middle: it fades NOISE only. Its precondition fails when the move has "
            "a news or fundamental cause (results, an order, a downgrade, a governance "
            "issue, a regulatory action): that move is information and should not be "
            "faded."),
}

PROMPT = """You are the risk reviewer of a SHADOW (paper) intraday trading research system for NSE India.
A rule-based strategy has proposed the trade below. Your only job is to look for reasons NOT to take it, using ONLY the evidence listed.
You may answer:
  PASS   - no listed evidence gives a material reason against the trade;
  SHRINK - the evidence suggests extra risk: take it at reduced size;
  VETO   - the evidence shows the trade's precondition is broken or the risk is unacceptable.
You may never create a trade, enlarge it, change its stop or target, or predict prices.
Every SHRINK or VETO must cite at least one evidence id from the list and at least one reason code.
If there is no stock-specific evidence, or it is immaterial, answer PASS. Do not use outside knowledge about these companies or dates.
Reason codes (closed list): {reasons}.
Use OTHER only with a short note.

Strategy hypothesis: {hypothesis}

Trade (all values known at the signal time):
{trade}

Evidence (each item has an id):
{evidence}

Answer with one JSON object and nothing else, with exactly these keys:
verdict (PASS|SHRINK|VETO), reason_codes (list), evidence_ids (list of ids from the evidence), note (<= 40 words)."""


class ReviewRefused(PrajnaError):
    """The reviewer cannot run or record (not frozen, no model, contradicting row)."""


def spec() -> dict[str, Any]:
    return {"reviewer_version": REVIEWER_VERSION, "prompt_version": PROMPT_VERSION,
            "model_id": MODEL_ID, "temperature": 0, "news_window_h": NEWS_WINDOW_H,
            "max_news": MAX_NEWS, "verdicts": VERDICTS, "reasons": REASONS,
            "hypothesis": HYPOTHESIS, "prompt": PROMPT, "attempts": ATTEMPTS,
            "failsafe": "PASS", "policy_version": SP.POLICY_VERSION}


def spec_sha256() -> str:
    return hashlib.sha256(json.dumps(spec(), sort_keys=True).encode()).hexdigest()


def _ist(t: _dt.datetime | None) -> str | None:
    return None if t is None else t.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")


# ── the evidence packet ────────────────────────────────────────────────────────────
async def packet(s: AsyncSession, trade: Any) -> dict[str, Any]:
    """The PIT, outcome-blind packet of one shadow_trade row."""
    t = trade.signal_at
    inst = (await s.execute(text("""select trading_symbol, name, sector from canon_instrument
        where instrument_key = :k"""), {"k": trade.instrument_key})).first()
    ev: list[dict[str, Any]] = []
    news = (await s.execute(text("""
        select distinct on (i.id) i.id, i.title, i.summary, i.publisher, i.published_at,
               e.output as ai
        from news_entity_link l join news_item i on i.id = l.item_id
        left join lateral (select output from news_ai_enrichment a where a.item_id = i.id
             and a.status = 'OK' and a.knowable_at <= :t order by a.knowable_at desc limit 1) e
             on true
        where l.instrument_key = :k and l.knowable_at <= :t and i.knowable_at <= :t
          and coalesce(i.published_at, i.knowable_at) >= :since
        order by i.id"""),
        {"k": trade.instrument_key, "t": t,
         "since": t - _dt.timedelta(hours=NEWS_WINDOW_H)})).all()
    news = sorted(news, key=lambda r: r.published_at or t, reverse=True)[:MAX_NEWS]
    for r in news:
        ai = r.ai or {}
        ev.append({"id": f"news:{r.id}", "kind": "news", "published": _ist(r.published_at),
                   "publisher": r.publisher, "title": r.title,
                   "summary": (r.summary or "")[:400] or None,
                   "ai_event_type": ai.get("event_type"), "ai_impact": ai.get("potential_impact"),
                   "ai_direction": ai.get("impact_direction")})
    res = (await s.execute(text("""select id, kind, meeting_date, event_at, verdict, flags
        from results_event where instrument_key = :k and knowable_at <= :t
          and kind in ('INTIMATION', 'OUTCOME', 'ESTIMATE_NEWS')
          and (meeting_date between :a and :b or event_at between :ta and :t)
        order by id"""),
        {"k": trade.instrument_key, "t": t, "a": trade.market_date - _dt.timedelta(days=3),
         "b": trade.market_date + _dt.timedelta(days=3),
         "ta": t - _dt.timedelta(days=3)})).all()
    for r in res:
        ev.append({"id": f"results:{r.id}", "kind": f"results_{r.kind.lower()}",
                   "meeting_date": str(r.meeting_date) if r.meeting_date else None,
                   "event_at": _ist(r.event_at), "verdict": r.verdict,
                   "flags": list(r.flags or [])})
    ca = (await s.execute(text("""select id, action_type, ex_date, ratio_from, ratio_to, amount
        from canon_corporate_action where instrument_key = :k and knowable_at <= :t
          and ex_date between :a and :b order by id"""),
        {"k": trade.instrument_key, "t": t, "a": trade.market_date,
         "b": trade.market_date + _dt.timedelta(days=7)})).all()
    for r in ca:
        ev.append({"id": f"ca:{r.id}", "kind": "corporate_action", "type": r.action_type,
                   "ex_date": str(r.ex_date),
                   "detail": {k: (None if v is None else float(v)) for k, v in
                              (("ratio_from", r.ratio_from), ("ratio_to", r.ratio_to),
                               ("amount", r.amount))}})
    cal, _ = J.calendar()
    for e in cal.get(trade.market_date, []):
        ev.append({"id": f"calendar:{trade.market_date}:{e}", "kind": "macro_calendar",
                   "event": e})
    snaps = (await s.execute(text("""select checkpoint, state, rule_fired, day_type, features
        from regime_snapshot where policy_version = :v and market_date = :d"""),
        {"v": trade.policy_version, "d": trade.market_date})).all()
    order = {"PRE": 0, "OPEN": 1}
    for r in sorted(snaps, key=lambda z: order.get(z.checkpoint, 2)):
        cp = r.checkpoint
        cp_t = None if cp in order else J.at(trade.market_date, f"{cp[:2]}:{cp[2:]}")
        if cp_t is not None and cp_t > t:
            continue
        f = r.features or {}
        keep = {k: f.get(k) for k in ("nifty_adx14", "breadth_50dma", "vix_close", "vix_pct252",
                                      "nifty_ret_1d", "nifty_gap", "nifty_from_open",
                                      "breadth_above_open") if k in f}
        ev.append({"id": f"regime:{cp}", "kind": "market_regime", "state": r.state,
                   "rule": r.rule_fired, "day_type": r.day_type, "features": keep})
    trade_view = {
        "strategy": trade.strategy, "symbol": inst.trading_symbol if inst else trade.instrument_key,
        "company": inst.name if inst else None, "sector": inst.sector if inst else None,
        "side": "LONG" if trade.side > 0 else "SHORT", "signal_time": _ist(t),
        "entry": float(trade.entry_raw), "stop": float(trade.stop), "target": float(trade.target),
        "reward_to_risk": round(trade.rrr, 2), "checklist": trade.checklist,
        "time_stop": _ist(trade.time_stop),
        "signal_facts": {k: v for k, v in (trade.evidence or {}).items()
                         if k not in ("mirror_of", "draw_seq")},
    }
    return {"trade": trade_view, "evidence": ev,
            "base": SP.VARIANTS[trade.strategy]["base"]}


def prompt_for(p: dict[str, Any]) -> str:
    return PROMPT.format(
        reasons=", ".join(REASONS), hypothesis=HYPOTHESIS[p["base"]],
        trade=json.dumps(p["trade"], default=str, indent=1, sort_keys=True),
        evidence=json.dumps(p["evidence"], default=str, indent=1) if p["evidence"]
        else "(none: no stock-specific item was knowable)")


def validate(text_: str, p: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str | None]:
    """(status, parsed answer, why) with status OK | INVALID | INVALID_EVIDENCE."""
    try:
        d = NAI._json_object(text_)
    except ValueError as e:
        return "INVALID", None, f"not JSON: {str(e)[:120]}"
    if not isinstance(d, dict) or set(d) != {"verdict", "reason_codes", "evidence_ids", "note"}:
        return "INVALID", None, f"keys {sorted(d) if isinstance(d, dict) else type(d).__name__}"
    v = d["verdict"].strip().upper() if isinstance(d["verdict"], str) else None
    rc, ids, note = d["reason_codes"], d["evidence_ids"], d["note"]
    if v not in VERDICTS or not isinstance(rc, list) or not isinstance(ids, list) \
            or not isinstance(note, str):
        return "INVALID", None, "verdict or list types outside the schema"
    rc = [str(x).strip().upper() for x in rc]
    ids = [str(x).strip() for x in ids]
    if any(x not in REASONS for x in rc):
        return "INVALID", None, f"reason outside the list: {rc}"
    d = {"verdict": v, "reason_codes": rc, "evidence_ids": ids, "note": note[:400]}
    known = {e["id"] for e in p["evidence"]}
    if any(x not in known for x in ids):
        return "INVALID_EVIDENCE", d, f"cited ids not in the packet: {[x for x in ids if x not in known]}"
    if v != "PASS" and (not rc or not ids):
        return "INVALID_EVIDENCE", d, f"{v} without a reason code and an evidence id"
    if "OTHER" in rc and not note.strip():
        return "INVALID", d, "OTHER without a note"
    return "OK", d, None


def effective(status: str, d: dict[str, Any] | None) -> str:
    return d["verdict"] if status == "OK" and d else "PASS"


# ── one review ─────────────────────────────────────────────────────────────────────
async def review_one(s: AsyncSession, trade: Any, model: NAI.Model) -> dict[str, Any]:
    p = await packet(s, trade)
    for k in OUTCOME_KEYS:                                  # blindness, asserted
        if k in p["trade"] or k in json.dumps(p["trade"]["signal_facts"]):
            raise ReviewRefused(f"outcome field {k} reached the packet")
    prompt = prompt_for(p)
    psha = hashlib.sha256(prompt.encode()).hexdigest()
    raw, version, status, d, why, lat = None, None, "ERROR", None, None, None
    for attempt in range(1, ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            raw, version = await asyncio.wait_for(model(MODEL_ID, prompt), TIMEOUT_S)
            lat = int((time.monotonic() - t0) * 1000)
            status, d, why = validate(raw, p)
            break
        except TimeoutError:
            status, why = "TIMEOUT", f"no answer within {TIMEOUT_S}s (attempt {attempt})"
        except Exception as e:  # noqa: BLE001 - a model failure is recorded, never raised
            status, why = "ERROR", f"{type(e).__name__} (attempt {attempt})"
    return {"trade_id": trade.id, "market_date": trade.market_date, "strategy": trade.strategy,
            "instrument_key": trade.instrument_key, "is_placebo": trade.is_placebo,
            "packet": p, "packet_sha256": hashlib.sha256(json.dumps(
                p, sort_keys=True, default=str).encode()).hexdigest(),
            "prompt_sha256": psha, "response_raw": raw, "model_version": version,
            "status": status, "invalid_reason": why,
            "verdict": d["verdict"] if d else None,
            "reason_codes": d["reason_codes"] if d else [],
            "evidence_ids": d["evidence_ids"] if d else [],
            "note": d["note"] if d else None,
            "effective_verdict": effective(status, d), "latency_ms": lat,
            "n_evidence": len(p["evidence"])}


# ── freeze, pending, record ────────────────────────────────────────────────────────
async def reviewer_row(s: AsyncSession) -> Any:
    return (await s.execute(text("""select reviewer_version, spec_sha256, forward_from
        from llm_reviewer where reviewer_version = :v"""), {"v": REVIEWER_VERSION})).first()


async def freeze(s: AsyncSession, *, forward_from: _dt.date, token: str | None,
                 code_git_sha: str) -> dict[str, Any]:
    fp = authorize_write(token)
    if FORWARD_FROM != forward_from:
        raise ReviewRefused(f"review.FORWARD_FROM is {FORWARD_FROM}, not {forward_from}")
    old = await reviewer_row(s)
    if old is not None:
        if old.spec_sha256 != spec_sha256():
            raise ReviewRefused(f"{REVIEWER_VERSION} is frozen with another spec")
        return {"status": "ALREADY_PRESENT", "reviewer_version": REVIEWER_VERSION}
    await s.execute(text("""insert into llm_reviewer (reviewer_version, policy_version,
        model_id, prompt_version, spec, spec_sha256, code_git_sha, forward_from, frozen_at,
        authz_token_sha256) values (:v, :p, :m, :pv, cast(:sp as jsonb), :sh, :g, :f, :n, :a)"""),
        {"v": REVIEWER_VERSION, "p": SP.POLICY_VERSION, "m": MODEL_ID, "pv": PROMPT_VERSION,
         "sp": json.dumps(spec(), sort_keys=True), "sh": spec_sha256(), "g": code_git_sha,
         "f": forward_from, "n": now(), "a": fp})
    await s.commit()
    return {"status": "WRITTEN", "reviewer_version": REVIEWER_VERSION,
            "spec_sha256": spec_sha256(), "forward_from": str(forward_from)}


async def pending(s: AsyncSession, forward_from: _dt.date, limit: int = RUN_LIMIT) -> list[Any]:
    return (await s.execute(text("""select t.* from shadow_trade t
        where t.policy_version = :p and t.market_date >= :f
          and not exists (select 1 from llm_review r where r.trade_id = t.id
                          and r.reviewer_version = :v)
        order by t.market_date, t.signal_at, t.id limit :n"""),
        {"p": SP.POLICY_VERSION, "f": forward_from, "v": REVIEWER_VERSION,
         "n": limit})).all()


async def record(s: AsyncSession, r: dict[str, Any], *, fp: str, code_git_sha: str) -> None:
    await s.execute(text("""insert into llm_review (trade_id, reviewer_version, policy_version,
        market_date, strategy, instrument_key, is_placebo, model_id, model_version,
        prompt_version, prompt_sha256, packet, packet_sha256, n_evidence, response_raw, status,
        invalid_reason, verdict, reason_codes, evidence_ids, note, effective_verdict,
        latency_ms, code_git_sha, authz_token_sha256, created_at, mode) values
        (:ti, :v, :p, :d, :s, :k, :pl, :m, :mv, :pv, :ps, cast(:pk as jsonb), :pks, :ne, :rr,
         :st, :ir, :vd, :rc, :ei, :no, :ev, :la, :g, :a, :n, 'SHADOW')"""),
        {"ti": r["trade_id"], "v": REVIEWER_VERSION, "p": SP.POLICY_VERSION,
         "d": r["market_date"], "s": r["strategy"], "k": r["instrument_key"],
         "pl": r["is_placebo"], "m": MODEL_ID, "mv": r["model_version"], "pv": PROMPT_VERSION,
         "ps": r["prompt_sha256"], "pk": json.dumps(r["packet"], default=str, sort_keys=True),
         "pks": r["packet_sha256"], "ne": r["n_evidence"], "rr": r["response_raw"],
         "st": r["status"], "ir": r["invalid_reason"], "vd": r["verdict"],
         "rc": r["reason_codes"], "ei": r["evidence_ids"], "no": r["note"],
         "ev": r["effective_verdict"], "la": r["latency_ms"], "g": code_git_sha, "a": fp,
         "n": now()})


async def run(s: AsyncSession, model: NAI.Model, *, commit: bool, token: str | None,
              code_git_sha: str, limit: int = RUN_LIMIT) -> dict[str, Any]:
    """Review every pending shadow trade of the frozen policy from the reviewer's forward
    start. Counts only in the result (verdict mix); the outcome is never read here."""
    fp = authorize_write(token) if commit else None
    row = await reviewer_row(s)
    if commit and (row is None or row.spec_sha256 != spec_sha256()):
        raise ReviewRefused(f"{REVIEWER_VERSION} is not frozen with this code's spec")
    start = row.forward_from if row is not None else (FORWARD_FROM or _dt.date.min)
    trades = await pending(s, start, limit)
    out: list[dict[str, Any]] = []
    results = [await review_one(s, t, model) for t in trades]   # sequential: one session
    for r in results:
        if commit:
            await record(s, r, fp=fp, code_git_sha=code_git_sha)
        out.append(r)
    if commit:
        await s.commit()
    mix: dict[str, int] = {}
    for r in out:
        key = f"{r['status']}:{r['effective_verdict']}"
        mix[key] = mix.get(key, 0) + 1
    return {"reviewer_version": REVIEWER_VERSION, "reviewed": len(out), "mix": mix,
            "commit": commit}
