"""Quarantine of out-of-contract training_sample slices (migration 0020; Option A approved
by the user 2026-10-12).

A slice is (dataset_version, label_version, snapshot). training_sample is append-only, so
an out-of-contract slice is never deleted; it is recorded here with the row count and
fingerprint seen at recording, and readers skip it:
  samples.build    the stored-vs-recompute check leaves quarantined slices out
  report/manifest  sample counts mark them; the full report refuses a quarantined label
  integrity        snapshot_allowed still counts the raw rows; a quarantined slice whose
                   stored rows changed since recording is drift (FAIL)
Only a slice outside its label's contract can be quarantined (samples.label_snapshots).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now

SLICE_FP = """select count(*), md5(string_agg(md5(concat_ws('|', session_date, snapshot,
        instrument_key, eligible, exclusion_reasons, masks)), '' order by session_date,
        instrument_key))
    from training_sample where dataset_version = :v and label_version = :lv
      and snapshot = :k"""


class QuarantineError(RuntimeError):
    pass


async def snapshots(s: AsyncSession, dataset: str, label_version: str) -> set[str]:
    """The quarantined snapshot types of (dataset, label version)."""
    return set((await s.execute(text("""select snapshot from training_sample_quarantine
        where dataset_version = :v and label_version = :lv"""),
        {"v": dataset, "lv": label_version})).scalars())


async def fingerprint(s: AsyncSession, dataset: str, label_version: str,
                      snapshot: str) -> tuple[int, str | None]:
    n, h = (await s.execute(text(SLICE_FP), {"v": dataset, "lv": label_version,
                                             "k": snapshot})).one()
    return int(n), h


async def verify(s: AsyncSession, dataset: str, label_version: str) -> list[dict[str, Any]]:
    """Read-only: every quarantine record of (dataset, label version) against the stored
    slice; match is False when rows were added (or changed) after recording."""
    out = []
    for r in (await s.execute(text("""select id, snapshot, rows, rows_md5, reason,
            approved_by, approval_ref, code_git_sha, created_at
            from training_sample_quarantine where dataset_version = :v and label_version = :lv
            order by id"""), {"v": dataset, "lv": label_version})).mappings().all():
        n, h = await fingerprint(s, dataset, label_version, r["snapshot"])
        out.append({**dict(r), "stored_rows": n, "stored_md5": h,
                    "match": n == r["rows"] and h == r["rows_md5"]})
    return out


async def record(s: AsyncSession, dataset: str, label_version: str, snapshot: str, *,
                 reason: str, approved_by: str, approval_ref: str,
                 code_git_sha: str) -> dict[str, Any]:
    """Record one out-of-contract slice (one transaction; append-only)."""
    from app.training.samples import label_snapshots
    allowed = label_snapshots(label_version)
    if allowed is None or snapshot in allowed:
        raise QuarantineError(f"{label_version}/{snapshot} is inside the label's contract; "
                              "only an out-of-contract slice can be quarantined")
    await s.rollback()
    if snapshot in await snapshots(s, dataset, label_version):
        raise QuarantineError(f"{dataset}/{label_version}/{snapshot} is already quarantined")
    n, h = await fingerprint(s, dataset, label_version, snapshot)
    if n == 0:
        raise QuarantineError(f"{dataset}/{label_version}/{snapshot}: no stored rows")
    at = now()
    await s.execute(text("""insert into training_sample_quarantine (dataset_version,
        label_version, snapshot, rows, rows_md5, reason, approved_by, approval_ref,
        code_git_sha, created_at) values (:v, :lv, :k, :n, :h, :r, :by, :ref, :g, :at)"""),
        {"v": dataset, "lv": label_version, "k": snapshot, "n": n, "h": h, "r": reason,
         "by": approved_by, "ref": approval_ref, "g": code_git_sha, "at": at})
    await s.commit()
    return {"dataset_version": dataset, "label_version": label_version, "snapshot": snapshot,
            "rows": n, "rows_md5": h, "created_at": at.isoformat()}
