"""Read-only measurement (2026-10-22): how late do items appear in an RSS feed after their
own pubDate? Polls each feed every INTERVAL seconds for MINUTES and records, per new item,
first_seen - pubDate. No database write; output JSON on stdout.

    .venv/bin/python ops/measure/rss_latency.py MINUTES URL [URL ...]
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import re
import sys
import time
import urllib.request

INTERVAL = 120
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def items(url: str) -> dict[str, dt.datetime]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    out = {}
    for block in re.findall(r"<item>(.*?)</item>", t, re.S):
        g = re.search(r"<(?:guid|link)[^>]*>([^<]+)</", block)
        p = re.search(r"<pubDate>([^<]+)</pubDate>", block)
        if g and p:
            try:
                out[g.group(1).strip()] = email.utils.parsedate_to_datetime(p.group(1))
            except (TypeError, ValueError):
                pass
    return out


def main() -> None:
    minutes, urls = int(sys.argv[1]), sys.argv[2:]
    seen = {u: set(items(u)) for u in urls}          # items already there are not measured
    delays: dict[str, list[float]] = {u: [] for u in urls}
    end = time.time() + minutes * 60
    while time.time() < end:
        time.sleep(INTERVAL)
        now = dt.datetime.now(dt.timezone.utc)
        for u in urls:
            try:
                cur = items(u)
            except OSError:
                continue
            for g, pub in cur.items():
                if g not in seen[u]:
                    seen[u].add(g)
                    delays[u].append((now - pub).total_seconds() / 60)
    out = {}
    for u, d in delays.items():
        d.sort()
        out[u] = {"new_items": len(d), "median_min": round(d[len(d) // 2], 1) if d else None,
                  "max_min": round(d[-1], 1) if d else None,
                  "note": f"polled every {INTERVAL}s, so up to {INTERVAL // 60} min is polling"}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
