"""Retiming rules and the camera-to-lane map. No SUMO: the sim run is the user test."""

import json
from pathlib import Path

import pytest

from common.schemas import Event
from signals.mapping import OUT, ZONES, load_mapping
from signals.retime import (
    blockage_for,
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
