"""E5 forward test (docs/STAGE4_E5_PREREGISTRATION.md): freeze, daily prediction, operational
status and the single confirmatory look. PAPER ONLY - nothing here places an order.

  freeze   fits the recipe on the latest TRAIN_SESSIONS labelled sessions of the training
           dataset, stores the artefact (var/models/<sha>/bundle.pkl, its sha256) and a
           model_version row (purpose FORWARD_TEST). Refuses a dirty tree and a second
           FORWARD_TEST model (the confirmatory test has one frozen model)
  predict  at the PRE_SESSION snapshot of a session: the production Stage 3 features of the
           session and of the 9 sessions before it (LSTM history), today's known results
           meetings (results_pit), the outputs and the hybrid selection; written before the
           open (CHECK predicted_at < deadline_at = the session's open)
  status   counts only (sessions predicted, rows, picks, late or missing days): never a
           performance number before the look
  report   the single look, once FORWARD_SESSIONS sessions have predictions and outcomes:
           outcomes from the canonical daily bars (open -> close of the session; a missing
           or locked bar, high == low, is not evaluable), the E5 metrics, the book and the
           acceptance gates A1-A4. A ledger refuses a second look
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import pickle
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import authorize_write
from app.core.clock import IST, now
from app.models import data as D
from app.models import evaluate as EV
from app.models import recipe as R

ROOT = pathlib.Path(__file__).resolve().parents[2]
ART = ROOT / "var/models"
LEDGER = ROOT / "var/stage4/experiments/e5/forward_ledger.jsonl"
FORWARD_SESSIONS = 40
SNAPSHOT = "PRE_SESSION"


class Refused(RuntimeError):
    pass


def _sha_file(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── freeze ──────────────────────────────────────────────────────────────────────────
async def freeze(s: AsyncSession, *, commit: bool = False, token: str | None = None,
                 through: _dt.date | None = None, allow_dirty: bool = False) -> dict[str, Any]:
    from app.training.replay import code_version
    code = code_version()
    if code["dirty"] and not allow_dirty:
        raise Refused("the working tree is dirty; commit first (the model records its code)")
    fp = authorize_write(token) if commit else None
    if commit and (await s.execute(text("""select model_sha256 from model_version
            where purpose = 'FORWARD_TEST'"""))).first():
        raise Refused("a FORWARD_TEST model exists; the confirmatory test has one model")
    days = [d for d in await D.training_sessions(s) if through is None or d <= through]
    panel = []
    for d in days[-(R.TRAIN_SESSIONS + D.SEQ_LEN):]:
        sess = await D.training_session(s, d)
        if sess is not None:
            panel.append(sess)
    labelled = [t for t, p in enumerate(panel) if not np.isnan(p.y["ret_oc"]).all()]
    train = labelled[-R.TRAIN_SESSIONS:]
    b = R.fit(panel, train)
    sha = b.sha256()
    out: dict[str, Any] = {"commit": commit, "model_sha256": sha, "recipe": R.VERSION,
                           "trained": [str(panel[train[0]].date), str(panel[train[-1]].date)],
                           "sessions": len(train), "rows": b.meta["rows"],
                           "round_trip_cost": b.cost, "code": code}
    if not commit:
        return out
    d = ART / sha
    d.mkdir(parents=True, exist_ok=True)
    path = d / "bundle.pkl"
    path.write_bytes(pickle.dumps(b, protocol=5))
    out["artefact_sha256"] = _sha_file(path)
    (d / "bundle.pkl.sha256").write_text(out["artefact_sha256"] + "\n")
    cfg = {"recipe": R.VERSION, "seed": R.SEED, "k": R.K, "capital_inr": R.CAPITAL_INR,
           "train_sessions": R.TRAIN_SESSIONS, "lgbm": R.LGBM, "rf": R.RF, "lstm": R.LSTM,
           "ridge_alpha": R.RIDGE_ALPHA, "winsor": R.WINSOR, "universe_top": D.UNIVERSE_TOP,
           "min_price": D.MIN_PRICE, "seq_len": D.SEQ_LEN, "core": list(D.CORE),
           "forward_sessions": FORWARD_SESSIONS, "dataset": D.TRAIN_DATASET,
           "labels": D.TRAIN_LABELS, "round_trip_cost": b.cost}
    await s.execute(text("""insert into model_version (model_sha256, recipe, purpose,
        trained_from, trained_to, train_sessions, train_rows, artefact_path, artefact_sha256,
        code_git_sha, config, created_at, authz_token_sha256) values (:m, :r, 'FORWARD_TEST',
        :a, :b, :n, :rows, :p, :ps, :g, cast(:c as jsonb), :t, :fp)"""),
        {"m": sha, "r": R.VERSION, "a": panel[train[0]].date, "b": panel[train[-1]].date,
         "n": len(train), "rows": b.meta["rows"], "p": str(path.relative_to(ROOT)),
         "ps": out["artefact_sha256"], "g": code["git_sha"], "c": json.dumps(cfg), "t": now(),
         "fp": fp})
    await s.commit()
    return out


async def load_model(s: AsyncSession, sha: str | None = None) -> tuple[str, R.Bundle]:
    row = (await s.execute(text("""select model_sha256, artefact_path, artefact_sha256
        from model_version where (cast(:m as text) is null and purpose = 'FORWARD_TEST')
           or model_sha256 = :m order by id desc limit 1"""), {"m": sha})).first()
    if row is None:
        raise Refused("no FORWARD_TEST model (run `prajna models freeze --commit`)")
    path = ROOT / row.artefact_path
    if _sha_file(path) != row.artefact_sha256:
        raise Refused(f"artefact {path} does not match its recorded sha256")
    b = pickle.loads(path.read_bytes())  # noqa: S301 - our own artefact, sha256-verified
    if b.sha256() != row.model_sha256:
        raise Refused("the artefact's content hash differs from model_version")
    return row.model_sha256, b


# ── predict (daily, before the open) ────────────────────────────────────────────────
async def _previous_sessions(s: AsyncSession, day: _dt.date, n: int) -> list[_dt.date]:
    return list(reversed((await s.execute(text("""select session_date from trading_session
        where is_trading_day and session_date < :d and open_ist is not null
        order by session_date desc limit :n"""), {"d": day, "n": n})).scalars().all()))


async def predict_live(s: AsyncSession, day: _dt.date, *, commit: bool = False,
                       token: str | None = None, model: str | None = None) -> dict[str, Any]:
    from app.canon import results_pit as RP
    from app.features.compute import results as RS
    from app.features.snapshots import resolve

    fp = authorize_write(token) if commit else None
    snap = await resolve(s, day, SNAPSHOT)
    cal = (await s.execute(text("select open_ist from trading_session where session_date = :d"),
                           {"d": day})).first()
    deadline = _dt.datetime.combine(day, cal.open_ist, tzinfo=IST)
    sha, b = await load_model(s, model)
    cur = await D.live_session(s, day)
    if cur is None:
        raise Refused(f"no Stage 3 {SNAPSHOT} features for {day} yet")
    # Every previous session keeps its position in the LSTM sequence: one without usable
    # values (no Stage 3 run, or values of an older feature version - 2026-10-08, before
    # the price-basis versions) is an absent session, not dropped (that would shift the
    # older ones one place nearer to today).
    hist, missing = [], []
    for d in await _previous_sessions(s, day, D.SEQ_LEN - 1):
        x = await D.live_session(s, d)
        if x is None:
            missing.append(str(d))
            x = D.empty_session(d)
        hist.append(x)
    panel = [*hist, cur]
    out = R.predict(b, panel, len(panel) - 1)
    evs = await RP.events(s, snap.as_of)
    cov = await RP.coverage_from(s, snap.as_of)
    today = {k for k, v in evs.items() if RS.today(v, day, cov, snap.as_of) == (1.0, None)}
    picks = R.select(out, b.cost, results_today=today)
    order = sorted(range(len(out["keys"])), key=lambda j: (-out["score"][j], out["keys"][j]))
    rank = {j: i + 1 for i, j in enumerate(order)}
    inputs = hashlib.sha256(json.dumps([[str(p.date), p.keys, p.X.round(12).tolist()]
                                        for p in panel]).encode()).hexdigest()
    res: dict[str, Any] = {"commit": commit, "session": str(day), "model_sha256": sha,
                           "universe": len(out["keys"]),
                           "history_sessions": len(hist) - len(missing),
                           "history_expected": D.SEQ_LEN - 1, "history_missing": missing,
                           "results_today_excluded": len(today & set(out["keys"])),
                           "picks": [out["keys"][j] for j in picks],
                           "deadline_at": deadline.isoformat(), "inserted": 0}
    if not commit:
        return res
    at = now()
    if at >= deadline:
        raise Refused(f"past the deadline {deadline.isoformat()}: a late prediction is not "
                      "written (the forward test would no longer be point in time)")
    sel = set(picks)
    rows = [{"m": sha, "d": day, "sn": SNAPSHOT, "k": out["keys"][j],
             "p": float(out["prob_up"][j]), "e": float(out["exp_return"][j]),
             "lo": float(out["range_lo"][j]), "hi": float(out["range_hi"][j]),
             "v": float(out["volatility"][j]), "c": float(out["confidence"][j]),
             "sc": float(out["score"][j]), "r": rank[j], "sel": j in sel, "fa": snap.as_of,
             "ih": inputs, "pa": at, "dl": deadline} for j in range(len(out["keys"]))]
    res["inserted"] = await insert_predictions(s, rows)
    await s.commit()
    res["authz"] = fp[:12] if fp else None
    return res


async def insert_predictions(s: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Insert (idempotent) and return how many rows are new. Counted in the transaction:
    an executemany's rowcount is -1 with asyncpg (2026-10-22 log: inserted=-1)."""
    if not rows:
        return 0
    q = text("""select count(*) from model_prediction where model_sha256 = :m
        and session_date = :d and snapshot = :sn""")
    key = {"m": rows[0]["m"], "d": rows[0]["d"], "sn": rows[0]["sn"]}
    before = (await s.execute(q, key)).scalar()
    await s.execute(text("""insert into model_prediction (model_sha256, session_date,
        snapshot, instrument_key, prob_up, exp_return, range_lo, range_hi, volatility,
        confidence, score, rank, selected, features_as_of, inputs_sha256, predicted_at,
        deadline_at) values (:m, :d, :sn, :k, :p, :e, :lo, :hi, :v, :c, :sc, :r, :sel, :fa,
        :ih, :pa, :dl) on conflict on constraint uq_model_prediction do nothing"""), rows)
    return int((await s.execute(q, key)).scalar() - before)


