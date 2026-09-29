"""Multi-source news acceptance gate (per source). Read-only; files + tests only.

A source PASSES only when every criterion is PASS - passing tests is never
enough. Its verdict unlocks nothing by itself: a database write additionally
needs the source's own flag, terms APPROVED, Stage 2 PASS and a token
(app.news.locks).

  EVIDENCE   DRY_RUN polls cover >= 1 full market session (weekday, 09:15-15:30 IST,
             no gap > 3x the expected interval; the expected interval is
             the configured one or the feed's own <ttl>, whichever is longer)
  LATENCY    >= 5 live discoveries with a publication time measured (latency is
             REPORTED, no threshold is invented); sources that publish a DATE only
             (SEBI) are NOT_MEASURABLE, which does not block
  HEALTH     no BLOCKED / AUTH_FAILED poll, < 20% failed polls in the session
  POLITENESS no gap between polls below 0.8x the source's minimum interval / ttl
  MAPPING    a human-reviewed sample (var/news/review/<SOURCE>.json, from
             `prajna news review-sample`) with every row judged and a
             false-positive rate <= 2% (PENDING until reviewed; never guessed)
  TERMS      the source's terms review is APPROVED (decision NEWS-COMPLIANCE)
  PIT        the news test suite passes (point-in-time, locks, parsers)
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import subprocess
import sys
from itertools import pairwise
from typing import Any

from app.core.clock import IST, now
from app.news.collector import BASE, DRYRUN_DIR
from app.news.report import _ts, load, summarise
from app.news.sources import SOURCES

REVIEW_DIR = BASE / "var" / "news" / "review"
MAX_FALSE_POSITIVE = 0.02
PASS, FAIL, PENDING, NA = "PASS", "FAIL", "PENDING", "NOT_MEASURABLE"


def run_tests() -> dict[str, Any]:
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:randomly", "tests/news"],
                       capture_output=True, text=True, timeout=1800)
    tail = [ln for ln in p.stdout.splitlines() if " passed" in ln or " failed" in ln]
    return {"exit": p.returncode, "summary": tail[-1] if tail else p.stdout[-300:]}


def market_sessions(polls: list[dict], interval_s: float) -> list[str]:
    """Weekdays whose 09:15-15:30 IST window is covered without a long gap."""
    by: dict[_dt.date, list[_dt.datetime]] = {}
    for p in polls:
        if p["outcome"] in ("OK", "NOT_MODIFIED"):
            t = _ts(p["finished_at"]).astimezone(IST)
            by.setdefault(t.date(), []).append(t)
    out = []
    for d, ts in sorted(by.items()):
        if d.weekday() >= 5:
            continue
        start = _dt.datetime.combine(d, _dt.time(9, 15), tzinfo=IST)
        end = _dt.datetime.combine(d, _dt.time(15, 30), tzinfo=IST)
        pts = sorted([start - _dt.timedelta(seconds=1)] + [t for t in ts if start <= t <= end]
                     + [end])
        inside = [t for t in ts if start <= t <= end]
        gaps = [(b - a).total_seconds() for a, b in pairwise(pts)]
        if inside and max(gaps) <= 3 * interval_s:
            out.append(str(d))
    return out


def feed_ttl_s(polls: list[dict], d: pathlib.Path) -> int:
    """The feed's declared <ttl> in seconds: from the newest poll that recorded it,
    else the collector's saved state; 0 when the feed declares none."""
    for p in reversed(polls):
        if p.get("ttl_s"):
            return int(p["ttl_s"])
    try:
        return int(json.loads((d / "state.json").read_text()).get("http", {}).get("ttl_s") or 0)
    except (OSError, ValueError):
        return 0


def review(key: str) -> tuple[str, dict[str, Any]]:
    p = REVIEW_DIR / f"{key}.json"
    if not p.exists():
        return PENDING, {"reason": f"no reviewed mapping sample ({p.name}); run "
                                   f"`prajna news review-sample --source {key}` and judge it"}
    rows = json.loads(p.read_text()).get("rows", [])
    judged = [r for r in rows if r.get("correct") in (True, False)]
    if not rows or len(judged) < len(rows):
        return PENDING, {"rows": len(rows), "judged": len(judged)}
    fp = sum(1 for r in judged if r["correct"] is False)
    rate = fp / len(judged)
    return (PASS if rate <= MAX_FALSE_POSITIVE else FAIL,
            {"rows": len(judged), "false_positives": fp, "rate": round(rate, 4)})


