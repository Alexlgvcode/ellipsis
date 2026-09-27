"""Incident notes (api/summarize.py) with a fake Anthropic client: CI never calls the API."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.summarize as summ
from api.main import create_app
from common.config import Settings
from common.schemas import Event, Recommendation, SignalChange, SimResult
from signals.worker import pass_once

CAM = "b0cbb042-de0a-449f-b5d1-49f68a9bf2ae"  # 7 Ave @ 36 St (mapped to a SUMO signal)
NOTE = "A delivery truck is double parked on 7 Ave @ 36 St."


def event(**over) -> Event:
    return Event(**{"id": "evt_1", "camera_id": CAM, "type": "double_parked",
                    "start_ts": "2026-09-26T18:21:44Z", "duration_s": 521,
                    "bbox": [192, 79, 228, 124], "lane_zone": "curb_adjacent",
                    "confidence": 0.69, **over})


def rec(sim=True) -> Recommendation:
    return Recommendation(
        event_id="evt_1", intersections=[SignalChange(id="tls_7av_35st", phase=1, change_s=-6.8)],
        sim=SimResult(delay_default=48.3, delay_new=39.1, queue_default=21, queue_new=13)
        if sim else None)


class FakeClaude:
    """Records the request and answers like client.beta.messages.create."""

    def __init__(self, text=NOTE, stop_reason="end_turn", error=None):
        self.calls = []
        self.text, self.stop_reason, self.error = text, stop_reason, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        blocks = [SimpleNamespace(type="thinking", thinking=""),
                  SimpleNamespace(type="text", text=self.text)]
        return SimpleNamespace(stop_reason=self.stop_reason, content=blocks)


class FakeGemini:
    """Records the request and answers like client.models.generate_content."""

    def __init__(self, text=NOTE, error=None):
        self.calls = []
        self.text, self.error = text, error
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)   # None: the response was blocked


def settings(provider="gemini", **keys):
    return SimpleNamespace(summary_provider=provider, gemini_model="gemini-test",
                           summary_model="claude-test", gemini_api_key=keys.get("gemini"),
                           anthropic_api_key=keys.get("claude"))


@pytest.fixture(autouse=True)
def _pinned_settings(monkeypatch):
    """Gemini is the default provider; a local .env can't change what these tests see."""
    monkeypatch.setattr(summ, "get_settings", lambda: settings())


def test_prompt_has_the_event_and_the_simulated_change():
    prompt = summ.build_prompt(event(), rec(), camera_name="7 Ave @ 36 St")
    assert "a double-parked vehicle" in prompt
    assert "Camera: 7 Ave @ 36 St" in prompt
    assert "2:21 PM New York time" in prompt              # 18:21 UTC is 14:21 EDT
    assert "at least: 521 s" in prompt
    assert "Lane: curb adjacent" in prompt and "69%" in prompt
    assert "phase 1 green 6.8 s shorter" in prompt
    assert "48.3 s now, 39.1 s with the change" in prompt
    assert "21 vehicles now, 13 with the change" in prompt


def test_prompt_without_a_recommendation_or_sim_yet():
    assert "Recommended change: none yet" in summ.build_prompt(event())
    assert "Simulation: still running" in summ.build_prompt(event(), rec(sim=False))
    assert f"Camera: {CAM}" in summ.build_prompt(event())   # no name: the id


def test_no_api_key_means_no_client_and_no_note(monkeypatch):
    monkeypatch.undo()                                      # the real _client this time
    monkeypatch.setattr(summ, "get_settings", lambda: settings())
    for provider in ("gemini", "claude"):
        assert summ._client(settings(provider)) is None
        assert summ._client(settings(provider, gemini="", claude="")) is None
    assert summ.summarize(event(), rec()) is None           # doesn't crash


