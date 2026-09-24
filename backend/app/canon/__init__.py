"""Stage 2: Data Processing & Storage. See docs/STAGE_2_DESIGN.md.

Stage 2 reads the validated Stage 1 tables, never calls a vendor, and never
feeds orders or signals (STAGE2_LIVE_ENABLED is false and gates nothing but a
future live mode).
"""

CANON_SOURCE = "PRAJNA_CANON"     # run-ledger source of Stage 2 runs (not a vendor)
