"""Generate docs/STAGE_3_FEATURE_AUDIT.md from the registry, the engine source and
the Stage 3 tests (read only; no database).

    .venv/bin/python -m app.features.audit_doc > ../docs/STAGE_3_FEATURE_AUDIT.md

Only facts the code states are written. Per feature: the registry entry, the
compute function(s) found in app/features/engine.py, and the tests that name the
feature id or call that compute function (found by parsing tests/stage3). The
per-input facts (source, timestamps, missing input, corporate actions) are
stated once per input kind, each with the code that implements it. Properties
common to all features cite tests that are verified to exist; generation fails
if one is missing, so the document cannot cite a test that is not there.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

from app.features.registry import FEATURES, REGISTRY_SHA256, VERSION

BACKEND = pathlib.Path(__file__).resolve().parents[2]
ENGINE = BACKEND / "app" / "features" / "engine.py"
TESTS = BACKEND / "tests" / "stage3"
MODULES = ("PR", "LQ", "FU", "EV", "PO", "CX")

# input kind -> (Stage 1 table -> Stage 2 view -> reader, timeframe, input timestamp,
#                knowable_at, missing / malformed, corporate actions)
INPUTS: dict[str, tuple[str, str, str, str, str, str]] = {
    "daily_bars": (
        "ohlcv_bar -> canon_market_bar (trading sessions, included instruments) -> "
        "pit.bars_adjusted (app/features/inputs.py instrument_inputs)",
        "1d; bars with market_date < session (up to 450 calendar days back)",
        "the session (canon event open..close IST)",
        "Stage 1 bar knowable_at; only rows with knowable_at < as_of",
        "previous session's bar not knowable -> MISSING_INPUT for every bar feature "
        "(InstrumentInputs.stale; an older bar is never relabelled); fewer bars than the "
        "lookback -> INSUFFICIENT_HISTORY",
        "split/bonus-adjusted with EXACT ca_factor rows knowable < as_of; LOW-confidence and "
        "RECONSTRUCTED rows refused and counted, never used (pit.bars_adjusted)"),
    "nifty_bars": (
        "ohlcv_bar -> canon_market_bar -> pit.bars (inputs.index_bars, NSE_INDEX|Nifty 50)",
        "1d, market_date < session", "the session", "bar knowable_at < as_of",
        "beta uses common dates only; too few -> INSUFFICIENT_HISTORY",
        "none needed (an index has no corporate actions)"),
    "key_ratios": (
        "fundamental_snapshot -> canon_fundamental -> pit.fundamentals (latest snapshot per "
        "statement type knowable < as_of)",
        "vendor snapshot (no bar timeframe)", "fetch time of the snapshot",
        "fetch time (basis 'fetched'); knowable_at < as_of",
        "no snapshot -> MISSING_INPUT; unparseable -> MALFORMED_INPUT",
        "not applicable (vendor ratios as published)"),
    "income_yearly": (
        "fundamental_snapshot (income:consolidated:yearly) -> canon_fundamental -> "
        "pit.fundamentals", "fiscal years inside the payload", "fetch time of the snapshot",
        "fetch time; knowable_at < as_of (a late statement is invisible until fetched)",
        "none -> MISSING_INPUT; malformed -> MALFORMED_INPUT; < 2 years -> "
        "INSUFFICIENT_HISTORY; base <= 0 -> DIVISION_UNDEFINED", "not applicable"),
    "income_quarterly": (
        "fundamental_snapshot (income:consolidated:quarterly) -> canon_fundamental -> "
        "pit.fundamentals", "quarters inside the payload", "fetch time of the snapshot",
        "fetch time; knowable_at < as_of",
        "none -> MISSING_INPUT; annual periods labelled quarterly -> MALFORMED_INPUT; no "
        "same quarter a year earlier -> INSUFFICIENT_HISTORY; base <= 0 -> "
        "DIVISION_UNDEFINED", "not applicable"),
    "balance_sheet": (
        "fundamental_snapshot (balance_sheet:consolidated) -> canon_fundamental -> "
        "pit.fundamentals", "latest fiscal year in the payload", "fetch time of the snapshot",
        "fetch time; knowable_at < as_of", "none -> MISSING_INPUT; malformed -> "
        "MALFORMED_INPUT", "not applicable"),
    "corporate_actions": (
        "corporate_action -> canon_corporate_action -> pit.corporate_actions",
        "event ex-dates vs the session date", "ex_date (the event); announcement recorded",
        "Stage 1 knowable_at (basis KN-CA); only events knowable < as_of",
        "no matching event -> MISSING_INPUT", "these ARE the corporate actions"),
    "news": (
        "news_article + news_instrument (Upstox) -> canon_news -> pit.news (since as_of - 8 d)",
        "published_at within [as_of - window, as_of)", "published_at",
        "greatest(article, vendor link) knowable_at < as_of",
        "no linked news -> count 0.0 (a real zero only if Upstox news ingestion ran; the "
        "feature does not prove coverage); hours since last -> MISSING_INPUT",
        "not applicable"),
    "fii_dii": (
        "macro_observation -> canon_macro_observation -> pit.macro (inputs.macro_rows, "
        "FII|/DII| NSE cash series)", "1 trading day per observation",
        "observation_date (the trading day)", "fetch time; knowable_at < as_of",
        "v2 (FII-DII-STALENESS): latest observation != previous session -> MISSING_INPUT; one "
        "side only -> MALFORMED_INPUT; < n days -> INSUFFICIENT_HISTORY", "not applicable"),
    "global_bars": (
        "ohlcv_bar -> canon_global_bar -> pit.global_bars (CONFIRMED labels only; the 2 "
        "latest)", "1d label", "label date", "knowable_at < as_of",
        "< 2 labels -> INSUFFICIENT_HISTORY; base <= 0 -> DIVISION_UNDEFINED",
        "not applicable"),
    "sector": (
        "fundamental_snapshot (profile) -> pit.sector (latest profile knowable < as_of; "
        "never today's canon_instrument.sector) + members' ret_20d",
        "20 sessions", "profile fetch time; member bars as daily_bars",
        "knowable_at < as_of", "no sector -> MISSING_INPUT; < 3 members -> "
        "INSUFFICIENT_HISTORY; stale stock -> MISSING_INPUT", "as daily_bars"),
    "preopen": (
        "preopen_tick -> canon_preopen -> pit.preopen (market_date = session; last tick "
        "before as_of)", "the session's pre-open window",
        "vendor currentTs of the tick", "receipt time (basis currentTs); knowable_at < as_of",
        "no tick -> MISSING_INPUT; bad fields -> MISSING_INPUT; zero denominators -> "
        "DIVISION_UNDEFINED", "previous close (for the gap) as daily_bars"),
}
CONTEXT_INDEX = ("ohlcv_bar -> canon_market_bar -> pit.bars (inputs.index_bars: NIFTY 50, "
                 "NIFTY BANK, India VIX)", "1d, market_date < session", "the session",
                 "bar knowable_at < as_of",
                 "previous session's bar not knowable -> MISSING_INPUT (engine._index_stale); "
                 "too few bars -> INSUFFICIENT_HISTORY", "none needed (indices)")

# properties common to every feature -> the tests that demonstrate them (checked)
COMMON: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Look-ahead", "every reader filters knowable_at < as_of (app.canon.pit asserts it); "
     "inputs._track raises LookAhead; compute_snapshot re-checks every row; the "
     "ck_feature_pit CHECK refuses input_max_knowable_at >= as_of",
     ("test_look_ahead_probe", "test_knowable_boundary_one_microsecond",
      "test_an_overclaiming_input_fails_loud", "test_storage_is_append_only_and_pit_checked",
      "test_late_bar_revision_is_never_used",
      "test_previous_session_bar_first_observed_after_as_of",
      "test_revised_corporate_action_known_after_as_of", "test_delayed_financial_statement",
      "test_india_vix_previous_session_missing",
      "test_publication_after_as_of_is_not_used_and_no_older_day_is_relabelled")),
    ("Reason contract", "a value XOR a reason code (ck_feature_value_or_reason); non-finite "
     "numbers are never values", ("test_normal_path", "test_non_finite_is_never_a_value",
                                  "test_unknown_reason_is_refused")),
    ("One snapshot", "compute, determinism check and persistence in one REPEATABLE READ "
     "transaction (engine.consistent_read); a run without it is refused",
     ("test_a_commit_during_the_run_is_not_observed",
      "test_the_production_session_sets_repeatable_read_itself",
      "test_a_run_refuses_without_a_consistent_snapshot")),
    ("Persistence", "feature_value, one row per (instrument_key, session_date, snapshot, "
     "feature_id), carrying feature_version, registry_sha256, inputs_sha256, "
     "input_max_knowable_at, run_id; append-only (trigger); one commit per snapshot; "
     "INSERT batches sized from a bind-parameter budget (15 per row, 2,000 rows, 30,000 < "
     "asyncpg's 32,767)",
     ("test_run_writes_then_rerun_is_idempotent", "test_both_snapshots_are_separate_rows",
      "test_storage_is_append_only_and_pit_checked",
      "test_bind_parameters_per_row_are_counted_from_the_real_statement",
      "test_rows_across_several_batches_persist_then_rerun_is_idempotent")),
    ("Idempotency", "insert on conflict do nothing, then every stored row compared to the "
     "recompute; a difference fails the run and nothing is overwritten",
     ("test_run_writes_then_rerun_is_idempotent", "test_determinism_mismatch_never_overwrites",
      "test_restart_resumes_without_duplicates")),
    ("Failure", "an exception rolls every value back (run FAILED); a crashed run is reaped; "
     "the kill switch stops a run mid-way with zero writes",
     ("test_exception_rolls_back_then_retry_succeeds",
      "test_crash_is_reaped_and_the_rerun_completes", "test_kill_switch_mid_run",
      "test_a_failure_after_a_batch_leaves_no_partial_snapshot")),
    ("Audit and locks", "one ingest_run per snapshot; stage3_event RUN_COMPLETE / RUN_FAILED "
     "/ REFUSED; every lock condition alone refuses a run", (
         "test_each_condition_alone_refuses_the_run", "test_bad_token_refuses",
         "test_defaults_refuse_everything", "test_backfill_needs_its_own_flag",
         "test_dry_run_needs_no_lock_and_writes_nothing")),
)


def _tests() -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    """-> (string constant -> tests, 'MOD.func' -> tests, all test names)."""
    by_str: dict[str, set[str]] = {}
    by_call: dict[str, set[str]] = {}
    names: set[str] = set()
    for p in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            names.add(node.name)
            tid = f"{p.stem}::{node.name}"
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    by_str.setdefault(sub.value, set()).add(tid)
                elif (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                      and sub.value.id in MODULES):
                    by_call.setdefault(f"{sub.value.id}.{sub.attr}", set()).add(tid)
    return by_str, by_call, names


def _key_regex(node: ast.AST) -> str | None:
    """A feature-id literal or f-string -> a regex matching the ids it can produce."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "^" + re.escape(node.value) + "$"
    if isinstance(node, ast.JoinedStr):
        return "^" + "".join(re.escape(v.value) if isinstance(v, ast.Constant) else "[a-z0-9]+"
                             for v in node.values) + "$"
    return None