# ── status (operational only) ───────────────────────────────────────────────────────
async def status(s: AsyncSession, model: str | None = None) -> dict[str, Any]:
    sha, _ = await load_model(s, model)
    rows = (await s.execute(text("""select session_date, count(*) as n,
        count(*) filter (where selected) as picks, max(predicted_at) as at, max(deadline_at) as dl
        from model_prediction where model_sha256 = :m group by 1 order by 1"""),
        {"m": sha})).all()
    first = rows[0].session_date if rows else None
    expected = (await s.execute(text("""select session_date from trading_session
        where is_trading_day and open_ist is not null and session_date >= :f
          and session_date <= (now() at time zone 'Asia/Kolkata')::date order by 1"""),
        {"f": first or now().date()})).scalars().all() if first else []
    have = {r.session_date for r in rows}
    return {"model_sha256": sha, "sessions_predicted": len(rows),
            "forward_sessions_needed": FORWARD_SESSIONS,
            "first_session": str(first) if first else None,
            "missing_sessions": [str(d) for d in expected if d not in have],
            "last": ({"session": str(rows[-1].session_date), "rows": rows[-1].n,
                      "picks": rows[-1].picks, "predicted_at": rows[-1].at.isoformat()}
                     if rows else None),
            "outcomes": _readiness_summary(await outcome_readiness(s, sha)),
            "performance": "not shown before the single look (pre-registration)"}


