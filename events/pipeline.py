"""Per-camera pipeline: frozen-feed and moved-view checks -> tracker -> event engine.

Detection happens outside (it's batched across frames or cameras on the GPU), so the
same pipeline serves replay (scripts/replay.py), the engine CLI and live mode.

    pipe = CameraPipeline.for_camera(camera_id)
    update = pipe.step(ts, image, detections)   # -> EngineUpdate (opened/updated/closed)
    pipe.congestion.readings                    # -> the camera's congestion state per approach

Moved view: NYC DOT cameras pan and zoom. Each frame's edges are compared with the
lane mask's reference frame (events/view.py); after `view.pause_after_frames` frames
below `view.min_similarity` the camera is paused (`paused` is True): its open events
close and none open, because the mask no longer lines up. It resumes, with a fresh
tracker, after `view.resume_after_frames` frames back above the threshold. Congestion
starts over too, and has no readings while paused.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from PIL import Image

from events.congestion import CongestionMonitor
from events.engine import EngineUpdate, EventEngine
from events.masks import MASKS_DIR
from events.rules import load_rules
from events.view import edge_signature, view_similarity
from ingest.health import is_frozen, thumbnail
from vision.detect import Detection
from vision.track import CameraTracker, Track


class CameraPipeline:
    def __init__(self, engine: EventEngine, rules: dict | None = None):
        rules = rules or load_rules()
        self.rules = rules
        self.engine = engine
        self.tracker = CameraTracker(rules)
        self.congestion = CongestionMonitor(engine.mask, rules)
        self.tracks: list[Track] = []  # the tracker's output for the last frame
        self._prev_thumb = None
        view = rules.get("view") or {}
        self.view_min = view.get("min_similarity", 0.0)
        self.pause_after = view.get("pause_after_frames", 3)
        self.resume_after = view.get("resume_after_frames", 3)
        self.paused = False
        self._view_streak = 0  # frames in a row on the other side of the threshold
        ref = MASKS_DIR / f"{engine.mask.camera_id}.jpg"
        self._reference = edge_signature(Image.open(ref)) if ref.exists() else None

    @classmethod
    def for_camera(cls, camera_id: str, rules: dict | None = None) -> CameraPipeline | None:
        """None for cameras without a lane mask."""
        engine = EventEngine.for_camera(camera_id, rules)
        return cls(engine, rules) if engine else None

    @property
    def camera_id(self) -> str:
        return self.engine.mask.camera_id

    def step(self, ts: datetime, image: Image.Image | None,
             detections: Sequence[Detection], frozen: bool | None = None,
             view: float | None = None) -> EngineUpdate:
        """`frozen` and `view` (similarity to the reference frame) can be given instead of
        computed from `image`, e.g. from evaluation/detections/."""
        if view is None and image is not None and self._reference is not None:
            view = view_similarity(self._reference, image)
        if view is not None and self._view_changed(view):
            self.tracks = []
            self.congestion.reset()
            return EngineUpdate(closed=self.engine.close_all()) if self.paused else EngineUpdate()
        if self.paused:
            return EngineUpdate()
        if frozen is None:
            thumb = thumbnail(image)
            frozen = self._prev_thumb is not None and is_frozen(self._prev_thumb, thumb)
            self._prev_thumb = thumb
        if frozen:  # don't let a stuck picture make every vehicle look parked
            self.tracks = []
            return self.engine.update(ts, [], [], feed_still=True)
        self.tracks = self.tracker.update(ts, detections)
        update = self.engine.update(ts, self.tracks, self.tracker.ended)
        self.congestion.update(ts, detections, [e.bbox for e in self.engine.open.values()])
        return update

    def _view_changed(self, similarity: float) -> bool:
        """Update the paused state; True on the frame the camera pauses or resumes."""
        off = similarity < self.view_min
        self._view_streak = self._view_streak + 1 if off != self.paused else 0
        if not self.paused and self._view_streak >= self.pause_after:
            self.paused, self._view_streak = True, 0
            return True
        if self.paused and self._view_streak >= self.resume_after:
            self.paused, self._view_streak = False, 0
            self.tracker = CameraTracker(self.rules)  # old tracks refer to the old view
            return True
        return False