def _calls(node: ast.AST) -> set[str]:
    return {f"{n.func.value.id}.{n.func.attr}" for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id in MODULES}


def _compute_fns() -> dict[str, set[str]]:
    """feature id -> the compute functions engine.py assigns to it (parsed, not guessed):
    out["id"] = F(...), out["a"], out["b"] = F(...), G(...), {"id": F(...)},
    ("id", F(...)) pairs and FeatureRow(scope, key, "id", *F(...))."""
    pairs: list[tuple[str, ast.AST]] = []
    for n in ast.walk(ast.parse(ENGINE.read_text())):
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            t, v = n.targets[0], n.value
            ts = t.elts if isinstance(t, ast.Tuple) else [t]
            vs = v.elts if isinstance(t, ast.Tuple) and isinstance(v, ast.Tuple) else [v] * len(ts)
            for ti, vi in zip(ts, vs, strict=False):
                if isinstance(ti, ast.Subscript) and (rx := _key_regex(ti.slice)):
                    pairs.append((rx, vi))
        elif isinstance(n, ast.Dict):
            pairs += [(rx, v) for k, v in zip(n.keys, n.values, strict=False)
                      if k is not None and (rx := _key_regex(k))]
        elif isinstance(n, ast.Tuple) and len(n.elts) == 2 and (rx := _key_regex(n.elts[0])):
            pairs.append((rx, n.elts[1]))
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "FeatureRow" and len(n.args) > 3
              and (rx := _key_regex(n.args[2]))):
            pairs += [(rx, x) for x in n.args[3:]]
    out: dict[str, set[str]] = {}
    for f in FEATURES:
        for rx, v in pairs:
            if re.match(rx, f.id) and (c := _calls(v)):
                out.setdefault(f.id, set()).update(c)
    out.setdefault("sector_rs_20", {"CX.sector_rs"})       # via a local result (_sector_rows)
    return out


