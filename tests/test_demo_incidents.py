"""The demo incidents (demo: true in evaluation/ground_truth.yaml) still alert, as the right
type, within 90 s. Runs the engine on the cached YOLO detections, so no frames or model are
needed and CI catches an engine or rules change that would break the demo (docs/demo.md)."""

import gzip
import json

import pytest

from evaluation.metrics import evaluate, load_ground_truth
from events.rules import load_rules
from scripts.evaluate import cache_path, run_window

GT = load_ground_truth()
DEMO = [t for t in GT.blockages if t.demo]


def test_the_demo_has_its_incidents():
    assert {t.id for t in DEMO} == {"gt_001", "gt_002", "gt_009"}
    assert {t.type for t in DEMO} == {"double_parked", "stopped_in_lane"}


@pytest.fixture(scope="module")
def report():
    windows = [w for w in GT.windows if any(t.camera == w.camera and w.start <= t.start <= w.end
                                            for t in DEMO)]
    rules = load_rules()
    preds = [p for w in windows
             for p in run_window(json.loads(gzip.decompress(cache_path(w).read_bytes())), rules)]
    return evaluate(preds, GT)


@pytest.mark.parametrize("truth", DEMO, ids=lambda t: t.id)
def test_demo_incident_alerts_in_time_as_the_right_type(report, truth):
    hits = [m for m in report.matches if m.truth is truth and m.outcome == "true_positive"]
    assert hits, f"{truth.id} ({truth.note}) no longer alerts"
    (hit,) = hits
    assert hit.prediction.event.type.value == truth.type
    if not truth.start_clipped:
        assert (hit.prediction.alert_ts - truth.start).total_seconds() < 90
