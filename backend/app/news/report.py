"""Summary of DRY_RUN evidence files (pure file reading).

Latency = discovered_at - published_at, over NON-backlog items only (items in
the first response existed before Prajna watched: their "latency" would measure
nothing but the start time). Negative values are counted as CLOCK_SKEW, not
averaged in.
"""

from __future__ import annotations

import collections
import json
import pathlib
import statistics
from typing import Any


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def summarise(src_dir: pathlib.Path, day: str | None = None) -> dict[str, Any]:
    files = sorted(src_dir.glob(f"events_{day or '*'}.jsonl"))
    if not files:
        return {"source": src_dir.name, "error": "no dry-run evidence"}
    polls, items, changes = [], [], []
    for f in files:
        for ln in f.read_text().splitlines():
            e = json.loads(ln)
            {"poll": polls, "item": items, "change": changes}[e["type"]].append(e)
    outcomes = collections.Counter(p["outcome"] for p in polls)
    live = [i for i in items if not i["backlog"]]
    lat = [i["latency_s"] for i in live if i["latency_s"] is not None]
    skew = [x for x in lat if x < 0]
    lat = [x for x in lat if x >= 0]
    methods = collections.Counter(i["link"]["method"] for i in items)
    cats = collections.Counter(i["classification"]["category"] for i in items)
    dups_in_feed = sum(1 for p in polls for i in p.get("issues", [])
                       if i["kind"] == "DUPLICATE_IN_FEED")
    title_groups = collections.Counter(i["title_norm_hash"] for i in items)
    ok_polls = [p for p in polls if p["outcome"] in ("OK", "NOT_MODIFIED")]
    gaps = [b - a for a, b in zip(
        [_ts(p["started_at"]) for p in polls[:-1]], [_ts(p["started_at"]) for p in polls[1:]],
        strict=True)]
    return {
        "source": src_dir.name, "files": [f.name for f in files],
        "polls": len(polls), "outcomes": dict(outcomes),
        "bytes_downloaded": sum(p["bytes"] for p in polls),
        "actual_interval_s": {"p50": _pct(gaps, .5), "min": min(gaps) if gaps else None,
                              "max": max(gaps) if gaps else None},
        "first_poll": polls[0]["started_at"], "last_poll": polls[-1]["started_at"],
        "last_success": ok_polls[-1]["finished_at"] if ok_polls else None,
        "items": len(items), "backlog_items": len(items) - len(live), "live_items": len(live),
        "changed_observations": len(changes),
        "latency_s_publisher_to_discovery_live": {
            "n": len(lat), "p50": _pct(lat, .5), "p95": _pct(lat, .95), "p99": _pct(lat, .99),
            "max": max(lat) if lat else None,
            "mean": round(statistics.fmean(lat), 1) if lat else None},
        "clock_skew_items": len(skew),
        "duplicates": {"same_link_repeated_in_feed": dups_in_feed,
                       "items_sharing_a_normalised_title": sum(
                           n for n in title_groups.values() if n > 1)},
        "mapping": dict(methods),
        "mapping_rate": round(sum(v for k, v in methods.items() if k != "UNRESOLVED")
                              / len(items), 3) if items else None,
        "categories": dict(cats.most_common()),
        "issues": dict(collections.Counter(i["kind"] for p in polls for i in p.get("issues", []))),
    }


def _ts(s: str) -> float:
    import datetime as _dt
    return _dt.datetime.fromisoformat(s).timestamp()
