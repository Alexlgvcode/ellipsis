"""Event engine tests.

Synthetic: a tiny test street (tests/fixtures/masks/engine_test.json) with one zone
of each type side by side, and vehicles fed through the real tracker 5 s apart.
Real footage: YOLO detections from the 2026-09-26 recordings
(tests/fixtures/detections/), run through tracker + engine with the committed masks.
"""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from common.schemas import EventType, LaneZone, VehicleClass
from events.engine import EventEngine
from events.masks import CameraMask, load_mask
from events.rules import load_rules
from vision.detect import Detection
from vision.track import CameraTracker

FIXTURES = Path(__file__).parent / "fixtures"
MASK = CameraMask.from_dict(json.loads((FIXTURES / "masks" / "engine_test.json").read_text()))
T0 = datetime(2026, 9, 26, 18, 0, 0, tzinfo=timezone.utc)
STEP = timedelta(seconds=5)
CAR, BUS = VehicleClass.CAR, VehicleClass.BUS

# one parked box per zone of the test street (bottom-center lands inside the zone)
CURBSIDE = (70, 100, 110, 130)    # curb_adjacent
MIDDLE = (160, 100, 200, 130)     # travel
BUS_STOP = (250, 100, 290, 130)   # bus_stop
PARKING = (10, 100, 50, 130)      # curb
IGNORED = (310, 100, 345, 130)    # ignore
IN_BOX = (150, 190, 200, 220)     # box


def det(box, cls=CAR, conf=0.8):
    return Detection(tuple(float(v) for v in box), cls, conf)


def run(frames, rules=None, frozen=None):
    """Feed one list of boxes per frame (5 s apart) through tracker + engine.
    Returns the engine's update for every frame."""
    rules = rules or load_rules()
    tracker, engine = CameraTracker(rules), EventEngine(MASK, rules)
    updates = []
    for i, dets in enumerate(frames):
        ts = T0 + i * STEP
        still = bool(frozen and frozen[i])
        tracks = [] if still else tracker.update(ts, [d if isinstance(d, Detection) else det(d)
                                                      for d in dets])
        updates.append(engine.update(ts, tracks, [] if still else tracker.ended,
                                     feed_still=still))
    return updates


def opened(updates):
    return [(i, e) for i, u in enumerate(updates) for e in u.opened]


def closed(updates):
    return [(i, e) for i, u in enumerate(updates) for e in u.closed]


@pytest.mark.parametrize("box, kind, zone, dwell", [
    (CURBSIDE, EventType.DOUBLE_PARKED, LaneZone.CURB_ADJACENT, 60),
    (MIDDLE, EventType.STOPPED_IN_LANE, LaneZone.TRAVEL, 120),
    (IN_BOX, EventType.BLOCKED_BOX, LaneZone.BOX, 30),
    (BUS_STOP, EventType.DOUBLE_PARKED, LaneZone.BUS_STOP, 120),
])
def test_each_type_fires_exactly_at_its_threshold(box, kind, zone, dwell):
    frames = dwell // 5
    events = opened(run([[box]] * (frames + 3)))
    assert len(events) == 1
    i, e = events[0]
    assert i == frames                      # not one frame earlier
    assert (e.type, e.lane_zone) == (kind, zone)
    assert e.start_ts == T0 and e.duration_s == dwell
    assert e.id == f"evt_engine_t_{T0:%Y%m%d%H%M%S}_1"
    assert 0 < e.confidence <= 1


def test_red_light_wait_shorter_than_the_cycle_does_not_fire():
    waiting = [[MIDDLE]] * 19                               # 90 s at the light
    driving = [[(160, 100 - 20 * k, 200, 130 - 20 * k)] for k in range(1, 4)]
    assert opened(run(waiting + driving)) == []


def test_bus_stop_uses_the_longer_threshold_for_any_class():
    updates = run([[det(BUS_STOP, cls=BUS)]] * 25)          # 120 s
    assert [i for i, _ in opened(updates)] == [24]          # not at 60 s
    # a vehicle labelled "bus" outside a bus stop is treated like any other vehicle
    assert [i for i, _ in opened(run([[det(CURBSIDE, cls=BUS)]] * 14))] == [12]


def test_curb_and_ignore_zones_never_fire():
    assert opened(run([[PARKING, IGNORED]] * 121)) == []    # 10 min


def test_only_the_front_vehicle_of_a_travel_lane_queue_fires():
    front, behind = (160, 60, 200, 90), (160, 95, 200, 125)
    events = opened(run([[front, behind]] * 26))
    assert len(events) == 1
    assert events[0][1].bbox == list(front)
    # the same vehicle on its own does fire
    assert len(opened(run([[behind]] * 26))) == 1