def test_each_provider_gets_its_own_sdk_client(monkeypatch):
    monkeypatch.undo()
    pytest.importorskip("google.genai")
    pytest.importorskip("anthropic")
    from anthropic import Anthropic
    from google.genai import Client

    assert isinstance(summ._client(settings("gemini", gemini="g-key")), Client)
    assert isinstance(summ._client(settings("claude", claude="c-key")), Anthropic)
    assert summ._client(settings("gemini", claude="c-key")) is None   # the other key isn't used


def test_gemini_gets_the_facts_the_system_prompt_and_the_model():
    fake = FakeGemini(text=f"  {NOTE}\n")
    assert summ.summarize(event(), rec(), "7 Ave @ 36 St", client=fake) == NOTE
    (call,) = fake.calls
    assert call["model"] == "gemini-test"
    assert "7 Ave @ 36 St" in call["contents"] and "48.3 s now" in call["contents"]
    assert call["config"] == {"system_instruction": summ.SYSTEM,
                              "max_output_tokens": summ.MAX_TOKENS}


@pytest.mark.parametrize("fake", [FakeGemini(text=None), FakeGemini(text="  "),
                                  FakeGemini(error=RuntimeError("quota"))])
def test_gemini_blocks_empty_answers_and_errors_give_no_note(fake):
    assert summ.summarize(event(), rec(), client=fake) is None


def test_summarize_sends_the_facts_and_returns_the_text():
    fake = FakeClaude(text=f"  {NOTE}\n")
    assert summ.summarize(event(), rec(), "7 Ave @ 36 St", client=fake, model="m",
                          provider="claude") == NOTE
    (call,) = fake.calls
    assert call["model"] == "m"
    assert call["system"] == summ.SYSTEM
    assert "7 Ave @ 36 St" in call["messages"][0]["content"]
    assert call["fallbacks"] == "default" and call["betas"] == [summ.FALLBACK_BETA]


@pytest.mark.parametrize("fake", [FakeClaude(stop_reason="refusal"), FakeClaude(text="  "),
                                  FakeClaude(error=RuntimeError("overloaded"))])
def test_refusals_empty_answers_and_errors_give_no_note(fake):
    assert summ.summarize(event(), rec(), client=fake, provider="claude") is None


@pytest.fixture
def client(tmp_path):
    settings = Settings(LW_DATABASE_URL=f"sqlite:///{tmp_path / 'api.db'}", LW_MOCK_MODE=False)
    with TestClient(create_app(settings)) as c:
        c.post("/events", json=event().model_dump(mode="json"))
        yield c


def test_note_is_stored_and_listed(client):
    assert summ.post_summary(client, event(), rec(), client=FakeGemini()) == NOTE
    want = {"event_id": "evt_1", "text": NOTE, "model": "gemini-test"}
    assert client.get("/events/evt_1/summary").json() == want
    assert client.get("/summaries").json() == [want]


def test_summary_endpoints_404_and_422(client):
    assert client.get("/events/evt_1/summary").status_code == 404
    assert client.post("/events/nope/summary", json={"text": NOTE}).status_code == 404
    assert client.post("/events/evt_1/summary", json={"text": ""}).status_code == 422


def test_worker_writes_a_note_after_scoring(client):
    notes = []

    def score(ev, mapping):
        return rec().model_copy(update={"event_id": ev.id})

    def note(api, ev, r, name):
        notes.append((ev.id, r.sim.delay_new, name))
        return summ.post_summary(api, ev, r, name, client=FakeGemini())

    assert pass_once(client, score=score, note=note) == 1
    assert notes == [("evt_1", 39.1, "7 Ave @ 36 St")]
    assert client.get("/events/evt_1/summary").json()["text"] == NOTE


def test_worker_still_scores_without_an_api_key(client):
    score = lambda ev, mapping: rec().model_copy(update={"event_id": ev.id})  # noqa: E731
    assert pass_once(client, score=score) == 1               # default note: no key, no note
    assert client.get("/recommendations/evt_1").status_code == 200
    assert client.get("/summaries").json() == []