def evaluate_source(key: str, tests: dict | None, at: _dt.datetime | None = None
                    ) -> dict[str, Any]:
    src = SOURCES[key]
    d = DRYRUN_DIR / key
    polls, items, _ = load(d) if d.exists() else ([], [], [])
    # the collector never polls faster than the feed's <ttl> (BusinessLine: 60 min), so
    # coverage is judged against the interval actually allowed, not the configured one
    ttl = feed_ttl_s(polls, d) if d.exists() else 0
    interval = max(src.market_interval_s, ttl, 60)
    rep = summarise(d, expected_interval_s=max(src.off_interval_s, 300), at=at) if polls else {}
    crit: dict[str, dict[str, Any]] = {}
    sessions = market_sessions(polls, interval)
    crit["EVIDENCE"] = {"status": PASS if sessions else PENDING,
                        "evidence": {"full_market_sessions": sessions, "polls": len(polls),
                                     "expected_interval_s": interval, "feed_ttl_s": ttl or None}}
    disc = (rep.get("latency") or {}).get("discovery_s", {}).get("all", {"n": 0})
    live_with_time = disc["n"]
    date_only = bool(items) and all(i["published_at"] is None for i in items)
    crit["LATENCY"] = {"status": NA if date_only else (PASS if live_with_time >= 5 else PENDING),
                       "evidence": {"discovery_s": disc, "market_hours": (rep.get("latency") or {})
                                    .get("discovery_s", {}).get("market_hours")}}
    blocked = [p for p in polls if p["outcome"] in ("BLOCKED", "AUTH_FAILED")]
    failed = sum(1 for p in polls if p["outcome"] not in ("OK", "NOT_MODIFIED"))
    crit["HEALTH"] = {"status": FAIL if blocked else (
        PASS if polls and failed / len(polls) < 0.2 else PENDING),
        "evidence": {"blocked": len(blocked), "failed": failed, "polls": len(polls),
                     "health_now": rep.get("health")}}
    # judged on the market-session day used as evidence (earlier days are reported)
    day = sessions[-1] if sessions else None
    starts = sorted(_ts(p["started_at"]) for p in polls
                    if day and str(_ts(p["started_at"]).astimezone(IST).date()) == day)
    min_gap = min(((b - a).total_seconds() for a, b in pairwise(starts)), default=None)
    floor = 0.8 * max(min(src.market_interval_s, src.off_interval_s), ttl)
    crit["POLITENESS"] = {"status": PENDING if min_gap is None else (
        PASS if min_gap >= floor else FAIL),
        "evidence": {"session_day": day, "min_gap_s": min_gap, "floor_s": floor}}
    st, ev = review(key)
    crit["MAPPING"] = {"status": st, "evidence": ev}
    crit["TERMS"] = {"status": PASS if src.compliance == "APPROVED" else PENDING,
                     "evidence": {"terms": src.compliance}}
    crit["PIT"] = {"status": PENDING if tests is None else (PASS if tests["exit"] == 0 else FAIL),
                   "evidence": tests or {"note": "run with --run-tests"}}
    sts = [c["status"] for c in crit.values()]
    status = FAIL if FAIL in sts else (PASS if all(x in (PASS, NA) for x in sts) else PENDING)
    return {"source": key, "status": status, "criteria": crit,
            "summary": {k: rep.get(k) for k in ("items", "live_items", "backlog_items",
                                                "mapping_rate", "unresolved", "stories",
                                                "assessment", "content_fetch_status",
                                                "rate_limit_events", "errors")}}


def evaluate(tests: dict | None) -> dict[str, Any]:
    at = now()
    srcs = {k: evaluate_source(k, tests, at) for k, s in SOURCES.items()
            if s.parse is not None and s.status != "UNSUPPORTED"}
    unsupported = {k: s.note for k, s in SOURCES.items() if s.status == "UNSUPPORTED"}
    return {"generated_at": at.isoformat(), "sources": srcs, "unsupported": unsupported,
            "overall": "PASS" if srcs and all(v["status"] == "PASS" for v in srcs.values())
            else "NOT PASSED",
            "note": "a PASS unlocks nothing by itself: writes also need the per-source flag, "
                    "terms APPROVED, Stage 2 PASS and a token"}


def to_markdown(rep: dict[str, Any]) -> str:
    L = ["# Multi-source news acceptance", "",
         f"**Generated:** {rep['generated_at']} by `prajna acceptance news` (read-only; "
         "regenerate, do not edit).", "", f"## Overall: **{rep['overall']}**", "",
         rep["note"] + ".", "", "| Source | Status | " + " | ".join(
             ("EVIDENCE", "LATENCY", "HEALTH", "POLITENESS", "MAPPING", "TERMS", "PIT")) + " |",
         "|---|---|" + "---|" * 7]
    for k, v in rep["sources"].items():
        L.append(f"| {k} | **{v['status']}** | " + " | ".join(
            v["criteria"][c]["status"] for c in ("EVIDENCE", "LATENCY", "HEALTH", "POLITENESS",
                                                 "MAPPING", "TERMS", "PIT")) + " |")
    L += ["", "## Per source", ""]
    for k, v in rep["sources"].items():
        L += [f"### {k}: {v['status']}", "", "```json",
              json.dumps({"criteria": v["criteria"], "summary": v["summary"]}, indent=1,
                         default=str)[:6000], "```", ""]
    L += ["## Unsupported", ""] + [f"- {k}: {n}" for k, n in rep["unsupported"].items()]
    return "\n".join(L) + "\n"


def review_sample(key: str, n: int = 50) -> pathlib.Path:
    """Write a sample of this source's MAPPED items for a human to judge
    (set "correct": true/false per row). Existing judgements are never overwritten."""
    out = REVIEW_DIR / f"{key}.json"
    if out.exists():
        return out
    _, items, _ = load(DRYRUN_DIR / key)
    mapped = [i for i in items
              if any(ln.get("instrument_key") for ln in i.get("links", [i["link"]]))]
    step = max(1, len(mapped) // n)
    rows = [{"id": i["id"], "title": i["title"],
             "links": [{"instrument_key": ln["instrument_key"], "method": ln["method"],
                        "matched": ln["matched_text"]}
                       for ln in i.get("links", [i["link"]]) if ln.get("instrument_key")],
             "correct": None} for i in mapped[::step][:n]]
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": key, "instructions": "set correct=true when every link "
                               "names the company the item is about, else false",
                               "rows": rows}, indent=1))
    return out
