"""Per-camera lane masks (F4): polygons for curb, travel lanes, intersection box...

One file per camera, events/masks/<camera_id>.json, drawn on a reference frame
saved next to it as <camera_id>.jpg (used later to notice when a camera's view
has moved). Format:

    {"camera_id": "...", "name": "8th Ave @ 33rd St", "frame_size": [352, 240],
     "traffic": "away",   # optional: traffic drives away from (default) or toward the camera
     "zones": [{"name": "parking_left", "type": "curb", "polygon": [[x, y], ...]}]}

A vehicle's zone is looked up at the bottom-center of its box (where it touches
the road); with these camera angles the box center often sits over the next lane.
Where zones overlap, the more specific one wins (see ZONE_PRIORITY).

    python -m events.masks overlay <camera_id> [--frame f.jpg ...] [--out overlay.png]
    python -m events.masks list
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from common.schemas import LaneZone

MASKS_DIR = Path(__file__).with_name("masks")

# first match wins where polygons overlap
ZONE_PRIORITY = [LaneZone.IGNORE, LaneZone.BUS_STOP, LaneZone.BOX, LaneZone.CURB,
                 LaneZone.CURB_ADJACENT, LaneZone.TRAVEL]

ZONE_COLORS = {
    LaneZone.CURB: (80, 160, 255),           # blue: legal parking / curb
    LaneZone.CURB_ADJACENT: (255, 150, 0),   # orange: where double parking happens
    LaneZone.TRAVEL: (60, 220, 90),          # green: travel lanes
    LaneZone.BOX: (255, 60, 200),            # magenta: intersection box
    LaneZone.BUS_STOP: (255, 230, 0),        # yellow
    LaneZone.IGNORE: (120, 120, 120),        # grey
}

Point = tuple[float, float]


def point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[float]]) -> bool:
    """Ray casting; points exactly on an edge may land either side."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def ground_point(bbox: Sequence[float]) -> Point:
    """Bottom-center of a box: where the vehicle touches the road."""
    x1, _, x2, y2 = bbox
    return (x1 + x2) / 2, y2


@dataclass(frozen=True)
class Zone:
    name: str
    type: LaneZone
    polygon: tuple[Point, ...]

    def contains(self, x: float, y: float) -> bool:
        return point_in_polygon(x, y, self.polygon)


@dataclass(frozen=True)
class CameraMask:
    camera_id: str
    name: str
    frame_size: tuple[int, int]
    zones: tuple[Zone, ...]
    traffic: str = "away"  # "away" (up the image) or "toward" the camera: which way is "ahead"

    def zone_at(self, x: float, y: float) -> Zone | None:
        hits = [z for z in self.zones if z.contains(x, y)]
        if not hits:
            return None
        return min(hits, key=lambda z: ZONE_PRIORITY.index(z.type))

    def lane_zone(self, bbox: Sequence[float]) -> LaneZone:
        zone = self.zone_at(*ground_point(bbox))
        return zone.type if zone else LaneZone.NONE

    @classmethod
    def from_dict(cls, d: dict) -> CameraMask:
        zones = tuple(Zone(z["name"], LaneZone(z["type"]),
                           tuple((float(x), float(y)) for x, y in z["polygon"]))
                      for z in d["zones"])
        w, h = d["frame_size"]
        return cls(d["camera_id"], d.get("name", ""), (int(w), int(h)), zones,
                   d.get("traffic", "away"))


def validate_mask(d: dict) -> list[str]:
    """Problems with a mask dict (empty list = valid)."""
    errors: list[str] = []
    try:
        w, h = d["frame_size"]
        zones = d["zones"]
        if not d.get("camera_id"):
            errors.append("camera_id is missing")
    except (KeyError, TypeError, ValueError):
        return ["needs camera_id, frame_size [w, h] and zones"]
    if d.get("traffic", "away") not in ("away", "toward"):
        errors.append("traffic must be 'away' or 'toward'")
    known = {z.value for z in ZONE_PRIORITY}
    names = [z.get("name", "") for z in zones]
    if len(names) != len(set(names)):
        errors.append("zone names must be unique")
    for z in zones:
        name = z.get("name") or "?"
        if not z.get("name"):
            errors.append("every zone needs a name")
        if z.get("type") not in known:
            errors.append(f"{name}: unknown type {z.get('type')!r}")
        poly = z.get("polygon") or []
        if len(poly) < 3:
            errors.append(f"{name}: a polygon needs at least 3 points")
        if any(not (0 <= x <= w and 0 <= y <= h) for x, y in poly):
            errors.append(f"{name}: points must be inside the {w}x{h} frame")
    return errors


