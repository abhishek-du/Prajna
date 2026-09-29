"""Poll a source, decide what is new, enrich it, and record it.

Timing (decision NEWS-KNOWABLE):
  discovered_at = the instant the response carrying the item was received
  knowable_at   = discovered_at (never the publisher's published_at)
  backlog       = the item was in the FIRST successful response of the source:
                  it existed before Prajna started watching, so its
                  publication->discovery latency is not a measurement and is
                  excluded from latency statistics (it is still knowable only
                  from discovered_at)

Two recorders share this logic:
  DryRunRecorder   files under var/news/dryrun/<source>/ (state.json, events.jsonl,
                   raw feed bodies gzipped); NO database write. The instrument
                   universe is read (read-only) for entity links; if the database
                   is unreachable, links are UNRESOLVED and collection continues.
  app.news.store   SHADOW writes to the news_* tables (locked).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import fcntl
import gzip
import json
import pathlib
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.clock import IST, now
from app.core.logging import get_logger
from app.news import assess as AS
from app.news import enrich as EN
from app.news import entities as X
from app.news import http as H
from app.news import stories as ST
from app.news.model import ItemObs, canonical_url, title_hash
from app.news.sources import SOURCES, Source

log = get_logger("news")
BASE = pathlib.Path(__file__).resolve().parents[2]
KILL_FILE = BASE / "var" / "run" / "news.kill"
DRYRUN_DIR = BASE / "var" / "news" / "dryrun"
TRACKED = ("title", "summary", "published_at", "source_updated_at")


@dataclass(slots=True)
class Seen:
    discovered_at: str
    title: str
    summary: str | None
    published_at: str | None
    source_updated_at: str | None


@dataclass(slots=True)
class Discovery:
    item: ItemObs
    discovered_at: _dt.datetime
    backlog: bool
    classification: EN.Classification
    links: list[EN.Link]
    mentions: list[X.Mention] = field(default_factory=list)
    story_id: str | None = None
    story: ST.Assignment | None = None
    assessment: AS.Assessment | None = None

    @property
    def latency_class(self) -> str:
        return "BACKLOG" if self.backlog else "LIVE_DISCOVERY"

    @property
    def link(self) -> EN.Link:
        """The most confident link (UNRESOLVED only when there is nothing else)."""
        return max(self.links, key=lambda ln: ln.confidence)

    @property
    def latency_s(self) -> float | None:
        if self.backlog or self.item.published_at is None:
            return None
        return (self.discovered_at - self.item.published_at).total_seconds()


@dataclass(slots=True)
class PollOutcome:
    source: str
    fetch: H.FetchResult
    new: list[Discovery] = field(default_factory=list)
    changed: list[tuple[ItemObs, list[str]]] = field(default_factory=list)
    seen: int = 0
    issues: list[dict[str, str]] = field(default_factory=list)
    backlog: bool = False


def market_hours(at: _dt.datetime) -> str:
    t = at.astimezone(IST)
    if t.weekday() >= 5:
        return "WEEKEND"
    return "MARKET" if _dt.time(9, 0) <= t.time() <= _dt.time(15, 45) else "OFF"


def interval_for(src: Source, at: _dt.datetime) -> int:
    return {"MARKET": src.market_interval_s, "OFF": src.off_interval_s,
            "WEEKEND": src.weekend_interval_s}[market_hours(at)]


def _iso(d: _dt.datetime | None) -> str | None:
    return d.isoformat() if d else None


def process(src: Source, fetch: H.FetchResult, seen: dict[str, Seen], *,
            universe: EN.Universe | None, aliases: EN.Aliases,
            first_success: bool, stories: ST.StoryIndex | None = None) -> PollOutcome:
    """Pure w.r.t. I/O: parse a response and split it into new / changed items.
    `seen` and `aliases` are updated in place."""
    out = PollOutcome(src.key, fetch)
    if fetch.outcome != "OK":
        return out
    try:
        feed = src.parse(fetch.body)
    except ValueError as e:
        out.fetch.outcome, out.fetch.error = "MALFORMED", str(e)[:300]
        return out
    out.issues = [{"kind": i.kind, "detail": i.detail} for i in feed.issues]
    out.seen, out.backlog = len(feed.items), first_success
    at = fetch.finished_at
    exchange = src.enrich == "EXCHANGE"
    index = EN.HeadlineIndex(universe) if (universe is not None and not exchange) else None
    # symbol-bearing items first, so a filer name learned in this response can
    # map the same filer's symbol-less items of the same response
    for it in sorted(feed.items, key=lambda i: i.symbol_raw is None):
        prev = seen.get(it.source_article_id)
        if prev is None:
            if exchange:
                cls, links = EN.classify(it), [EN.resolve(it, universe, aliases)]
            else:
                cls = (EN.classify_regulator(it) if src.enrich == "REGULATOR"
                       else EN.classify_keywords(it))
                links = EN.resolve_headline(it, universe, index)
                known = {ln.instrument_key for ln in links}
                extra = [ln for ln in X.alias_links(it, universe) if ln.instrument_key not in known]
                links = [ln for ln in links if ln.instrument_key] + extra or links
            d = Discovery(it, at, first_success, cls, links, X.mentions(it))
            _enrich_story_and_assess(d, src, stories)
            out.new.append(d)
            seen[it.source_article_id] = Seen(_iso(at), it.title, it.summary,
                                              _iso(it.published_at), _iso(it.source_updated_at))
            continue
        cur = {"title": it.title, "summary": it.summary, "published_at": _iso(it.published_at),
               "source_updated_at": _iso(it.source_updated_at)}
        changed = [f for f in TRACKED if getattr(prev, f) != cur[f]]
        if changed:
            out.changed.append((it, changed))
            for f in changed:
                setattr(prev, f, cur[f])
    return out


class SourceBusy(RuntimeError):
    """Another process is already dry-running this source (its state is not shared)."""


def _enrich_story_and_assess(d: Discovery, src: Source, stories: ST.StoryIndex | None) -> None:
    """Story membership (point in time: only members knowable at discovery) and the
    rule-based assessment; a second publisher within 30 min confirms (breaking c)."""
    it = d.item
    companies = sorted({ln.instrument_key for ln in d.links if ln.instrument_key})
    ments = [(m.entity_type, m.entity_id) for m in d.mentions]
    confirmed: list[str] = []
    if stories is not None:
        m = ST.Member(f"{src.key}|{it.source_article_id}", "", src.key, ST.words(it.title),
                      canonical_url(it.url), title_hash(it.title), frozenset(companies),
                      frozenset(f"{t}:{e}" for t, e in ments), d.classification.category,
                      it.published_at or d.discovered_at, d.discovered_at,
                      strict=src.enrich in ("EXCHANGE", "REGULATOR"))
        a = stories.assign(m, d.discovered_at)
        m.story_id = a.story_id or stories.new_id()
        stories.add(m)
        d.story_id, d.story = m.story_id, a
        if a.story_id is not None:
            first = min(c.knowable_at for c in stories.members if c.story_id == a.story_id)
            confirmed = sorted({c.source for c in stories.members if c.story_id == a.story_id
                                and c.source != src.key
                                and d.discovered_at - first <= _dt.timedelta(minutes=30)})
    d.assessment = AS.assess(it.title, d.classification.category, companies=companies,
                             mentions=ments, backlog=d.backlog, published_at=it.published_at,
                             discovered_at=d.discovered_at,
                             confirmed_by=None if d.backlog else confirmed)


def load_stories(root: pathlib.Path) -> ST.StoryIndex:
    p = root / "stories.json"
    if not p.exists():
        return ST.StoryIndex()
    d = json.loads(p.read_text())
    ix = ST.StoryIndex(next_id=d["next_id"])
    for m in d["members"]:
        ix.add(ST.Member(m["item_key"], m["story_id"], m["source"], frozenset(m["words"]),
                         m["canonical_url"], m["title_hash"], frozenset(m["companies"]),
                         frozenset(m["entities"]), m["category"],
                         _dt.datetime.fromisoformat(m["t"]),
                         _dt.datetime.fromisoformat(m["knowable_at"]), m.get("strict", False)))
    return ix


def save_stories(root: pathlib.Path, ix: ST.StoryIndex) -> None:
    ix.prune(now())
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "stories.json.part"
    tmp.write_text(json.dumps({"next_id": ix.next_id, "members": [
        {**{k: getattr(m, k) for k in ("item_key", "story_id", "source", "canonical_url",
                                       "title_hash", "category", "strict")},
         "words": sorted(m.words), "companies": sorted(m.companies),
         "entities": sorted(m.entities), "t": m.t.isoformat(),
         "knowable_at": m.knowable_at.isoformat()} for m in ix.members]}))
    tmp.replace(root / "stories.json")


class DryRunRecorder:
    """Evidence files only. Never opens a write transaction."""

    def __init__(self, src: Source, root: pathlib.Path = DRYRUN_DIR, *, lock: bool = False):
        self.src, self.dir = src, root / src.key
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = None
        if lock:
            self._lock = open(self.dir / ".lock", "a")  # held for the run (released at exit)
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self._lock.close()
                raise SourceBusy(f"{src.key}: already being dry-run by another process") from None
        self.state_file = self.dir / "state.json"
        st = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.seen = {k: Seen(**v) for k, v in st.get("seen", {}).items()}
        self.aliases = EN.Aliases.from_json(st.get("aliases", {}))
        self.http = H.SourceState(**st.get("http", {}))
        self.last_ok = _dt.datetime.fromisoformat(st["last_ok"]) if st.get("last_ok") else None
        self.last_poll_at = (_dt.datetime.fromisoformat(st["last_poll_at"])
                             if st.get("last_poll_at") else None)
        self.polls = st.get("polls", 0)

    @property
    def first_success(self) -> bool:
        return self.last_ok is None

    def save(self) -> None:
        tmp = self.state_file.with_suffix(".part")
        tmp.write_text(json.dumps({
            "seen": {k: asdict(v) for k, v in self.seen.items()},
            "aliases": self.aliases.to_json(), "http": asdict(self.http),
            "last_ok": _iso(self.last_ok), "last_poll_at": _iso(self.last_poll_at),
            "polls": self.polls}, default=str))
        tmp.replace(self.state_file)

    def record(self, o: PollOutcome) -> dict[str, Any]:
        f = o.fetch
        day = f.finished_at.astimezone(IST).date().isoformat()
        raw = None
        if f.body:
            import hashlib
            raw = hashlib.sha256(f.body).hexdigest()
            p = self.dir / "raw" / day / f"{raw}.xml.gz"
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(gzip.compress(f.body, mtime=0))
        poll = {"type": "poll", "source": o.source, "started_at": _iso(f.started_at),
                "finished_at": _iso(f.finished_at), "outcome": f.outcome,
                "http_status": f.http_status, "bytes": len(f.body), "items_seen": o.seen,
                "items_new": len(o.new), "items_changed": len(o.changed), "backlog": o.backlog,
                "payload_sha256": raw, "error": f.error, "retry_after_s": f.retry_after_s,
                "ttl_s": self.http.ttl_s, "issues": o.issues}
        lines = [poll]
        for d in o.new:
            it = d.item
            lines.append({"type": "item", "source": o.source, "id": it.source_article_id,
                          "title": it.title, "url": it.url, "canonical_url": canonical_url(it.url),
                          "title_norm_hash": title_hash(it.title), "summary": it.summary,
                          "category_raw": it.category_raw, "symbol_raw": it.symbol_raw,
                          "published_at": _iso(it.published_at),
                          "published_at_raw": it.published_at_raw,
                          "discovered_at": _iso(d.discovered_at),
                          "knowable_at": _iso(d.discovered_at), "backlog": d.backlog,
                          "latency_s": d.latency_s, "latency_class": d.latency_class,
                          "classification": asdict(d.classification),
                          "link": asdict(d.link), "links": [asdict(x) for x in d.links],
                          "mentions": [asdict(x) for x in d.mentions],
                          "story_id": d.story_id,
                          "story": asdict(d.story) if d.story else None,
                          "assessment": asdict(d.assessment) if d.assessment else None,
                          "source_priority": self.src.priority,
                          "terms_status": self.src.compliance,
                          "content_fetch_status": "NOT_AVAILABLE",
                          "processed_at": _iso(now())})
        for it, ch in o.changed:
            lines.append({"type": "change", "source": o.source, "id": it.source_article_id,
                          "observed_at": _iso(f.finished_at), "changed": ch, "title": it.title,
                          "published_at": _iso(it.published_at),
                          "latency_class": "UPDATED_ITEM"})
        with open(self.dir / f"events_{day}.jsonl", "a") as fh:
            for ln in lines:
                fh.write(json.dumps(ln, default=str) + "\n")
        self.polls += 1
        self.last_poll_at = f.started_at
        if f.outcome in ("OK", "NOT_MODIFIED"):
            self.last_ok = f.finished_at
        self.save()
        return poll


async def load_universe() -> EN.Universe | None:
    """Included NSE_EQ instruments, read-only; None if the database is unreachable."""
    try:
        from sqlalchemy import text

        from app.db.engine import get_sessionmaker
        async with get_sessionmaker()() as s:
            await s.execute(text("set transaction read only"))
            rows = (await s.execute(text("""select upper(trading_symbol), instrument_key, name
                from canon_instrument where included and segment = 'NSE_EQ'"""))).all()
            await s.rollback()
        return EN.Universe({r[0]: (r[1], r[2]) for r in rows})
    except Exception as e:                            # isolation: never stops collection
        log.warning("news_universe_unavailable", error=f"{type(e).__name__}: {e}"[:200])
        return None


async def dry_run(source_key: str, *, polls: int = 1, until: _dt.datetime | None = None,
                  transport=None, root: pathlib.Path = DRYRUN_DIR,
                  sleep=asyncio.sleep, rng: random.Random | None = None,
                  stories: ST.StoryIndex | None = None) -> list[dict]:
    """DRY_RUN: poll `polls` times (or until `until`), spacing polls by the
    source's interval (never below the feed ttl). Files only."""
    src = SOURCES[source_key]
    if src.parse is None or src.status == "UNSUPPORTED":
        raise ValueError(f"{source_key}: no adapter ({src.status})")
    rng = rng or random.Random()  # noqa: S311 - poll jitter, not cryptography
    rec = DryRunRecorder(src, root, lock=True)
    universe = await load_universe()
    out: list[dict] = []
    n = 0
    # politeness across restarts: the minimum interval (never below the feed ttl)
    # also separates the first poll of this process from the last poll of the previous one
    if rec.last_poll_at is not None:
        floor = max(interval_for(src, now()), rec.http.ttl_s or 0)
        wait = floor - (now() - rec.last_poll_at).total_seconds()
        if wait > 0:
            log.info("news_poll_deferred", source=source_key, wait_s=round(wait, 1))
            await sleep(wait)
    while True:
        if KILL_FILE.exists():
            log.warning("news_kill_switch", source=source_key)
            break
        log.info("news_poll_started", source=source_key, mode="DRY_RUN")
        f = await H.fetch(src.url, rec.http, transport=transport)
        shared = stories if stories is not None else load_stories(root)
        o = process(src, f, rec.seen, universe=universe, aliases=rec.aliases,
                    first_success=rec.first_success, stories=shared)
        save_stories(root, shared)
        if f.outcome == "OK" and o.fetch.outcome == "OK":
            feed_ttl = src.parse(f.body).ttl_minutes
            rec.http.ttl_s = feed_ttl * 60 if feed_ttl else None
        poll = rec.record(o)
        log.info("news_poll_completed", **{k: poll[k] for k in (
            "source", "outcome", "http_status", "items_seen", "items_new", "items_changed")})
        for d in o.new:
            if d.link.method == "UNRESOLVED":
                log.info("news_mapping_unresolved", source=source_key, id=d.item.source_article_id)
        if f.outcome in ("BLOCKED", "AUTH_FAILED"):
            log.error("news_source_failed", source=source_key, outcome=f.outcome)
        elif f.outcome == "RATE_LIMITED":
            log.warning("news_source_rate_limited", source=source_key)
        out.append(poll)
        n += 1
        if rec.http.stopped or (until is None and n >= polls) or (until and now() >= until):
            break
        await sleep(H.next_delay(interval_for(src, now()), rec.http, rng))
    return out


async def dry_run_many(keys: list[str], **kw) -> dict[str, list[dict] | str]:
    """Several sources concurrently; one source's failure never affects another."""
    root = kw.get("root", DRYRUN_DIR)
    shared = load_stories(root)              # one story index across all sources
    res = await asyncio.gather(*(dry_run(k, stories=shared, **kw) for k in keys),
                               return_exceptions=True)
    return {k: (r if not isinstance(r, BaseException) else f"{type(r).__name__}: {r}")
            for k, r in zip(keys, res, strict=True)}
