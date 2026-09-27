"""Metrics on tiny hand-made sets with known answers."""

from datetime import datetime, timedelta, timezone

import pytest

from common.schemas import Event, EventType, LaneZone
from evaluation.metrics import (
    CongestionSample,
    CongestionTruth,
    GroundTruth,
    Prediction,
    Truth,
    Window,
    evaluate,
    evaluate_congestion,
    iou,
    level_runs,
    load_ground_truth,
)

T0 = datetime(2026, 9, 26, 20, 0, 0, tzinfo=timezone.utc)
CAM, OTHER = "cam_a", "cam_b"
BOX = (100.0, 100.0, 160.0, 140.0)


def at(s):
    return T0 + timedelta(seconds=s)


def truth(id, start, end, real=True, box=BOX, cam=CAM, type="double_parked", **kw):
    return Truth(id=id, camera=cam, type=type, start=at(start), end=at(end),
                 bbox=box, real=real, **kw)


def pred(start, duration, alert_after=60, box=BOX, cam=CAM, type=EventType.DOUBLE_PARKED):
    e = Event(id=f"evt_{cam}_{start}_{box[0]}", camera_id=cam, type=type, start_ts=at(start),
              duration_s=duration, bbox=list(box), lane_zone=LaneZone.CURB_ADJACENT,
              confidence=0.8)
    return Prediction(e, at(start + alert_after))


def gt(*items, windows=((CAM, 0, 3600), (OTHER, 0, 3600))):
    return GroundTruth([Window(c, at(s), at(e)) for c, s, e in windows], list(items))


def test_iou():
    assert iou(BOX, BOX) == 1
    assert iou(BOX, (160, 100, 220, 140)) == 0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)


def test_perfect_detection():
    r = evaluate([pred(10, 200)], gt(truth("gt1", 10, 210)))
    assert (r.precision, r.recall, r.type_accuracy) == (1, 1, 1)
    assert r.time_to_alert_s == [60]


def test_known_false_and_unreviewed_both_count_against_precision():
    g = gt(truth("gt1", 10, 210), truth("no1", 300, 400, real=False, box=(200, 100, 260, 140)))
    r = evaluate([pred(10, 200), pred(300, 100, box=(200, 100, 260, 140)),
                  pred(500, 90, box=(10, 10, 50, 40))], g)
    assert [m.outcome for m in r.matches] == ["true_positive", "known_false", "unreviewed"]
    assert r.precision == pytest.approx(1 / 3) and r.recall == 1


def test_missed_blockage_lowers_recall():
    g = gt(truth("gt1", 10, 210), truth("gt2", 400, 700, box=(200, 100, 260, 140)))
    r = evaluate([pred(10, 200)], g)
    assert r.recall == 0.5 and [t.id for t in r.missed] == ["gt2"]


def test_two_alerts_on_one_incident_count_one_duplicate():
    r = evaluate([pred(10, 100), pred(150, 100)], gt(truth("gt1", 10, 300)))
    assert [m.outcome for m in r.matches] == ["true_positive", "duplicate"]
    assert r.precision == 0.5 and r.recall == 1


@pytest.mark.parametrize("p", [
    pred(10, 200, cam=OTHER),                     # other camera
    pred(1000, 100),                              # other time
    pred(10, 200, box=(162, 100, 222, 140)),      # other spot
])
def test_no_match_without_same_camera_time_and_place(p):
    r = evaluate([p], gt(truth("gt1", 10, 210)))
    assert r.matches[0].outcome == "unreviewed" and r.recall == 0


def test_wrong_type_still_catches_the_blockage_but_lowers_type_accuracy():
    r = evaluate([pred(10, 200, type=EventType.STOPPED_IN_LANE)], gt(truth("gt1", 10, 210)))
    assert r.precision == 1 and r.type_accuracy == 0


def test_clipped_start_is_left_out_of_time_to_alert():
    g = gt(truth("gt1", 0, 300, start_clipped=True),
           truth("gt2", 100, 400, box=(200, 100, 260, 140)))
    r = evaluate([pred(0, 300), pred(100, 300, alert_after=70, box=(200, 100, 260, 140))], g)
    assert r.time_to_alert_s == [70] and r.median_time_to_alert_s == 70


def test_alerts_outside_the_reviewed_windows_are_ignored():
    g = gt(truth("gt1", 10, 210), windows=((CAM, 0, 1000),))
    r = evaluate([pred(10, 200), pred(2000, 100, alert_after=60)], g)
    assert r.alerts == 1


def test_excluding_a_category_drops_it_from_both_sides():
    g = gt(truth("gt1", 10, 210),
           truth("gt2", 400, 700, box=(200, 100, 260, 140), category="bus_lane"),
           truth("no1", 800, 900, real=False, box=(10, 10, 60, 40), category="camera_moved"))
    preds = [pred(10, 200), pred(400, 300, box=(200, 100, 260, 140)),
             pred(800, 100, box=(10, 10, 60, 40))]
    full = evaluate(preds, g)
    assert (full.alerts, full.count("true_positive"), len(full.blockages)) == (3, 2, 2)
    strict = evaluate(preds, g, exclude=["bus_lane", "camera_moved"])
    assert (strict.alerts, strict.precision, strict.recall) == (1, 1, 1)


