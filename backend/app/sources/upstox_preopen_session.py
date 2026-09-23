"""A pre-open capture across several WebSocket connections.

Upstox serves at most 2,000 keys per `full` connection (measured 2026-09-23),
and the eligible universe is larger. So one capture SESSION runs N independent
PreopenRecorders, one per shard of the sorted universe:

    universe --plan_shards--> shard 0 (keys 0..1999)    -> connection 0 -> archive c0
                              shard 1 (keys 2000..3524) -> connection 1 -> archive c1

Each connection has its own archive, authorize, reconnect budget, stale
watchdog and lifecycle events; one failing never stops the others. Shards are
disjoint by construction, so no key is subscribed twice.

The SESSION MANIFEST (<stem>.session.json) ties them together. It is written
at the start (status "running", so a crash still leaves the plan on disk) and
rewritten at the end with each connection's outcome and the union coverage:
which subscribed keys produced at least one frame, and which never did.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import pathlib
import uuid
from dataclasses import dataclass
from typing import Any

from app.contracts.provenance import Source
from app.contracts.universe import ShardPlan, SubscriptionPlan
from app.core.clock import now, to_utc
from app.core.logging import get_logger
from app.sources.upstox_preopen_ws import (
    Authorizer,
    PreopenRecorder,
    RecorderConfig,
    RecorderSummary,
    open_capture_archive,
)
from app.storage.frame_archive import FrameArchiveWriter
from app.vendor.upstox.proto import PROTO_SHA256

log = get_logger("upstox.preopen_session")


@dataclass(slots=True)
class ShardOutcome:
    index: int
    archive: str
    keys: int
    keys_sha256: str
    summary: RecorderSummary | None = None
    error: str | None = None


def _stem(session_date: _dt.date, started: _dt.datetime) -> str:
    s = to_utc(started)
    return f"preopen_{session_date.isoformat()}_{s:%H%M%S}Z"


def _write_json(path: pathlib.Path, doc: dict) -> None:
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str))
    os.replace(tmp, path)


class PreopenCaptureSession:
    def __init__(
        self,
        root: pathlib.Path,
        *,
        session_date: _dt.date,
        plan: ShardPlan,
        authorize: Authorizer,
        config: RecorderConfig | None = None,
        stop_at: _dt.datetime | None = None,
        max_frames_per_connection: int | None = None,
        stop: asyncio.Event | None = None,
        extra_header: dict[str, Any] | None = None,
    ):
        if not plan.shards:
            raise ValueError("nothing to subscribe: the shard plan is empty")
        self.cfg = config or RecorderConfig(cap=plan.per_connection)
        if self.cfg.cap is not None and self.cfg.cap < plan.per_connection:
            raise ValueError("recorder cap is below the shard size; keys would be cut twice")
        self.plan = plan
        self.session_date = session_date
        self.started = now()
        self.session_id = uuid.uuid4().hex
        self.stop = stop or asyncio.Event()
        self.stop_at = stop_at
        self.max_frames = max_frames_per_connection
        self.authorize = authorize
        self.extra = extra_header or {}
        stem = _stem(session_date, self.started)
        self.dir = (pathlib.Path(root) / Source.UPSTOX_WS_V3.value / f"{to_utc(self.started):%Y}"
                    / f"{to_utc(self.started):%m}" / f"{to_utc(self.started):%d}")
        self.manifest_path = self.dir / f"{stem}.session.json"

        n = len(plan.shards)
        self.writers: list[FrameArchiveWriter] = []
        self.shard_plans: list[SubscriptionPlan] = []
        for i, keys in enumerate(plan.shards):
            # Session-level exclusions are carried by shard 0 only, so replay
            # raises exactly one COVERAGE_CAP anomaly for them.
            sp = SubscriptionPlan(plan.requested if i == 0 else keys, keys,
                                  plan.excluded if i == 0 else (), 0, plan.per_connection)
            self.shard_plans.append(sp)
            self.writers.append(open_capture_archive(
                root, session_date=session_date, plan=sp, config=self.cfg, started=self.started,
                path=self.dir / f"{stem}_c{i}of{n}.frames.gz",
                extra={**self.extra, "session_id": self.session_id, "shard_index": i,
                       "shard_count": n, "universe_sha256": plan.universe_sha256,
                       "universe_count": len(plan.requested)},
            ))
        self.outcomes = [ShardOutcome(i, str(w.path), len(sp.subscribed), sp.keys_sha256)
                         for i, (w, sp) in enumerate(zip(self.writers, self.shard_plans,
                                                         strict=True))]
        self._manifest("running")

    def _manifest(self, status: str) -> dict:
        seen: set[str] = set()
        never: list[str] = []
        for o, sp in zip(self.outcomes, self.shard_plans, strict=True):
            if o.summary is not None:
                never += o.summary.never_seen
                seen |= set(sp.subscribed) - set(o.summary.never_seen)
        doc = {
            "session_id": self.session_id,
            "status": status,
            "session_date": self.session_date.isoformat(),
            "source": Source.UPSTOX_WS_V3.value,
            "proto_sha256": PROTO_SHA256,
            "started_at": to_utc(self.started).isoformat(),
            "ended_at": now().isoformat() if status != "running" else None,
            "config": self.cfg.public(),
            "universe": {
                "count": len(self.plan.requested),
                "sha256": self.plan.universe_sha256,
                "per_connection": self.plan.per_connection,
                "max_connections": self.plan.max_connections,
                "excluded_by_capacity": list(self.plan.excluded),
                "duplicates_removed": self.plan.duplicates,
            },
            "shards": [{
                "index": o.index, "archive": o.archive, "keys": o.keys,
                "keys_sha256": o.keys_sha256,
                "first_key": sp.subscribed[0], "last_key": sp.subscribed[-1],
                "summary": None if o.summary is None else {
                    k: getattr(o.summary, k) for k in o.summary.__slots__ if k != "never_seen"},
                "never_seen_keys": None if o.summary is None else o.summary.never_seen,
                "error": o.error,
            } for o, sp in zip(self.outcomes, self.shard_plans, strict=True)],
            "coverage": None if status == "running" else {
                "subscribed": len(self.plan.subscribed),
                "seen": len(seen),
                "never_seen": len(never),
                "never_seen_keys": sorted(never),
            },
            **({"extra": self.extra} if self.extra else {}),
        }
        _write_json(self.manifest_path, doc)
        return doc

    async def _one(self, i: int) -> None:
        rec = PreopenRecorder(
            self.writers[i], self.authorize, self.shard_plans[i], self.cfg,
            stop_at=self.stop_at, max_frames=self.max_frames, stop=self.stop,
        )
        try:
            await rec.run()
        except Exception as e:
            # Independent failure: record it, let the other connections run on.
            self.outcomes[i].error = f"{type(e).__name__}: {e}"[:500]
            log.error("preopen_session.shard_failed", shard=i, error=self.outcomes[i].error)
        finally:
            self.outcomes[i].summary = rec.summary

    async def run(self) -> dict:
        try:
            await asyncio.gather(*(self._one(i) for i in range(len(self.writers))))
        finally:
            status = "complete" if all(o.error is None for o in self.outcomes) else "partial"
            doc = self._manifest(status)
        return doc