def _readiness_summary(rd: list[dict[str, Any]]) -> dict[str, Any]:
    today = now().astimezone(IST).date().isoformat()
    closed = [r for r in rd if r["session"] < today]
    return {"sessions_ready": sum(r["ready"] for r in closed),
            "sessions_closed": len(closed),
            "pending": [r["session"] for r in closed if not r["ready"]],
            "rule": f">= {OUTCOME_READY_SHARE:.0%} of the predicted names with a 1d bar"}


# A session's outcomes are READY when this share of its predicted names has a canonical
# daily bar (a halted or suspended name has none: not evaluable, per the pre-registration).
OUTCOME_READY_SHARE = 0.9


async def outcome_readiness(s: AsyncSession, sha: str) -> list[dict[str, Any]]:
    """Per predicted session: predicted names, names with a canonical 1d bar, ready.
    Counts only - no price, no return (no look)."""
    rows = (await s.execute(text("""
        select p.session_date, count(*) as n,
               count(b.instrument_key) as with_bar
        from model_prediction p
        left join canon_market_bar b on b.timeframe = '1d' and b.market_date = p.session_date
             and b.instrument_key = p.instrument_key
        where p.model_sha256 = :m group by 1 order by 1"""), {"m": sha})).all()
    return [{"session": str(r.session_date), "predicted": r.n, "with_bar": r.with_bar,
             "ready": r.n > 0 and r.with_bar >= OUTCOME_READY_SHARE * r.n} for r in rows]


