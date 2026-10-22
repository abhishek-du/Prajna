"""E5 data: one PRE_SESSION cross-section per session, from the Stage 4 dataset (training,
AS_IF_LIVE v3 on features-v4) or from production feature_value (the live forward test).
Read only.

A Session holds the feature-complete NSE_EQ rows of one session: the 24 core features
(E1 CORE24, raw values), the labels when known (label-v2: ret_oc, high_exc, low_exc; NaN
otherwise) and the evaluation mask (E1: CA_WINDOW, EXTREME_UNEXPLAINED, vendor-adjusted
price level). The universe is cut per session from past-only fields: price (sma_20) >=
MIN_PRICE, then the top UNIVERSE_TOP by turnover_20 (ties by key).
Model inputs are cross-sectional unit ranks per session (scale-free across regimes).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.training import e1 as E1

CORE = E1.CORE24
UNIVERSE_TOP, MIN_PRICE = 500, 50.0
LABELS = ("ret_oc", "high_exc", "low_exc")
TRAIN_DATASET, TRAIN_LABELS = "stage4-ds-v3-asif", "label-v2"
SEQ_LEN = 10                       # sessions of history per LSTM sequence
_I = {f: i for i, f in enumerate(CORE)}


@dataclass
class Session:
    date: _dt.date
    keys: list[str]
    X: np.ndarray                  # (n, 24) raw core features
    y: dict[str, np.ndarray]       # label -> (n,) NaN when not known / not VALID
    masked: np.ndarray             # (n,) bool: excluded from evaluation and training
    source: str
    extra: dict = field(default_factory=dict)

    def col(self, f: str) -> np.ndarray:
        return self.X[:, _I[f]]

    def universe(self, top: int = UNIVERSE_TOP) -> np.ndarray:
        """Row indices of the session universe (past-only: price, then turnover)."""
        if ("u", top) not in self.extra:
            ok = np.flatnonzero(self.col("sma_20") >= MIN_PRICE)
            turn = self.col("turnover_20")
            order = sorted(ok.tolist(), key=lambda i: (-turn[i], self.keys[i]))
            self.extra[("u", top)] = np.array(order[:top], dtype=int)
        return self.extra[("u", top)]

    def universe_ranks(self) -> np.ndarray:
        """ranks(universe()), cached (a session is ranked once however often it is read)."""
        if "r" not in self.extra:
            self.extra["r"] = self.ranks(self.universe())
        return self.extra["r"]

    def ranks(self, idx: np.ndarray) -> np.ndarray:
        """Unit ranks of the core features among the rows idx (per column)."""
        return np.column_stack([E1.unit_rank(self.X[idx, j]) for j in range(len(CORE))])


def _pivot(rows, label_rows=None) -> tuple[list[str], np.ndarray, dict, np.ndarray]:
    keys = [r["instrument_key"] for r in rows]
    X = np.array([[float(r[f"f{i}"]) for i in range(len(CORE))] for r in rows])
    y = {lb: np.full(len(keys), np.nan) for lb in LABELS}
    if label_rows is not None:
        pos = {k: i for i, k in enumerate(keys)}
        for k, lid, v in label_rows:
            if k in pos and v is not None:
                y[lid][pos[k]] = float(v)
    return keys, X, y, np.array([False] * len(keys))


_COLS = ", ".join(f"max(value) filter (where feature_id = '{f}') as f{i}"
                  for i, f in enumerate(CORE))


async def training_session(s: AsyncSession, day: _dt.date,
                           dataset: str = TRAIN_DATASET) -> Session | None:
    rows = (await s.execute(text(f"""
        with smp as (select instrument_key, masks, label_flags from training_sample
              where dataset_version = :v and label_version = :lv and snapshot = 'PRE_SESSION'
                and session_date = :d and feature_eligible
                and instrument_key like 'NSE_EQ|%%'),
        f as (select instrument_key, {_COLS} from training_feature_value
              where dataset_version = :v and snapshot = 'PRE_SESSION' and session_date = :d
                and status = 'VALID' and feature_id = any(:ids) group by 1)
        select * from smp join f using (instrument_key) order by instrument_key"""),  # noqa: S608
        {"v": dataset, "lv": TRAIN_LABELS, "d": day, "ids": list(CORE)})).mappings().all()
    rows = [r for r in rows if all(r[f"f{i}"] is not None for i in range(len(CORE)))]
    if not rows:
        return None
    labels = (await s.execute(text("""select instrument_key, label_id, value from training_label
        where label_version = :lv and session_date = :d and status = 'VALID'
          and label_id = any(:ids)"""), {"lv": TRAIN_LABELS, "d": day,
                                         "ids": list(LABELS)})).all()
    keys, X, y, _ = _pivot(rows, labels)
    masked = np.array([any(m in E1.EVAL_MASKS for m in (r["masks"] or []))
                       or any(fl.startswith(E1.EVAL_FLAG_PREFIXES)
                              for fl in (r["label_flags"] or [])) for r in rows])
    return Session(day, keys, X, y, masked, dataset)


async def training_sessions(s: AsyncSession, dataset: str = TRAIN_DATASET) -> list[_dt.date]:
    return list((await s.execute(text("""select session_date from training_session_done
        where dataset_version = :v and snapshot = 'PRE_SESSION' order by 1"""),
        {"v": dataset})).scalars())


# feature versions of the CORE ids as computed by the live engine (registry independent:
# the same definition keeps its version across registries features-v4 -> v5)
async def live_session(s: AsyncSession, day: _dt.date) -> Session | None:
    """Production PRE_SESSION feature values of `day` (Stage 3, STRICT point in time);
    labels unknown (NaN). Rows are the active NSE_EQ instruments with all 24 present."""
    from app.features.registry import BY_ID
    vers = {f: BY_ID[f].version for f in CORE}
    rows = (await s.execute(text(f"""
        select instrument_key, {_COLS} from feature_value
         where snapshot = 'PRE_SESSION' and session_date = :d and scope = 'INSTRUMENT'
           and instrument_key like 'NSE_EQ|%%' and feature_id = any(:ids)
           and value is not null
           and feature_version = (cast(:vers as jsonb) ->> feature_id)::int
         group by 1 order by 1"""),  # noqa: S608
        {"d": day, "ids": list(CORE), "vers": __import__("json").dumps(vers)})).mappings().all()
    rows = [r for r in rows if all(r[f"f{i}"] is not None for i in range(len(CORE)))]
    if not rows:
        return None
    keys, X, y, masked = _pivot(rows)
    return Session(day, keys, X, y, masked, "feature_value")


def empty_session(day: _dt.date) -> Session:
    """A session with no usable rows: it holds its place in a sequence (every name absent,
    a zero row), so the sessions around it keep their positions."""
    return Session(day, [], np.zeros((0, len(CORE))), {lb: np.zeros(0) for lb in LABELS},
                   np.zeros(0, dtype=bool), "absent")


def sequences(history: list[Session], cur: Session, idx: np.ndarray,
              length: int = SEQ_LEN) -> tuple[np.ndarray, np.ndarray]:
    """LSTM inputs for the rows idx of `cur`: (len(idx), length, 24) unit ranks of each
    name's core features over the last `length` sessions ending at cur (rank within each
    session's own universe; a session where the name is absent is a zero row), plus a
    (len(idx),) count of present sessions."""
    past = [*history[-(length - 1):], cur] if length > 1 else [cur]
    out = np.zeros((len(idx), length, len(CORE)), dtype=np.float32)
    present = np.zeros(len(idx), dtype=np.int32)
    off = length - len(past)
    want = {cur.keys[i]: j for j, i in enumerate(idx)}
    for t, sess in enumerate(past):
        if not sess.keys:               # an absent session (empty_session): zero rows
            continue
        if sess is cur and np.array_equal(idx, cur.universe()):
            u, r = idx, cur.universe_ranks()
        elif sess is cur:
            u, r = idx, cur.ranks(idx)
        else:
            u, r = sess.universe(), sess.universe_ranks()
        keys = sess.keys
        rows = [(want.get(keys[i]), row) for row, i in enumerate(u)]
        js = np.array([j for j, _ in rows if j is not None], dtype=int)
        rs = np.array([row for j, row in rows if j is not None], dtype=int)
        if len(js):
            out[js, off + t] = r[rs]
            present[js] += 1
    return out, present
