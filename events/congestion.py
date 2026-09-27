"""Per-camera congestion state (issue #47 Part B): free / slow / congested + a 0-1 score.

A stopped vehicle means a blockage only if the traffic around it moves; when nobody moves
it's a jam, which operators want to see as such. One monitor per camera, fed the
detections of every frame (not tracks: creeping cars 5 s apart break IoU tracking).
For each approach (the mask's `approaches`, or all road zones when it has none), split in
a far and a near part when `far_split` > 0 (the far part is the top `far_split` of the
approach's height, reported as "<name>_far"), so a queue up the street isn't averaged away by
an empty stop line:

    vehicles    detections whose box bottom-center is in the approach, leaving out curb
                zones (parked cars) and vehicles that have an open blockage event
    stuck       vehicles whose box overlaps a box of the previous frame (IoU >= stuck_iou).
                Frames are 2-5 s apart, so a moving vehicle never does
    occupancy   share of the approach covered by vehicles (the lower half of each box,
                roughly where it sits on the road)

Frames go into `bin_s` bins over the last `window_s` (two signal cycles):

    floor       the lowest stuck share of any bin (a bin with no vehicles counts as 0)
    busy        mean occupancy >= min_occupancy, or mean vehicles per frame >= min_vehicles
                (far cars are tiny at 352x240: a packed far queue covers little area)
    congested   floor >= congested_floor and busy
    slow        floor >= slow_floor and busy
    score       floor x min(1, occupancy / full_occupancy): the heatmap intensity

A red light stops everyone for less than a cycle, so within every window there's a bin
where the queue moves on green and the floor drops. A jam never clears. Until a camera
has a full window of frames it reads free.

    monitor = CongestionMonitor(mask)
    readings = monitor.update(ts, detections, exclude=[e.bbox for e in engine.open.values()])
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from common.schemas import BBox, Congestion, CongestionLevel, LaneZone
from events.masks import Approach, CameraMask, ground_point
from events.rules import load_rules
from vision.detect import Detection
from vision.track import iou

ROAD_ZONES = {LaneZone.CURB_ADJACENT, LaneZone.TRAVEL, LaneZone.BOX, LaneZone.BUS_STOP}
ROAD = "road"  # the approach used when a mask has no `approaches`
EXCLUDE_IOU = 0.5  # a detection this close to an open blockage's box is that vehicle


@dataclass(frozen=True)
class _Frame:
    ts: datetime
    vehicles: int
    stuck: int
    occupancy: float


@dataclass
class _ApproachState:
    name: str
    cells: np.ndarray  # (n, 2) centers of the grid cells the approach covers
    direction: str | None
    contains: object   # (x, y) -> bool: is a vehicle standing here in the approach?
    frames: deque[_Frame] = field(default_factory=deque)
    level: CongestionLevel = CongestionLevel.FREE
    since: datetime | None = None


class CongestionMonitor:
    """Congestion for one camera. Call update() once per frame that isn't frozen."""

    def __init__(self, mask: CameraMask, rules: dict | None = None):
        rules = rules or load_rules()
        c = rules["congestion"]
        self.mask = mask
        self.min_conf = c["min_conf"]
        self.stuck_iou = c["stuck_iou"]
        self.bin_s = c["bin_s"]
        self.window_s = c["window_s"]
        self.max_gap_s = c["max_gap_s"]
        self.slow_floor = c["slow_floor"]
        self.congested_floor = c["congested_floor"]
        self.min_occupancy = c["min_occupancy"]
        self.min_vehicles = c.get("min_vehicles", 0)
        self.far_split = c.get("far_split", 0.0)
        self.exit_floor_drop = c.get("exit_floor_drop", 0.0)
        self.exit_occupancy = c.get("exit_occupancy", self.min_occupancy)
        self.full_occupancy = c["full_occupancy"]
        self.cell_px = c["cell_px"]
        self.approaches = [s for a in (mask.approaches or [None]) for s in self._states(a)]
        self._prev: tuple[datetime, list[BBox]] | None = None
        self.readings: list[Congestion] = []

    def update(self, ts: datetime, detections: Sequence[Detection],
               exclude: Sequence[BBox] = ()) -> list[Congestion]:
        """One reading per approach. `exclude`: boxes of vehicles with open blockage events."""
        boxes = [d.bbox for d in detections if d.conf >= self.min_conf]
        prev = self._prev
        self._prev = (ts, boxes)
        fresh = prev is not None and (ts - prev[0]).total_seconds() <= self.max_gap_s
        counted = [b for b in boxes if not any(iou(b, e) >= EXCLUDE_IOU for e in exclude)]
        self.readings = []
        for a in self.approaches:
            if fresh:
                mine = [b for b in counted if a.contains(*ground_point(b))]
                stuck = sum(any(iou(b, p) >= self.stuck_iou for p in prev[1]) for b in mine)
                a.frames.append(_Frame(ts, len(mine), stuck, self._occupancy(a, mine)))
            while a.frames and (ts - a.frames[0].ts).total_seconds() >= self.window_s:
                a.frames.popleft()
            self.readings.append(self._reading(a, ts))
        return self.readings

    def reset(self) -> None:
        """Forget everything (the camera's view moved: the approaches no longer line up)."""
        self._prev = None
        self.readings = []
        for a in self.approaches:
            a.frames.clear()
            a.level, a.since = CongestionLevel.FREE, None

    # --- helpers -------------------------------------------------------------------------

    def _states(self, approach: Approach | None) -> list[_ApproachState]:
        if approach is None:
            def inside(x, y):
                zone = self.mask.zone_at(x, y)
                return zone is not None and zone.type in ROAD_ZONES
        else:
            def inside(x, y):
                zone = self.mask.zone_at(x, y)
                return approach.contains(x, y) and (zone is None or zone.type is not LaneZone.CURB)
        name = approach.name if approach else ROAD
        direction = approach.direction if approach else None
        w, h = self.mask.frame_size
        step = self.cell_px
        cells = [(x, y) for y in np.arange(step / 2, h, step) for x in np.arange(step / 2, w, step)
                 if inside(x, y)]
        if not self.far_split or not cells:
            return [self._state(name, direction, cells, inside)]
        ys = [y for _, y in cells]
        split = min(ys) + self.far_split * (max(ys) - min(ys))
        return [self._state(f"{name}_far", direction, [c for c in cells if c[1] < split],
                            lambda x, y: y < split and inside(x, y)),
                self._state(name, direction, [c for c in cells if c[1] >= split],
                            lambda x, y: y >= split and inside(x, y))]

    @staticmethod
    def _state(name: str, direction: str | None, cells: list, contains) -> _ApproachState:
        return _ApproachState(name, np.array(cells, dtype=float).reshape(-1, 2), direction,
                              contains)

    def _occupancy(self, a: _ApproachState, boxes: Sequence[BBox]) -> float:
        if not len(a.cells):
            return 0.0
        covered = np.zeros(len(a.cells), dtype=bool)
        xs, ys = a.cells[:, 0], a.cells[:, 1]
        for x1, y1, x2, y2 in boxes:
            covered |= (xs >= x1) & (xs <= x2) & (ys >= (y1 + y2) / 2) & (ys <= y2)
        return float(covered.mean())

    def _reading(self, a: _ApproachState, ts: datetime) -> Congestion:
        n_bins = math.ceil(self.window_s / self.bin_s)
        bins = [[0, 0, 0] for _ in range(n_bins)]  # vehicles, stuck, frames
        for f in a.frames:
            b = bins[min(n_bins - 1, int((ts - f.ts).total_seconds() // self.bin_s))]
            b[0] += f.vehicles
            b[1] += f.stuck
            b[2] += 1
        vehicles = sum(f.vehicles for f in a.frames)
        stuck_share = sum(f.stuck for f in a.frames) / vehicles if vehicles else 0.0
        occupancy = sum(f.occupancy for f in a.frames) / len(a.frames) if a.frames else 0.0
        per_frame = vehicles / len(a.frames) if a.frames else 0.0
        # hysteresis: a level is kept until traffic clearly recovers (lower thresholds to
        # leave it than to enter it), so one jam doesn't flicker congested / slow / free
        held = a.level is not CongestionLevel.FREE
        drop = self.exit_floor_drop if held else 0.0
        busy = occupancy >= (self.exit_occupancy if held else self.min_occupancy) or \
            bool(self.min_vehicles) and per_frame >= self.min_vehicles
        full = bool(a.frames) and \
            (ts - a.frames[0].ts).total_seconds() >= self.window_s - self.bin_s
        shares = [s / n if n else 0.0 for n, s, frames in bins if frames]
        floor = min(shares) if full and shares else 0.0
        level = CongestionLevel.FREE
        if busy:
            congested = self.congested_floor - (drop if a.level is CongestionLevel.CONGESTED else 0)
            if floor >= congested:
                level = CongestionLevel.CONGESTED
            elif floor >= self.slow_floor - drop:
                level = CongestionLevel.SLOW
        if level is not a.level or a.since is None:
            a.level, a.since = level, ts
        score = floor * min(1.0, occupancy / self.full_occupancy) if self.full_occupancy else floor
        return Congestion(camera_id=self.mask.camera_id, approach=a.name, direction=a.direction,
                          ts=ts, level=level, score=round(min(1.0, score), 3),
                          occupancy=round(min(1.0, occupancy), 3),
                          stuck_share=round(min(1.0, stuck_share), 3), since_ts=a.since)
