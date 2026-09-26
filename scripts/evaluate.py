"""Score the event engine against hand-tagged ground truth (issue #16).

    python scripts/evaluate.py                       # current masks + events/rules.yaml
    python scripts/evaluate.py --rules my_rules.yaml # try other thresholds in seconds
    python scripts/evaluate.py --exclude bus_lane police camera_moved
    python scripts/evaluate.py --candidates         # GIFs of possible missed blockages

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
from datetime import datetime, timedelta
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


ACTIVE_ZONES = {"travel", "curb_adjacent", "box", "bus_stop"}
ZONE_TYPES = {"box": "blocked_box", "travel": "stopped_in_lane"}


def still_vehicles(cache: dict, rules: dict, min_still_s: float) -> list[dict]:
    """Every stretch where a tracked vehicle stood still >= min_still_s in an active zone."""
    pipe = CameraPipeline.for_camera(cache["camera"], rules)
    if pipe is None:
        return []
    mask = pipe.engine.mask
    stretches: dict[tuple, dict] = {}
    for row in cache["frames"]:
        ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        dets = [Detection(tuple(d[:4]), VehicleClass(d[4]), d[5]) for d in row["dets"]]
        pipe.step(ts, None, dets, frozen=row["frozen"])
        for t in pipe.tracks:
            if t.missed or t.stationary_s <= 0:
                continue
            zone = mask.lane_zone(t.bbox).value
            key = (t.id, t.stationary_since)
            s = stretches.setdefault(key, {"camera": cache["camera"], "start": t.stationary_since,
                                           "zone": zone, "bbox": list(t.bbox)})
            s.update(end=ts, still_s=t.stationary_s, cls=t.cls.value)
            if zone in ACTIVE_ZONES:
                s["zone"], s["bbox"] = zone, list(t.bbox)
    return [s for s in stretches.values()
            if s["still_s"] >= min_still_s and s["zone"] in ACTIVE_ZONES]


def find_candidates(stills: list[dict], gt: GroundTruth,
                    predictions: list[Prediction]) -> list[dict]:
    """Still vehicles nobody has judged and no alert covers, merged when they're one vehicle."""
    from evaluation.metrics import iou

    def same(a_cam, a_start, a_end, a_box, b_cam, b_start, b_end, b_box, slack=15):
        return (a_cam == b_cam and a_start.timestamp() <= b_end.timestamp() + slack
                and a_end.timestamp() >= b_start.timestamp() - slack and iou(a_box, b_box) >= 0.3)

    alerts = [(p.event.camera_id, p.event.start_ts,
               p.event.start_ts + timedelta(seconds=p.event.duration_s), p.event.bbox)
              for p in predictions]
    judged = [(t.camera, t.start, t.end, t.bbox) for t in gt.items]
    fresh = [s for s in stills
             if not any(same(s["camera"], s["start"], s["end"], s["bbox"], *o)
                        for o in alerts + judged)]
    merged: list[dict] = []
    for s in sorted(fresh, key=lambda s: -s["still_s"]):
        for m in merged:
            if same(s["camera"], s["start"], s["end"], s["bbox"],
                    m["camera"], m["start"], m["end"], m["bbox"]):
                m["start"], m["end"] = min(m["start"], s["start"]), max(m["end"], s["end"])
                break
        else:
            merged.append(dict(s))
    return sorted(merged, key=lambda m: (m["camera"], m["start"]))


