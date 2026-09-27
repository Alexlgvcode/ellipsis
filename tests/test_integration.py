"""Event posted to the API is scored once and can be read back. SUMO is stubbed."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from common.config import Settings
from common.schemas import Event, Recommendation, SimResult
from signals.retime import signal_changes
from signals.worker import pass_once

CAMERA = "6a85384f-d82e-4bff-b5f1-15c22cca70e6"  # 8th Ave @ 33rd St, in camera_signals.json


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        LW_DATABASE_URL=f"sqlite:///{tmp_path / 'test.db'}",
        LW_MOCK_MODE=False,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def event() -> dict:
    return {
        "id": "evt_live",
        "camera_id": CAMERA,
        "type": "double_parked",
        "start_ts": "2026-09-26T18:23:00Z",
        "duration_s": 74,
        "bbox": [120, 88, 176, 130],
        "lane_zone": "curb_adjacent",
        "confidence": 0.82,
        "snapshot_path": None,
    }


def test_worker_scores_a_new_event_once(client):
    calls = {"n": 0}

    def score(ev: Event, mapping: dict) -> Recommendation:
        calls["n"] += 1
        return Recommendation(
            event_id=ev.id,
            intersections=signal_changes(ev, mapping),
            sim=SimResult(delay_default=40.0, delay_new=32.0, queue_default=8, queue_new=4),
        )

    assert client.post("/events", json=event()).status_code == 201
    assert pass_once(client, score=score) == 1
    got = client.get("/recommendations/evt_live").json()
    assert got["sim"]["queue_default"] == 8
    assert got["sim"]["queue_new"] == 4
    assert got["intersections"][0]["change_s"] < 0

    assert pass_once(client, score=score) == 0
    assert calls["n"] == 1


def test_worker_skips_an_unmapped_camera(client):
    body = {**event(), "id": "evt_other", "camera_id": "cam_test"}

    def score(ev: Event, mapping: dict) -> Recommendation:
        raise AssertionError("should not score")

    assert client.post("/events", json=body).status_code == 201
    assert pass_once(client, score=score) == 0
    assert client.get("/recommendations/evt_other").status_code == 404
