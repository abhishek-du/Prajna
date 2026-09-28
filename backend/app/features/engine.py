"""Stage 3 engine: compute a snapshot's features, optionally persist them.

compute_snapshot()  pure w.r.t. storage: reads canonical inputs (app.features.inputs)
                    and returns rows. Used by dry-run, acceptance probes and runs.
run_snapshot()      a production run: locks are checked HERE (defence in depth, in
                    addition to the CLI), one IngestRunner run per snapshot, rows
                    inserted idempotently; a rerun that disagrees with a stored value
                    fails the run (determinism), it never overwrites.

A compute exception (a bug, a look-ahead) fails loud: the run is FAILED and its
writes roll back. Missing or malformed inputs are not exceptions: they produce
null values with a reason, and the run continues.

Every input read, the determinism check and the persistence of one snapshot
share ONE database snapshot (consistent_read: REPEATABLE READ), so a canon job
committing mid-run (maintenance canon at 09:10, during PRE_OPEN) can never give
one snapshot a mix of before and after states.
"""

from __future__ import annotations

import datetime as _dt
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.canon import pit
from app.core.clock import now
from app.db.models import FeatureValue
from app.features import inputs as I
from app.features import locks
from app.features.compute import MISSING_INPUT, NOT_APPLICABLE, Result, miss, ok
from app.features.compute import context as CX
from app.features.compute import event as EV
from app.features.compute import fundamental as FU
from app.features.compute import liquidity as LQ
from app.features.compute import preopen as PO
from app.features.compute import price as PR
from app.features.registry import (
    BY_ID,
    CONTEXT_INDEX_KEYS,
    FEATURES,
    MARKET_KEY,
    REGISTRY_SHA256,
    VIX_KEY,
)
from app.features.snapshots import Snapshot
from app.ingest.runner import IngestRunner

SOURCE = "PRAJNA_STAGE3"
BENCHMARK = "NSE_INDEX|Nifty 50"


@dataclass(frozen=True, slots=True)
class FeatureRow:
    scope: str
    instrument_key: str
    feature_id: str
    value: float | None
    reason: str | None
    inputs_sha256: str
    input_max_knowable_at: _dt.datetime | None


@dataclass
class SnapshotResult:
    snapshot: Snapshot
    rows: list[FeatureRow] = field(default_factory=list)
    refused_bars: Counter = field(default_factory=Counter)
    seconds: float = 0.0

    def stats(self) -> dict[str, Any]:
        reasons = Counter(r.reason or "OK" for r in self.rows)
        return {"rows": len(self.rows), "values": reasons.get("OK", 0),
                "nulls_by_reason": {k: v for k, v in sorted(reasons.items()) if k != "OK"},
                "refused_bars": dict(self.refused_bars), "seconds": round(self.seconds, 2),
                "instruments": len({r.instrument_key for r in self.rows
                                    if r.scope == "INSTRUMENT"})}


class DeterminismMismatch(RuntimeError):
    """A recompute disagrees with a stored value: never overwritten; the run fails."""


class KillSwitchEngaged(RuntimeError):
    """The Stage 3 kill switch was engaged while the run was in progress."""


class SnapshotIsolationError(RuntimeError):
    """The transaction cannot provide one consistent snapshot; nothing is computed."""


CONSISTENT_LEVELS = ("repeatable read", "serializable")


async def consistent_read(s: AsyncSession, *, read_only: bool) -> str:
    """Begin the session's next transaction at REPEATABLE READ (optionally READ ONLY),
    so every later statement in it sees the database as of its first query.

    Must be called with no transaction in progress (after a commit). A session
    joined to an enclosing transaction (the test harness: a savepoint) cannot set
    the level itself; the enclosing transaction must already be REPEATABLE READ or
    SERIALIZABLE, otherwise this refuses rather than run at READ COMMITTED."""
    conn = await s.connection()
    if conn.in_nested_transaction():
        level = (await s.execute(text("show transaction_isolation"))).scalar()
        if level not in CONSISTENT_LEVELS:
            raise SnapshotIsolationError(f"enclosing transaction is {level!r}; one consistent "
                                         "snapshot needs repeatable read")
        return level
    await s.execute(text("set transaction isolation level repeatable read"
                         + (", read only" if read_only else "")))
    return (await s.execute(text("show transaction_isolation"))).scalar()


