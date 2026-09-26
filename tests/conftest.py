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
