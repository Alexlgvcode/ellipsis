"""Congestion state tests (events/congestion.py, issue #47 Part B).

A made-up street: parking on the left (x < 60), a travel area to its right, and one
approach over both. Traffic is a grid of queued cars in the travel area, 5 s per frame:
standing = the same boxes again; moving = the grid shifted by half a car, so no box
overlaps its last position by IoU 0.5 (at 2-5 s per frame, a moving car never does).
"""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.schemas import VehicleClass
from events.congestion import ROAD, CongestionLevel, CongestionMonitor
from events.engine import EventEngine
from events.masks import CameraMask, dump_mask, validate_mask
from events.pipeline import CameraPipeline
from events.rules import load_rules
from vision.detect import Detection

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 9, 26, 20, 0, 0, tzinfo=timezone.utc)
STEP = timedelta(seconds=5)
CYCLE = 18  # frames per 90 s signal cycle
FREE, SLOW, CONGESTED = CongestionLevel.FREE, CongestionLevel.SLOW, CongestionLevel.CONGESTED

MASK_DICT = {
    "camera_id": "congestion_test", "name": "Congestion test street", "frame_size": [352, 240],
    "zones": [
        {"name": "parking", "type": "curb", "polygon": [[0, 0], [60, 0], [60, 240], [0, 240]]},
        {"name": "lanes", "type": "travel", "polygon": [[60, 0], [300, 0], [300, 240], [60, 240]]},
    ],
    "approaches": [{"name": "avenue", "direction": "southbound",
                    "polygon": [[0, 0], [300, 0], [300, 240], [0, 240]]}],
}
MASK = CameraMask.from_dict(MASK_DICT)
PARKED = (10, 100, 50, 130)  # in the parking lane


def queue(shift=0):
    """5 lanes x 7 cars of 40x30 in the travel area, moved down by `shift` px."""
    return [(70 + 46 * lane, 10 + 32 * row + shift, 110 + 46 * lane, 40 + 32 * row + shift)
            for lane in range(5) for row in range(7)]


def standing(frames):
    return [queue()] * frames


def moving(frames):
    return [queue(16 * (i % 2)) for i in range(frames)]