# ── per-instrument features ──────────────────────────────────────────────────
def _daily_features(bars, nifty) -> dict[str, Result]:
    out: dict[str, Result] = {}
    for n in (1, 5, 20):
        out[f"ret_{n}d"] = PR.ret(bars, n)
    for n in (20, 50, 200):
        out[f"sma_{n}"] = PR.sma(bars, n)
        out[f"close_to_sma_{n}"] = PR.close_to_sma(bars, n)
    out["ema_12"], out["ema_26"] = PR.ema(bars, 12), PR.ema(bars, 26)
    out["rsi_14"] = PR.rsi(bars, 14)
    out["macd_line"], out["macd_trigger"], out["macd_histogram"] = PR.macd(bars)
    out["atr_14"], out["atr_pct_14"] = PR.atr(bars, 14), PR.atr_pct(bars, 14)
    out["volatility_20"] = PR.realised_vol(bars, 20)
    out["beta_60"] = PR.beta(bars, nifty, 60)
    out["dist_high_20"], out["dist_low_20"] = PR.range_position(bars, 20)
    out["breakout_20"], out["breakdown_20"] = PR.breakout(bars, 20)
    out["avg_volume_20"] = LQ.avg_volume(bars, 20)
    out["volume_spike_20"] = LQ.volume_spike(bars, 20)
    out["turnover_20"] = LQ.turnover(bars, 20)
    return out


def _fundamental_features(f: dict[str, Any]) -> dict[str, Result]:
    kr = f.get("key_ratios")
    iy, iq = f.get("income:consolidated:yearly"), f.get("income:consolidated:quarterly")
    return {
        "pe": FU.key_ratio(kr, "P/E"), "pb": FU.key_ratio(kr, "P/B"),
        "roe_pct": FU.key_ratio(kr, "ROE"), "roce_pct": FU.key_ratio(kr, "ROCE"),
        "ev_ebitda": FU.key_ratio(kr, "EV/EBITDA"),
        "pe_to_sector": FU.ratio_to_sector(kr, "P/E"),
        "pb_to_sector": FU.ratio_to_sector(kr, "P/B"),
        "revenue_yoy": FU.growth(iy, "Revenue"), "pat_yoy": FU.growth(iy, "Profit After Tax"),
        "eps_yoy": FU.growth(iy, "EPS - Diluted"),
        "revenue_yoy_q": FU.growth(iq, "Revenue", quarterly=True),
        "pat_yoy_q": FU.growth(iq, "Profit After Tax", quarterly=True),
        "liabilities_to_assets": FU.liabilities_to_assets(f.get("balance_sheet:consolidated")),
    }


def _event_features(inp: I.InstrumentInputs, snap: Snapshot) -> dict[str, Result]:
    out: dict[str, Result] = {}
    for k in EV.TYPES:
        out[f"ca_days_since_{k}"] = EV.ca_days_since(inp.corporate_actions, snap.session_date, k)
        out[f"ca_days_to_{k}"] = EV.ca_days_to(inp.corporate_actions, snap.session_date, k)
    out["news_count_24h"] = EV.news_count(inp.news_published, snap.as_of, 24)
    out["news_count_7d"] = EV.news_count(inp.news_published, snap.as_of, 24 * 7)
    out["news_hours_since_last"] = EV.news_hours_since(inp.news_published, snap.as_of)
    return out


