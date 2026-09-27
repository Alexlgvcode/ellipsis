"""Every file in data/mock/ must match the shared contract, and every mock incident must be
a real, hand-checked one (scripts/build_mock.py, issue #63)."""

import json

import pytest

from common.schemas import Event, EventType, Recommendation


def _load(repo_root, name):
    return json.loads((repo_root / "data" / "mock" / name).read_text())


@pytest.fixture
def events(repo_root) -> list[Event]:
    return [Event(**e) for e in _load(repo_root, "events.json")]


@pytest.fixture
def recommendations(repo_root) -> list[Recommendation]:
    return [Recommendation(**r) for r in _load(repo_root, "recommendations.json")]


def test_every_blocking_type_is_there(events):
    assert {e.type for e in events} == {
        EventType.DOUBLE_PARKED, EventType.STOPPED_IN_LANE, EventType.BLOCKED_BOX,
    }
    assert len({e.id for e in events}) == len(events)


def test_every_mock_event_is_a_real_tagged_blockage(events):
    from evaluation.metrics import iou, load_ground_truth

    blockages = load_ground_truth().blockages
    for e in events:
        end = e.start_ts.timestamp() + e.duration_s
        match = [t for t in blockages if t.camera == e.camera_id and t.type == e.type.value
                 and t.start.timestamp() <= end and t.end.timestamp() >= e.start_ts.timestamp()
                 and iou(e.bbox, t.bbox) >= 0.3]
        assert match, f"{e.id} matches no blockage in evaluation/ground_truth.yaml"
        assert not {t.category for t in match} & {"police", "bus_lane"}  # left out (#63)


def test_snapshots_exist(repo_root, events):
    for e in events:
        assert (repo_root / e.snapshot_path).is_file(), e.snapshot_path


def test_every_mock_event_has_a_simulated_recommendation(events, recommendations):
    assert sorted(r.event_id for r in recommendations) == sorted(e.id for e in events)
    assert all(r.sim is not None and r.intersections for r in recommendations)


def test_mock_data_is_what_build_mock_builds():
    from scripts.build_mock import main

    assert main(["--check"]) == 0  # events.json and congestion.json, from committed caches


def test_camera_ids_are_in_camera_list(repo_root, events):
    cameras_path = repo_root / "data" / "cameras.json"
    if not cameras_path.exists():
        pytest.skip("data/cameras.json not added yet (feat/camera-list)")
    known = {c["id"] for c in json.loads(cameras_path.read_text())}
    assert {e.camera_id for e in events} <= known


def test_mock_congestion_matches_the_contract_and_the_masks(repo_root):
    from common.schemas import Congestion, CongestionLevel
    from events.masks import load_mask

    readings = [Congestion(**c) for c in _load(repo_root, "congestion.json")]
    assert {r.level for r in readings} == set(CongestionLevel)
    for r in readings:
        mask = load_mask(r.camera_id)
        assert mask is not None, r.camera_id
        assert (r.approach, r.direction) in {(a.name, a.direction) for a in mask.approaches}


def test_mock_notes_are_real_model_notes_for_mock_events(repo_root, events):
    notes = _load(repo_root, "summaries.json")
    ids = {e.id for e in events}
    assert notes, "data/mock/summaries.json has no notes"
    for n in notes:
        assert n["event_id"] in ids
        assert n["text"].strip()
        assert n["model"] and n["facts"]  # which model wrote it, and from which facts
    assert len({n["event_id"] for n in notes}) == len(notes)
