import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from common.config import Settings
from common.schemas import Event


@pytest.fixture
def make_client(tmp_path):
    """TestClient on a fresh SQLite file; startup (tables + seeding) runs on enter."""
    clients = []

    def _make(mock_mode: bool = False) -> TestClient:
        settings = Settings(LW_DATABASE_URL=f"sqlite:///{tmp_path / 'test.db'}",
                            LW_MOCK_MODE=mock_mode)
        client = TestClient(create_app(settings))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client(mock_mode=False)


@pytest.fixture
def mock_client(make_client) -> TestClient:
    return make_client(mock_mode=True)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root_redirects_to_docs(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/docs"


def test_posted_event_can_be_read_back(client, sample_event):
    assert client.post("/events", json=sample_event).status_code == 201
    got = client.get(f"/events/{sample_event['id']}")
    assert got.status_code == 200
    assert Event(**got.json()) == Event(**sample_event)
    assert [e["id"] for e in client.get("/events").json()] == [sample_event["id"]]


def test_posting_same_event_again_updates_it(client, sample_event):
    client.post("/events", json=sample_event)
    client.post("/events", json={**sample_event, "duration_s": 300})
    events = client.get("/events").json()
    assert len(events) == 1
    assert events[0]["duration_s"] == 300


@pytest.mark.parametrize("bad", [{"confidence": 1.5}, {"type": "crash"}, {"bbox": [1, 2]}])
def test_invalid_event_returns_422(client, sample_event, bad):
    assert client.post("/events", json={**sample_event, **bad}).status_code == 422


def test_unknown_event_returns_404(client):
    assert client.get("/events/nope").status_code == 404


def test_events_newest_first_and_filterable(client, sample_event):
    older = {**sample_event, "id": "evt_old", "start_ts": "2026-09-26T10:00:00Z"}
    other_cam = {**sample_event, "id": "evt_other", "camera_id": "cam_other",
                 "start_ts": "2026-09-26T16:00:00Z"}
    for e in (sample_event, older, other_cam):
        client.post("/events", json=e)
    assert [e["id"] for e in client.get("/events").json()] == ["evt_other", "evt_test", "evt_old"]
    by_cam = client.get("/events", params={"camera_id": "cam_test"}).json()
    assert {e["id"] for e in by_cam} == {"evt_test", "evt_old"}


def test_mock_mode_serves_the_three_mocks(mock_client):
    ids = {e["id"] for e in mock_client.get("/events").json()}
    assert ids == {"evt_mock_001", "evt_mock_002", "evt_mock_003"}
    rec = mock_client.get("/recommendations/evt_mock_001").json()
    assert rec["sim"]["delay_new"] < rec["sim"]["delay_default"]


def test_mock_mode_off_starts_empty(client):
    assert client.get("/events").json() == []


def test_cameras_loaded_from_camera_list(mock_client):
    cam_ids = {c["id"] for c in mock_client.get("/cameras").json()}
    event_cams = {e["camera_id"] for e in mock_client.get("/events").json()}
    assert event_cams <= cam_ids


def test_recommendation_for_unknown_event_returns_404(client):
    assert client.get("/recommendations/nope").status_code == 404


def test_cannot_post_recommendation_for_unknown_event(client):
    rec = {"event_id": "nope", "intersections": []}
    assert client.post("/recommendations", json=rec).status_code == 404


def test_recommendation_sim_filled_in_later(client, sample_event):
    client.post("/events", json=sample_event)
    rec = {"event_id": "evt_test", "intersections": [{"id": "tls_1", "phase": 0, "change_s": -6}]}
    assert client.post("/recommendations", json=rec).status_code == 201
    assert client.get("/recommendations/evt_test").json()["sim"] is None
    sim = {"delay_default": 40, "delay_new": 30, "queue_default": 12, "queue_new": 8}
    client.post("/recommendations", json={**rec, "sim": sim})
    assert client.get("/recommendations/evt_test").json()["sim"] == sim


def test_snapshot_is_served(mock_client):
    resp = mock_client.get("/events/evt_mock_001/snapshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_snapshot_outside_data_dir_is_refused(client, sample_event):
    client.post("/events", json={**sample_event, "snapshot_path": "pyproject.toml"})
    assert client.get("/events/evt_test/snapshot").status_code == 404


def test_missing_snapshot_returns_404(client, sample_event):
    client.post("/events", json=sample_event)  # snapshot_path is None
    assert client.get("/events/evt_test/snapshot").status_code == 404
