"""Tracker tests on synthetic box sequences (no model needed, run in CI)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from common.schemas import VehicleClass
from events.rules import load_rules
from vision.detect import Detection
from vision.track import CameraTracker, MultiCameraTracker, frame_timestamp, iou, is_still

T0 = datetime(2026, 9, 26, 18, 0, 0, tzinfo=timezone.utc)
STEP = timedelta(seconds=5)
CAR, BUS, TRUCK = VehicleClass.CAR, VehicleClass.BUS, VehicleClass.TRUCK


def det(x1, y1, x2, y2, cls=CAR, conf=0.8):
    return Detection((float(x1), float(y1), float(x2), float(y2)), cls, conf)


def run(tracker, frames):
    """Feed one list of detections per frame, 5 s apart; return the last update."""
    out = []
    for i, dets in enumerate(frames):
        out = tracker.update(T0 + i * STEP, dets)
    return out


@pytest.fixture
def tracker():
    return CameraTracker(load_rules())


def test_is_still_counts_steady_edges():
    box = (100.0, 100.0, 200.0, 150.0)  # diagonal 111.8 -> each edge may move < 5.6 px
    assert is_still(box, (102, 101, 202, 151), 0.05, 0.5)        # jitter on every edge
    assert is_still(box, (100, 100, 200, 135), 0.05, 0.5)        # bottom hidden: 1 edge moved
    assert not is_still(box, (106, 100, 206, 150), 0.05, 0.5)    # slid sideways: 2 edges
    assert not is_still(box, (100, 110, 200, 160), 0.05, 0.5)    # drove forward: 2 edges
    assert not is_still(box, (100, 100, 200, 124), 0.05, 0.5)    # 1 edge, but IoU 0.48
    assert not is_still(box, (100, 100, 200, 135), 0.05, 0.5, min_edges=4)


def test_truck_with_bottom_edge_hidden_on_and_off_keeps_its_timer(tracker):
    # 7 Ave @ 36 St: a double-parked box truck whose bottom keeps disappearing behind a
    # police SUV and pedestrians (real box range from the footage: bottom y 116-134)
    bottoms = [129, 124, 133, 120, 129, 134, 127, 116, 131, 125, 129, 118, 133, 129,
               122, 130, 134, 126, 129, 121, 128, 133, 125, 129]   # 24 frames = 115 s
    tracks = run(tracker, [[det(191, 79, 226, y, cls=BUS)] for y in bottoms])
    t = tracks[0]
    assert t.id == 1
    assert t.stationary_since == T0
    assert t.stationary_s == 115


def test_parked_car_with_jitter_builds_stationary_time(tracker):
    jitter = [0, 1, -1, 1, 0, -1, 1, 0, 0, 1, -1, 0, 1]  # 13 frames = 60 s
    tracks = run(tracker, [[det(100 + j, 100, 160 + j, 140)] for j in jitter])
    assert len(tracks) == 1
    assert tracks[0].id == 1
    assert tracks[0].stationary_s == 60
    assert tracks[0].stationary_since == T0


def test_moving_car_keeps_id_but_never_builds_stationary_time(tracker):
    # 8 px per frame on a 60 px wide box: still linked (IoU ~0.76) but shift > 5%
    tracks = run(tracker, [[det(100 + 8 * i, 100, 160 + 8 * i, 140)] for i in range(10)])
    assert [t.id for t in tracks] == [1]
    assert tracks[0].hits == 10
    assert tracks[0].stationary_s == 0
    assert tracks[0].max_stationary_s == 0


def test_sustained_change_resets_timer(tracker):
    # top and bottom both move 9 px (> 5% of the 72 px diagonal): 2 edges moved
    still = [[det(100, 100, 160, 140)]] * 5                     # still for 20 s
    moved = [[det(100, 91, 160, 149)]] * 4
    tracks = run(tracker, still + moved)
    t = tracks[0]
    assert 0.68 < iou((100, 100, 160, 140), (100, 91, 160, 149)) < 0.7
    # frames 5 and 6 fail vs the anchor -> reset at frame 6; new streak from frame 6
    assert t.stationary_since == T0 + 6 * STEP
    assert t.stationary_s == 10
    assert t.max_stationary_s == 20  # frame 5 (first strike) doesn't count
    assert t.anchor == (100.0, 91.0, 160.0, 149.0)


def test_single_glitchy_box_does_not_reset_timer(tracker):
    parked = det(100, 100, 160, 140)
    glitch = det(100, 100, 130, 140)          # half hidden for one frame
    tracks = run(tracker, [[parked]] * 5 + [[glitch]] + [[parked]] * 3)
    t = tracks[0]
    assert t.stationary_since == T0
    assert t.stationary_s == 40
    assert t.strikes == 0


def test_slow_creep_never_builds_long_stationary_time(tracker):
    # a queue inching forward 2 px/frame (3% of width, under the 5% per-step limit)
    tracks = run(tracker, [[det(100 + 2 * i, 100, 160 + 2 * i, 140)] for i in range(24)])
    assert [t.id for t in tracks] == [1]
    assert tracks[0].max_stationary_s <= 20


def test_history_fields_and_majority_class(tracker):
    classes = [CAR, BUS, CAR, TRUCK, CAR]  # a cab the detector keeps relabelling
    tracks = run(tracker, [[det(10, 10, 70, 50, cls=c, conf=0.5 + i / 10)]
                           for i, c in enumerate(classes)])
    t = tracks[0]
    assert t.cls is CAR
    assert t.first_seen == T0
    assert t.last_seen == T0 + 4 * STEP
    assert t.hits == 5
    assert t.bbox == (10.0, 10.0, 70.0, 50.0)
    assert t.conf == pytest.approx(0.9)
    assert t.to_dict()["cls"] == "car"


def test_occlusion_keeps_id_and_stationary_time(tracker):
    parked = det(100, 100, 160, 140)
    frames = [[parked]] * 4 + [[]] * 2 + [[parked]] * 2   # a bus hides it for 2 frames
    tracks = run(tracker, frames)
    assert [t.id for t in tracks] == [1]
    assert tracks[0].missed == 0
    assert tracks[0].stationary_s == 35  # T0 .. T0 + 7 steps


def test_missed_track_is_reported_then_ended(tracker):
    parked = det(100, 100, 160, 140)
    tracks = run(tracker, [[parked]] * 2 + [[]])
    assert tracks[0].missed == 1
    for i in range(3):
        tracks = tracker.update(T0 + (3 + i) * STEP, [])
    assert tracks == []
    assert [t.id for t in tracker.ended] == [1]
    # comes back later: a new track, the old stationary time doesn't carry over
    tracks = tracker.update(T0 + 6 * STEP, [parked])
    assert [t.id for t in tracks] == [2]
    assert tracks[0].stationary_s == 0


def test_two_vehicles_side_by_side_keep_their_own_ids(tracker):
    a, b = det(100, 100, 160, 140), det(170, 100, 230, 140)
    tracks = run(tracker, [[a, b], [b, a], [a, b]])  # detection order shouldn't matter
    by_id = {t.id: t.bbox for t in tracks}
    assert by_id == {1: a.bbox, 2: b.bbox}


def test_cameras_are_tracked_independently():
    multi = MultiCameraTracker(load_rules())
    box = det(100, 100, 160, 140)
    for i in range(3):
        a = multi.update("cam_a", T0 + i * STEP, [box])
        b = multi.update("cam_b", T0 + i * STEP, [box] if i == 0 else [])
    assert [t.id for t in a] == [1] and a[0].stationary_s == 10
    assert [t.id for t in b] == [1] and b[0].missed == 2


def test_frame_timestamp_from_poller_path():
    ts = frame_timestamp(Path("data/frames/cam/20260926/180539.jpg"))
    assert ts == datetime(2026, 9, 26, 18, 5, 39, tzinfo=timezone.utc)


def test_recording_gap_ends_tracks_instead_of_bridging_them(tracker):
    parked = det(100, 100, 160, 140)
    run(tracker, [[parked]] * 3)                                   # still 10 s
    later = T0 + 2 * STEP + timedelta(minutes=15)                  # recorder was off
    tracks = tracker.update(later, [parked])
    assert [t.id for t in tracker.ended] == [1]
    assert [t.id for t in tracks] == [2]
    assert tracks[0].stationary_s == 0


def test_seen_frac_counts_detected_vs_missed_frames_while_still(tracker):
    parked = det(100, 100, 160, 140)
    tracks = run(tracker, [[parked], [parked], [], [parked], [], [parked]])
    t = tracks[0]
    assert (t.still_seen, t.still_missed) == (4, 2)
    assert t.seen_frac == pytest.approx(4 / 6)
