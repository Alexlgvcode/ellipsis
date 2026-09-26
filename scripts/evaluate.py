"""Score the event engine against hand-tagged ground truth (issue #16).

    python scripts/evaluate.py                       # current masks + events/rules.yaml
    python scripts/evaluate.py --rules my_rules.yaml # try other thresholds in seconds
    python scripts/evaluate.py --exclude bus_lane police camera_moved

Runs tracker + event engine over every reviewed window in
evaluation/ground_truth.yaml and prints precision, recall, type accuracy and time to
alert, overall and per camera, then lists missed blockages and unreviewed alerts
(alerts nobody has judged yet: add them to the ground truth).

Detections come from evaluation/detections/ (committed, so this runs from a clean
checkout without the frames or the YOLO model). --refresh-cache rebuilds them from
data/frames/ (needs `.[vision]`); do that after recording new footage or changing
a camera's reference frame.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.config import get_settings  # noqa: E402
from common.schemas import Event, VehicleClass  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    GroundTruth,
    Prediction,
    Report,
    Window,
    evaluate,
    load_ground_truth,
)
from events.masks import MASKS_DIR, load_masks  # noqa: E402
from events.pipeline import CameraPipeline  # noqa: E402
from events.rules import load_rules  # noqa: E402
from vision.detect import Detection  # noqa: E402
from vision.track import frame_timestamp  # noqa: E402

CACHE_DIR = REPO_ROOT / "evaluation" / "detections"


def cache_path(w: Window) -> Path:
    return CACHE_DIR / f"{w.camera[:8]}_{w.start:%Y%m%dT%H%M%S}_{w.end:%H%M%S}.json.gz"


def build_cache(w: Window, frames_dir: Path, detector) -> dict:
    """Detections, frozen flags and view similarity for every recorded frame in a window."""
    from PIL import Image

    from events.view import edge_signature, view_similarity
    from ingest.health import is_frozen, thumbnail

    root = frames_dir / w.camera
    frames = sorted((p for p in root.glob("*/*.jpg") if w.start <= frame_timestamp(p) <= w.end),
                    key=frame_timestamp)
    reference = edge_signature(Image.open(MASKS_DIR / f"{w.camera}.jpg"))
    rows, prev = [], None
    for path, dets in zip(frames, detector(frames), strict=True):
        image = Image.open(path)
        thumb = thumbnail(image)
        rows.append({
            "ts": frame_timestamp(path).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "frozen": bool(prev is not None and is_frozen(prev, thumb)),
            "view": round(view_similarity(reference, image), 3),
            "dets": [[*(round(v, 1) for v in d.bbox), d.cls.value, round(d.conf, 2)]
                     for d in dets],
        })
        prev = thumb
    return {"camera": w.camera, "start": w.start.isoformat(), "end": w.end.isoformat(),
            "note": "YOLO detections per frame: x1,y1,x2,y2,class,conf", "frames": rows}


def load_cache(w: Window, refresh: bool, detector_factory) -> dict | None:
    path = cache_path(w)
    if path.exists() and not refresh:
        return json.loads(gzip.decompress(path.read_bytes()))
    frames_dir = get_settings().frames_dir
    if not (frames_dir / w.camera).exists():
        return None
    data = build_cache(w, frames_dir, detector_factory())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode()))
    return data


def run_window(cache: dict, rules: dict) -> list[Prediction]:
    pipe = CameraPipeline.for_camera(cache["camera"], rules)
    if pipe is None:
        return []
    final: dict[str, Event] = {}
    alert_at: dict[str, datetime] = {}
    for row in cache["frames"]:
        ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        dets = [Detection(tuple(d[:4]), VehicleClass(d[4]), d[5]) for d in row["dets"]]
        update = pipe.step(ts, None, dets, frozen=row["frozen"])
        for e in update.opened:
            alert_at[e.id] = ts
        final.update({e.id: e for e in update.changed})
    return [Prediction(e, alert_at[i]) for i, e in final.items() if i in alert_at]


def _pct(v: float | None) -> str:
    return "  -  " if v is None else f"{v:5.0%}"


def print_report(title: str, report: Report, gt: GroundTruth, names: dict[str, str],
                 verbose: bool) -> None:
    s = report.summary()
    tta = report.median_time_to_alert_s
    print(f"\n== {title}")
    print(f"   precision {_pct(s['precision'])} ({s['true_positives']}/{s['alerts']} alerts)   "
          f"recall {_pct(s['recall'])} ({s['blockages'] - s['missed']}/{s['blockages']} "
          f"blockages)   type accuracy {_pct(s['type_accuracy'])}   median time to alert "
          + ("-" if tta is None else f"{tta:.0f} s"))
    print(f"   false alerts: {s['known_false']} known, {s['duplicates']} duplicate, "
          f"{s['unreviewed']} unreviewed")
    if not verbose:
        return
    by_cam: dict[str, list] = defaultdict(list)
    for m in report.matches:
        by_cam[m.prediction.event.camera_id].append(m)
    print(f"\n   {'camera':<26}{'alerts':>7}{'real':>6}{'false':>7}{'missed':>8}")
    for cam in sorted({w.camera for w in gt.windows}, key=lambda c: names.get(c, c)):
        ms = by_cam.get(cam, [])
        real = sum(m.outcome == "true_positive" for m in ms)
        missed = sum(t.camera == cam for t in report.missed)
        print(f"   {names.get(cam, cam[:8]):<26}{len(ms):>7}{real:>6}{len(ms) - real:>7}"
              f"{missed:>8}")
    if report.missed:
        print("\n   missed blockages:")
        for t in report.missed:
            print(f"     {t.id}  {names.get(t.camera, t.camera[:8]):<24} {t.type:<16} "
                  f"{t.start:%H:%M:%S}-{t.end:%H:%M:%S}  {t.note}")
    unreviewed = [m for m in report.matches if m.outcome == "unreviewed"]
    if unreviewed:
        print("\n   unreviewed alerts (judge them and add to evaluation/ground_truth.yaml):")
        for m in unreviewed:
            e = m.prediction.event
            print(f"     {names.get(e.camera_id, e.camera_id[:8]):<24} {e.type.value:<16} "
                  f"{e.start_ts:%H:%M:%S} {e.duration_s:>5.0f}s  bbox "
                  f"{[round(v) for v in e.bbox]}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score the event engine against ground truth.")
    ap.add_argument("--rules", type=Path, default=None, help="default: events/rules.yaml")
    ap.add_argument("--ground-truth", type=Path, default=None)
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="ground-truth categories to leave out, e.g. bus_lane police")
    ap.add_argument("--refresh-cache", action="store_true",
                    help="rebuild evaluation/detections/ from data/frames/ (needs .[vision])")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "runs" / "eval")
    args = ap.parse_args(argv)

    gt = load_ground_truth(args.ground_truth) if args.ground_truth else load_ground_truth()
    rules = load_rules(args.rules) if args.rules else load_rules()
    names = {c: m.name for c, m in load_masks().items()}

    def detector_factory():
        from vision.detect import Detector
        return Detector().detect

    predictions: list[Prediction] = []
    for w in gt.windows:
        cache = load_cache(w, args.refresh_cache, detector_factory)
        if cache is None:
            print(f"skipping {names.get(w.camera, w.camera)} {w.start:%H:%M}: no cached "
                  "detections and no recorded frames")
            continue
        predictions += run_window(cache, rules)

    report = evaluate(predictions, gt, exclude=args.exclude)
    title = "all ground truth" + (f" (excluding {', '.join(args.exclude)})" if args.exclude else "")
    print_report(title, report, gt, names, verbose=True)
    strict = ["bus_lane", "police", "camera_moved"]
    if not args.exclude:
        print_report(f"excluding {', '.join(strict)}", evaluate(predictions, gt, exclude=strict),
                     gt, names, verbose=False)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report.summary(), indent=2))
    with (args.out / "predictions.jsonl").open("w") as f:
        for m in report.matches:
            f.write(json.dumps({"outcome": m.outcome, "truth": m.truth.id if m.truth else None,
                                "alert_ts": m.prediction.alert_ts.isoformat(),
                                "event": m.prediction.event.model_dump(mode="json")}) + "\n")
    print(f"\nreport -> {args.out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