def red_light(cycles):
    """Everyone stops for half a cycle, then drives on for the other half."""
    return [f for _ in range(cycles) for f in standing(CYCLE // 2) + moving(CYCLE // 2)]


def run(frames, mask=MASK, rules=None, exclude=None, start=T0):
    monitor = CongestionMonitor(mask, rules or load_rules())
    out = []
    for i, boxes in enumerate(frames):
        dets = [Detection(tuple(float(v) for v in b), VehicleClass.CAR, 0.8) for b in boxes]
        out.append(monitor.update(start + i * STEP, dets, exclude or ())[0])
    return out


def levels(readings):
    return {r.level for r in readings}


def test_red_light_is_never_congested():
    readings = run(red_light(6))
    assert CONGESTED not in levels(readings)
    assert readings[-1].stuck_share > 0.3  # half the time everyone is stopped...
    assert readings[-1].level is FREE      # ...but the queue clears on every green


def test_everyone_stuck_for_three_cycles_is_congested():
    readings = run(standing(3 * CYCLE))
    last = readings[-1]
    assert last.level is CONGESTED
    assert last.stuck_share > 0.9 and last.occupancy >= load_rules()["congestion"]["min_occupancy"]
    assert 0.5 < last.score <= 1
    # congested from the first frame with a full 180 s window of it, and still since then
    assert last.since_ts == next(r.ts for r in readings if r.level is CONGESTED)
    assert (last.since_ts - T0).total_seconds() >= 180 - 30


def test_a_jam_shorter_than_the_window_is_not_congested_yet():
    assert levels(run(standing(2 * CYCLE - 8))) == {FREE}  # 140 s


def test_jam_clears_when_traffic_moves_again():
    readings = run(standing(3 * CYCLE) + moving(CYCLE))
    assert readings[3 * CYCLE - 1].level is CONGESTED
    assert readings[-1].level is FREE
    assert readings[-1].since_ts > readings[3 * CYCLE - 1].ts


def test_queue_where_only_some_cars_move_is_slow():
    # 3 of every 5 cars keep moving, the rest stay: ~40% stuck in every bin, never clearing
    frames = [[(x1, y1 + 16, x2, y2 + 16) if n % 5 < 3 and i % 2 else (x1, y1, x2, y2)
               for n, (x1, y1, x2, y2) in enumerate(queue())] for i in range(3 * CYCLE)]
    last = run(frames)[-1]
    assert 0.3 < last.stuck_share < 0.5
    assert last.level is SLOW
    assert 0 < last.score < run(standing(3 * CYCLE))[-1].score


def test_one_stopped_truck_on_an_empty_road_is_free():
    assert levels(run([[(150, 100, 200, 140)]] * (3 * CYCLE))) == {FREE}


def test_parked_cars_are_left_out():
    readings = run([[PARKED] + b for b in moving(3 * CYCLE)])
    assert readings[-1].level is FREE
    assert readings[-1].stuck_share == 0  # the parked car isn't one of the approach's vehicles


def test_vehicles_with_a_blockage_event_are_left_out():
    readings = run(standing(3 * CYCLE), exclude=queue())
    assert readings[-1].level is FREE and readings[-1].occupancy == 0


def test_frames_far_apart_are_not_compared():
    frames = [queue(), queue()]
    monitor = CongestionMonitor(MASK, load_rules())
    dets = [[Detection(tuple(map(float, b)), VehicleClass.CAR, 0.8) for b in f] for f in frames]
    monitor.update(T0, dets[0])
    far = monitor.update(T0 + timedelta(seconds=load_rules()["congestion"]["max_gap_s"] + 5),
                         dets[1])[0]
    assert far.stuck_share == 0  # the same boxes, but nobody saw the cars stay put in between


def test_thresholds_come_from_the_rules():
    rules = copy.deepcopy(load_rules())
    rules["congestion"]["congested_floor"] = 1.01
    rules["congestion"]["slow_floor"] = 0.5
    assert run(standing(3 * CYCLE), rules=rules)[-1].level is SLOW


def some_moving(frames, movers_of_5=3):
    """`movers_of_5` of every 5 cars keep moving, the rest stay."""
    return [[(x1, y1 + 16, x2, y2 + 16) if n % 5 < movers_of_5 and i % 2 else (x1, y1, x2, y2)
             for n, (x1, y1, x2, y2) in enumerate(queue())] for i in range(frames)]


def test_a_jam_stays_congested_while_it_only_partly_eases():
    # hysteresis: ~40% stuck enters slow, not congested, but doesn't end a jam already on
    frames = standing(3 * CYCLE) + some_moving(3 * CYCLE)
    assert run(frames)[-1].level is CONGESTED
    assert levels(run(frames)) == {FREE, CONGESTED}          # no flicker through slow
    rules = copy.deepcopy(load_rules())
    rules["congestion"]["exit_floor_drop"] = 0
    assert run(frames, rules=rules)[-1].level is SLOW
    assert run(some_moving(3 * CYCLE))[-1].level is SLOW       # from free it's only slow


def test_min_vehicles_counts_a_queue_of_small_far_cars():
    small = [(70 + 46 * lane, 10 + 14 * row, 90 + 46 * lane, 20 + 14 * row)
             for lane in range(5) for row in range(3)]           # covers ~4% of the approach
    assert levels(run([small] * (3 * CYCLE))) == {FREE}
    rules = copy.deepcopy(load_rules())
    rules["congestion"]["min_vehicles"] = 10
    assert run([small] * (3 * CYCLE), rules=rules)[-1].level is CONGESTED


def test_far_split_judges_the_far_part_of_the_approach_on_its_own():
    top = [b for b in queue() if b[3] < 120]                      # a queue up the street
    near = [(70 + 46 * lane, 170, 110 + 46 * lane, 200) for lane in range(5)]  # moving on
    frames = [top + [(x1, y1 + 30 * (i % 2), x2, y2 + 30 * (i % 2)) for x1, y1, x2, y2 in near]
              for i in range(3 * CYCLE)]
    rules = copy.deepcopy(load_rules())
    rules["congestion"]["far_split"] = 0.5
    monitor = CongestionMonitor(MASK, rules)
    for i, boxes in enumerate(frames):
        readings = monitor.update(T0 + i * STEP, [Detection(tuple(map(float, b)), VehicleClass.CAR,
                                                            0.8) for b in boxes])
    assert {r.approach: r.level for r in readings} == {"avenue_far": CONGESTED, "avenue": FREE}


def test_mask_without_approaches_uses_the_road_zones():
    mask = CameraMask.from_dict(json.loads((FIXTURES / "masks" / "engine_test.json").read_text()))
    monitor = CongestionMonitor(mask, load_rules())
    assert [a.name for a in monitor.approaches] == [ROAD]
    # a car parked at the curb (x < 60) isn't on the road
    readings = run([[(10, 100, 50, 130)]] * CYCLE, mask=mask)
    assert readings[-1].stuck_share == 0 and readings[-1].approach == ROAD


def test_pipeline_pauses_congestion_while_the_view_has_moved():
    rules = load_rules()
    pipe = CameraPipeline(EventEngine(MASK, rules), rules)
    dets = [Detection(tuple(map(float, b)), VehicleClass.CAR, 0.8) for b in queue()]
    for i in range(3 * CYCLE):
        pipe.step(T0 + i * STEP, None, dets, frozen=False, view=1.0)
    assert pipe.congestion.readings[0].level is CONGESTED
    t = T0 + 3 * CYCLE * STEP
    for i in range(rules["view"]["pause_after_frames"]):
        pipe.step(t + i * STEP, None, dets, frozen=False, view=0.0)
    assert pipe.paused and pipe.congestion.readings == []
    t += 10 * STEP
    for i in range(rules["view"]["resume_after_frames"] + 1):
        pipe.step(t + i * STEP, None, dets, frozen=False, view=1.0)
    assert not pipe.paused
    assert pipe.congestion.readings[0].level is FREE  # starts over: no full window yet


def test_mask_approaches_validate_and_round_trip():
    assert validate_mask(MASK_DICT) == []
    text = dump_mask(MASK_DICT)
    assert json.loads(text)["approaches"] == MASK_DICT["approaches"]
    assert CameraMask.from_dict(json.loads(text)).approaches[0].direction == "southbound"
    bad = copy.deepcopy(MASK_DICT)
    bad["approaches"].append({"name": "avenue", "direction": "up", "polygon": [[0, 0], [400, 0]]})
    errors = validate_mask(bad)
    assert any("unique" in e for e in errors)
    assert any("direction" in e for e in errors)
    assert any("at least 3 points" in e for e in errors)
    assert any("inside" in e for e in errors)


def test_every_committed_mask_has_an_approach():
    for path in sorted((Path(__file__).parent.parent / "events" / "masks").glob("*.json")):
        assert CameraMask.from_dict(json.loads(path.read_text())).approaches, path.name
