"""Shared fixtures.

Tests that need heavy deps should skip cleanly when those aren't installed, so the
default CI job (core deps only) stays fast:

    ultralytics = pytest.importorskip("ultralytics")   # vision
    traci = pytest.importorskip("traci")               # sim
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def sample_event() -> dict:
    return {
        "id": "evt_test",
        "camera_id": "cam_test",
        "type": "double_parked",
        "start_ts": "2026-09-26T14:05:12Z",
        "duration_s": 74,
        "bbox": [120, 88, 176, 130],
        "lane_zone": "curb_adjacent",
        "confidence": 0.82,
        "snapshot_path": None,
    }


@pytest.fixture(autouse=True)
def _no_real_claude_calls(monkeypatch):
    """Tests never reach the Anthropic API, even with ANTHROPIC_API_KEY in a local .env:
    code that would build a real client gets None (tests pass a fake client instead)."""
    import api.summarize

    monkeypatch.setattr(api.summarize, "_client", lambda api_key: None)


@pytest.fixture(autouse=True)
def _no_real_elevenlabs_calls(monkeypatch):
    """Same for spoken alerts: tests see no ELEVENLABS_API_KEY unless they set one."""
    from types import SimpleNamespace

    import api.voice

    monkeypatch.setattr(api.voice, "get_settings", lambda: SimpleNamespace(
        elevenlabs_api_key=None, voice_id="v", voice_model="m"))
