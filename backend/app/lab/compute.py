"""Strategy Lab daily build: for one session, read every family's trades (P1 shadow, the
paper book, the E5 forward picks, the E6 monitor), price their path on 1-minute bars, link
the news, classify each outcome, and roll them up per strategy with the day's reasons.
Read-only on every source table; it writes only the lab tables (store.py). Pure helpers live
in forensic.py; everything here is a loader or an assembler."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import pathlib
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import IST
from app.lab import forensic as F
from app.lab import registry as RG
from app.lab import switches as SW

LAB_VERSION = "lab-v1"
BASE_EQUITY = 1_000_000.0
NIFTY = "NSE_INDEX|Nifty 50"
P1_POLICY = "p1-shadow-v1"
E5_STRATEGY, E6_STRATEGY = "e5_ensemble", "e6_results_drift"
DESK_STRATEGY = "desk_llm_v1"
E5_NOTIONAL = 100_000.0          # app/paper/sim.py Config.order_value_inr (Rs 1 L per name)
E6_NOTIONAL = 100_000.0
E6_HOLD = 20                     # app/e6/monitor.py RULE hold_sessions
NEWS_BEFORE_H = 48
MAX_NEWS = 10


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def ist_at(d: _dt.date, hhmm: str) -> _dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return _dt.datetime(d.year, d.month, d.day, h, m, tzinfo=IST).astimezone(_dt.UTC)


def _j(x: Any) -> str:
    return json.dumps(x, default=str, sort_keys=True)


# ── shared loaders ───────────────────────────────────────────────────────────────
async def sessions(s: AsyncSession, a: _dt.date, b: _dt.date) -> list[_dt.date]:
    return list((await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date between :a and :b order by 1"""),
        {"a": a, "b": b})).scalars())


