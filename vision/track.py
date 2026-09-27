"""Tracker + stationary test (F3).

One tracker per camera. Frames arrive 2-5 s apart, so motion models (Kalman,
as in ByteTrack) can't predict where a moving car will be; what matters is
that a *stopped* vehicle keeps its ID. Tracks are linked by box overlap only
(class is ignored for matching) and survive a few missed frames, e.g. while a
bus passes in front of a parked van.

Stationary test (events/rules.yaml `stationary`): at least 3 of the box's 4 edges
moved less than 5% of the box diagonal, AND IoU > 0.5. Counting edges instead of
the center matters for occlusion: when a passing car or pedestrian hides a
parked truck's bottom, only that edge moves, but the center shifts enough to
look like motion. Driving moves at least two edges. A still streak starts when
two consecutive boxes pass; from then
on each new box is compared to the streak's *anchor* box (where the vehicle
parked), not the previous frame, and the streak only resets after
`reset_after_frames` failures in a row. One glitchy box (partly hidden by a
passing bus or a pedestrian) no longer wipes out minutes of stationary time.
`stationary_since` is the time of the first frame of the current streak.

The reported class is the majority vote over the track's history, since the
per-frame class is unreliable (yellow cabs flip between car/truck/bus).

    python -m vision.track data/frames/<camera_id> --out runs/track [--limit 80]
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from common.schemas import VehicleClass
from events.rules import load_rules
from vision.detect import Detection, find_frames

BBox = tuple[float, float, float, float]


def iou(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def center(b: BBox) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def is_still(prev: BBox, cur: BBox, max_shift_frac: float, min_iou: float,
             min_edges: int = 3) -> bool:
    """At least `min_edges` of the 4 edges moved < max_shift_frac of the box diagonal,
    and IoU > min_iou."""
    tol = max_shift_frac * math.hypot(prev[2] - prev[0], prev[3] - prev[1])
    steady = sum(abs(a - b) < tol for a, b in zip(prev, cur, strict=True))
    return steady >= min_edges and iou(prev, cur) > min_iou


def frame_timestamp(path: Path) -> datetime:
    """UTC time from the poller's path: .../<YYYYMMDD>/<HHMMSS>.jpg"""
    return datetime.strptime(path.parent.name + path.stem, "%Y%m%d%H%M%S").replace(
        tzinfo=timezone.utc)


@dataclass
class Track:
    id: int
    first_seen: datetime
    last_seen: datetime
    bbox: BBox
    conf: float
    stationary_since: datetime | None = None
    anchor: BBox | None = None  # box where the current still streak started
    strikes: int = 0            # consecutive frames that failed the test vs anchor
    still_seen: int = 0         # frames the vehicle was detected during the current still streak
    still_missed: int = 0       # frames it wasn't
    max_stationary_s: float = 0.0
    hits: int = 1
    missed: int = 0  # consecutive frames without a matching detection
    class_votes: Counter = field(default_factory=Counter)

    @property
    def cls(self) -> VehicleClass:
        return self.class_votes.most_common(1)[0][0]

    @property
    def seen_frac(self) -> float:
        """Share of the still streak's frames the vehicle was actually detected in. A parked
        vehicle is seen almost every frame; different buses passing one spot leave gaps."""
        total = self.still_seen + self.still_missed
        return self.still_seen / total if total else 0.0

    @property
    def stationary_s(self) -> float:
        """Seconds still, as of the last frame this track was seen."""
        if self.stationary_since is None:
            return 0.0
        return (self.last_seen - self.stationary_since).total_seconds()

    def to_dict(self) -> dict:
        return {"id": self.id, "cls": self.cls.value, "bbox": [round(v, 1) for v in self.bbox],
                "conf": round(self.conf, 3), "stationary_s": round(self.stationary_s, 1),
                "first_seen": self.first_seen.isoformat(), "hits": self.hits,
                "missed": self.missed}


