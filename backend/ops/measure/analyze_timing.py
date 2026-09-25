"""B1/B2 verdict from the poller logs (var/measure/candle_timing_*.jsonl). Read-only.

    .venv/bin/python ops/measure/analyze_timing.py [--out var/acceptance/b1b2.json]

Every logged response was archived (sha in the log line), so each number here
can be re-derived from the archive.

B2, per trading session and timeframe (intraday endpoint, polled every 6 s for
1m and every 60 s for 5m/15m/1h):
  first_seen_lag  first fetch that listed the bar minus its END (bar start +
                  width); negative = served before the bar ended (forming)
  changed         the bar's OHLCV differed between polls after it was first seen
B1, per session D (historical endpoint, 1D): the last poll without D's bar,
  the first poll with it, and whether its values changed afterwards.

RULE (unchanged, set before any measurement): VERIFIED needs >= 3 sessions,
and all of them agreeing (a disagreeing session makes the contract CONTRADICTED,
with the broken clause per session - more sessions cannot verify it):
  B2  1m is never served before its end and never changes once listed
      (5m/15m/1h forming/settling behaviour is reported, and the ingest's
      completion margin must exceed the largest post-end change observed);
  B1  a session's daily bar is never on the historical endpoint on the
      session's own IST date, and never changes once listed.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import glob
import json
import pathlib
import statistics as st
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.contracts import timing as T
from app.core.clock import IST

WIDTH = {"1m": 60, "5m_intraday": 300, "15m_intraday": 900, "1h_intraday": 3600}
TF = {"1m": "1m", "5m_intraday": "5m", "15m_intraday": "15m", "1h_intraday": "1h"}
MIN_SESSIONS = 3


def load(paths):
    for p in sorted(paths):
        for line in open(p):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "fetched_at" in d and "newest" in d:
                yield d


def analyze(paths) -> dict:
    lines = list(load(paths))
    seen: dict = {}                       # (kind, key, ts) -> first fetched
    vals: dict = collections.defaultdict(list)
    b1_first: dict = {}
    b1_last_absent: dict = {}
    b1_vals: dict = collections.defaultdict(set)
    for d in sorted(lines, key=lambda x: x["fetched_at"]):
        f = _dt.datetime.fromisoformat(d["fetched_at"])
        kind, key = d["kind"], d["key"]
        if kind in WIDTH:
            for c in d["newest"]:
                k = (kind, key, c[0])
                seen.setdefault(k, f)
                vals[k].append((f, tuple(c[1:6])))
        elif kind == "1d_hist":
            present = {c[0][:10] for c in d["newest"]}
            for c in d["newest"]:
                b1_vals[(key, c[0][:10])].add(tuple(c[1:6]))
                b1_first.setdefault((key, c[0][:10]), f)
            ist_day = f.astimezone(IST).date()
            for back in range(0, 5):
                day = (ist_day - _dt.timedelta(days=back)).isoformat()
                if day not in present and (key, day) not in b1_first:
                    b1_last_absent[(key, day)] = f

    b2: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    revisions: list[dict] = []            # every value change seen after a bar's end
    for (kind, key, ts), f in seen.items():
        start = _dt.datetime.fromisoformat(ts)
        session = start.astimezone(IST).date().isoformat()
        lag = (f - start).total_seconds() - WIDTH[kind]
        obs = vals[(kind, key, ts)]
        changed = len({v for _, v in obs}) > 1
        # the latest fetch at which a DIFFERENT value was seen, after the bar end
        end = start + _dt.timedelta(seconds=WIDTH[kind])
        post = [(t - end).total_seconds() for (t, v), (_, pv) in zip(obs[1:], obs[:-1], strict=True)
                if v != pv and t > end]
        b2[session][kind].append((lag, changed, max(post) if post else None))
        for sec in post:
            revisions.append({"timeframe": TF[kind], "key": key, "bar_start": ts,
                              "session": session, "first_seen": f.isoformat(),
                              "seconds_after_end": round(sec, 1)})
    b2_out = {}
    for session, kinds in sorted(b2.items()):
        b2_out[session] = {}
        for kind, xs in sorted(kinds.items()):
            # only bars whose end fell inside the polling (lag < 10 min) measure latency
            lags = [lag for lag, _, _ in xs if lag < 600]
            post = [p for _, _, p in xs if p is not None]
            b2_out[session][kind] = {
                "bars": len(xs), "measured": len(lags),
                "served_before_end": sum(1 for lag in lags if lag < 0),
                "changed_after_first_seen": sum(1 for _, ch, _ in xs if ch),
                "changed_after_end": len(post),
                "max_change_after_end_s": round(max(post), 1) if post else None,
                "lag_s": {"min": round(min(lags), 1), "median": round(st.median(lags), 1),
                          "max": round(max(lags), 1)} if lags else None}
    b1_out = {}
    for (key, day), f in sorted(b1_first.items()):
        la = b1_last_absent.get((key, day))
        b1_out.setdefault(day, {})[key] = {
            "last_absent": la.astimezone(IST).isoformat() if la else None,
            "first_present": f.astimezone(IST).isoformat(),
            "first_present_ist_date_after_session": f.astimezone(IST).date().isoformat() > day,
            "changed_after_first_seen": len(b1_vals[(key, day)]) > 1}

    # sessions that the poller observed from before their bars appeared
    b1_sessions = {d: v for d, v in b1_out.items()
                   if all(x["last_absent"] is not None for x in v.values())}
    b1_ok = [d for d, v in b1_sessions.items() if all(
        x["first_present_ist_date_after_session"] and not x["changed_after_first_seen"]
        for x in v.values())]
    full_b2 = {d: v for d, v in b2_out.items() if v.get("1m", {}).get("measured", 0) >= 300}
    margin = 120.0                        # the ORIGINAL B2 wording
    b2_ok = [d for d, v in full_b2.items() if v["1m"]["served_before_end"] == 0
             and v["1m"]["changed_after_first_seen"] == 0
             and all((x.get("max_change_after_end_s") or 0) < margin
                     for k, x in v.items() if k != "1m")]
    b1_verified = len(b1_sessions) >= MIN_SESSIONS and len(b1_ok) == len(b1_sessions)
    b2_verified = len(full_b2) >= MIN_SESSIONS and len(b2_ok) == len(full_b2)
    # which clause each disagreeing session breaks: a contradicted contract cannot
    # become VERIFIED by waiting for more sessions (the rule is all-agreeing)
    b1_breaks = {d: [f"{k}: " + ("present on the session's own IST date"
                                 if not x["first_present_ist_date_after_session"]
                                 else "changed after first seen")
                     for k, x in v.items() if not x["first_present_ist_date_after_session"]
                     or x["changed_after_first_seen"]]
                 for d, v in b1_sessions.items() if d not in b1_ok}
    b2_breaks = {}
    for d, v in full_b2.items():
        if d in b2_ok:
            continue
        why = []
        if v["1m"]["served_before_end"]:
            why.append(f"1m served before its end: {v['1m']['served_before_end']} bars")
        if v["1m"]["changed_after_first_seen"]:
            why.append(f"1m changed after first seen: {v['1m']['changed_after_first_seen']} bars "
                       f"(latest {v['1m']['max_change_after_end_s']} s after the end)")
        why += [f"{k} changed {x['max_change_after_end_s']} s after the end (margin {margin:.0f} s)"
                for k, x in v.items() if k != "1m"
                and (x.get("max_change_after_end_s") or 0) >= margin]
        b2_breaks[d] = why

    def status(verified: bool, breaks: dict) -> str:
        return "CONTRADICTED" if breaks else ("VERIFIED" if verified else "UNVERIFIED")

    # REVISED B2 (decision TIMING-B2, 2026-09-25): a candle is timing-final from
    # bar_end + margin(timeframe); a revision at or after that is LATE and
    # contradicts the contract (never absorbed by enlarging the margin).
    stats = {}
    for kind, tf in TF.items():
        bars = [(s_, x) for s_, kinds in b2.items() for k_, xs in kinds.items() if k_ == kind
                for x in xs]
        lat = sorted(r["seconds_after_end"] for r in revisions if r["timeframe"] == tf)

        def q(p, lat=lat):
            return lat[min(len(lat) - 1, int(p * (len(lat) - 1) + 0.5))] if lat else None
        observed_max = lat[-1] if lat else None
        stats[tf] = {
            "in_scope": tf in T.IN_SCOPE, "margin_s": T.margin(tf).total_seconds(),
            "bars_sampled": len(bars),
            "sessions_sampled": sorted({s_ for s_, _ in bars}),
            "instruments_sampled": sorted({k[1] for k in seen if k[0] == kind}),
            "revision_events_after_end": len(lat),
            "bars_revised_after_end": len({(r["key"], r["bar_start"]) for r in revisions
                                           if r["timeframe"] == tf}),
            "revision_latency_s": {"p95": q(0.95), "p99": q(0.99), "max": observed_max},
            "headroom_s": T.headroom_s(tf, observed_max),
            "late_revisions": sum(1 for x in lat if x >= T.margin(tf).total_seconds())}
    late = [r for r in revisions if r["timeframe"] in T.IN_SCOPE
            and T.Revision(r["timeframe"], r["seconds_after_end"]).late]
    b2r_sessions = sorted(full_b2)
    b2r_bad = sorted({r["session"] for r in late})
    b2_revised = {
        "contract": "timing-final from bar_end + completion_margin(timeframe); a later "
                    "revision contradicts it (explicit review, margin never enlarged "
                    "silently); knowable_at stays the fetch time",
        "margin_basis": T.BASIS,
        "status": ("CONTRADICTED" if late else
                   ("VERIFIED" if len(b2r_sessions) >= MIN_SESSIONS else "UNVERIFIED")),
        "sessions_observed": b2r_sessions,
        "sessions_agreeing": [d for d in b2r_sessions if d not in b2r_bad],
        "sessions_disagreeing": {d: [f"{r['timeframe']} {r['key']} {r['bar_start']} revised "
                                     f"{r['seconds_after_end']} s after the end (margin "
                                     f"{T.margin(r['timeframe']).total_seconds():.0f} s)"
                                     for r in late if r["session"] == d] for d in b2r_bad},
        "late_revisions": late,
        "per_timeframe": stats,
        "evidence_sufficiency": (
            f"{len(b2r_sessions)} full session(s), "
            f"{len(stats['1m']['instruments_sampled'])} instrument(s); the margin is an "
            "engineering threshold, not a statistically established bound"),
    }
    return {
        "rule": {"min_sessions": MIN_SESSIONS,
                 "completion_margin_s": dict(T.COMPLETION_MARGIN_S)},
        "B1": {"status": status(b1_verified, b1_breaks),
               "sessions_observed": sorted(b1_sessions), "sessions_agreeing": sorted(b1_ok),
               "sessions_disagreeing": b1_breaks,
               "per_session": b1_out},
        "B2": {**b2_revised, "per_session": b2_out},
        "B2_original": {"contract": "1m never served before its end and never changed once "
                                    "listed; other timeframes settle inside 120 s",
                        "status": status(b2_verified, b2_breaks),
                        "superseded_by": "decision TIMING-B2 (2026-09-25)",
                        "sessions_observed": sorted(full_b2), "sessions_agreeing": sorted(b2_ok),
                        "sessions_disagreeing": b2_breaks},
        "source_logs": sorted(paths), "lines": len(lines),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="var/acceptance/b1b2.json")
    a = ap.parse_args()
    rep = analyze(glob.glob("var/measure/candle_timing_*.jsonl"))
    pathlib.Path(a.out).write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps({k: rep[k] for k in ("B1", "B2")}, indent=1, default=str)[:4000])