async def names(s: AsyncSession, keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    rows = (await s.execute(text("""select instrument_key, trading_symbol, name, sector
        from canon_instrument where instrument_key = any(:k)"""), {"k": keys})).all()
    return {r.instrument_key: {"symbol": r.trading_symbol, "name": r.name, "sector": r.sector}
            for r in rows}


async def bars_1m(s: AsyncSession, keys: list[str], day: _dt.date) -> dict[str, list[F.Bar]]:
    if not keys:
        return {}
    rows = (await s.execute(text("""select instrument_key, bar_start_utc, event_end, high, low,
        close, open from canon_market_bar where timeframe = '1m' and market_date = :d
          and instrument_key = any(:k) order by instrument_key, bar_start_utc"""),
        {"d": day, "k": keys})).all()
    out: dict[str, list[F.Bar]] = defaultdict(list)
    for r in rows:
        if r.high is None or r.low is None or r.close is None:
            continue
        out[r.instrument_key].append(F.Bar(r.bar_start_utc, r.event_end, float(r.high),
                                           float(r.low), float(r.close),
                                           _f(r.open)))
    return out


async def bars_1d(s: AsyncSession, keys: list[str], days: list[_dt.date]
                  ) -> dict[tuple[str, _dt.date], dict[str, float]]:
    if not keys or not days:
        return {}
    rows = (await s.execute(text("""select instrument_key, market_date, open, close
        from canon_market_bar where timeframe = '1d' and market_date = any(:d)
          and instrument_key = any(:k)"""), {"d": days, "k": keys})).all()
    return {(r.instrument_key, r.market_date): {"open": _f(r.open), "close": _f(r.close)}
            for r in rows}


async def news(s: AsyncSession, keys: list[str], t0: _dt.datetime, t1: _dt.datetime,
               *, by_knowable: bool) -> dict[str, list[dict[str, Any]]]:
    """News linked to each name. by_knowable=False: published (or knowable) in [t0, t1] and
    knowable by t1 (the news before a signal). True: became knowable in (t0, t1] (news that
    arrived during a trade). Each item carries its AI fields when they existed by then."""
    if not keys:
        return {}
    cond = ("greatest(l.knowable_at, i.knowable_at) > :a and greatest(l.knowable_at, "
            "i.knowable_at) <= :b") if by_knowable else \
        ("l.knowable_at <= :b and i.knowable_at <= :b and "
         "coalesce(i.published_at, i.knowable_at) >= :a")
    rows = (await s.execute(text(f"""select l.instrument_key, i.id, i.source, i.title, i.url,
            i.published_at, greatest(l.knowable_at, i.knowable_at) as knowable_at,
            e.output as ai
        from news_entity_link l join news_item i on i.id = l.item_id
        left join lateral (select output from news_ai_enrichment x where x.item_id = i.id
            and x.status = 'OK' and x.knowable_at <= :b order by x.knowable_at desc limit 1) e
            on true
        where l.instrument_key = any(:k) and {cond}
        order by l.instrument_key, coalesce(i.published_at, i.knowable_at) desc"""),  # noqa: S608
        {"k": keys, "a": t0, "b": t1})).all()
    out: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for r in rows:
        if (r.instrument_key, r.id) in seen or len(out[r.instrument_key]) >= MAX_NEWS:
            continue
        seen.add((r.instrument_key, r.id))
        ai = r.ai or {}
        out[r.instrument_key].append({
            "id": r.id, "source": r.source, "title": r.title, "url": r.url,
            "published_at": r.published_at, "knowable_at": r.knowable_at,
            "event_type": ai.get("event_type"), "impact": ai.get("potential_impact"),
            "direction": ai.get("impact_direction"), "summary": ai.get("summary")})
    return out


def lag_minutes(signal_at: _dt.datetime | None, items: list[dict]) -> float | None:
    if signal_at is None or not items:
        return None
    t = items[0]["published_at"] or items[0]["knowable_at"]
    return round((signal_at - t).total_seconds() / 60, 1) if t else None


# ── family loaders: each returns (trades, context) ──────────────────────────────────
async def p1(s: AsyncSession, day: _dt.date) -> tuple[list[dict], dict[str, Any]]:
    run = (await s.execute(text("""select run_id, status, reason, counts from shadow_run
        where policy_version = :v and market_date = :d"""), {"v": P1_POLICY, "d": day})).first()
    if run is None:
        return [], {"run": None}
    snaps = {r.checkpoint: {"state": r.state, "rule": r.rule_fired, "day_type": r.day_type,
                            "mult": r.risk_mult, "features": r.features}
             for r in (await s.execute(text("""select checkpoint, state, rule_fired, day_type,
                 risk_mult, features from regime_snapshot where run_id = :r"""),
                 {"r": run.run_id})).all()}
    skips: dict[str, Counter] = defaultdict(Counter)
    for r in (await s.execute(text("""select strategy, reason, count(*) n from shadow_skip
            where run_id = :r group by 1, 2"""), {"r": run.run_id})).all():
        skips[r.strategy][r.reason] += r.n
    rows = (await s.execute(text("""select t.*, v.effective_verdict, v.reason_codes, v.note
        from shadow_trade t left join lateral (select effective_verdict, reason_codes, note
            from llm_review x where x.trade_id = t.id order by x.created_at desc limit 1) v
            on true
        where t.run_id = :r order by t.strategy, t.is_placebo, t.entry_at"""),
        {"r": run.run_id})).mappings().all()
    trades = []
    for x in rows:
        charges = sum(float(v) for v in (x["charges"] or {}).values())
        trades.append({
            "strategy": x["strategy"], "family": "P1", "source": "shadow_trade",
            "source_id": str(x["id"]), "instrument_key": x["instrument_key"],
            "side": x["side"], "is_placebo": x["is_placebo"], "signal_at": x["signal_at"],
            "entry_at": x["entry_at"], "exit_at": x["exit_at"], "entry_px": _f(x["entry_px"]),
            "exit_px": _f(x["exit_px"]), "stop": _f(x["stop"]), "target": _f(x["target"]),
            "qty": x["qty"], "gross_inr": _f(x["gross_inr"]), "charges_inr": charges,
            "net_inr": _f(x["net_inr"]), "net_r": x["net_r"], "exit_reason": x["exit_reason"],
            "regime_state": x["regime_state"], "day_type": x["day_type"],
            "ai_verdict": x["effective_verdict"], "sector": x["sector"],
            "plan": {"entry_raw": _f(x["entry_raw"]), "exit_raw": _f(x["exit_raw"]),
                     "time_stop": x["time_stop"], "atr": x["atr"], "rrr": x["rrr"],
                     "risk_inr": _f(x["risk_inr"]), "size_factor": x["size_factor"],
                     "risk_mult": x["risk_mult"], "checklist": x["checklist"],
                     "checklist_score": x["checklist_score"], "evidence": x["evidence"],
                     "by_slippage": x["by_slippage"], "guard_flags": list(x["guard_flags"] or []),
                     "ai_reasons": list(x["reason_codes"] or []), "ai_note": x["note"]}})
    return trades, {"run": str(run.run_id), "status": run.status, "reason": run.reason,
                    "counts": run.counts, "snaps": snaps,
                    "skips": {k: dict(v) for k, v in skips.items()}}


async def paper(s: AsyncSession, day: _dt.date) -> tuple[list[dict], dict[str, Any]]:
    runs = (await s.execute(text("""select r.run_id, r.strategy, r.target_list, r.config,
            d.targets, d.filled, d.start_cash_inr, d.end_cash_inr, d.pnl_inr, d.charges_inr
        from paper_run r left join paper_day d on d.run_id = r.run_id
        where r.session_date = :d"""), {"d": day})).mappings().all()
    trades, ctx = [], {}
    for r in runs:
        tl = {e["key"]: e for e in ((r["target_list"] or {}).get("entries") or [])}
        rej = Counter(x.reason for x in (await s.execute(text("""select reason from
            paper_risk_decision where run_id = :r and decision = 'REJECTED'"""),
            {"r": r["run_id"]})).all())
        ctx[r["strategy"]] = {"run": str(r["run_id"]), "targets": r["targets"],
                              "filled": r["filled"], "end_cash": _f(r["end_cash_inr"]),
                              "start_cash": _f(r["start_cash_inr"]), "rejected": dict(rej),
                              "rule": ((r["target_list"] or {}).get("meta") or {}).get("rule")}
        for f in (await s.execute(text("""select id, instrument_key, status, reason, qty,
                buy_px, sell_px, charges, pnl_inr from paper_fill where run_id = :r"""),
                {"r": r["run_id"]})).mappings().all():
            ch = sum(float(v) for v in (f["charges"] or {}).values())
            pnl = _f(f["pnl_inr"])
            e = tl.get(f["instrument_key"], {})
            filled = f["status"] != "NOT_FILLED"
            trades.append({
                "strategy": r["strategy"], "family": "PAPER", "source": "paper_fill",
                "source_id": str(f["id"]), "instrument_key": f["instrument_key"], "side": 1,
                "is_placebo": False, "signal_at": ist_at(day, "09:15"),
                "entry_at": ist_at(day, "09:15") if filled else None,
                "exit_at": ist_at(day, "15:30") if filled else None,
                "entry_px": _f(f["buy_px"]), "exit_px": _f(f["sell_px"]), "stop": None,
                "target": None, "qty": f["qty"], "gross_inr": (pnl or 0) + ch if filled else 0.0,
                "charges_inr": ch, "net_inr": pnl, "net_r": None,
                "exit_reason": "CLOSE" if filled else "NOT_FILLED", "regime_state": None,
                "day_type": None, "ai_verdict": None, "sector": None,
                "plan": {"rank": e.get("rank"), "score": e.get("score"),
                         "rule": ctx[r["strategy"]]["rule"], "fill_status": f["status"],
                         "fill_reason": f["reason"]}})
    return trades, ctx


async def e5(s: AsyncSession, day: _dt.date) -> tuple[list[dict], dict[str, Any]]:
    from app.shadow import fill as SF
    rows = (await s.execute(text("""select id, instrument_key, prob_up, exp_return, range_lo,
            range_hi, volatility, confidence, score, rank, predicted_at
        from model_prediction where session_date = :d and selected order by rank"""),
        {"d": day})).mappings().all()
    if not rows:
        return [], {}
    px = await bars_1d(s, [r["instrument_key"] for r in rows], [day])
    trades = []
    for r in rows:
        b = px.get((r["instrument_key"], day)) or {}
        o, c = b.get("open"), b.get("close")
        qty = int(E5_NOTIONAL // o) if o else 0
        st = SF.settle(1, qty, o, c, 0.0) if o and c and qty else None
        trades.append({
            "strategy": E5_STRATEGY, "family": "E5", "source": "model_prediction",
            "source_id": str(r["id"]), "instrument_key": r["instrument_key"], "side": 1,
            "is_placebo": False, "signal_at": r["predicted_at"],
            "entry_at": ist_at(day, "09:15") if st else None,
            "exit_at": ist_at(day, "15:30") if st else None,
            "entry_px": st["entry_px"] if st else None, "exit_px": st["exit_px"] if st else None,
            "stop": None, "target": None, "qty": qty,
            "gross_inr": st["gross_inr"] if st else 0.0,
            "charges_inr": sum(st["charges"].values()) if st else 0.0,
            "net_inr": st["net_inr"] if st else None, "net_r": None,
            "exit_reason": "CLOSE" if st else "NOT_FILLED", "regime_state": None,
            "day_type": None, "ai_verdict": None, "sector": None,
            "plan": {k: _f(r[k]) for k in ("prob_up", "exp_return", "range_lo", "range_hi",
                                            "volatility", "confidence", "score")}
            | {"rank": r["rank"]}})
    return trades, {"picks": len(rows)}


def e6_rows(directory: pathlib.Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted((directory / "signals").glob("*.jsonl")) if directory.exists() else []:
        for line in f.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


async def e6(s: AsyncSession, day: _dt.date, directory: pathlib.Path | None = None
             ) -> tuple[list[dict], dict[str, Any]]:
    """E6 positions open on `day` (PICK; CONTROL rows are its comparison group, shown as
    placebo). Entry at the entry day's open, exit at the close of the 20th session; between
    the two the position is marked at the day's close."""
    if directory is None:
        from app.e6 import monitor as EM
        directory = pathlib.Path(EM.DIR)
    rows = [r for r in e6_rows(directory) if r.get("cls") in ("PICK", "CONTROL")]
    if not rows:
        return [], {"open": 0}
    first = min(_dt.date.fromisoformat(r["entry_day"]) for r in rows)
    axis = await sessions(s, first, day)
    trades = []
    for r in rows:
        ed = _dt.date.fromisoformat(r["entry_day"])
        if ed > day or ed not in axis:
            continue
        i = axis.index(ed)
        held = axis[i:i + E6_HOLD]
        if day not in held:
            continue
        b = await bars_1d(s, [r["key"]], [ed, day])
        o = (b.get((r["key"], ed)) or {}).get("open")
        c = (b.get((r["key"], day)) or {}).get("close")
        qty = int(E6_NOTIONAL // o) if o else 0
        last = len(held) == E6_HOLD and day == held[-1]
        net = (c - o) * qty if o and c else None
        trades.append({
            "strategy": E6_STRATEGY, "family": "E6", "source": "e6_signal",
            "source_id": f"{r['key']}|{r['entry_day']}", "instrument_key": r["key"], "side": 1,
            "is_placebo": r["cls"] == "CONTROL", "signal_at": _dt.datetime.fromisoformat(
                r["event_at"]), "entry_at": ist_at(ed, "09:15"),
            "exit_at": ist_at(day, "15:30") if last else None, "entry_px": o, "exit_px": c,
            "stop": None, "target": None, "qty": qty, "gross_inr": net or 0.0,
            "charges_inr": 0.0, "net_inr": net, "net_r": None,
            "exit_reason": "CLOSE" if last else "OPEN_POSITION", "regime_state": None,
            "day_type": None, "ai_verdict": None, "sector": None,
            "plan": {"cls": r["cls"], "car01": r.get("car01"), "event_at": r["event_at"],
                     "day0": r.get("day0"), "entry_day": r["entry_day"],
                     "session_n": held.index(day) + 1, "hold": E6_HOLD,
                     "note": "marked to market, charges at exit not included"}})
    return trades, {"open": sum(1 for t in trades if not t["is_placebo"])}


async def desk(s: AsyncSession, day: _dt.date) -> tuple[list[dict], dict[str, Any]]:
    """Research Desk suggestions closed on `day` (desk_llm_v1): entry at the quote that
    triggered the entry zone; the whole position exits at the first of T1, the stop or the
    intraday expiry (booking at T1 keeps the record simple and conservative); MIS costs."""
    from app.shadow import fill as SF
    try:
        rows = (await s.execute(text("""select v.id, v.instrument_key, v.symbol, v.decision,
                v.score, v.horizon, v.entry_lo, v.entry_hi, v.stop, v.t1, v.t2, v.conflicts,
                v.rule_decision, v.created_at,
                (select json_agg(json_build_object('kind', t.kind, 'price', t.price, 'at', t.at)
                        order by t.at) from desk_track_event t where t.verdict_id = v.id) ev
            from desk_verdict v where exists (select 1 from desk_track_event t
                where t.verdict_id = v.id and t.kind = 'ENTRY_TRIGGERED')"""))).mappings().all()
    except Exception:
        await s.rollback()
        return [], {}
    trades = []
    for r in rows:
        ev = {e["kind"]: e for e in (r["ev"] or [])}
        en = ev["ENTRY_TRIGGERED"]
        ex = min((ev[k] for k in ("T1", "STOP", "EXPIRED") if k in ev),
                 key=lambda e: e["at"], default=None)
        if ex is None:
            continue
        ex_at = _dt.datetime.fromisoformat(str(ex["at"]))
        if ex_at.astimezone(IST).date() != day:
            continue
        ep, xp = float(en["price"]), float(ex["price"])
        qty = int(E5_NOTIONAL // ep) if ep else 0
        st = SF.settle(1, qty, ep, xp, 0.0) if qty else None
        reason = {"T1": "TARGET", "STOP": "STOP", "EXPIRED": "EOD"}[ex["kind"]]
        trades.append({
            "strategy": DESK_STRATEGY, "family": "DESK", "source": "desk_verdict",
            "source_id": str(r["id"]), "instrument_key": r["instrument_key"], "side": 1,
            "is_placebo": False, "signal_at": r["created_at"],
            "entry_at": _dt.datetime.fromisoformat(str(en["at"])), "exit_at": ex_at,
            "entry_px": st["entry_px"] if st else ep, "exit_px": st["exit_px"] if st else xp,
            "stop": _f(r["stop"]), "target": _f(r["t1"]), "qty": qty,
            "gross_inr": st["gross_inr"] if st else 0.0,
            "charges_inr": sum(st["charges"].values()) if st else 0.0,
            "net_inr": st["net_inr"] if st else None,
            "net_r": (xp - ep) / (ep - float(r["stop"])) if r["stop"] and ep > float(r["stop"])
            else None, "exit_reason": reason, "regime_state": None, "day_type": None,
            "ai_verdict": r["decision"], "sector": None,
            "plan": {"decision": r["decision"], "score": r["score"], "horizon": r["horizon"],
                     "entry_zone": [_f(r["entry_lo"]), _f(r["entry_hi"])], "t2": _f(r["t2"]),
                     "conflicts": list(r["conflicts"] or []), "rule_decision": r["rule_decision"],
                     "events": r["ev"]}})
    return trades, {"closed": len(trades)}


# ── assembly ─────────────────────────────────────────────────────────────────────
async def enrich(s: AsyncSession, day: _dt.date, trades: list[dict]) -> None:
    """Path, news and outcome class for every trade (in place)."""
    keys = sorted({t["instrument_key"] for t in trades})
    meta = await names(s, keys)
    m1 = await bars_1m(s, [*keys, NIFTY], day)
    nifty = m1.get(NIFTY, [])
    t_open = ist_at(day, "09:15")
    before = await news(s, keys, t_open - _dt.timedelta(hours=NEWS_BEFORE_H),
                        ist_at(day, "15:30"), by_knowable=False)
    during = await news(s, keys, t_open, ist_at(day, "15:30"), by_knowable=True)
    for t in trades:
        k = t["instrument_key"]
        t["symbol"] = (meta.get(k) or {}).get("symbol")
        t["sector"] = t["sector"] or (meta.get(k) or {}).get("sector")
        sig = t["signal_at"] or t_open
        t["news_before"] = [n for n in before.get(k, [])
                            if (n["knowable_at"] or sig) <= sig]
        ent, ext = t["entry_at"], t["exit_at"] or ist_at(day, "15:30")
        t["news_after"] = [n for n in during.get(k, [])
                           if ent is not None and ent < n["knowable_at"] <= ext]
        t["first_news_lag_min"] = lag_minutes(sig, t["news_before"])
        if t["family"] == "E6" and ent is not None:      # results event -> entry
            t["first_news_lag_min"] = round((ent - t["signal_at"]).total_seconds() / 60, 1)
        path = F.excursion(m1.get(k, []), t["side"], t["entry_px"] or 0.0, ent, ext,
                           t["stop"], t["target"]) if ent else {}
        mv = F.index_move(nifty, ent, ext) if ent else None
        t["path"] = {**path, "index_move": mv}
        t["mfe_pct"], t["mae_pct"] = path.get("mfe_pct"), path.get("mae_pct")
        t["mfe_r"], t["mae_r"] = path.get("mfe_r"), path.get("mae_r")
        t["target_after_exit"] = path.get("target_after_exit")
        t["outcome_class"], t["outcome_rule"] = F.classify({**t, "index_move": mv})


def _net(t: dict) -> float:
    return t["net_inr"] or 0.0


async def prior_equity(s: AsyncSession, strategy: str, day: _dt.date) -> tuple[float, float]:
    """(equity, peak) after the strategy's last session before `day` (latest lab run)."""
    rows = (await s.execute(text("""select distinct on (d.session_date) d.equity_inr
        from strategy_day d join lab_run r using (run_id)
        where d.strategy = :s and d.session_date < :d
        order by d.session_date, r.created_at desc"""), {"s": strategy, "d": day})).scalars()
    eq = [float(x) for x in rows]
    if not eq:
        return BASE_EQUITY, BASE_EQUITY
    return eq[-1], max([BASE_EQUITY, *eq])


async def grade_buylist(s: AsyncSession, day: _dt.date) -> dict | None:
    """The day's Buy List (the last brief published before 09:15) graded as intraday trades
    on the 1-minute path (app/lab/buylist.grade_one)."""
    from app.lab import buylist as BL
    row = (await s.execute(text("""select b.candidates from daily_brief b join lab_run r
        using (run_id) where b.session_date = :d and r.created_at < :o
        order by r.created_at desc limit 1"""), {"d": day, "o": ist_at(day, "09:15")})).first()
    items = (row.candidates.get("BUYLIST") or []) if row else []
    if not items:
        return None
    m1 = await bars_1m(s, [x["key"] for x in items], day)
    grades = [BL.grade_one(x, m1.get(x["key"], []), day) for x in items]
    sm = BL.summary(grades)
    if not sm.get("graded"):
        return None
    return {"strategy": "_BUYLIST", "thought": {"picks": len(items), "items": items},
            "happened": {"grades": grades, "summary": sm},
            "why": [{"code": "BUYLIST_GRADE",
                     "en": f"{sm['profitable']} of {sm['graded']} picks profitable after costs "
                           f"(T1 hit {sm['t1_hit']}, stopped {sm['stopped']}, closed at 15:15 "
                           f"{sm['eod']}); average {sm['avg_net_pct']:+.2%} per pick.",
                     "hi": f"{sm['graded']} mein se {sm['profitable']} picks kharche ke baad "
                           f"fayde mein (T1 {sm['t1_hit']}, stop {sm['stopped']}, 15:15 par "
                           f"band {sm['eod']}); average {sm['avg_net_pct']:+.2%} per pick."}]}


async def grade_brief(s: AsyncSession, day: _dt.date, trades: list[dict]) -> dict | None:
    """Yesterday-evening check of the morning brief: did each suggested name trigger its
    strategy (a P1 trade on it), and how did the stock move open -> close."""
    row = (await s.execute(text("""select b.candidates from daily_brief b join lab_run r
        using (run_id) where b.session_date = :d order by r.created_at desc limit 1"""),
        {"d": day})).first()
    if row is None:
        return None
    base = {"S1": "orb_breadth", "S2": "vwap_revert"}
    traded = {(t["instrument_key"], t["strategy"].rsplit("_", 2)[0]) for t in trades
              if t["family"] == "P1" and not t["is_placebo"]}
    cands = [c for k in ("S1", "S2") for c in (row.candidates.get(k) or [])]
    px = await bars_1d(s, [c["key"] for c in cands], [day])
    out = []
    for c in cands:
        b = px.get((c["key"], day)) or {}
        oc = None if not b.get("open") or b.get("close") is None else b["close"] / b["open"] - 1
        out.append({"symbol": c.get("symbol"), "strategy": c["strategy"], "side": c["side"],
                    "triggered": (c["key"], base[c["strategy"]]) in traded,
                    "open_to_close": oc,
                    "right_way": None if oc is None else (oc * c["side"] > 0)})
    n = [x for x in out if x["right_way"] is not None]
    return {"strategy": "_BRIEF", "thought": {"candidates": len(cands)},
            "happened": {"grades": out},
            "why": [{"code": "BRIEF_GRADE",
                     "en": f"{sum(x['triggered'] for x in out)} of {len(out)} suggestions "
                           f"triggered; {sum(1 for x in n if x['right_way'])} of {len(n)} "
                           "moved the suggested way open to close.",
                     "hi": f"{len(out)} mein se {sum(x['triggered'] for x in out)} suggestions "
                           f"trigger hue; {len(n)} mein se {sum(1 for x in n if x['right_way'])} "
                           "open se close sahi disha mein chale."}]}


async def build(s: AsyncSession, day: _dt.date, *, e6_dir: pathlib.Path | None = None
                ) -> dict[str, Any]:
    """Everything the lab stores for one session (nothing written here)."""
    p1t, p1c = await p1(s, day)
    pat, pac = await paper(s, day)
    e5t, _ = await e5(s, day)
    e6t, _ = await e6(s, day, e6_dir)
    dkt, _ = await desk(s, day)
    trades = p1t + pat + e5t + e6t + dkt
    await enrich(s, day, trades)
    sw = await SW.current(s)
    snaps = p1c.get("snaps") or {}
    pre, opn = snaps.get("PRE") or {}, snaps.get("OPEN") or {}
    last_cp = next((snaps[c] for c in ("1330", "1200", "1030", "0930") if c in snaps), {})
    day_type = last_cp.get("day_type")
    days: list[dict] = []
    forensics: list[dict] = []
    by: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by[t["strategy"]].append(t)
    present = set(by) | ({x for x in RG.P1} if p1c.get("run") else set()) | set(pac)
    for name in [x.name for x in RG.STRATEGIES if x.name in present]:
        meta = RG.BY_NAME[name]
        ts = by.get(name, [])
        real = [t for t in ts if not t["is_placebo"] and t["exit_reason"] != "NOT_FILLED"]
        plc = [t for t in ts if t["is_placebo"]]
        net = sum(t["net_inr"] or 0.0 for t in real)
        eq0, peak = await prior_equity(s, name, day)
        # the paper book restarts each session at its capital (paper_day.start_cash), so
        # its end_cash is that day's result, not the running equity: all families chain
        if meta.family == "E6":
            eq = BASE_EQUITY + net          # marked open positions, not cumulative
        else:
            eq = eq0 + net
        peak = max(peak, eq)
        skips = (p1c.get("skips") or {}).get(name) or (pac.get(name) or {}).get("rejected") or {}
        on = sw.get(name, {}).get("enabled") if meta.switchable else None
        if meta.family == "P1" and "SWITCHED_OFF" in skips:
            on = False
        pnet = sum(t["net_inr"] or 0.0 for t in plc) if plc else None
        why = F.day_why(name, ts, regime_pre=pre.get("state") if meta.family == "P1" else None,
                        day_type=day_type if meta.family == "P1" else None, skips=skips,
                        placebo_net=pnet, enabled=on if meta.family == "P1" else True)
        days.append({
            "strategy": name, "family": meta.family, "enabled": on, "trades": len(real),
            "wins": sum(1 for t in real if (t["net_inr"] or 0) > 0),
            "losses": sum(1 for t in real if (t["net_inr"] or 0) <= 0),
            "gross_inr": sum(t["gross_inr"] or 0.0 for t in real),
            "charges_inr": sum(t["charges_inr"] or 0.0 for t in real), "net_inr": net,
            "net_r": sum(t["net_r"] for t in real if t["net_r"] is not None)
            if meta.family == "P1" else None,
            "placebo_trades": len(plc) if meta.family in ("P1", "E6") else None,
            "placebo_net_inr": pnet, "regime_pre": pre.get("state"),
            "regime_open": opn.get("state"), "day_type": day_type, "equity_inr": eq,
            "drawdown": (peak - eq) / peak if peak else 0.0,
            "detail": {"classes": dict(Counter(t["outcome_class"] for t in real)),
                       "skips": skips, "counts": (p1c.get("counts") or {}).get(name)
                       or {k: v for k, v in (pac.get(name) or {}).items()
                           if k in ("targets", "filled", "rule")},
                       "best": max(real, key=_net)["symbol"] if real else None,
                       "worst": min(real, key=_net)["symbol"] if real else None}})
        forensics.append({
            "strategy": name,
            "thought": {"tool": meta.tool, "title": meta.title, "regime_pre": pre.get("state"),
                        "regime_rule": pre.get("rule"), "regime_open": opn.get("state"),
                        "counts": (p1c.get("counts") or {}).get(name)
                        or (pac.get(name) or {}), "enabled": on,
                        "candidates": [{"symbol": t["symbol"], "side": t["side"],
                                        "entry": t["entry_px"], "stop": t["stop"],
                                        "target": t["target"],
                                        "plan_rrr": (t["plan"] or {}).get("rrr"),
                                        "rank": (t["plan"] or {}).get("rank")}
                                       for t in ts if not t["is_placebo"]]},
            "happened": {"day_type": day_type, "nifty_from_open": (last_cp.get("features") or {})
                         .get("nifty_from_open"),
                         "trades": [{"symbol": t["symbol"], "class": t["outcome_class"],
                                     "net_inr": t["net_inr"], "exit_reason": t["exit_reason"]}
                                    for t in real]},
            "why": why})
    market = {"strategy": "_MARKET",
              "thought": {"regime_pre": pre, "regime_open": opn},
              "happened": {"checkpoints": {c: {"state": v["state"], "day_type": v["day_type"],
                                               "features": v["features"]}
                                           for c, v in snaps.items()}},
              "why": []}
    if snaps:
        forensics.append(market)
    graded = await grade_brief(s, day, trades)
    if graded:
        forensics.append(graded)
    bl = await grade_buylist(s, day)
    if bl:
        forensics.append(bl)
    sha = hashlib.sha256(_j([LAB_VERSION, trades, days, forensics]).encode()).hexdigest()
    return {"session": day, "trades": trades, "days": days, "forensics": forensics,
            "inputs_sha256": sha,
            "counts": {"P1": len(p1t), "PAPER": len(pat), "E5": len(e5t), "E6": len(e6t),
                       "DESK": len(dkt),
                       "strategies": len(days)}}