# ── report (the single look) ────────────────────────────────────────────────────────
async def outcomes(s: AsyncSession, day: _dt.date, keys: list[str]) -> dict[str, tuple]:
    rows = (await s.execute(text("""select instrument_key, open, high, low, close
        from canon_market_bar where timeframe = '1d' and market_date = :d
          and instrument_key = any(:k)"""), {"d": day, "k": keys})).all()
    return {r.instrument_key: (float(r.open), float(r.high), float(r.low), float(r.close))
            for r in rows}


def _ledger_has(sha: str) -> bool:
    if not LEDGER.exists():
        return False
    return any(json.loads(x).get("model_sha256") == sha and json.loads(x).get("phase") == "look"
               for x in LEDGER.read_text().splitlines() if x.strip())


async def report(s: AsyncSession, model: str | None = None, *, look: bool = False
                 ) -> dict[str, Any]:
    sha, b = await load_model(s, model)
    st = await status(s, sha)
    days = list((await s.execute(text("""select distinct session_date from model_prediction
        where model_sha256 = :m order by 1"""), {"m": sha})).scalars())[:FORWARD_SESSIONS]
    if len(days) < FORWARD_SESSIONS:
        raise Refused(f"{len(days)} of {FORWARD_SESSIONS} forward sessions predicted; the "
                      "look waits (operational status only)")
    today = now().astimezone(IST).date()
    if days[-1] >= today:
        raise Refused("the last forward session has not closed")
    ready = {r["session"]: r for r in await outcome_readiness(s, sha)}
    pending = [str(d) for d in days if not ready.get(str(d), {}).get("ready")]
    if pending:
        raise Refused(f"outcomes not ready for {len(pending)} session(s) {pending[:5]}: the "
                      "look waits for their canonical daily bars (operational status only)")
    if not look:
        raise Refused("the single look needs --look (it is recorded; a second is refused)")
    if _ledger_has(sha):
        raise Refused("this model already had its look")
    per, placebo, not_evaluable = [], [], []
    rng = np.random.default_rng(R.SEED)
    for d in days:
        pr = (await s.execute(text("""select instrument_key, prob_up, exp_return, range_lo,
            range_hi, volatility, confidence, score, selected from model_prediction
            where model_sha256 = :m and session_date = :d order by instrument_key"""),
            {"m": sha, "d": d})).all()
        keys = [r.instrument_key for r in pr]
        live = await D.live_session(s, d)
        if live is None:              # reported, never dropped silently
            not_evaluable.append({"session": str(d), "reason": "no usable PRE_SESSION values"})
            continue
        pos = {k: i for i, k in enumerate(live.keys)}
        keys = [k for k in keys if k in pos]
        idx = np.array([pos[k] for k in keys], dtype=int)
        oc = await outcomes(s, d, keys)
        y = {lb: np.full(len(live.keys), np.nan) for lb in D.LABELS}
        locked = np.zeros(len(live.keys), dtype=bool)
        for k, (o, h, lo, c) in oc.items():
            i = pos[k]
            if o > 0 and h > lo:
                y["ret_oc"][i], y["high_exc"][i], y["low_exc"][i] = c / o - 1, h / o - 1, lo / o - 1
            else:
                locked[i] = True
        sess = D.Session(d, live.keys, live.X, y, locked, "forward")
        by = {r.instrument_key: r for r in pr}
        out = {"idx": idx, "keys": keys,
               **{f: np.array([getattr(by[k], f) for k in keys], dtype=float)
                  for f in ("prob_up", "exp_return", "range_lo", "range_hi", "volatility",
                            "confidence", "score")}}
        picks = [j for j, k in enumerate(keys) if by[k].selected]
        per.append(EV.session(sess, out, picks, b.cost, seed=R.SEED))
        pl = sorted(rng.choice(len(keys), size=min(len(picks), len(keys)), replace=False).tolist())
        placebo.append(EV.session(sess, out, pl, b.cost, seed=R.SEED + 1))
    pooled, pp = EV.pooled(per, seed=R.SEED), EV.pooled(placebo, seed=R.SEED)
    stress = [p["p_gross"] - 1.5 * p["p_cost"] - p["c2_gross"] for p in per
              if p.get("s") is not None]
    s_ = [p["s"] for p in per if p.get("s") is not None]
    half = len(s_) // 2
    gates = {"A1_ci_above_zero": bool(pooled.get("s_ci") and pooled["s_ci"][0] > 0),
             "A2_stress_mean_ge_zero": bool(stress) and float(np.mean(stress)) >= 0,
             "A3_both_halves_positive": bool(half) and float(np.mean(s_[:half])) > 0
             and float(np.mean(s_[half:])) > 0,
             "A4_placebo_ci_contains_zero": bool(pp.get("s_ci"))
             and pp["s_ci"][0] <= 0 <= pp["s_ci"][1]}
    rep = {"experiment": "E5", "phase": "look", "model_sha256": sha, "at": now().isoformat(),
           "sessions": [str(days[0]), str(days[-1])], "status": st, "pooled": pooled,
           "placebo": pp, "stress_mean": float(np.mean(stress)) if stress else None,
           "gates": gates, "verdict": "ACCEPTED" if all(gates.values()) else "NOT_ACCEPTED",
           "not_evaluable_sessions": not_evaluable,
           "per_session": per, "note": "PAPER ONLY; not a profitability claim"}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps({"phase": "look", "model_sha256": sha, "at": rep["at"],
                            "verdict": rep["verdict"]}) + "\n")
    (LEDGER.parent / f"forward_look_{sha[:12]}.json").write_text(
        json.dumps(rep, indent=1, default=str) + "\n")
    return rep


