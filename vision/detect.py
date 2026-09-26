"""Vehicle detector (F2).

Pretrained YOLO11s (COCO) for now; swap LW_YOLO_WEIGHTS for fine-tuned weights
later. Classes come from the model's own names, so a fine-tuned model with a
`van` class works without code changes. Frames (~352x240) are letterboxed up
to 640 by YOLO; boxes come back in original frame pixels.

    python -m vision.detect data/frames --out runs/detect [--limit 50]

Writes annotated frames and detections.jsonl to --out.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from common.config import get_settings
from common.schemas import VehicleClass

# COCO ids of the classes we keep (pretrained model). Motorcycles and bicycles
# don't block lanes the way we care about, so they're dropped.
COCO_TO_VEHICLE: dict[int, VehicleClass] = {
    2: VehicleClass.CAR,
    5: VehicleClass.BUS,
    7: VehicleClass.TRUCK,
}

COLORS = {
    VehicleClass.CAR: (255, 64, 64),
    VehicleClass.TRUCK: (255, 170, 0),
    VehicleClass.BUS: (64, 160, 255),
    VehicleClass.VAN: (190, 90, 255),
}

Frame = str | Path | np.ndarray | Image.Image


@dataclass(frozen=True)
class Detection:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in frame pixels
    cls: VehicleClass
    conf: float

    def to_dict(self) -> dict:
        return {"bbox": [round(v, 1) for v in self.bbox], "cls": self.cls.value,
                "conf": round(self.conf, 3)}


def class_map_from_names(names: dict[int, str]) -> dict[int, VehicleClass]:
    """Map a model's class ids to our vehicle classes by name; others are dropped."""
    ours = {c.value for c in VehicleClass}
    return {i: VehicleClass(n) for i, n in names.items() if n in ours}


def to_detections(xyxy: Iterable[Sequence[float]], cls_ids: Iterable[int],
                  confs: Iterable[float], class_map: dict[int, VehicleClass],
                  conf_threshold: float) -> list[Detection]:
    """Turn raw model outputs into Detections: keep mapped classes above threshold."""
    out = []
    for box, cid, conf in zip(xyxy, cls_ids, confs, strict=True):
        cls = class_map.get(int(cid))
        if cls is None or float(conf) < conf_threshold:
            continue
        x1, y1, x2, y2 = (float(v) for v in box)
        out.append(Detection((x1, y1, x2, y2), cls, float(conf)))
    return out


def draw_detections(image: Image.Image, detections: Iterable[Detection]) -> Image.Image:
    """Copy of the image with each detection's box and label drawn."""
    img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    for d in detections:
        color = COLORS.get(d.cls, (255, 255, 255))
        draw.rectangle(d.bbox, outline=color, width=2)
        draw.text((d.bbox[0] + 2, max(0.0, d.bbox[1] - 11)), f"{d.cls.value} {d.conf:.2f}",
                  fill=color)
    return img


def find_frames(root: Path) -> list[Path]:
    """All .jpg frames under root, in path order (camera, then date, then time)."""
    return sorted(p for p in root.rglob("*.jpg") if p.is_file())


class Detector:
    """Batched YOLO wrapper. Loads the model on construction (needs `.[vision]`)."""

    def __init__(self, weights: str | None = None, conf: float | None = None,
                 imgsz: int = 640, device: str | None = None, batch_size: int = 16,
                 nms_iou: float = 0.5):
        from ultralytics import YOLO  # heavy import, keep it out of module import

        settings = get_settings()
        self.model = YOLO(weights or settings.yolo_weights)
        self.conf = settings.detect_conf if conf is None else conf
        self.imgsz = imgsz
        self.device = settings.device if device is None else device
        self.batch_size = batch_size
        # YOLO's default 0.7 left the same car boxed twice at 0.6-0.7 overlap on
        # these low-res frames; 0.5 merges those. Distant queued cars that overlap
        # more than that may merge too, which doesn't matter for near-lane events.
        self.nms_iou = nms_iou
        self.class_map = class_map_from_names(self.model.names)
        if not self.class_map:
            raise ValueError(f"model has none of our classes: {self.model.names}")

    def detect(self, frames: Sequence[Frame]) -> list[list[Detection]]:
        """One list of detections per input frame, same order as the input."""
        out: list[list[Detection]] = []
        for i in range(0, len(frames), self.batch_size):
            batch = [str(f) if isinstance(f, Path) else f
                     for f in frames[i:i + self.batch_size]]
            # agnostic_nms: one box per vehicle even when YOLO is torn between classes
            # (yellow cabs come out as car + truck + bus otherwise, which the tracker
            # would count as several vehicles in one spot)
            results = self.model.predict(
                batch, imgsz=self.imgsz, conf=self.conf, classes=list(self.class_map),
                iou=self.nms_iou, agnostic_nms=True, device=self.device or None,
                verbose=False,
            )
            for r in results:
                b = r.boxes
                out.append(to_detections(b.xyxy.tolist(), b.cls.tolist(), b.conf.tolist(),
                                         self.class_map, self.conf))
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the vehicle detector on a folder of frames.")
    ap.add_argument("frames_dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("runs/detect"))
    ap.add_argument("--weights", default=None, help="default: LW_YOLO_WEIGHTS")
    ap.add_argument("--conf", type=float, default=None, help="default: LW_DETECT_CONF")
    ap.add_argument("--limit", type=int, default=None, help="only the first N frames")
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args(argv)

    frames = find_frames(args.frames_dir)[: args.limit]
    if not frames:
        print(f"no .jpg frames under {args.frames_dir}")
        return 1

    detector = Detector(args.weights, args.conf, batch_size=args.batch)
    t0 = time.perf_counter()
    all_dets = detector.detect(frames)
    elapsed = time.perf_counter() - t0

    args.out.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    empty = 0
    with (args.out / "detections.jsonl").open("w") as f:
        for path, dets in zip(frames, all_dets, strict=True):
            rel = path.relative_to(args.frames_dir)
            dest = args.out / rel.with_suffix(".png")
            dest.parent.mkdir(parents=True, exist_ok=True)
            draw_detections(Image.open(path), dets).save(dest)
            f.write(json.dumps({"frame": str(path), "detections": [d.to_dict() for d in dets]})
                    + "\n")
            counts.update(d.cls.value for d in dets)
            empty += not dets

    n = len(frames)
    print(f"{n} frames in {elapsed:.1f}s ({1000 * elapsed / n:.0f} ms/frame), "
          f"conf >= {detector.conf}")
    print(f"detections: {sum(counts.values())} "
          f"({', '.join(f'{k} {v}' for k, v in counts.most_common()) or 'none'}), "
          f"{sum(counts.values()) / n:.1f} per frame, {empty} frames with none")
    print(f"annotated frames + detections.jsonl -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