def write_candidate_gifs(candidates: list[dict], names: dict[str, str], out: Path) -> None:
    from PIL import Image, ImageDraw

    frames_dir = get_settings().frames_dir
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("cand_*.gif"):
        old.unlink()
    lines = ["# Possible missed blockages: fill in `verdict` (real / not) and a note,",
             "# then copy the real ones into blockages: and the rest into not_blockages:",
             "# in evaluation/ground_truth.yaml.", "candidates:"]
    for n, c in enumerate(candidates, 1):
        lo, hi = c["start"] - timedelta(seconds=30), c["end"] + timedelta(seconds=30)
        paths = sorted((p for p in (frames_dir / c["camera"]).glob("*/*.jpg")
                        if lo <= frame_timestamp(p) <= hi), key=frame_timestamp)
        paths = paths[::max(1, len(paths) // 80)]
        images = []
        for p in paths:
            ts = frame_timestamp(p)
            img = Image.open(p).convert("RGB").resize((704, 480))
            d = ImageDraw.Draw(img)
            still = c["start"] <= ts <= c["end"]
            if still:
                d.rectangle([v * 2 for v in c["bbox"]], outline=(255, 210, 0), width=4)
            d.rectangle((0, 450, 704, 480), fill=(0, 0, 0))
            label = (f"#{n} {names.get(c['camera'], c['camera'][:8])}  {ts:%H:%M:%S} UTC  "
                     + (f"still {int((ts - c['start']).total_seconds())}s in {c['zone']}"
                        if still else "not still"))
            d.text((8, 458), label, fill=(255, 210, 0) if still else (230, 230, 230))
            images.append(img.quantize(colors=128))
        cam = names.get(c["camera"], c["camera"][:8])
        name = f"cand_{n:02d}_{cam.replace(' ', '').replace('@', '_').replace('/', '-')}.gif"
        if images:
            images[0].save(out / name, save_all=True, append_images=images[1:], duration=250,
                           loop=0, optimize=True)
        lines += [f"  - id: cand_{n:02d}   # {name}",
                  f"    camera: {c['camera']}   # {names.get(c['camera'], '')}",
                  f"    type: {ZONE_TYPES.get(c['zone'], 'double_parked')}",
                  f"    start: {c['start']:%Y-%m-%dT%H:%M:%SZ}",
                  f"    end: {c['end']:%Y-%m-%dT%H:%M:%SZ}",
                  f"    bbox: {[round(v) for v in c['bbox']]}",
                  f"    still_s: {c['still_s']:.0f}   # zone {c['zone']}, looks like a {c['cls']}",
                  "    verdict: \"\"   # real / not",
                  "    note: \"\""]
    (out / "candidates.yaml").write_text("\n".join(lines) + "\n")


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
    ap.add_argument("--candidates", action="store_true",
                    help="also list vehicles still >= --min-still s in an active zone that no "
                         "alert or ground-truth entry covers, with GIFs (needs data/frames/)")
    ap.add_argument("--min-still", type=float, default=45.0)
    args = ap.parse_args(argv)

    gt = load_ground_truth(args.ground_truth) if args.ground_truth else load_ground_truth()
    rules = load_rules(args.rules) if args.rules else load_rules()
    names = {c: m.name for c, m in load_masks().items()}

    def detector_factory():
        from vision.detect import Detector
        return Detector().detect

    predictions: list[Prediction] = []
    stills: list[dict] = []
    for w in gt.windows:
        cache = load_cache(w, args.refresh_cache, detector_factory)
        if cache is None:
            print(f"skipping {names.get(w.camera, w.camera)} {w.start:%H:%M}: no cached "
                  "detections and no recorded frames")
            continue
        predictions += run_window(cache, rules)
        if args.candidates:
            stills += still_vehicles(cache, rules, args.min_still)

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
    if args.candidates:
        cands = find_candidates(stills, gt, predictions)
        print(f"\n{len(cands)} possible missed blockages (still >= {args.min_still:.0f} s, "
              "no alert, not judged yet):")
        for n, c in enumerate(cands, 1):
            print(f"  #{n:<3}{names.get(c['camera'], c['camera'][:8]):<26}{c['zone']:<15}"
                  f"{c['start']:%H:%M:%S}  still {c['still_s']:>4.0f}s  {c['cls']}")
        write_candidate_gifs(cands, names, args.out / "candidates")
        print(f"GIFs + candidates.yaml -> {args.out / 'candidates'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