def _preopen_features(inp: I.InstrumentInputs, snap: Snapshot) -> dict[str, Result]:
    if snap.kind != "PRE_OPEN":
        return {}
    prev = inp.daily[-1].close if inp.daily else None
    avg, _ = LQ.avg_volume(inp.daily, 20)
    t = inp.preopen_tick
    return {"preopen_gap_pct": PO.gap_pct(t, prev), "preopen_imbalance": PO.imbalance(t),
            "preopen_ieq": PO.ieq(t), "preopen_ieq_to_avg_volume": PO.ieq_to_avg_volume(t, avg)}


_GROUPS = {"daily_bars": ("daily_bars",), "nifty_bars": ("daily_bars", "nifty"),
           "key_ratios": ("fundamentals",), "income_yearly": ("fundamentals",),
           "income_quarterly": ("fundamentals",), "balance_sheet": ("fundamentals",),
           "corporate_actions": ("corporate_actions",), "news": ("news",),
           "preopen": ("preopen", "daily_bars")}
_BAR_INPUTS = {"daily_bars", "nifty_bars", "preopen"}


def instrument_rows(inp: I.InstrumentInputs, snap: Snapshot, nifty: list,
                    nifty_tracked: I.Tracked) -> list[FeatureRow]:
    inp.tracked["nifty"] = nifty_tracked
    vals = {**_daily_features(inp.daily, nifty), **_fundamental_features(inp.fundamentals),
            **_event_features(inp, snap), **_preopen_features(inp, snap)}
    rows = []
    for spec in FEATURES:
        if spec.scope != "INSTRUMENT" or spec.id == "sector_rs_20":
            continue
        if snap.kind not in spec.snapshots:
            continue
        v, why = vals.get(spec.id, miss(NOT_APPLICABLE))
        if inp.stale and _BAR_INPUTS.intersection(spec.inputs):
            v, why = miss(MISSING_INPUT)
        groups = tuple(g for i in spec.inputs for g in _GROUPS.get(i, ()))
        sha, kn = inp.provenance(groups)
        rows.append(FeatureRow("INSTRUMENT", inp.key, spec.id, v, why, sha, kn))
    return rows


# ── context features ─────────────────────────────────────────────────────────
async def context_rows(s: AsyncSession, snap: Snapshot) -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    for key in CONTEXT_INDEX_KEYS:
        bars, tr = await I.index_bars(s, key, snap)
        stale = _index_stale(bars, snap)
        for fid, res in (("index_ret_1d", PR.ret(bars, 1)), ("index_ret_5d", PR.ret(bars, 5)),
                         ("index_close_to_sma_50", PR.close_to_sma(bars, 50))):
            res = miss(MISSING_INPUT) if stale else res
            rows.append(FeatureRow("CONTEXT", key, fid, *res, tr.sha256, tr.max_knowable_at))
    vix, tr = await I.index_bars(s, VIX_KEY, snap)
    closes = [b.close for b in vix]
    level = ok(closes[-1]) if closes else miss(MISSING_INPUT)
    for fid, res in (("india_vix_level", level), ("india_vix_change_5d", CX.vix_change(closes, 5))):
        res = miss(MISSING_INPUT) if _index_stale(vix, snap) else res
        rows.append(FeatureRow("CONTEXT", VIX_KEY, fid, *res, tr.sha256, tr.max_knowable_at))
    macro, tr = await I.macro_rows(s, snap)
    for who in ("FII", "DII"):
        for n in (1, 5):
            rows.append(FeatureRow("CONTEXT", MARKET_KEY, f"{who.lower()}_net_cash_{n}d",
                                   *CX.flow(macro, who, n, snap.previous_session),
                                   tr.sha256, tr.max_knowable_at))
    gkeys = (await s.execute(text("""select instrument_key from instrument where valid_to =
        'infinity' and segment in ('GLOBAL_INDEX','GLOBAL_INDICATOR') order by 1"""))).scalars()
    for key in list(gkeys):
        closes, tr = await I.global_closes(s, key, snap)
        rows.append(FeatureRow("CONTEXT", key, "global_ret_1d", *CX.global_ret(closes),
                               tr.sha256, tr.max_knowable_at))
    return rows


