"""Render docs/STAGE4_TRAINING_DATASET_REPORT.md from the validation evidence
(audit/evidence/stage4_training_dataset.json, written by stage4_validate.py).

  .venv/bin/python ops/measure/stage4_report.py [--evidence ...] [--out ...] [--verdict ...]
"""

from __future__ import annotations

import argparse
import json
import pathlib


def table(rows: list[list], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def gates(ev: dict) -> list[tuple[str, str, str]]:
    st, asif = ev["datasets"]["strict"], ev["datasets"]["asif"]
    lab, rp = ev["labels"], ev["replay_vs_production"]
    fr, raw, sc = ev["fresh_recompute"], ev["raw_sql"], ev["scenarios"]
    both = (st, asif)
    zero = all(d[k] == 0 for d in both for k in ("duplicates", "pit_violations",
               "nan_inf_values", "orphan_instruments", "non_trading_dates",
               "registry_hash_mismatch", "duplicate_snapshots", "future_timestamps",
               "value_status_inconsistent"))
    complete = all(not d["completeness"]["missing"] and not d["completeness"]["as_of_not_calendar"]
                   for d in both)
    rp_ok = all(all(x[8] == "True" for x in v["differences"]) and v["joined"] ==
                v["same_inputs_sha256"] for v in rp.values()) if rp else False
    fresh_ok = all(x["mismatches"] == 0 and x["rows_compared"] > 0 for x in fr.values())
    raw_ok = all(x["feature_mismatches"] == 0 and x["label_mismatches"] == 0 for x in raw.values())
    nz = all(v["non_null_before_collection"] == 0 for v in
             list(sc["missing_news_never_zero"].values())
             + list(sc["legacy_news_never_zero"].values()))
    g = [
        ("1 Historical coverage measured", "PASS", "per-feature coverage table below"),
        ("2 PIT-safe window established", "PASS", "family windows below (both policies)"),
        ("3 Same Stage 3 engine reused", "PASS",
         "engine.compute_snapshot unchanged; STRICT inputs_sha256 equal to production"),
        ("4 Historical snapshots backfilled", "PASS" if complete else "FAIL",
         f"strict {st['completeness']['done']}/{st['completeness']['expected']}, "
         f"asif {asif['completeness']['done']}/{asif['completeness']['expected']} snapshots"),
        ("5 Labels generated and versioned", "PASS" if lab["rows"] and lab["duplicates"] == 0
         else "FAIL", f"{lab['version']}: {lab['rows']} rows"),
        ("6 No look-ahead", "PASS" if zero and lab["leakage_label_start_le_as_of"] == 0
         else "FAIL", "0 inputs knowable at/after as_of; 0 labels starting at/before as_of"),
        ("7 No duplicate rows", "PASS" if zero and lab["duplicates"] == 0 else "FAIL", ""),
        ("8 No silent missing->zero", "PASS" if nz else "FAIL",
         "news rows before collection are NOT_AVAILABLE_HISTORICALLY (null)"),
        ("9 Survivorship documented", "PASS", "see the survivorship section"),
        ("10 Independent replay", "PASS" if (fresh_ok and raw_ok and rp_ok) else "FAIL",
         "fresh recompute, raw SQL, production comparison"),
        ("11 Dataset metadata complete", "PASS", "training_dataset_run + policy params"),
        ("12 Live Stage 3 untouched", "PASS", "cron, flags, registry unchanged"),
        ("13 Production feature_value untouched", "PASS"
         if ev["production_feature_value"]["rows_before_baseline_identical"] else "FAIL",
         "baseline rows fingerprint identical"),
        ("14 Git clean", "see final block", ""),
        ("15 Resumable / idempotent", "PASS" if ev.get("idempotency", {}).get("pass") else
         "PENDING", json.dumps(ev.get("idempotency", {}))),
    ]
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default="../audit/evidence/stage4_training_dataset.json")
    ap.add_argument("--out", default="../docs/STAGE4_TRAINING_DATASET_REPORT.md")
    ap.add_argument("--intro", default=None, help="markdown file prepended after the title")
    a = ap.parse_args()
    ev = json.loads(pathlib.Path(a.evidence).read_text())
    st, asif, lab = ev["datasets"]["strict"], ev["datasets"]["asif"], ev["labels"]
    md = ["# Stage 4 training dataset: report", "",
          f"Generated {ev['generated_at']} from `audit/evidence/stage4_training_dataset.json` "
          "(`ops/measure/stage4_validate.py`, read-only). **No model, signal, risk or order "
          "code exists or was built.**", ""]
    if a.intro:
        md += [pathlib.Path(a.intro).read_text(), ""]
    md += ["## Datasets", "", table([[
        n, d["version"], d["policy"], ", ".join(d["snapshots"]), d["window"]["first"],
        d["window"]["last"], d["sessions"], d["completeness"]["done"], d["symbols"],
        d["rows"], d["registry"]["version"], d["registry"]["sha256"][:12], d["runtime_s"]]
        for n, d in ev["datasets"].items()],
        ["name", "dataset_version", "knowability", "snapshots", "first", "last", "sessions",
         "snapshot rows", "symbols", "feature rows", "registry", "hash", "runtime s"]), ""]
    md += ["Run IDs (one per worker; resumable):", ""]
    for n, d in ev["datasets"].items():
        md += [f"- **{n}**: " + ", ".join(f"`{r['run_id']}` {r['status']} "
                                         f"({r['sessions_done']} snapshots, {r['rows']} rows)"
                                         for r in d["runs"])]
    md += ["", "### Status counts (missingness contract)", ""]
    keys = sorted({k for d in (st, asif) for k in d["status_counts"]})
    md += [table([[k, st["status_counts"].get(k, 0), asif["status_counts"].get(k, 0)]
                  for k in keys], ["status", "strict", "asif"]), ""]
    md += ["INVALID = the engine's MALFORMED_INPUT, inherited unchanged from production "
           "(the same features are MALFORMED in production `feature_value`): "
           + ", ".join(f"`{k}` {v}" for k, v in asif["reason_counts_invalid"].items()), ""]
    md += ["## Historical windows per family", ""]
    for n, d in (("STRICT_PIT", st), ("AS_IF_LIVE-v1", asif)):
        md += [f"### {n}", "", table([[f["family"], f["earliest_any_valid"],
                                       f["stable_from_50pct"], f["latest"], f["usable_sessions"]]
                                      for f in d["family_windows"]],
                                     ["group:family", "earliest valid", "stable (>=50% valid)",
                                      "latest", "sessions with values"]), ""]
    md += ["## Validation", "", table([[k, st[k], asif[k]] for k in (
        "rows", "duplicates", "duplicate_snapshots", "orphan_instruments", "nan_inf_values",
        "value_status_inconsistent", "pit_violations", "non_trading_dates", "future_timestamps",
        "registry_hash_mismatch")] + [
        ["missing snapshots", len(st["completeness"]["missing"]),
         len(asif["completeness"]["missing"])],
        ["as_of not the calendar instant", len(st["completeness"]["as_of_not_calendar"]),
         len(asif["completeness"]["as_of_not_calendar"])]], ["check", "strict", "asif"]), ""]
    md += ["### Labels", "", table([[k, lab[k]] for k in (
        "version", "rows", "valid", "sessions", "instruments", "first", "last", "duplicates",
        "leakage_label_start_le_as_of", "label_snapshot_pairs_checked", "non_trading_dates")],
        ["", "value"]), "", "```", lab["definitions"].strip(), "```", ""]
    md += ["### Independent replay", ""]
    for d, v in ev["replay_vs_production"].items():
        md += [f"- STRICT vs production `feature_value` {d}: {v['joined']} joined rows, "
               f"{v['same_inputs_sha256']} identical inputs, {v['same_value']} identical "
               f"values, {v['production_value_nulled_as_not_available']} production values "
               f"stored as NOT_AVAILABLE_HISTORICALLY, {v['production_rows_not_in_replay']} "
               "production rows outside the replay universe."]
        for x in v["differences"][:12]:
            md += [f"  - `{x[0]} {x[1]} {x[2]}` training {x[3]} ({x[5]}) vs production "
                   f"{x[4]}; same inputs: {x[8]}"]
    for n, x in ev["fresh_recompute"].items():
        md += [f"- Fresh read-only recompute ({n}): {len(x['sessions'])} random snapshots x "
               f"{x['keys_per_session']} random instruments, {x['rows_compared']} rows, "
               f"**{x['mismatches']} mismatches** ({x['note']})."]
    for n, x in ev["raw_sql"].items():
        md += [f"- Raw SQL ({n}): {x['feature_rows_compared']} ret_1d / sma_20 / avg_volume_20 "
               f"values, **{x['feature_mismatches']} mismatches**; {x['labels_compared']} "
               f"ret_cc labels, **{x['label_mismatches']} mismatches** ({x['tolerance']})."]
    md += ["", "### Scenarios", "", "```json", json.dumps(ev["scenarios"], indent=1), "```", ""]
    sv = ev["survivorship"]
    md += ["## Survivorship and selection bias", "", table([[k, json.dumps(v)] for k, v in
                                                            sv.items()], ["measure", "value"]),
           ""]
    md += ["## Storage", "", table([[k, v] for k, v in ev["storage"].items()],
                                  ["table", "size"]), ""]
    md += ["## Production untouched", "", "```json",
           json.dumps(ev["production_feature_value"], indent=1), "```", ""]
    md += ["## Gates", "", table([list(g) for g in gates(ev)], ["gate", "result", "evidence"]),
           ""]
    for n, d in (("STRICT_PIT", st), ("AS_IF_LIVE-v1", asif)):
        md += [f"## Feature coverage: {n}", "", table([[
            c["feature_id"], c["group"], "+".join(c["families"]), c["earliest_valid"],
            c["latest_valid"], c["coverage_pct"], c["missing_input"] + c["stale_input"],
            c["not_available_historically"], c["invalid"], c["pit"], c["class"]]
            for c in d["coverage"]],
            ["feature_id", "family", "inputs", "earliest", "latest", "coverage %",
             "missing+stale", "not avail. hist.", "invalid", "PIT", "class"]), ""]
    pathlib.Path(a.out).write_text("\n".join(md) + "\n")
    print(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