def test_committed_ground_truth_loads_and_is_consistent():
    g = load_ground_truth()
    assert len(g.windows) >= 4 and len(g.blockages) >= 5
    ids = [t.id for t in g.items] + [c.id for c in g.congestion]
    assert len(ids) == len(set(ids))
    for t in g.items:
        assert t.start <= t.end, t.id
        assert g.in_windows(t.camera, t.start) or g.in_windows(t.camera, t.end), t.id
        x1, y1, x2, y2 = t.bbox
        assert 0 <= x1 < x2 <= 352 and 0 <= y1 < y2 <= 240, t.id
    assert g.congestion_windows and g.congestion
    for c in g.congestion:
        assert c.start <= c.end, c.id
        assert g.in_congestion_windows(c.camera, c.start), c.id


# --- congestion --------------------------------------------------------------------------------

def samples(levels, cam=CAM, start=0, step=5):
    """One reading per `step` s: a string like "ffssCCCf" (free / slow / Congested)."""
    names = {"f": "free", "s": "slow", "C": "congested"}
    return [CongestionSample(cam, "avenue", at(start + i * step), names[c])
            for i, c in enumerate(levels)]


def cgt(*jams, windows=((CAM, 0, 3600),)):
    return GroundTruth([], [], [Window(c, at(s), at(e)) for c, s, e in windows], list(jams))


def jam(id, start, end, level="congested", cam=CAM, **kw):
    return CongestionTruth(id=id, camera=cam, start=at(start), end=at(end), level=level, **kw)


def test_congestion_caught_on_time():
    r = evaluate_congestion(samples("f" * 20 + "C" * 40 + "f" * 20), cgt(jam("j1", 60, 300)))
    c = r.levels["congested"]
    assert (c.precision, c.recall, c.median_time_to_detect_s) == (1, 1, 40)
    assert r.confusion[("congested", "congested")] == 40
    # read free at 60-95 s and at 300 s (the jam's last moment), all tagged congested
    assert r.confusion[("free", "free")] == 31 and r.confusion[("congested", "free")] == 9


def test_a_run_on_free_traffic_is_a_false_alarm_and_a_missed_jam_lowers_recall():
    r = evaluate_congestion(samples("CCCC" + "f" * 100), cgt(jam("j1", 300, 500)))
    c = r.levels["congested"]
    assert (len(c.runs), len(c.false_runs), c.precision, c.recall) == (1, 1, 0, 0)
    assert [t.id for t in c.missed] == ["j1"]


def test_slow_reading_on_a_jam_counts_at_slow_or_worse_only():
    r = evaluate_congestion(samples("ssssss"), cgt(jam("j1", 0, 30)))
    assert r.levels["congested"].recall == 0
    assert r.levels["slow"].recall == 1 and r.levels["slow"].precision == 1


def test_flickering_level_splits_into_runs():
    runs = level_runs(samples("CCsCCsCC"), "congested")
    assert len(runs) == 3
    assert len(level_runs(samples("CCsCCsCC"), "slow")) == 1


def test_readings_outside_the_congestion_windows_are_ignored():
    r = evaluate_congestion(samples("CCCC", cam=OTHER), cgt())
    assert r.levels["congested"].runs == [] and r.agreement is None


def test_clipped_jam_start_is_left_out_of_time_to_detect():
    r = evaluate_congestion(samples("fC"), cgt(jam("j1", 0, 10, start_clipped=True)))
    assert r.levels["congested"].recall == 1
    assert r.levels["congested"].time_to_detect_s == []


def test_evaluation_runs_from_a_clean_checkout(tmp_path, repo_root):
    """scripts/evaluate.py on the committed detections: no frames, no YOLO model needed."""
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("evaluate", repo_root / "scripts" / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    g = load_ground_truth()
    missing = [w for w in g.windows + g.congestion_windows if not mod.cache_path(w).exists()]
    assert not missing, f"no committed detections for {missing}"

    assert mod.main(["--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["alerts"] > 0 and report["blockages"] == len(g.blockages)
    assert report["congestion"]["frames"] > 0
    assert report["congestion"]["congested"]["intervals"] == sum(
        c.level == "congested" for c in g.congestion)
    # the double-parked delivery trucks on 7 Ave @ 36 St are always caught
    outcomes = [json.loads(line) for line in (tmp_path / "predictions.jsonl").open()]
    trucks = [o for o in outcomes if o["truth"] in ("gt_001", "gt_002")]
    assert [o["outcome"] for o in trucks] == ["true_positive", "true_positive"]
