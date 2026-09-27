"""Event engine (F4-F6): stationary tracks + lane masks + dwell rules -> Events.

One engine per camera. Each frame, for every vehicle the tracker saw:

    zone (mask, at the box's bottom-center)  ->  event type and wait threshold
        curb_adjacent -> double_parked    (dwell_s.double_parked)
        travel        -> stopped_in_lane  (dwell_s.stopped_in_lane, front of a queue only)
        box           -> blocked_box      (dwell_s.blocked_box)
        bus_stop      -> double_parked    (dwell_s.bus_stop, any vehicle)
        curb, ignore, none -> nothing

An event opens once the vehicle has been still in its zone for the threshold
(start_ts = when it stopped) and closes when it drives off or the tracker drops
it (track lost for more than `track_lost_frames`). Vehicles cut off by the bottom
of the frame never open events: their box bottom isn't where they touch the road.
The vehicle class is never used in a rule: the detector labels delivery trucks
and cabs as "bus".

Front of queue: in travel lanes, vehicles stopped right behind another stopped
vehicle are its impact, not separate events. Double-parked vehicles back to back
are each an event (e.g. two delivery trucks on 7 Ave @ 36 St).

Frozen feed: pass feed_still=True when a frame is near-identical to the previous
one (ingest.health.is_frozen). After dwell_s.frozen_feed a frozen_feed event opens,
and vehicles are ignored while the picture is frozen. Don't feed frozen frames
to the tracker either, or parked vehicles' timers keep counting.

    python -m events.engine data/frames/<camera_id> [--rules my.yaml] [--out runs/events] [--gif]
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from common.schemas import Event, EventType, LaneZone
from events.masks import CameraMask, load_mask
from events.rules import load_rules
from vision.track import Track

# zone -> (event type, key in rules.yaml dwell_s)
ZONE_EVENTS: dict[LaneZone, tuple[EventType, str]] = {
    LaneZone.CURB_ADJACENT: (EventType.DOUBLE_PARKED, "double_parked"),
    LaneZone.TRAVEL: (EventType.STOPPED_IN_LANE, "stopped_in_lane"),
    LaneZone.BOX: (EventType.BLOCKED_BOX, "blocked_box"),
    LaneZone.BUS_STOP: (EventType.DOUBLE_PARKED, "bus_stop"),
}


@dataclass
class EngineUpdate:
    """What changed this frame. Closed events carry their final duration."""

    opened: list[Event] = field(default_factory=list)
    updated: list[Event] = field(default_factory=list)
    closed: list[Event] = field(default_factory=list)

    @property
    def changed(self) -> list[Event]:
        return self.opened + self.updated + self.closed


class EventEngine:
    """Events for one camera. Call update() once per frame, after the tracker."""

    def __init__(self, mask: CameraMask, rules: dict | None = None):
        rules = rules or load_rules()
        self.mask = mask
        self.dwell: dict[str, float] = rules["dwell_s"]
        self.edge_margin = rules["edge_margin_px"]
        self.side_edges = rules.get("edge_sides", False)
        self.min_seen_frac = rules["stationary"].get("min_seen_frac", 0.0)
        self.max_gap_frac = rules["queue"]["max_gap_frac"]
        self.min_x_overlap = rules["queue"]["min_x_overlap"]
        self.open: dict[int, Event] = {}  # track id -> its open event
        self.frozen_since: datetime | None = None
        self.frozen_event: Event | None = None

    @classmethod
    def for_camera(cls, camera_id: str, rules: dict | None = None) -> EventEngine | None:
        """None for cameras without a lane mask (they never produce vehicle events)."""
        mask = load_mask(camera_id)
        return cls(mask, rules) if mask else None

    def update(self, ts: datetime, tracks: Sequence[Track], ended: Sequence[Track] = (),
               feed_still: bool = False) -> EngineUpdate:
        """`tracks` / `ended` are CameraTracker.update()'s result and .ended."""
        out = EngineUpdate()
        self._update_feed(ts, feed_still, out)
        if feed_still:
            return out  # nothing about the vehicles can be trusted on a frozen picture

        live = {t.id for t in tracks}
        still = [t for t in tracks if not t.missed and t.stationary_s > 0]
        for t in tracks:
            if t.missed:
                continue  # hidden this frame (a bus passing in front): keep its event open
            event = self.open.get(t.id)
            if t.stationary_s <= 0:
                if event:
                    out.closed.append(self.open.pop(t.id))  # drove off
                continue
            if event:
                if t.strikes:
                    continue  # looks like it's pulling away: keep the last duration
                zone = event.lane_zone
                event = event.model_copy(update={
                    "duration_s": t.stationary_s, "bbox": list(t.bbox),
                    "confidence": self._confidence(t, zone, self._dwell_for(zone))})
                self.open[t.id] = event
                out.updated.append(event)
                continue
            if self._cut_off(t.bbox):
                continue  # cut off by the frame edge: its zone can't be read
            zone = self.mask.lane_zone(t.bbox)
            if zone not in ZONE_EVENTS or t.stationary_s < self._dwell_for(zone):
                continue
            if zone is LaneZone.TRAVEL and self._queued(t, still):
                continue
            if t.seen_frac < self.min_seen_frac:
                continue  # gaps while "still": likely different vehicles passing one spot
            event = self._new_event(t, zone)
            self.open[t.id] = event
            out.opened.append(event)

        dropped = {t.id for t in ended} | (set(self.open) - live)
        for tid in sorted(dropped & set(self.open)):
            out.closed.append(self.open.pop(tid))  # track lost
        return out

    def close_all(self) -> list[Event]:
        """Close every open event (e.g. the camera's view moved, so they're no longer valid)."""
        closed = list(self.open.values())
        self.open.clear()
        return closed

    # --- helpers -------------------------------------------------------------------------

    def _cut_off(self, bbox) -> bool:
        w, h = self.mask.frame_size
        m = self.edge_margin
        bottom = bbox[3] >= h - m
        side = self.side_edges and (bbox[0] <= m or bbox[2] >= w - m)
        return bottom or side

    def _dwell_for(self, zone: LaneZone) -> float:
        return self.dwell[ZONE_EVENTS[zone][1]]

    def _new_event(self, t: Track, zone: LaneZone) -> Event:
        since = t.stationary_since
        return Event(
            id=f"evt_{self.mask.camera_id[:8]}_{since:%Y%m%d%H%M%S}_{t.id}",
            camera_id=self.mask.camera_id,
            type=ZONE_EVENTS[zone][0],
            start_ts=since,
            duration_s=t.stationary_s,
            bbox=list(t.bbox),
            lane_zone=zone,
            confidence=self._confidence(t, zone, self._dwell_for(zone)),
        )

    def _queued(self, t: Track, still: Sequence[Track]) -> bool:
        """Is `t` stopped right behind another stopped vehicle in the same lane?"""
        lane = self.mask.zone_at((t.bbox[0] + t.bbox[2]) / 2, t.bbox[3])
        x1, y1, x2, y2 = t.bbox
        height = y2 - y1
        for o in still:
            if o.id == t.id:
                continue
            if self.mask.zone_at((o.bbox[0] + o.bbox[2]) / 2, o.bbox[3]) is not lane:
                continue
            ox1, oy1, ox2, oy2 = o.bbox
            if self.mask.traffic == "away":   # ahead = further up the image
                ahead, gap = oy2 < y2, y1 - oy2
            else:                              # traffic toward the camera: ahead = lower
                ahead, gap = oy1 > y1, oy1 - y2
            overlap = min(x2, ox2) - max(x1, ox1)
            narrower = min(x2 - x1, ox2 - ox1)
            if ahead and gap <= self.max_gap_frac * height and \
                    overlap >= self.min_x_overlap * narrower:
                return True
        return False

    def _confidence(self, t: Track, zone: LaneZone, dwell: float) -> float:
        """0.4 detector confidence + 0.3 time past the threshold (full at 2x) + 0.3 fit:
        the share of the box's bottom edge that sits in the event's zone."""
        x1, _, x2, y2 = t.bbox
        points = [x1 + (x2 - x1) * f for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
        fit = sum((z := self.mask.zone_at(px, y2)) is not None and z.type is zone
                  for px in points) / len(points)
        time = min(1.0, t.stationary_s / (2 * dwell))
        return round(min(1.0, 0.4 * t.conf + 0.3 * time + 0.3 * fit), 3)

    def _update_feed(self, ts: datetime, feed_still: bool, out: EngineUpdate) -> None:
        if not feed_still:
            self.frozen_since = None
            if self.frozen_event:
                out.closed.append(self.frozen_event)
                self.frozen_event = None
            return
        self.frozen_since = self.frozen_since or ts
        duration = (ts - self.frozen_since).total_seconds()
        if self.frozen_event:
            self.frozen_event = self.frozen_event.model_copy(update={"duration_s": duration})
            out.updated.append(self.frozen_event)
        elif duration >= self.dwell["frozen_feed"]:
            w, h = self.mask.frame_size
            self.frozen_event = Event(
                id=f"evt_{self.mask.camera_id[:8]}_{self.frozen_since:%Y%m%d%H%M%S}_frozen",
                camera_id=self.mask.camera_id, type=EventType.FROZEN_FEED,
                start_ts=self.frozen_since, duration_s=duration, bbox=[0, 0, w, h],
                lane_zone=LaneZone.NONE, confidence=1.0)
            out.opened.append(self.frozen_event)


LABELS = {EventType.DOUBLE_PARKED: "DOUBLE PARKED", EventType.STOPPED_IN_LANE: "STOPPED IN LANE",
          EventType.BLOCKED_BOX: "BLOCKED BOX", EventType.FROZEN_FEED: "FROZEN FEED"}


def draw_events(image, engine: EventEngine, tracks: Sequence[Track], ts: datetime, scale: int = 2):
    """A frame with the mask, tracked vehicles and open events drawn (for --gif)."""
    from PIL import ImageDraw

    from events.masks import draw_mask

    img = draw_mask(image, engine.mask, alpha=40)
    img = img.resize((img.width * scale, img.height * scale))
    d = ImageDraw.Draw(img)
    box = lambda b: [v * scale for v in b]  # noqa: E731
    events = {tid: e for tid, e in engine.open.items()}
    for t in tracks:
        if t.missed or t.id in events:
            continue
        color = (255, 170, 0) if t.stationary_s > 0 else (230, 230, 230)
        d.rectangle(box(t.bbox), outline=color, width=1)
    for tid, e in events.items():
        t = next((t for t in tracks if t.id == tid), None)
        b = box(t.bbox if t else e.bbox)
        d.rectangle(b, outline=(255, 30, 30), width=4)
        m, s = divmod(int(e.duration_s), 60)
        label = f"{LABELS[e.type]} {m}:{s:02d}"
        w = d.textlength(label)
        d.rectangle((b[0], b[1] - 14, b[0] + w + 6, b[1]), fill=(255, 30, 30))
        d.text((b[0] + 3, b[1] - 13), label, fill=(255, 255, 255))
    if engine.frozen_event:
        d.rectangle((0, 0, img.width, 20), fill=(255, 30, 30))
        d.text((6, 4), "FROZEN FEED", fill=(255, 255, 255))
    alerts = len(events) + bool(engine.frozen_event)
    d.rectangle((0, img.height - 20, img.width, img.height),
                fill=(160, 0, 0) if alerts else (0, 0, 0))
    d.text((6, img.height - 16), f"{engine.mask.name}   {ts:%H:%M:%S} UTC   "
           f"{alerts} open alert{'s' * (alerts != 1)}", fill=(255, 255, 255))
    return img.quantize(colors=128)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run detect + track + events on recorded frames.")
    ap.add_argument("frames_dir", type=Path, help="data/frames/<camera_id>")
    ap.add_argument("--rules", type=Path, default=None, help="default: events/rules.yaml")
    ap.add_argument("--out", type=Path, default=Path("runs/events"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--gif", action="store_true",
                    help="also write <out>/<camera_id>.gif with the events drawn on the frames")
    args = ap.parse_args(argv)

    from PIL import Image

    from events.pipeline import CameraPipeline
    from vision.detect import Detector, find_frames
    from vision.track import frame_timestamp

    camera_id = args.frames_dir.name
    rules = load_rules(args.rules) if args.rules else load_rules()
    pipe = CameraPipeline.for_camera(camera_id, rules)
    if pipe is None:
        print(f"no lane mask for camera {camera_id}: add one with python -m events.mask_editor")
        return 1
    engine = pipe.engine
    frames = sorted(find_frames(args.frames_dir), key=frame_timestamp)[: args.limit]
    detections = Detector(conf=rules["tracking"]["keep_conf"]).detect(frames)

    final: dict[str, Event] = {}
    gif_frames: list = []
    for path, dets in zip(frames, detections, strict=True):
        ts = frame_timestamp(path)
        image = Image.open(path)
        upd = pipe.step(ts, image, dets)
        tracks = pipe.tracks
        for e in upd.opened:
            print(f"{ts:%H:%M:%S}  OPEN   {e.type.value:<16} {e.lane_zone.value:<14} "
                  f"still {e.duration_s:>4.0f}s  box {[round(v) for v in e.bbox]}  {e.id}")
        for e in upd.closed:
            print(f"{ts:%H:%M:%S}  CLOSE  {e.type.value:<16} after {e.duration_s:.0f}s  {e.id}")
        final.update({e.id: e for e in upd.changed})
        if args.gif:
            gif_frames.append(draw_events(image, engine, tracks, ts))

    args.out.mkdir(parents=True, exist_ok=True)
    if gif_frames:
        gif_path = args.out / f"{camera_id}.gif"
        gif_frames[0].save(gif_path, save_all=True, append_images=gif_frames[1:],
                           duration=250, loop=0, optimize=True)
        print(f"gif -> {gif_path}")
    out_path = args.out / f"{camera_id}.jsonl"
    with out_path.open("w") as f:
        for e in final.values():
            f.write(e.model_dump_json() + "\n")
    span = (frame_timestamp(frames[-1]) - frame_timestamp(frames[0])).total_seconds()
    print(f"\n{engine.mask.name}: {len(frames)} frames over {span / 60:.1f} min, "
          f"{len(final)} events -> {out_path}")
    for e in sorted(final.values(), key=lambda e: -e.duration_s):
        print(f"  {e.type.value:<16} {e.duration_s:>5.0f}s  conf {e.confidence:.2f}  "
              f"box {[round(v) for v in e.bbox]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