# ── E5.1: scheduled refits of the ACCEPTED recipe (docs/STAGE4_E5_AFTER_THE_LOOK.md §4) ──
# Inactive until E5's single look is ACCEPTED (ledger). No tuning: the recipe, window,
# universe and selection are E5's; only the training sessions move forward.
E51_DATASET = "stage4-ds-v4b-asif"        # AS_IF_LIVE on features-v5, appended daily
REFIT_EVERY = 20                          # labelled sessions after the previous model's window
MIN_UNIVERSE = 400


def look_verdict(sha: str) -> str | None:
    if not LEDGER.exists():
        return None
    for x in LEDGER.read_text().splitlines():
        if x.strip():
            d = json.loads(x)
            if d.get("model_sha256") == sha and d.get("phase") == "look":
                return d.get("verdict")
    return None


async def _base(s: AsyncSession) -> Any:
    row = (await s.execute(text("""select model_sha256, trained_to from model_version
        where purpose = 'FORWARD_TEST' order by id limit 1"""))).first()
    if row is None:
        raise Refused("no FORWARD_TEST model")
    return row


async def production_lineage(s: AsyncSession) -> list[Any]:
    """The accepted E5 model, then every PRODUCTION refit, oldest first."""
    base = await _base(s)
    if look_verdict(base.model_sha256) != "ACCEPTED":
        raise Refused("E5.1 is inactive: E5's single look is not ACCEPTED "
                      "(docs/STAGE4_E5_AFTER_THE_LOOK.md)")
    refits = (await s.execute(text("""select model_sha256, trained_to, created_at,
        previous_sha256 from model_version where purpose = 'PRODUCTION' order by id"""))).all()
    return [base, *refits]


async def production_model_for(s: AsyncSession, day: _dt.date) -> str:
    """The model that predicts `day` in production: the latest of the lineage created
    before that day (a refit is effective from the next session). One model per session:
    refused if another model of the lineage already predicted the day."""
    chain = await production_lineage(s)
    usable = [m for m in chain if not hasattr(m, "created_at")
              or m.created_at.astimezone(IST).date() < day]
    sha = usable[-1].model_sha256
    others = {m.model_sha256 for m in chain} - {sha}
    clash = (await s.execute(text("""select distinct model_sha256 from model_prediction
        where session_date = :d and model_sha256 = any(:o)"""),
        {"d": day, "o": list(others)})).scalars().all()
    if clash:
        raise Refused(f"{day} already has predictions of {clash[0][:12]}: one model per session")
    return sha


