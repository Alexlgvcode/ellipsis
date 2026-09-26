"""Per-camera pipeline: frozen-feed check -> tracker -> event engine, one frame at a time.

Detection happens outside (it's batched across frames or cameras on the GPU), so the
same pipeline serves replay (scripts/replay.py), the engine CLI and live mode.

    pipe = CameraPipeline.for_camera(camera_id)
    update = pipe.step(ts, image, detections)   # -> EngineUpdate (opened/updated/closed)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from PIL import Image

from events.engine import EngineUpdate, EventEngine
from events.rules import load_rules
from ingest.health import is_frozen, thumbnail
from vision.detect import Detection
from vision.track import CameraTracker, Track


class CameraPipeline:
    def __init__(self, engine: EventEngine, rules: dict | None = None):
        rules = rules or load_rules()
        self.engine = engine
        self.tracker = CameraTracker(rules)
        self.tracks: list[Track] = []  # the tracker's output for the last frame
        self._prev_thumb = None

    @classmethod
    def for_camera(cls, camera_id: str, rules: dict | None = None) -> CameraPipeline | None:
        """None for cameras without a lane mask."""
        engine = EventEngine.for_camera(camera_id, rules)
        return cls(engine, rules) if engine else None

    @property
    def camera_id(self) -> str:
        return self.engine.mask.camera_id

    def step(self, ts: datetime, image: Image.Image,
             detections: Sequence[Detection]) -> EngineUpdate:
        thumb = thumbnail(image)
        frozen = self._prev_thumb is not None and is_frozen(self._prev_thumb, thumb)
        self._prev_thumb = thumb
        if frozen:  # don't let a stuck picture make every vehicle look parked
            self.tracks = []
            return self.engine.update(ts, [], [], feed_still=True)
        self.tracks = self.tracker.update(ts, detections)
        return self.engine.update(ts, self.tracks, self.tracker.ended)
