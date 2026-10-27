"""Every strategy the lab reports on. Families: P1 (shadow, frozen p1-shadow-v1), PAPER
(the Stage 5-8 paper book), E5 (the frozen ML model's forward picks, valued open->close),
E6 (the post-results paper monitor). `switchable`: the admin switch is enforced by the
strategy's own job (paper_daily.sh, shadow daily). E5/E6 are reported, not switched."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Strategy:
    name: str
    family: str
    kind: str                 # SHADOW / PAPER / MONITOR
    switchable: bool
    tool: str                 # TREND / RANGE / GAP / RANDOM / MODEL / EVENT
    title: str
    title_hi: str
    look: str | None          # the pre-registered look(s), if any
    default_on: bool = True   # the state before any switch row (what was scheduled)


STRATEGIES: tuple[Strategy, ...] = (
    Strategy("orb_breadth_core_v1", "P1", "SHADOW", True, "TREND",
             "S1 opening-range breakout (core: Varsity rules, RRR >= 1.5)",
             "S1 breakout, core (sirf Varsity rules)", "60 / 250 sessions"),
    Strategy("orb_breadth_strict_v1", "P1", "SHADOW", True, "TREND",
             "S1 opening-range breakout (strict: core + the 7 checklist rules)",
             "S1 breakout, strict (core + checklist)", "60 / 250 sessions"),
    Strategy("vwap_revert_core_v1", "P1", "SHADOW", True, "RANGE",
             "S2 mean reversion to VWAP / band middle (core)",
             "S2 average par wapsi, core", "60 / 250 sessions"),
    Strategy("vwap_revert_strict_v1", "P1", "SHADOW", True, "RANGE",
             "S2 mean reversion to VWAP / band middle (strict)",
             "S2 average par wapsi, strict", "60 / 250 sessions"),
    Strategy("baseline_gap_fade", "PAPER", "PAPER", True, "GAP",
             "Gap fade: buy the 10 largest gap-downs at the open, sell at the close",
             "Gap fade: 10 sabse bade gap-down open par kharido, close par becho", None),
    Strategy("bench_c0", "PAPER", "PAPER", True, "RANDOM",
             "Benchmark: 10 random names, open to close, never halted",
             "Benchmark: 10 random stocks, open se close", None),
    Strategy("baseline_c0", "PAPER", "PAPER", True, "RANDOM",
             "Random baseline with the paper risk halts",
             "Random baseline (risk halts ke saath)", None, default_on=False),
    Strategy("e5_ensemble", "E5", "MONITOR", False, "MODEL",
             "E5 ML ensemble: top 10 picks at 09:06, valued open to close after costs",
             "E5 ML: 09:06 ke top 10 picks, open se close", "40 sessions"),
    Strategy("e6_results_drift", "E6", "MONITOR", False, "EVENT",
             "E6 post-results drift: day-2 open entry, 20-session hold",
             "E6 results ke baad: din-2 open entry, 20 din hold", "single look ~Apr 2027"),
)
BY_NAME = {s.name: s for s in STRATEGIES}
SWITCHABLE = tuple(s.name for s in STRATEGIES if s.switchable)
P1 = tuple(s.name for s in STRATEGIES if s.family == "P1")
PAPER = tuple(s.name for s in STRATEGIES if s.family == "PAPER")
# which market a tool is built for (the "regime fit" in the forensics): the PRE/OPEN state
# (app/shadow/regime.classify) and the realised day type (app/shadow/regime.day_type)
FIT_STATE = {"TREND": ("TREND_UP", "TREND_DOWN"), "RANGE": ("RANGE",)}
FIT_DAY = {"TREND": ("TREND_DAY_UP", "TREND_DAY_DOWN"), "RANGE": ("RANGE_DAY",)}
