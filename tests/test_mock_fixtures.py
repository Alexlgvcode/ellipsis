"""Every file in data/mock/ must match the shared contract."""

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


def test_one_mock_event_per_blocking_type(events):
    assert {e.type for e in events} == {
        EventType.DOUBLE_PARKED, EventType.STOPPED_IN_LANE, EventType.BLOCKED_BOX,
    }
    assert len({e.id for e in events}) == len(events)


def test_snapshots_exist(repo_root, events):
    for e in events:
        assert (repo_root / e.snapshot_path).is_file(), e.snapshot_path


def test_recommendations_point_at_mock_events(events, recommendations):
    ids = {e.id for e in events}
    assert all(r.event_id in ids for r in recommendations)
    assert any(r.sim is not None for r in recommendations)


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
