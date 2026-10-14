"""Chronological walk-forward splits (training_split), one set per dataset x label x
snapshot type. Boundaries are session dates, identical for every instrument, so no
instrument's session can sit in two roles.

  scheme wf-exp-120-20-20-e1   expanding TRAIN (>= 120 sessions), then EMBARGO 1 session,
                               VALID 20, EMBARGO 1, TEST 20; the next fold adds 20 sessions
                               to TRAIN. label-v1/v2 span one session (T open -> T close)
                               and features at T+1 use bar T, so a 1-session embargo keeps
                               every training label strictly before the next block's as_of.
                               A multi-session label of h sessions needs embargo >= h.
  scheme wf-exp-120-20-20-e5   (E2, Amendment 2 rev 2, PROPOSED) the same blocks with a
                               5-session EMBARGO and a 5-session TAIL purge: a TEST
                               session needs the open of T+5, so the last 5 sessions are
                               never TEST. Identical to app.training.e2.make_folds.
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
SCHEME_E5 = "wf-exp-120-20-20-e5"
SCHEMES = {SCHEME: {"embargo": EMBARGO, "tail": 0},
           SCHEME_E5: {"embargo": 5, "tail": 5}}
E5_LABELS = ("label-hold5-v1-asif",)            # the only label version of scheme e5


def folds(sessions: list[_dt.date], *, train_min: int = TRAIN_MIN, valid_n: int = VALID_N,
          test_n: int = TEST_N, step: int = STEP, embargo: int = EMBARGO,
          tail: int = 0) -> list[dict]:
    """Pure: the fold blocks of a sorted session list (tail: sessions after the last
    TEST block that its labels need)."""
    ss = sorted(set(sessions))
    out, k = [], 0
    while True:
        tr_end = train_min + k * step                          # exclusive
        va0 = tr_end + embargo
        va1 = va0 + valid_n
        te0 = va1 + embargo
        te1 = te0 + test_n
        if te1 + tail > len(ss):
            break
        for role, a, b in (("TRAIN", 0, tr_end), ("VALID", va0, va1), ("TEST", te0, te1)):
            out.append({"fold": k, "role": role, "session_from": ss[a], "session_to": ss[b - 1],
                        "sessions": b - a, "embargo_sessions": embargo})
        k += 1
    return out


def violations(sessions: list[_dt.date], blocks: list[dict]) -> list[str]:
    """Pure: everything wrong with stored fold blocks against the dataset's sessions -
    unknown boundaries, wrong counts, overlap, a wrong embargo, a TRAIN that does not
    start at the first session, a non-expanding TRAIN."""
    ss = sorted(set(sessions))
    pos = {d: i for i, d in enumerate(ss)}
    out = []
    by: dict[int, dict[str, dict]] = {}
    for b in blocks:
        by.setdefault(b["fold"], {})[b["role"]] = b
        a, z = pos.get(b["session_from"]), pos.get(b["session_to"])
        if a is None or z is None:
            out.append(f"fold {b['fold']} {b['role']}: a boundary is not a dataset session")
        elif z - a + 1 != b["sessions"]:
            out.append(f"fold {b['fold']} {b['role']}: {b['sessions']} sessions declared, "
                       f"{z - a + 1} in the window")
    prev_train = 0
    for k, roles in sorted(by.items()):
        if set(roles) != {"TRAIN", "VALID", "TEST"}:
            out.append(f"fold {k}: roles {sorted(roles)}")
            continue
        tr, va, te = roles["TRAIN"], roles["VALID"], roles["TEST"]
        if tr["session_from"] != ss[0]:
            out.append(f"fold {k}: TRAIN does not start at the first session")
        for x, y in ((tr, va), (va, te)):
            if x["session_to"] in pos and y["session_from"] in pos:
                gap = pos[y["session_from"]] - pos[x["session_to"]] - 1
                if gap != y["embargo_sessions"] or gap < 1:
                    out.append(f"fold {k}: {gap} embargo session(s) before {y['role']}")
        if tr["sessions"] <= prev_train:
            out.append(f"fold {k}: TRAIN does not expand")
        prev_train = tr["sessions"]
    return out


async def verify(s: AsyncSession, dataset: str, label_version: str) -> dict[str, Any]:
    """Read-only: the stored folds of every snapshot type against the dataset's sessions."""
    out = {}
    for (kind,) in (await s.execute(text("""select distinct snapshot from training_split
            where dataset_version = :v and label_version = :lv order by 1"""),
            {"v": dataset, "lv": label_version})).all():
        sessions = list((await s.execute(text("""select session_date from training_session_done
            where dataset_version = :v and snapshot = :k order by 1"""),
            {"v": dataset, "k": kind})).scalars())
        blocks = [dict(r) for r in (await s.execute(text("""select fold, role, session_from,
            session_to, sessions, embargo_sessions from training_split where dataset_version = :v
              and label_version = :lv and snapshot = :k order by fold, role"""),
            {"v": dataset, "lv": label_version, "k": kind})).mappings().all()]
        v = violations(sessions, blocks)
        out[kind] = {"folds": len({b["fold"] for b in blocks}), "violations": v, "pass": not v}
    return out


