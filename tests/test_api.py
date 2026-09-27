import json

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from common.config import REPO_ROOT, Settings
from common.schemas import Event

MOCK_IDS = [e["id"] for e in json.loads((REPO_ROOT / "data" / "mock" / "events.json").read_text())]


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


def test_health_reports_the_data_source(tmp_path):
    def health(**env):
        settings = Settings(LW_DATABASE_URL=f"sqlite:///{tmp_path / 'h.db'}", LW_MOCK_MODE=False,
                            **env)
        with TestClient(create_app(settings)) as c:
            return c.get("/health").json()["source"]

    assert health() == "live"
    assert health(LW_DATA_SOURCE="replay") == "replay"
    with pytest.raises(ValueError):
        Settings(LW_DATA_SOURCE="tape")


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


def test_mock_mode_serves_the_mocks(mock_client):
    ids = {e["id"] for e in mock_client.get("/events").json()}
    assert ids == set(MOCK_IDS)
    rec = mock_client.get(f"/recommendations/{MOCK_IDS[0]}").json()
    assert rec["sim"]["delay_new"] > 0 and rec["intersections"]


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
    sim = {"delay_default": 40, "delay_new": 30, "queue_default": 12, "queue_new": 8,
           "queue_series_default": [], "queue_series_new": []}
    client.post("/recommendations", json={**rec, "sim": sim})
    assert client.get("/recommendations/evt_test").json()["sim"] == sim


