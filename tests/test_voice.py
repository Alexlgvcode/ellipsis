"""Spoken alerts (api/voice.py) with a mocked ElevenLabs endpoint: CI never calls it."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import api.voice as voice
from api.main import create_app
from common.config import Settings
from common.schemas import Event

CAM = "b0cbb042-de0a-449f-b5d1-49f68a9bf2ae"   # 7 Ave @ 36 St
MP3 = b"ID3fake-mp3"


def event(**over) -> Event:
    return Event(**{"id": "evt_1", "camera_id": CAM, "type": "double_parked",
                    "start_ts": "2026-09-26T18:21:44Z", "duration_s": 61,
                    "bbox": [192, 79, 228, 124], "lane_zone": "curb_adjacent",
                    "confidence": 0.69, **over})


def with_key(monkeypatch):
    monkeypatch.setattr(voice, "get_settings", lambda: SimpleNamespace(
        elevenlabs_api_key="k", voice_id="VOICE", voice_model="MODEL"))


def test_alert_text_reads_like_a_dispatcher():
    assert voice.spoken_place("7 Ave @ 36 St") == "7 Avenue at 36 Street"
    assert voice.spoken_place("Broadway @ 6 Ave / 33 St") == "Broadway at 6 Avenue and 33 Street"
    assert voice.alert_text(event(), "7 Ave @ 36 St") == \
        "Double-parked vehicle, 7 Avenue at 36 Street. Needs review."
    assert voice.alert_text(event(type="stopped_in_lane", confidence=0.9), "8th Ave @ 31st St") == \
        "Vehicle stopped in a travel lane, 8th Avenue at 31st Street."


def test_speak_calls_elevenlabs_with_the_key_voice_and_model(monkeypatch):
    with_key(monkeypatch)
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), key=request.headers["xi-api-key"],
                    body=json.loads(request.content))
        return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert voice.speak("hello", client) == MP3
    assert seen == {"url": "https://api.elevenlabs.io/v1/text-to-speech/VOICE", "key": "k",
                    "body": {"text": "hello", "model_id": "MODEL"}}


def test_no_key_or_an_api_error_gives_no_audio(monkeypatch):
    assert voice.speak("hello") is None                      # conftest: no key
    with_key(monkeypatch)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))) as client:
        assert voice.speak("hello", client) is None


@pytest.fixture
def client(tmp_path):
    settings = Settings(LW_DATABASE_URL=f"sqlite:///{tmp_path / 'api.db'}", LW_MOCK_MODE=False,
                        LW_DATA_DIR=str(tmp_path / "data"))
    with TestClient(create_app(settings)) as c:
        c.post("/events", json=event().model_dump(mode="json"))
        yield c, tmp_path / "data"


def test_voice_endpoint_is_404_without_a_key(client):
    c, _ = client
    assert c.get("/events/evt_1/voice").status_code == 404
    assert c.get("/events/nope/voice").status_code == 404


def test_voice_endpoint_generates_once_then_serves_the_cache(client, monkeypatch):
    c, data = client
    calls = []
    monkeypatch.setattr(voice, "speak", lambda text, client=None: calls.append(text) or MP3)
    for _ in range(2):
        resp = c.get("/events/evt_1/voice")
        assert resp.status_code == 200 and resp.content == MP3
        assert resp.headers["content-type"] == "audio/mpeg"
    assert len(calls) == 1 and calls[0].startswith("Double-parked vehicle")
    assert (data / "voice" / "evt_1.mp3").read_bytes() == MP3


def test_voice_endpoint_stops_at_the_daily_cap(tmp_path, monkeypatch):
    settings = Settings(LW_DATABASE_URL=f"sqlite:///{tmp_path / 'api.db'}", LW_MOCK_MODE=False,
                        LW_DATA_DIR=str(tmp_path / "data"), LW_VOICE_PER_DAY=1)
    monkeypatch.setattr(voice, "speak", lambda text, client=None: MP3)
    with TestClient(create_app(settings)) as c:
        for i in (1, 2):
            c.post("/events", json=event(id=f"evt_{i}").model_dump(mode="json"))
        assert c.get("/events/evt_1/voice").status_code == 200
        assert c.get("/events/evt_2/voice").status_code == 404   # today's one is used
        assert c.get("/events/evt_1/voice").status_code == 200   # cached ones still play