async def build(s: AsyncSession, dataset: str, label_version: str,
                scheme: str = SCHEME) -> dict[str, Any]:
    from app.training.samples import check_versions
    check_versions(dataset, label_version)
    if scheme not in SCHEMES:
        raise ValueError(f"unknown scheme {scheme!r}")
    if (scheme == SCHEME_E5) != (label_version in E5_LABELS):
        raise ValueError(f"{label_version} does not use scheme {scheme}")
    params = SCHEMES[scheme]
    await s.rollback()
    out: dict[str, Any] = {"dataset_version": dataset, "label_version": label_version,
                           "scheme": scheme, "snapshots": {}}
    from app.training.samples import label_snapshots
    allowed = label_snapshots(label_version)
    for (kind,) in (await s.execute(text("""select distinct snapshot from training_session_done
            where dataset_version = :v order by 1"""), {"v": dataset})).all():
        if allowed is not None and kind not in allowed:
            continue
        sessions = list((await s.execute(text("""select session_date from training_session_done
            where dataset_version = :v and snapshot = :k order by 1"""),
            {"v": dataset, "k": kind})).scalars())
        fs = folds(sessions, **params)
        need = TRAIN_MIN + 2 * params["embargo"] + VALID_N + TEST_N + params["tail"]
        at, inserted = now(), 0
        for f in fs:
            inserted += (await s.execute(text("""insert into training_split (dataset_version,
                label_version, snapshot, scheme, fold, role, session_from, session_to, sessions,
                embargo_sessions, created_at) values (:v, :lv, :k, :sc, :fold, :role, :a, :b,
                :n, :e, :at) on conflict on constraint uq_training_split do nothing"""),
                {"v": dataset, "lv": label_version, "k": kind, "sc": scheme, "fold": f["fold"],
                 "role": f["role"], "a": f["session_from"], "b": f["session_to"],
                 "n": f["sessions"], "e": f["embargo_sessions"], "at": at})).rowcount
        stored = [dict(r) for r in (await s.execute(text("""select fold, role, session_from,
            session_to, sessions, embargo_sessions from training_split where dataset_version = :v
              and label_version = :lv and snapshot = :k and scheme = :sc order by fold, role"""),
            {"v": dataset, "lv": label_version, "k": kind, "sc": scheme})).mappings().all()]
        want = sorted(fs, key=lambda f: (f["fold"], f["role"]))
        if stored != want:
            await s.rollback()
            raise RuntimeError(f"{dataset}/{kind}: stored splits differ from the recompute")
        out["snapshots"][kind] = {"sessions": len(sessions), "folds": len(fs) // 3,
                                  "inserted": inserted,
                                  "note": None if fs else f"insufficient: {len(sessions)} "
                                  f"sessions < {need}"}
    await s.commit()
    return out