def test_back_to_back_double_parkers_both_fire():
    front, behind = (70, 60, 110, 90), (70, 95, 110, 125)
    events = opened(run([[front, behind]] * 14))
    assert sorted(e.bbox for _, e in events) == [list(front), list(behind)]


def test_event_closes_when_the_vehicle_drives_off():
    parked = [[CURBSIDE]] * 14                              # opens at 60 s, 65 s at frame 13
    leaving = [[(70, 100 - 8 * k, 110, 130 - 8 * k)] for k in range(1, 5)]  # pulls out
    updates = run(parked + leaving)
    (i, e), = closed(updates)
    assert e.duration_s == 65                               # not counting the moved frames
    assert opened(updates)[0][1].id == e.id


def test_event_closes_after_3_lost_frames_with_its_duration():
    updates = run([[CURBSIDE]] * 14 + [[]] * 4)
    assert closed(updates[:17]) == []                       # missed 1-3: still open
    (i, e), = closed(updates)
    assert i == 17 and e.duration_s == 65


def test_brief_occlusion_keeps_the_same_event_open():
    updates = run([[CURBSIDE]] * 14 + [[]] * 2 + [[CURBSIDE]] * 3)
    assert closed(updates) == [] and len(opened(updates)) == 1
    last = updates[-1].updated[0]
    assert last.id == opened(updates)[0][1].id
    assert last.start_ts == T0 and last.duration_s == 90


def test_frozen_feed_fires_and_hides_vehicles():
    frames = [[CURBSIDE]] * 20
    frozen = [True] * 16 + [False] * 4                      # identical frames for 75 s
    updates = run(frames, frozen=frozen)
    events = opened(updates)
    assert [(i, e.type) for i, e in events] == [(6, EventType.FROZEN_FEED)]
    assert events[0][1].bbox == [0, 0, 352, 240]
    (i, e), = closed(updates)
    assert i == 16 and e.type is EventType.FROZEN_FEED and e.duration_s == 75


def test_thresholds_come_from_the_rules():
    rules = copy.deepcopy(load_rules())
    rules["dwell_s"]["double_parked"] = 30
    assert [i for i, _ in opened(run([[CURBSIDE]] * 8, rules))] == [6]


def test_vehicle_cut_off_at_the_bottom_never_fires():
    assert opened(run([[(150, 200, 200, 240)]] * 10)) == []  # box bottom = frame edge
    assert len(opened(run([[IN_BOX]] * 10))) == 1


def test_confidence_grows_while_the_vehicle_stays():
    updates = run([[CURBSIDE]] * 30)
    first = opened(updates)[0][1].confidence
    last = updates[-1].updated[0].confidence
    assert 0 < first < last <= 1


def test_for_camera_needs_a_mask():
    assert EventEngine.for_camera("no-such-camera") is None
    assert EventEngine.for_camera("b0cbb042-de0a-449f-b5d1-49f68a9bf2ae") is not None


# --- real footage ------------------------------------------------------------------


def replay_fixture(camera_id):
    raw = json.loads((FIXTURES / "detections" / f"{camera_id}.json").read_text())
    rules = load_rules()
    tracker, engine = CameraTracker(rules), EventEngine(load_mask(camera_id), rules)
    final = {}
    for frame in raw["frames"]:
        ts = datetime.fromisoformat(frame["ts"].replace("Z", "+00:00"))
        dets = [Detection(tuple(d[:4]), VehicleClass(d[4]), d[5]) for d in frame["dets"]]
        update = engine.update(ts, tracker.update(ts, dets), tracker.ended)
        final.update({e.id: e for e in update.changed})
    return list(final.values())


def test_real_footage_7_ave_36_st_double_parked_trucks():
    events = replay_fixture("b0cbb042-de0a-449f-b5d1-49f68a9bf2ae")
    assert {e.type for e in events} == {EventType.DOUBLE_PARKED}
    long = sorted((e for e in events if e.duration_s >= 400), key=lambda e: e.bbox[1])
    # both delivery trucks, still for the whole 7-min recording (ground truth in #16)
    assert [round(e.bbox[1]) for e in long] == [67, 80]
    # plus the police SUV that stopped behind them for ~2 min
    assert len(events) == 3


@pytest.mark.parametrize("camera_id, why", [
    ("6a85384f-d82e-4bff-b5f1-15c22cca70e6", "SUV in the parking lane, red-light queue"),
    ("ec9ffb62-e3bf-4352-8bcf-7c9adf5fbe9c", "cabs at the taxi stand, cut-off vehicles"),
])
def test_real_footage_without_incidents_stays_quiet(camera_id, why):
    assert replay_fixture(camera_id) == [], why
