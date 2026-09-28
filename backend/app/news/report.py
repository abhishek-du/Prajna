"""Summary of DRY_RUN evidence files (pure file reading): latency and source health.

Latency (never uses published_at as knowable_at; it only MEASURES against it):
  discovery_latency   discovered_at - published_at    LIVE_DISCOVERY items only
  processing_latency  processed_at - discovered_at    (parse + enrichment)
  end_to_end_latency  processed_at - published_at     (= when the API could serve it;
                      in DRY_RUN "available" means written to the evidence file)
  frontend latency    UNKNOWN: not observable from the backend
Classes: BACKLOG (the first response: existed before Prajna watched - excluded),
LIVE_DISCOVERY, UPDATED_ITEM (a later edit). A negative discovery latency is
CLOCK_SKEW (counted, never averaged). Items without a publication TIME (SEBI
gives a date only) have no latency. Market hours = weekdays 09:00-15:45 IST
(by discovery time).

Health (per source): HEALTHY / DEGRADED (>20% of the last 10 polls failed) /
STALE (no successful poll for 3x the expected interval) / RATE_LIMITED /
BLOCKED / AUTH_FAILED - a source that stops responding never looks healthy.
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import pathlib
from itertools import pairwise
from typing import Any

from app.core.clock import IST, now

PCTS = (("p50", .5), ("p90", .9), ("p95", .95), ("p99", .99))


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def stats(xs: list[float]) -> dict[str, Any]:
    return {"n": len(xs), **{k: _pct(xs, p) for k, p in PCTS},
            "max": round(max(xs), 1) if xs else None}


def _ts(s: str | None) -> _dt.datetime | None:
    return _dt.datetime.fromisoformat(s) if s else None


def market_hours(t: _dt.datetime) -> bool:
    x = t.astimezone(IST)
    return x.weekday() < 5 and _dt.time(9, 0) <= x.time() <= _dt.time(15, 45)


def load(src_dir: pathlib.Path, day: str | None = None):
    polls, items, changes = [], [], []
    for f in sorted(src_dir.glob(f"events_{day or '*'}.jsonl")):
        for ln in f.read_text().splitlines():
            e = json.loads(ln)
            {"poll": polls, "item": items, "change": changes}[e["type"]].append(e)
    return polls, items, changes


def latency(items: list[dict]) -> dict[str, Any]:
    disc: dict[str, list[float]] = {"all": [], "market_hours": [], "off_hours": []}
    proc, e2e, skew = [], [], 0
    for i in items:
        d, p, pr = _ts(i["discovered_at"]), _ts(i["published_at"]), _ts(i.get("processed_at"))
        if pr:
            proc.append((pr - d).total_seconds())
        if i["backlog"] or p is None:
            continue
        x = (d - p).total_seconds()
        if x < 0:
            skew += 1
            continue
        disc["all"].append(x)
        disc["market_hours" if market_hours(d) else "off_hours"].append(x)
        if pr:
            e2e.append((pr - p).total_seconds())
    return {"discovery_s": {k: stats(v) for k, v in disc.items()},
            "processing_s": stats(proc), "end_to_end_s": stats(e2e),
            "frontend_s": "UNKNOWN (not observable from the backend)",
            "clock_skew_items": skew}


def health(polls: list[dict], expected_interval_s: float, at: _dt.datetime | None = None) -> str:
    at = at or now()
    if not polls:
        return "STALE"
    last = polls[-1]
    if last["outcome"] in ("BLOCKED", "AUTH_FAILED"):
        return last["outcome"]
    if last["outcome"] == "RATE_LIMITED":
        return "RATE_LIMITED"
    ok = [p for p in polls if p["outcome"] in ("OK", "NOT_MODIFIED")]
    if not ok or (at - _ts(ok[-1]["finished_at"])).total_seconds() > 3 * expected_interval_s:
        return "STALE"
    recent = polls[-10:]
    bad = sum(1 for p in recent if p["outcome"] not in ("OK", "NOT_MODIFIED"))
    return "DEGRADED" if bad / len(recent) > 0.2 else "HEALTHY"


def summarise(src_dir: pathlib.Path, day: str | None = None, *,
              expected_interval_s: float = 3600, at: _dt.datetime | None = None
              ) -> dict[str, Any]:
    polls, items, changes = load(src_dir, day)
    if not polls:
        return {"source": src_dir.name, "error": "no dry-run evidence", "health": "STALE"}
    outcomes = collections.Counter(p["outcome"] for p in polls)
    live = [i for i in items if not i["backlog"]]
    methods = collections.Counter(i["link"]["method"] for i in items)
    cats = collections.Counter(i["classification"]["category"] for i in items)
    title_groups = collections.Counter(i["title_norm_hash"] for i in items)
    ok_polls = [p for p in polls if p["outcome"] in ("OK", "NOT_MODIFIED")]
    starts = [_ts(p["started_at"]) for p in polls]
    gaps = [(b - a).total_seconds() for a, b in pairwise(starts)]
    assessed = [i["assessment"] for i in items if i.get("assessment")]
    stories = [i for i in items if i.get("story")]
    return {
        "source": src_dir.name, "day": day, "polls": len(polls), "outcomes": dict(outcomes),
        "http_status": dict(collections.Counter(str(p["http_status"]) for p in polls)),
        "rate_limit_events": outcomes.get("RATE_LIMITED", 0),
        "errors": sum(v for k, v in outcomes.items() if k not in ("OK", "NOT_MODIFIED")),
        "bytes_downloaded": sum(p["bytes"] for p in polls),
        "actual_interval_s": {"p50": _pct(gaps, .5), "min": min(gaps) if gaps else None,
                              "max": max(gaps) if gaps else None},
        "first_poll": polls[0]["started_at"], "last_poll": polls[-1]["started_at"],
        "last_success": ok_polls[-1]["finished_at"] if ok_polls else None,
        "last_item_discovered": max((i["discovered_at"] for i in items), default=None),
        "health": health(polls, expected_interval_s, at),
        "items": len(items), "backlog_items": len(items) - len(live), "live_items": len(live),
        "updated_items": len(changes),
        "latency": latency(items),
        "duplicates": {"same_link_repeated_in_feed": sum(
            1 for p in polls for i in p.get("issues", []) if i["kind"] == "DUPLICATE_IN_FEED"),
            "items_sharing_a_normalised_title": sum(n for n in title_groups.values() if n > 1)},
        "mapping": dict(methods),
        "mapping_rate": round(sum(v for k, v in methods.items() if k != "UNRESOLVED")
                              / len(items), 3) if items else None,
        "unresolved": methods.get("UNRESOLVED", 0),
        "categories": dict(cats.most_common()),
        "stories": {"items_with_story": len(stories), "joined_existing": sum(
            1 for i in stories if i["story"]["method"] != "FOUNDER"),
            "by_method": dict(collections.Counter(i["story"]["method"] for i in stories))},
        "assessment": {"breaking": sum(1 for a in assessed if a["is_breaking"]),
                       "impact": dict(collections.Counter(a["potential_impact"] for a in assessed)),
                       "scope": dict(collections.Counter(a["market_scope"] for a in assessed))},
        "content_fetch_status": dict(collections.Counter(
            i.get("content_fetch_status", "NOT_AVAILABLE") for i in items)),
        "issues": dict(collections.Counter(i["kind"] for p in polls for i in p.get("issues", []))),
    }