def test_snapshot_is_served(mock_client):
    resp = mock_client.get(f"/events/{MOCK_IDS[0]}/snapshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_snapshot_outside_data_dir_is_refused(client, sample_event):
    client.post("/events", json={**sample_event, "snapshot_path": "pyproject.toml"})
    assert client.get("/events/evt_test/snapshot").status_code == 404


def test_missing_snapshot_returns_404(client, sample_event):
    client.post("/events", json=sample_event)  # snapshot_path is None
    assert client.get("/events/evt_test/snapshot").status_code == 404


def test_turning_mock_mode_off_removes_the_mocks(make_client, sample_event):
    mock = make_client(mock_mode=True)
    assert len(mock.get("/events").json()) == len(MOCK_IDS)
    mock.post("/events", json=sample_event)             # a real event, same database
    mock.__exit__(None, None, None)
    real = make_client(mock_mode=False)
    assert [e["id"] for e in real.get("/events").json()] == [sample_event["id"]]
    assert real.get(f"/recommendations/{MOCK_IDS[0]}").status_code == 404


@pytest.mark.parametrize("action", ["accept", "reject", "false_positive"])
def test_each_feedback_action_is_stored_and_returned(client, sample_event, action):
    client.post("/events", json=sample_event)
    resp = client.post("/events/evt_test/feedback", json={"action": action, "note": "checked"})
    assert resp.status_code == 201
    want = {"event_id": "evt_test", "action": action, "note": "checked"}
    assert resp.json() == want
    assert client.get("/events/evt_test/feedback").json() == want
    assert client.get("/feedback").json() == [want]


def test_latest_feedback_replaces_the_earlier_one(client, sample_event):
    client.post("/events", json=sample_event)
    client.post("/events/evt_test/feedback", json={"action": "accept"})
    client.post("/events/evt_test/feedback", json={"action": "reject"})
    assert [f["action"] for f in client.get("/feedback").json()] == ["reject"]


def test_feedback_on_unknown_event_returns_404(client):
    assert client.post("/events/nope/feedback", json={"action": "accept"}).status_code == 404
    assert client.get("/events/nope/feedback").status_code == 404


def test_event_without_feedback_returns_404(client, sample_event):
    client.post("/events", json=sample_event)
    assert client.get("/events/evt_test/feedback").status_code == 404
    assert client.get("/feedback").json() == []


@pytest.mark.parametrize("body", [{"action": "approve"}, {}, {"action": None}])
def test_invalid_feedback_action_returns_422(client, sample_event, body):
    client.post("/events", json=sample_event)
    assert client.post("/events/evt_test/feedback", json=body).status_code == 422


def test_feedback_survives_an_api_restart(make_client):
    first = make_client(mock_mode=True)
    decisions = dict(zip(MOCK_IDS[:3], ["accept", "reject", "false_positive"], strict=True))
    for eid, action in decisions.items():
        first.post(f"/events/{eid}/feedback", json={"action": action})
    first.__exit__(None, None, None)
    again = make_client(mock_mode=True)  # re-seeding the mocks keeps the decisions
    got = {f["event_id"]: f["action"] for f in again.get("/feedback").json()}
    assert got == decisions


def test_turning_mock_mode_off_removes_mock_feedback(make_client):
    mock = make_client(mock_mode=True)
    mock.post(f"/events/{MOCK_IDS[0]}/feedback", json={"action": "accept"})
    mock.__exit__(None, None, None)
    assert make_client(mock_mode=False).get("/feedback").json() == []


# --- congestion (issue #47) ----------------------------------------------------------------

CAM_7AV_32 = "1e60ade7-c760-48cf-acd9-d9d6cbfa9420"


def reading(level="congested", ts="2026-09-27T01:20:00Z", camera=CAM_7AV_32, approach="7_ave",
            score=0.8):
    return {"camera_id": camera, "approach": approach, "direction": "southbound", "ts": ts,
            "level": level, "score": score, "occupancy": 0.3, "stuck_share": 0.7,
            "since_ts": "2026-09-27T01:15:00Z"}


def test_congestion_round_trips_and_only_the_latest_per_approach_is_listed(client):
    for body in (reading("slow", "2026-09-27T01:18:00Z", score=0.4), reading(),
                 reading("free", "2026-09-27T01:19:00Z", approach="7_ave_far", score=0)):
        assert client.post("/congestion", json=body).status_code == 201
    latest = {c["approach"]: c for c in client.get("/congestion").json()}
    assert set(latest) == {"7_ave", "7_ave_far"}
    assert latest["7_ave"]["level"] == "congested" and latest["7_ave"]["score"] == 0.8
    assert latest["7_ave_far"]["level"] == "free"          # a cleared approach is listed too
    fresh = client.get("/congestion", params={"since": "2026-09-27T01:19:30Z"}).json()
    assert [c["approach"] for c in fresh] == ["7_ave"]


def test_posting_the_same_congestion_reading_again_updates_it(client):
    client.post("/congestion", json=reading(score=0.5))
    client.post("/congestion", json=reading(score=0.9))
    history = client.get(f"/cameras/{CAM_7AV_32}/congestion").json()
    assert [c["score"] for c in history] == [0.9]


def test_camera_congestion_history_is_newest_first_and_filterable(client):
    for minute in (15, 16, 17):
        client.post("/congestion", json=reading(ts=f"2026-09-27T01:{minute}:00Z"))
    client.post("/congestion", json=reading(camera="other-camera"))
    history = client.get(f"/cameras/{CAM_7AV_32}/congestion").json()
    assert [c["ts"][:16] for c in history] == ["2026-09-27T01:17", "2026-09-27T01:16",
                                                 "2026-09-27T01:15"]
    since = client.get(f"/cameras/{CAM_7AV_32}/congestion",
                       params={"since": "2026-09-27T01:16:00Z", "limit": 1}).json()
    assert [c["ts"][:16] for c in since] == ["2026-09-27T01:17"]


@pytest.mark.parametrize("bad", [{"level": "jammed"}, {"score": 1.5}, {"camera_id": None}])
def test_invalid_congestion_returns_422(client, bad):
    assert client.post("/congestion", json={**reading(), **bad}).status_code == 422


def test_mock_mode_serves_mock_congestion_and_removes_it_when_off(make_client):
    mock = make_client(mock_mode=True)
    levels = {c["level"] for c in mock.get("/congestion").json()}
    assert levels == {"free", "slow", "congested"}
    real = make_client(mock_mode=False)                   # same database, mock mode off
    assert real.get("/congestion").json() == []