def _index_stale(bars: list, snap: Snapshot) -> bool:
    return bool(bars) and bars[-1].day != snap.previous_session


async def _sector_rows(s: AsyncSession, snap: Snapshot, keys: list[str],
                       ret20: dict[str, tuple[float | None, I.InstrumentInputs]],
                       ) -> list[FeatureRow]:
    """sector_rs_20 for `keys`. Sector membership is point-in-time (pit.sector at
    as_of); today's classification only pre-selects the candidates to check."""
    sec = {k: await pit.sector(s, k, snap.as_of) for k in keys}
    wanted = sorted({v for v in sec.values() if v})
    members: dict[str, list[str]] = {w: [] for w in wanted}
    cands = (await s.execute(text("""select instrument_key from canon_instrument
        where included and segment = 'NSE_EQ' and lifecycle_status = 'ACTIVE'
          and sector = any(:s) order by 1"""), {"s": wanted})).scalars().all() if wanted else []
    for k in cands:
        ps = sec[k] if k in sec else await pit.sector(s, k, snap.as_of)
        if ps in members:
            members[ps].append(k)
    out = []
    for k in keys:
        stock, inp = ret20[k]
        sector = sec.get(k)
        if sector is None:
            res = miss(MISSING_INPUT)
        elif stock is None and inp.stale:
            res = miss(MISSING_INPUT)
        else:
            others = []
            for m in members.get(sector, []):
                if m == k:
                    continue
                if m not in ret20:
                    mi = await I.instrument_inputs(s, m, snap)
                    ret20[m] = (None if mi.stale else PR.ret(mi.daily, 20)[0], mi)
                if ret20[m][0] is not None:
                    others.append(ret20[m][0])
            res = CX.sector_rs(stock, others)
        sha, kn = inp.provenance(("daily_bars", "fundamentals"))
        out.append(FeatureRow("INSTRUMENT", k, "sector_rs_20", *res, sha, kn))
    return out


async def compute_snapshot(s: AsyncSession, snap: Snapshot, keys: list[str], *,
                           with_context: bool = True, with_sector: bool = True,
                           kill_check: bool = False) -> SnapshotResult:
    t0 = time.monotonic()
    res = SnapshotResult(snap)
    nifty, ntr = await I.index_bars(s, BENCHMARK, snap)
    ret20: dict[str, tuple[float | None, I.InstrumentInputs]] = {}
    for k in keys:
        if kill_check and locks.kill_switch_engaged():
            raise KillSwitchEngaged("Stage 3 kill switch engaged during the run")
        inp = await I.instrument_inputs(s, k, snap)
        res.refused_bars.update(inp.refused)
        res.rows.extend(instrument_rows(inp, snap, nifty, ntr))
        ret20[k] = (None if inp.stale else PR.ret(inp.daily, 20)[0], inp)
    stock_keys = [k for k in keys if k.startswith("NSE_EQ|")]
    if with_sector and stock_keys:
        res.rows.extend(await _sector_rows(s, snap, stock_keys, ret20))
    if with_context:
        res.rows.extend(await context_rows(s, snap))
    for r in res.rows:     # defence in depth: every value is point-in-time
        if r.input_max_knowable_at is not None and r.input_max_knowable_at >= snap.as_of:
            raise I.LookAhead(f"{r.instrument_key} {r.feature_id}: input knowable at/after as_of")
    res.seconds = time.monotonic() - t0
    return res


# ── production run (locked) ──────────────────────────────────────────────────
async def universe(s: AsyncSession) -> list[str]:
    return list((await s.execute(text("""select instrument_key from canon_instrument
        where included and lifecycle_status = 'ACTIVE' and segment in ('NSE_EQ','NSE_INDEX')
        order by instrument_key"""))).scalars())


