"""Chronological walk-forward splits (training_split), one set per dataset x label x
snapshot type. Boundaries are session dates, identical for every instrument, so no
instrument's session can sit in two roles.

  scheme wf-exp-120-20-20-e1   expanding TRAIN (>= 120 sessions), then EMBARGO 1 session,
                               VALID 20, EMBARGO 1, TEST 20; the next fold adds 20 sessions
                               to TRAIN. label-v1/v2 span one session (T open -> T close)
                               and features at T+1 use bar T, so a 1-session embargo keeps
                               every training label strictly before the next block's as_of.
                               A multi-session label of h sessions needs embargo >= h.
A dataset with too few sessions gets no fold (reported, never padded).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now

SCHEME = "wf-exp-120-20-20-e1"
TRAIN_MIN, VALID_N, TEST_N, STEP, EMBARGO = 120, 20, 20, 20, 1


def folds(sessions: list[_dt.date], *, train_min: int = TRAIN_MIN, valid_n: int = VALID_N,
          test_n: int = TEST_N, step: int = STEP, embargo: int = EMBARGO) -> list[dict]:
    """Pure: the fold blocks of a sorted session list."""
    ss = sorted(set(sessions))
    out, k = [], 0
    while True:
        tr_end = train_min + k * step                          # exclusive
        va0 = tr_end + embargo
        va1 = va0 + valid_n
        te0 = va1 + embargo
        te1 = te0 + test_n
        if te1 > len(ss):
            break
        for role, a, b in (("TRAIN", 0, tr_end), ("VALID", va0, va1), ("TEST", te0, te1)):
            out.append({"fold": k, "role": role, "session_from": ss[a], "session_to": ss[b - 1],
                        "sessions": b - a, "embargo_sessions": embargo})
        k += 1
    return out


async def build(s: AsyncSession, dataset: str, label_version: str) -> dict[str, Any]:
    await s.rollback()
    out: dict[str, Any] = {"dataset_version": dataset, "label_version": label_version,
                           "scheme": SCHEME, "snapshots": {}}
    for (kind,) in (await s.execute(text("""select distinct snapshot from training_session_done
            where dataset_version = :v order by 1"""), {"v": dataset})).all():
        sessions = list((await s.execute(text("""select session_date from training_session_done
            where dataset_version = :v and snapshot = :k order by 1"""),
            {"v": dataset, "k": kind})).scalars())
        fs = folds(sessions)
        at, inserted = now(), 0
        for f in fs:
            inserted += (await s.execute(text("""insert into training_split (dataset_version,
                label_version, snapshot, scheme, fold, role, session_from, session_to, sessions,
                embargo_sessions, created_at) values (:v, :lv, :k, :sc, :fold, :role, :a, :b,
                :n, :e, :at) on conflict on constraint uq_training_split do nothing"""),
                {"v": dataset, "lv": label_version, "k": kind, "sc": SCHEME, "fold": f["fold"],
                 "role": f["role"], "a": f["session_from"], "b": f["session_to"],
                 "n": f["sessions"], "e": f["embargo_sessions"], "at": at})).rowcount
        stored = [dict(r) for r in (await s.execute(text("""select fold, role, session_from,
            session_to, sessions, embargo_sessions from training_split where dataset_version = :v
              and label_version = :lv and snapshot = :k and scheme = :sc order by fold, role"""),
            {"v": dataset, "lv": label_version, "k": kind, "sc": SCHEME})).mappings().all()]
        want = sorted(fs, key=lambda f: (f["fold"], f["role"]))
        if stored != want:
            await s.rollback()
            raise RuntimeError(f"{dataset}/{kind}: stored splits differ from the recompute")
        out["snapshots"][kind] = {"sessions": len(sessions), "folds": len(fs) // 3,
                                  "inserted": inserted,
                                  "note": None if fs else f"insufficient: {len(sessions)} "
                                  f"sessions < {TRAIN_MIN + 2 * EMBARGO + VALID_N + TEST_N}"}
    await s.commit()
    return out
