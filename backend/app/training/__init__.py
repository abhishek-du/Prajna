"""Stage 4 training data (historical Stage 3 replay + future-outcome labels).

NOT a model, NOT signals/risk/orders. Features come from the production Stage 3
engine unchanged (app.features.engine.compute_snapshot); this package only
chooses the snapshots, the knowability policy and the storage:

  policy        the two knowability policies (STRICT_PIT, AS_IF_LIVE-v1) and the
                measured live lags behind AS_IF_LIVE-v1
  availability  the missingness contract (NOT_AVAILABLE_HISTORICALLY vs
                MISSING_INPUT vs STALE_INPUT; a missing history is never 0)
  replay        the resumable, idempotent historical replay into
                training_feature_value (never feature_value)
  labels        label-v1: the session's outcome, strictly after the snapshot
  validate      independent SQL checks and replays
"""