async def persist(s: AsyncSession, res: SnapshotResult, run_id) -> tuple[int, int]:
    """Insert new rows; verify existing ones are identical. Returns (inserted, present)."""
    snap = res.snapshot
    ids = dict((await s.execute(text("select instrument_key, instrument_id from instrument "
                                     "where valid_to = 'infinity'"))).all())
    at = now()
    values = [{"scope": r.scope, "instrument_key": r.instrument_key,
               "instrument_id": ids.get(r.instrument_key), "session_date": snap.session_date,
               "snapshot": snap.kind, "as_of": snap.as_of, "feature_id": r.feature_id,
               "feature_version": BY_ID[r.feature_id].version, "registry_sha256": REGISTRY_SHA256,
               "value": r.value, "reason": r.reason, "inputs_sha256": r.inputs_sha256,
               "input_max_knowable_at": r.input_max_knowable_at, "computed_at": at,
               "run_id": run_id} for r in res.rows]
    inserted = 0
    for i in range(0, len(values), 5000):
        chunk = values[i:i + 5000]
        inserted += (await s.execute(pg_insert(FeatureValue).values(chunk).on_conflict_do_nothing(
            constraint="uq_feature_value"))).rowcount
    stored = {(r[0], r[1]): (r[2], r[3], r[4]) for r in (await s.execute(text("""
        select instrument_key, feature_id, value, reason, inputs_sha256 from feature_value
        where session_date = :d and snapshot = :k"""),
        {"d": snap.session_date, "k": snap.kind})).all()}
    bad = []
    for r in res.rows:
        v, why, sha = stored[(r.instrument_key, r.feature_id)]
        same_v = (v is None and r.value is None) or (v is not None and r.value is not None
                                                      and float(v) == r.value)
        if not (same_v and why == r.reason and sha == r.inputs_sha256):
            bad.append(f"{r.instrument_key}:{r.feature_id}")
    if bad:
        raise DeterminismMismatch(f"{len(bad)} stored feature values differ from a recompute "
                                  f"(first: {bad[:3]}); nothing overwritten")
    return inserted, len(values) - inserted


async def run_snapshot(s: AsyncSession, snap: Snapshot, *, keys: list[str] | None, mode: str,
                       token: str | None, operator: str = "cli") -> dict[str, Any]:
    """A committed run. Refused (LockRefused) unless every lock condition holds."""
    report = await locks.require(s, mode=mode, token=token, operator=operator)
    keys = keys if keys is not None else await universe(s)
    runner = IngestRunner(s, source=SOURCE, stream=f"features.{snap.kind}",
                          vendor_endpoint="derived: app.canon.pit (no vendor call)",
                          request_params={"session": str(snap.session_date), "snapshot": snap.kind,
                                          "as_of": snap.as_of.isoformat(), "mode": mode,
                                          "registry_sha256": REGISTRY_SHA256,
                                          "instruments": len(keys)},
                          operator=operator, logical_date=snap.session_date)
    ctx = await runner.open(commit=True, token=token)      # the run row is committed first
    try:
        await consistent_read(s, read_only=False)           # compute + persist: one snapshot
        res = await compute_snapshot(s, snap, keys, kill_check=True)
        inserted, present = await persist(s, res, ctx.run_id)
        outcome = {**res.stats(), "inserted": inserted, "already_present": present,
                   "locks": report.summary()}
        await runner.finalize(rows_written=inserted, outcome=outcome)
        await locks.record_event(s, "RUN_COMPLETE", mode, operator, outcome, ctx.run_id)
        await s.commit()
        return {"run_id": str(ctx.run_id), "committed": True, **outcome}
    except BaseException as e:
        await runner.fail(f"{type(e).__name__}: {e}"[:500])
        await locks.record_event(s, "RUN_FAILED", mode, operator,
                                 {"error": f"{type(e).__name__}: {e}"[:500]}, ctx.run_id)
        await s.commit()
        raise