def _cell(x: object) -> str:
    return str(x).replace("|", "\\|")


def render() -> str:
    by_str, by_call, names = _tests()
    fns = _compute_fns()
    missing = [t for _, _, ts in COMMON for t in ts if t not in names]
    if missing:
        raise SystemExit(f"cited tests not found: {missing}")
    L = [
        "# Stage 3 feature audit", "",
        f"**Generated** by `python -m app.features.audit_doc` from registry `{VERSION}` "
        f"(`REGISTRY_SHA256 {REGISTRY_SHA256}`), `app/features/engine.py` and "
        "`tests/stage3`. Regenerate, do not edit. Only what the code and tests show is "
        "claimed; the test columns list tests that name the feature id or call its "
        "compute function, found by parsing the test files.", "",
        f"**{len(FEATURES)} features**; snapshot as_of: PRE_SESSION = pre-open start - 1 s "
        "(08:59:59 IST), PRE_OPEN = pre-open start + 8 min (09:08:00 IST), from the "
        "trading calendar (app/features/snapshots.py). Every input must satisfy "
        "`knowable_at < as_of`.", "",
        "## Properties common to all features", "",
        "| Property | What the code does | Demonstrated by |", "|---|---|---|"]
    for name, what, ts in COMMON:
        L.append(f"| {name} | {_cell(what)} | {', '.join(f'`{t}`' for t in ts)} |")
    L += ["", "## Inputs", "",
          "| Input | Source (Stage 1 -> Stage 2 -> reader) | Timeframe | Input timestamp | "
          "knowable_at | Missing / malformed | Corporate actions |",
          "|---|---|---|---|---|---|---|"]
    for k, v in INPUTS.items():
        L.append(f"| `{k}` | " + " | ".join(map(_cell, v)) + " |")
    L.append("| context index bars | " + " | ".join(map(_cell, CONTEXT_INDEX)) + " |")
    L += ["", "## Features", "",
          "| # | Feature | v | Group | Scope | Snapshots | Definition | Inputs | Lookback "
          "(sessions) | Params | Compute | Tests (value / behaviour) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    untested = []
    for i, f in enumerate(FEATURES, 1):
        inputs = ("context index bars" if f.scope == "CONTEXT" and f.inputs == ("daily_bars",)
                  else ", ".join(f"`{x}`" for x in f.inputs))
        fn = sorted(fns.get(f.id, ()))
        tests = set(by_str.get(f.id, ()))
        for c in fn:
            tests |= by_call.get(c, set())
        if not tests:
            untested.append(f.id)
        L.append(f"| {i} | `{f.id}` | {f.version} | {f.group} | {f.scope} | "
                 f"{'/'.join(f.snapshots)} | {_cell(f.definition)} | {inputs} | "
                 f"{f.lookback_sessions or '-'} | "
                 f"{_cell(', '.join(f'{k}={v}' for k, v in f.params.items()) or '-')} "
                 f"({f.param_status}) | {', '.join(f'`{c}`' for c in fn) or 'engine'} | "
                 f"{'<br>'.join(f'`{t}`' for t in sorted(tests)) or '**none found**'} |")
    L += ["", "## Test mapping summary", "",
          f"- features with at least one value/behaviour test: "
          f"{len(FEATURES) - len(untested)} of {len(FEATURES)}",
          "- features with none found by the parser: "
          + (", ".join(f"`{x}`" for x in untested) or "none"),
          "- every feature is additionally covered by the common-property tests above "
          "(each run computes and stores the full feature set of each snapshot)", ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.stdout.write(render())