def dump_mask(d: dict) -> str:
    """Mask JSON with one line per polygon, so diffs of hand edits stay readable."""
    zones = ",\n".join(
        "    {" + f'"name": {json.dumps(z["name"])}, "type": {json.dumps(z["type"])},\n'
        + '     "polygon": ' + json.dumps([[round(x), round(y)] for x, y in z["polygon"]])
        + "}"
        for z in d["zones"])
    head = {k: d[k] for k in ("camera_id", "name", "frame_size", "traffic") if k in d}
    lines = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in head.items())
    return "{\n" + lines + ',\n  "zones": [\n' + zones + "\n  ]\n}\n"


def mask_path(camera_id: str, masks_dir: Path = MASKS_DIR) -> Path:
    return masks_dir / f"{camera_id}.json"


def load_mask(camera_id: str, masks_dir: Path = MASKS_DIR) -> CameraMask | None:
    path = mask_path(camera_id, masks_dir)
    return CameraMask.from_dict(json.loads(path.read_text())) if path.exists() else None


def load_masks(masks_dir: Path = MASKS_DIR) -> dict[str, CameraMask]:
    masks = (CameraMask.from_dict(json.loads(p.read_text()))
             for p in sorted(masks_dir.glob("*.json")))
    return {m.camera_id: m for m in masks}


def draw_mask(image: Image.Image, mask: CameraMask, alpha: int = 90) -> Image.Image:
    """Image with each zone filled in its color and labelled."""
    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for zone in sorted(mask.zones, key=lambda z: -ZONE_PRIORITY.index(z.type)):
        color = ZONE_COLORS[zone.type]
        draw.polygon(zone.polygon, fill=(*color, alpha), outline=(*color, 255))
    out = Image.alpha_composite(base, layer)
    draw = ImageDraw.Draw(out)
    for zone in mask.zones:
        xs, ys = zip(*zone.polygon, strict=True)
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        draw.text((cx - 12, cy - 5), zone.name, fill=(255, 255, 255, 255))
    return out.convert("RGB")


def _overlay(args: argparse.Namespace) -> int:
    mask = load_mask(args.camera_id)
    if mask is None:
        print(f"no mask at {mask_path(args.camera_id)}")
        return 1
    frames = args.frame or [MASKS_DIR / f"{args.camera_id}.jpg"]
    tiles = [draw_mask(Image.open(f), mask) for f in frames]
    tiles = [t.resize((t.width * args.scale, t.height * args.scale)) for t in tiles]
    sheet = Image.new("RGB", (sum(t.width for t in tiles), max(t.height for t in tiles)))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width
    out = args.out or Path("runs/masks") / f"{args.camera_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"{mask.name}: {len(mask.zones)} zones on {len(frames)} frame(s) -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lane mask tools.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ov = sub.add_parser("overlay", help="draw a camera's mask over one or more frames")
    ov.add_argument("camera_id")
    ov.add_argument("--frame", type=Path, action="append",
                    help="frame(s) to draw on; default: the mask's reference frame")
    ov.add_argument("--out", type=Path, default=None)
    ov.add_argument("--scale", type=int, default=2)
    sub.add_parser("list", help="list cameras that have a mask")
    args = ap.parse_args(argv)

    if args.cmd == "overlay":
        return _overlay(args)
    for m in load_masks().values():
        kinds = sorted({z.type.value for z in m.zones})
        print(f"{m.camera_id}  {m.name:<22} {len(m.zones)} zones: {', '.join(kinds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
