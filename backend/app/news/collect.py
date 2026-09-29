"""Scheduled multi-source collection into the database (SHADOW or PRODUCTION).

The same polite loop as the DRY_RUN collector (interval by market phase, never
below the feed's <ttl>, conditional GET, backoff, Retry-After, jitter; the
deadline checked before every poll and never slept past), but every poll goes
through the LOCKED store path `store.poll_shadow` - one committed transaction
per poll, serialised per source by advisory locks.

  * one task per source: one source's failure never affects another
  * a LockRefused (flag off, kill switch, acceptance, token ...) stops that
    source at once; the refusal is audited by the lock itself
  * any other error fails that poll's run (rolled back; run row FAILED) and the
    loop backs off and continues
  * a restart waits out the source's interval since its last stored poll
  * the client state (ETag, ttl, backoff, BLOCKED) and a status line per source
    are kept in var/news/collect/<SOURCE>/state.json for the next run and for
    `prajna news health`
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import pathlib
import random
from dataclasses import asdict
from typing import Any

from sqlalchemy import text

from app.core.clock import now
from app.features.locks import LockRefused
from app.news import http as H
from app.news.collector import BASE, _iso, interval_for, log
from app.news.sources import SOURCES

COLLECT_DIR = BASE / "var" / "news" / "collect"


class CollectState:
    """What one source's collector remembers between polls and between runs."""

    def __init__(self, key: str, root: pathlib.Path = COLLECT_DIR):
        self.file = root / key / "state.json"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        st = json.loads(self.file.read_text()) if self.file.exists() else {}
        self.http = H.SourceState(**st.get("http", {}))
        self.status: dict[str, Any] = st.get("status", {})

    def save(self, **status: Any) -> None:
        self.status = {**self.status, **status}
        tmp = self.file.with_suffix(".part")
        tmp.write_text(json.dumps({"http": asdict(self.http), "status": self.status},
                                  default=str))
        tmp.replace(self.file)


async def last_stored_poll(sm, key: str, mode: str) -> _dt.datetime | None:
    async with sm() as s:
        return (await s.execute(text(
            "select max(started_at) from news_poll where source = :s and mode = :m"),
            {"s": key, "m": mode})).scalar()


async def collect(source_key: str, *, mode: str, token: str | None,
                  until: _dt.datetime, operator: str = "cron", transport=None,
                  sleep=asyncio.sleep, rng: random.Random | None = None,
                  sessionmaker=None, root: pathlib.Path = COLLECT_DIR) -> list[dict]:
    """Poll one source into the database until `until`. Returns the poll outcomes."""
    from app.db.engine import get_sessionmaker
    from app.news.store import poll_shadow

    if mode not in ("SHADOW", "PRODUCTION"):
        raise ValueError(f"mode must be SHADOW or PRODUCTION, not {mode!r}")
    src = SOURCES[source_key]
    if src.parse is None or src.status == "UNSUPPORTED":
        raise ValueError(f"{source_key}: no adapter ({src.status})")
    sm = sessionmaker or get_sessionmaker()
    rng = rng or random.Random()  # noqa: S311 - poll jitter, not cryptography
    st = CollectState(source_key, root)
    out: list[dict] = []
    last = await last_stored_poll(sm, source_key, mode)
    if last is not None:                     # politeness across restarts
        wait = (max(interval_for(src, now()), st.http.ttl_s or 0)
                - (now() - last).total_seconds())
        if wait > 0:
            if now() + _dt.timedelta(seconds=wait) >= until:
                return out
            await sleep(wait)
    while now() < until:
        if st.http.stopped:
            log.error("news_collect_source_stopped", source=source_key, reason=st.http.stopped)
            break
        try:
            async with sm() as s:
                r = await poll_shadow(s, source_key, token=token, operator=operator,
                                      transport=transport, http_state=st.http, mode=mode)
            out.append(r)
            st.save(mode=mode, last_poll_at=_iso(now()), last_outcome=r["outcome"],
                    last_ok_at=(_iso(now()) if r["outcome"] in ("OK", "NOT_MODIFIED")
                                else st.status.get("last_ok_at")),
                    polls=st.status.get("polls", 0) + 1, last_error=None)
            log.info("news_collect_poll", source=source_key, mode=mode,
                     **{k: r[k] for k in ("outcome", "inserted", "changed")})
        except LockRefused as e:
            failing = e.report.summary()["failing"]
            st.save(mode=mode, last_outcome="REFUSED", refused=failing, refused_at=_iso(now()))
            log.error("news_collect_refused", source=source_key, mode=mode, failing=failing)
            break
        except Exception as e:                        # the poll's run is FAILED, rolled back
            st.http.failures += 1
            st.save(mode=mode, last_poll_at=_iso(now()), last_outcome="ERROR",
                    last_error=f"{type(e).__name__}: {e}"[:300])
            log.error("news_collect_error", source=source_key, error=f"{type(e).__name__}: {e}"
                      [:300])
        delay = H.next_delay(interval_for(src, now()), st.http, rng)
        if now() + _dt.timedelta(seconds=delay) >= until:
            break
        await sleep(delay)
    return out


async def collect_many(keys: list[str], **kw) -> dict[str, list[dict] | str]:
    """Several sources concurrently; one source's failure never affects another."""
    res = await asyncio.gather(*(collect(k, **kw) for k in keys), return_exceptions=True)
    return {k: (r if not isinstance(r, BaseException) else f"{type(r).__name__}: {r}")
            for k, r in zip(keys, res, strict=True)}
