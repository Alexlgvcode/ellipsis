"""Retiming rules and the camera-to-lane map. No SUMO: the sim run is the user test."""

import json
from pathlib import Path

import pytest

from common.schemas import Event
from signals.mapping import OUT, ZONES, load_mapping
from signals.retime import (
    blockage_for,
    candidate_plans,
    cut_seconds,
    mock_events,
    recommend,
    signal_changes,
    within_bounds,
)
from sim.run_scenario import adjust_phases

REPO = Path(__file__).resolve().parents[1]
MASKS = REPO / "events" / "masks"


def test_every_masked_camera_is_mapped():
    mapping = load_mapping()
    masks = {p.stem for p in MASKS.glob("*.json")}
    assert masks
    assert masks <= set(mapping["cameras"])
    for cam in mapping["cameras"].values():
        assert cam["tls"] and cam["upstream"]
        for zone in ZONES:
            lane = cam["lanes"][zone]
            assert lane["id"].rsplit("_", 1)[-1].isdigit()
            assert lane["pos_m"] > 0
        program = mapping["programs"][cam["upstream"]]
        assert abs(sum(d for d, _ in program) - 90) <= 1


def test_each_rule_cuts_the_expected_signal():
    mapping = load_mapping()
    events = {e.id: e for e in mock_events()}
    parked = signal_changes(events["evt_mock_001"], mapping)[0]
    stopped = signal_changes(events["evt_mock_002"], mapping)[0]
    box = signal_changes(events["evt_mock_003"], mapping)[0]
    assert parked.id == mapping["cameras"][events["evt_mock_001"].camera_id]["upstream"]
    assert stopped.id == mapping["cameras"][events["evt_mock_002"].camera_id]["upstream"]
    assert box.id == mapping["cameras"][events["evt_mock_003"].camera_id]["tls"]
    assert parked.change_s < 0 and stopped.change_s < 0 and box.change_s < 0
    eight = mapping["cameras"]["6a85384f-d82e-4bff-b5f1-15c22cca70e6"]
    lane = blockage_for(events["evt_mock_001"], mapping).lane_id
    assert lane == eight["lanes"]["curb_adjacent"]["id"]


@pytest.mark.parametrize("event_id", ["evt_mock_001", "evt_mock_002", "evt_mock_003"])
def test_changes_keep_the_cycle_the_floor_and_the_cap(event_id):
    mapping = load_mapping()
    event = next(e for e in mock_events() if e.id == event_id)
    change = signal_changes(event, mapping)[0]
    phases = [(float(d), s) for d, s in mapping["programs"][change.id]]
    assert within_bounds(phases, change.phase, change.change_s)
    adjusted = adjust_phases(phases, change.phase, change.change_s)
    assert sum(d for d, _ in adjusted) == pytest.approx(sum(d for d, _ in phases))
    duration = phases[change.phase][0]
    assert abs(change.change_s) <= 0.20 * duration + 0.05
    assert abs(change.change_s) >= min(0.10 * duration, duration - 8) - 0.05


def test_cut_seconds_stays_inside_the_band():
    assert cut_seconds(40) == pytest.approx(-6.0)
    assert abs(cut_seconds(40)) <= 0.20 * 40
    short = cut_seconds(10)
    assert 10 + short >= 8


def test_recommend_without_sim_is_a_recommendation():
    mapping = load_mapping()
    event = mock_events()[0]
    rec = recommend(event, mapping, simulate=False)
    assert rec.event_id == event.id
    assert rec.sim is None
    assert rec.intersections[0].change_s < 0


def test_mapping_file_matches_the_builder():
    assert OUT.is_file()
    raw = json.loads(OUT.read_text())
    assert raw["meta"]["cameras"] == len(raw["cameras"])
    assert isinstance(mock_events()[2], Event)


TRUCK = Event(id="evt_truck", camera_id="b0cbb042-de0a-449f-b5d1-49f68a9bf2ae",
              type="double_parked", start_ts="2026-09-26T18:21:44Z", duration_s=521,
              bbox=[192, 79, 228, 124], lane_zone="curb_adjacent", confidence=0.69)


def test_blockage_starts_after_the_warm_up_and_is_capped():
    blockage = blockage_for(TRUCK, load_mapping())
    assert blockage.start_s == 300 and blockage.duration_s == 300    # 521 s capped


def test_candidates_add_more_green_for_the_blocked_approach():
    pytest.importorskip("sumolib")
    mapping = load_mapping()
    rule, own, both = candidate_plans(TRUCK, mapping)
    cam = mapping["cameras"][TRUCK.camera_id]
    assert rule == signal_changes(TRUCK, mapping) and rule[0].id == cam["upstream"]
    (extend,) = own
    assert extend.id == cam["tls"] and extend.change_s > 0
    phases = [(float(d), s) for d, s in mapping["programs"][cam["tls"]]]
    assert within_bounds(phases, extend.phase, extend.change_s)
    assert both == rule + own


def test_without_sumolib_only_the_rule_is_offered(monkeypatch):
    import signals.retime as retime

    monkeypatch.setattr(retime, "approach_phase", lambda event, mapping: None)
    assert candidate_plans(TRUCK, load_mapping()) == [signal_changes(TRUCK, load_mapping())]


def test_recommend_returns_the_candidate_with_the_lowest_delay(monkeypatch):
    import signals.retime as retime
    from common.schemas import SignalChange, SimResult
    from sim.run_scenario import ScenarioReport

    plans = [[SignalChange(id="a", phase=1, change_s=-6)],
             [SignalChange(id="b", phase=1, change_s=9)]]
    seen = {}

    def fake_run(blockage, candidates, seeds, end_s):
        seen.update(candidates=candidates, seeds=seeds, end_s=end_s)
        return [ScenarioReport(SimResult(delay_default=120, delay_new=d, queue_default=9,
                                         queue_new=8), 0, 0, None, None, seeds)
                for d in (124.0, 115.0)]

    monkeypatch.setattr(retime, "candidate_plans", lambda event, mapping: plans)
    monkeypatch.setattr(retime, "run_candidates", fake_run)
    rec = recommend(TRUCK, load_mapping(), simulate=True)
    assert rec.intersections == plans[1] and rec.sim.delay_new == 115.0
    assert seen["candidates"] == plans and seen["seeds"] == (42, 43, 44)
    assert seen["end_s"] == 300 + 300 + 180                   # warm-up, stop, recovery
