"""E5-H (docs/STAGE4_E5H_PREREGISTRATION.md): the research-only switch that lets a training
dataset read vendor-adjusted history older than the corporate-action horizon. Production
never sets it; only a dataset declared with allow_low_confidence does, for its replay."""

from app.canon import pit
from app.training import labels as L
from app.training import policy as P


def test_switch_is_off_by_default_and_only_h2020_sets_it():
    assert pit.RESEARCH_ALLOW_LOW_CONFIDENCE.get() is False
    on = {k for k, d in P.DATASETS.items() if d.allow_low_confidence}
    assert on == {"h2020"}
    assert P.DATASETS["h2020"].version == "stage4-ds-h2020"
    assert P.DATASETS["h2020"].registry_version == "features-v5"


def test_label_research_versions():
    assert L.RESEARCH_VERSIONS == frozenset({"label-h2020"})
    rows = L.v2_rows("NSE_EQ|X", [], {}, {}, {}, {}, "label-h2020")
    assert rows == []