async def refit(s: AsyncSession, *, commit: bool = False, token: str | None = None,
                through: _dt.date | None = None) -> dict[str, Any]:
    """One E5.1 refit: e5-recipe-v2 on the latest 120 labelled sessions of E51_DATASET.
    Refused (the previous model stays; the caller alerts) on: E5 not ACCEPTED, a dirty tree,
    fewer than 120 labelled sessions, fewer than REFIT_EVERY new labelled sessions since the
    previous model's window, a universe below MIN_UNIVERSE, a failed or missing member,
    every stacking weight 0, or a hash that changes through the artefact."""
    from app.training.replay import code_version
    code = code_version()
    if code["dirty"]:
        raise Refused("the working tree is dirty; commit first (the model records its code)")
    fp = authorize_write(token) if commit else None
    chain = await production_lineage(s)
    prev = chain[-1]
    days = [d for d in await D.training_sessions(s, E51_DATASET)
            if through is None or d <= through]
    panel = []
    for d in days[-(R.TRAIN_SESSIONS + D.SEQ_LEN):]:
        x = await D.training_session(s, d, E51_DATASET)
        if x is not None:
            panel.append(x)
    labelled = [t for t, p in enumerate(panel) if not np.isnan(p.y["ret_oc"]).all()]
    train = labelled[-R.TRAIN_SESSIONS:]
    if len(train) < R.TRAIN_SESSIONS:
        raise Refused(f"{len(train)} labelled sessions in {E51_DATASET}; "
                      f"{R.TRAIN_SESSIONS} needed")
    new = [t for t in train if panel[t].date > prev.trained_to]
    if len(new) < REFIT_EVERY:
        raise Refused(f"{len(new)} labelled sessions after {prev.trained_to}; a refit every "
                      f"{REFIT_EVERY}")
    n_u = len(panel[train[-1]].universe())
    if n_u < MIN_UNIVERSE:
        raise Refused(f"universe {n_u} < {MIN_UNIVERSE} on {panel[train[-1]].date}")
    try:
        b = R.fit(panel, train)
    except Exception as e:                        # the previous model stays
        raise Refused(f"refit failed: {type(e).__name__}: {e}"[:300]) from e
    expected = {"ridge", "lgbm_reg", "lgbm_clf", "rf_clf", "lstm_clf", "lgbm_q10",
                "lgbm_q90", "lgbm_range"}
    if set(b.members) != expected or any(v is None for v in b.members.values()):
        raise Refused(f"members {sorted(b.members)} differ from the recipe")
    if not any(w > 0 for w in b.weights.values()):
        raise Refused("every stacking weight is 0 (no member carries signal)")
    sha = b.sha256()
    if pickle.loads(pickle.dumps(b, protocol=5)).sha256() != sha:  # noqa: S301 - our own
        raise Refused("the model hash changes through its artefact")
    if (await s.execute(text("select 1 from model_version where model_sha256 = :m"),
                        {"m": sha})).first():
        raise Refused(f"model {sha[:12]} exists already")
    out: dict[str, Any] = {"commit": commit, "model_sha256": sha, "previous": prev.model_sha256,
                           "recipe": R.VERSION, "dataset": E51_DATASET,
                           "trained": [str(panel[train[0]].date), str(panel[train[-1]].date)],
                           "new_sessions": len(new), "universe": n_u,
                           "weights": b.weights, "rows": b.meta["rows"]}
    if not commit:
        return out
    d = ART / sha
    d.mkdir(parents=True, exist_ok=True)
    path = d / "bundle.pkl"
    path.write_bytes(pickle.dumps(b, protocol=5))
    out["artefact_sha256"] = _sha_file(path)
    (d / "bundle.pkl.sha256").write_text(out["artefact_sha256"] + "\n")
    cfg = {"recipe": R.VERSION, "e51": True, "dataset": E51_DATASET, "labels": D.TRAIN_LABELS,
           "refit_every": REFIT_EVERY, "train_sessions": R.TRAIN_SESSIONS, "seed": R.SEED,
           "k": R.K, "round_trip_cost": b.cost}
    await s.execute(text("""insert into model_version (model_sha256, recipe, purpose,
        trained_from, trained_to, train_sessions, train_rows, artefact_path, artefact_sha256,
        code_git_sha, config, created_at, authz_token_sha256, previous_sha256) values (:m, :r,
        'PRODUCTION', :a, :b, :n, :rows, :p, :ps, :g, cast(:c as jsonb), :t, :fp, :prev)"""),
        {"m": sha, "r": R.VERSION, "a": panel[train[0]].date, "b": panel[train[-1]].date,
         "n": len(train), "rows": b.meta["rows"], "p": str(path.relative_to(ROOT)),
         "ps": out["artefact_sha256"], "g": code["git_sha"], "c": json.dumps(cfg), "t": now(),
         "fp": fp, "prev": prev.model_sha256})
    await s.commit()
    return out