class CameraTracker:
    """Tracks for one camera. Call update() once per frame, in time order."""

    def __init__(self, rules: dict | None = None):
        rules = rules or load_rules()
        self.max_shift_frac = rules["stationary"]["max_edge_shift_frac"]
        self.min_edges = rules["stationary"]["min_still_edges"]
        self.min_iou = rules["stationary"]["min_iou"]
        self.reset_after = rules["stationary"]["reset_after_frames"]
        self.match_iou = rules["tracking"]["match_iou"]
        self.start_conf = rules["tracking"].get("start_conf", 0.0)
        self.keep_conf = rules["tracking"].get("keep_conf", 0.0)
        self.keep_iou = rules["tracking"].get("keep_iou", self.match_iou)
        self.max_missed = rules["track_lost_frames"]
        self.max_gap_s = rules["tracking"]["max_gap_s"]
        self.tracks: dict[int, Track] = {}
        self.ended: list[Track] = []  # tracks dropped by the last update()
        self._next_id = 1

    def update(self, ts: datetime, detections: Sequence[Detection]) -> list[Track]:
        """Link detections to tracks. Returns live tracks, including ones missed for
        up to `track_lost_frames` frames (`missed` > 0)."""
        self.ended = [self.tracks.pop(tid) for tid, t in list(self.tracks.items())
                      if (ts - t.last_seen).total_seconds() > self.max_gap_s]
        # Two confidence levels (the ByteTrack idea): confident detections link first and may
        # start tracks; weak ones (keep_conf..start_conf) may only continue an existing track
        # at a tighter overlap. The model's confidence on a tow truck swings 0.10-0.62 frame
        # to frame; with one cutoff it "disappears" in half the frames.
        strong = [i for i, d in enumerate(detections) if d.conf >= self.start_conf]
        weak = [i for i, d in enumerate(detections) if self.keep_conf <= d.conf < self.start_conf]
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for dets, min_overlap in ((strong, self.match_iou), (weak, self.keep_iou)):
            pairs = sorted(
                ((iou(t.bbox, detections[di].bbox), tid, di)
                 for tid, t in self.tracks.items() if tid not in matched_tracks for di in dets),
                reverse=True,
            )
            for overlap, tid, di in pairs:  # greedy, best overlap first
                if overlap < min_overlap:
                    break
                if tid in matched_tracks or di in matched_dets:
                    continue
                matched_tracks.add(tid)
                matched_dets.add(di)
                self._extend(self.tracks[tid], ts, detections[di])

        for di in strong:
            d = detections[di]
            if di not in matched_dets:
                self.tracks[self._next_id] = Track(
                    id=self._next_id, first_seen=ts, last_seen=ts, bbox=d.bbox, conf=d.conf,
                    class_votes=Counter([d.cls]))
                self._next_id += 1

        for tid in [t for t in self.tracks if t not in matched_tracks]:
            track = self.tracks[tid]
            if track.last_seen == ts:  # created this frame
                continue
            track.missed += 1
            if track.stationary_since is not None:
                track.still_missed += 1
            if track.missed > self.max_missed:
                self.ended.append(self.tracks.pop(tid))
        return list(self.tracks.values())

    def _extend(self, track: Track, ts: datetime, det: Detection) -> None:
        def still(ref: BBox) -> bool:
            return is_still(ref, det.bbox, self.max_shift_frac, self.min_iou, self.min_edges)

        if track.stationary_since is None:
            if still(track.bbox):  # start a streak at the previous observation
                track.stationary_since, track.anchor, track.strikes = (
                    track.last_seen, track.bbox, 0)
                track.still_seen, track.still_missed = 1, 0
        elif still(track.anchor):
            track.strikes = 0
        else:
            track.strikes += 1
            if track.strikes >= self.reset_after:  # it really moved
                track.stationary_since, track.anchor, track.strikes = None, None, 0
        if track.stationary_since is not None:
            track.still_seen += 1
        track.last_seen = ts
        track.bbox = det.bbox
        track.conf = det.conf
        track.hits += 1
        track.missed = 0
        track.class_votes[det.cls] += 1
        if not track.strikes:  # a frame that already looks moved doesn't extend the record
            track.max_stationary_s = max(track.max_stationary_s, track.stationary_s)


class MultiCameraTracker:
    """One CameraTracker per camera id."""

    def __init__(self, rules: dict | None = None):
        self.rules = rules
        self.cameras: dict[str, CameraTracker] = {}

    def update(self, camera_id: str, ts: datetime,
               detections: Sequence[Detection]) -> list[Track]:
        tracker = self.cameras.setdefault(camera_id, CameraTracker(self.rules))
        return tracker.update(ts, detections)


def draw_tracks(image: Image.Image, tracks: Sequence[Track]) -> Image.Image:
    """Seen tracks with `#id class Ns`; red once still >= 60 s, orange if still, else white."""
    img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    for t in tracks:
        if t.missed:
            continue
        s = t.stationary_s
        color = (255, 60, 60) if s >= 60 else (255, 170, 0) if s > 0 else (235, 235, 235)
        draw.rectangle(t.bbox, outline=color, width=2)
        draw.text((t.bbox[0] + 2, max(0.0, t.bbox[1] - 11)), f"#{t.id} {t.cls.value} {s:.0f}s",
                  fill=color)
    return img


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detect + track one camera's recorded frames.")
    ap.add_argument("frames_dir", type=Path, help="data/frames/<camera_id>")
    ap.add_argument("--out", type=Path, default=Path("runs/track"))
    ap.add_argument("--limit", type=int, default=None, help="only the first N frames")
    ap.add_argument("--weights", default=None)
    args = ap.parse_args(argv)

    from vision.detect import Detector

    frames = sorted(find_frames(args.frames_dir), key=frame_timestamp)[: args.limit]
    if len(frames) < 2:
        print(f"need at least 2 frames under {args.frames_dir}")
        return 1
    all_dets = Detector(args.weights).detect(frames)

    tracker = CameraTracker()
    seen: dict[int, Track] = {}
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "tracks.jsonl").open("w") as f:
        for path, dets in zip(frames, all_dets, strict=True):
            ts = frame_timestamp(path)
            tracks = tracker.update(ts, dets)
            seen.update({t.id: t for t in tracks})
            draw_tracks(Image.open(path), tracks).save(args.out / f"{path.stem}.png")
            f.write(json.dumps({"frame": str(path), "ts": ts.isoformat(),
                                "tracks": [t.to_dict() for t in tracks if not t.missed]}) + "\n")

    span = (frame_timestamp(frames[-1]) - frame_timestamp(frames[0])).total_seconds()
    print(f"{len(frames)} frames over {span / 60:.1f} min, {len(seen)} tracks")
    longest = sorted(seen.values(), key=lambda t: t.max_stationary_s, reverse=True)[:8]
    print("longest-stationary tracks:")
    for t in longest:
        if t.max_stationary_s <= 0:
            break
        print(f"  #{t.id:<4} {t.cls.value:<5} still {t.max_stationary_s:>5.0f}s  "
              f"seen {t.hits:>3} frames  box {[round(v) for v in t.bbox]}")
    print(f"annotated frames + tracks.jsonl -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
