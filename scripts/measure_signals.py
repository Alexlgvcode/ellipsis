"""Measure cycle, avenue green window, and offset from recorded camera frames.

Uses motion inside each camera's travel-zone mask (Alex's lane masks). Writes
sim/sources/measurements.json for signal_plans.yaml overrides.

    python scripts/measure_signals.py
    python scripts/measure_signals.py --frames data/frames --limit 400

If frames are missing the script exits 0 and writes an empty measurements file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from common.config import REPO_ROOT
from events.masks import MASKS_DIR, CameraMask, load_mask
from ingest.camera_list import CHOSEN, read_cameras

OUT = REPO_ROOT / "sim" / "sources" / "measurements.json"


def _motion_series(frames: list[Path], mask: CameraMask) -> np.ndarray:
    """Mean abs-diff inside travel / curb_adjacent polygons."""
    polys = [z.polygon for z in mask.zones if z.type.value in {"travel", "curb_adjacent"}]
    if not polys:
        polys = [z.polygon for z in mask.zones if z.type.value != "ignore"]
    series = []
    prev = None
    for path in frames:
        im = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
        if prev is None:
            prev = im
            series.append(0.0)
            continue
        diff = np.abs(im - prev)
        prev = im
        h, w = diff.shape
        ys, xs = np.mgrid[0:h, 0:w]
        inside = np.zeros((h, w), dtype=bool)
        for poly in polys:
            # coarse bounding-box + ray test on a 4 px grid for speed
            pts = np.array(poly, dtype=np.float32)
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            for y in range(max(0, int(y0)), min(h, int(y1) + 1), 2):
                for x in range(max(0, int(x0)), min(w, int(x1) + 1), 2):
                    if _in_poly(x, y, poly):
                        inside[y, x] = True
        series.append(float(diff[inside].mean()) if inside.any() else float(diff.mean()))
    return np.asarray(series, dtype=np.float64)


def _in_poly(x: float, y: float, polygon) -> bool:
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1 + 1e-9):
            inside = not inside
    return inside


def cycle_and_green(series: np.ndarray, dt_s: float = 2.0, expect: float = 90.0
                    ) -> dict:
    """Autocorrelation peak near `expect` seconds; green = time above median."""
    x = series - series.mean()
    if len(x) < 20 or x.std() < 1e-6:
        return {"cycle_s": None, "green_s": None, "confidence": 0.0}
    corr = np.correlate(x, x, mode="full")[len(x) - 1:]
    lo = max(1, int((expect * 0.7) / dt_s))
    hi = min(len(corr) - 1, int((expect * 1.3) / dt_s))
    if hi <= lo:
        return {"cycle_s": None, "green_s": None, "confidence": 0.0}
    peak = lo + int(np.argmax(corr[lo:hi + 1]))
    cycle = peak * dt_s
    snr = float(corr[peak] / (np.median(np.abs(corr[lo:hi + 1])) + 1e-9))
    # green window: fraction of samples above the series median, times cycle
    frac = float((series > np.median(series)).mean())
    green = cycle * frac
    conf = max(0.0, min(1.0, (snr - 1.0) / 8.0)) * (1.0 - min(abs(cycle - expect) / expect, 1.0))
    return {
        "cycle_s": round(cycle, 2),
        "green_s": round(green, 1),
        "green_share": round(frac, 3),
        "snr": round(snr, 2),
        "confidence": round(conf, 3),
    }


def _list_frames(root: Path, camera_id: str, limit: int) -> list[Path]:
    folder = root / camera_id
    if not folder.is_dir():
        return []
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return files[:limit]


def measure(frames_dir: Path, limit: int = 500) -> dict:
    cams_path = REPO_ROOT / "data" / "cameras.json"
    cams = read_cameras(cams_path) if cams_path.is_file() else []
    by_name = {c.name: c for c in cams}
    rows = []
    ref_phase = None
    for name, _lat, _lon in CHOSEN:
        cam = by_name.get(name)
        # chosen names may differ slightly from cameras.json
        if cam is None:
            for c in cams:
                if name.split("@")[0].strip()[:5] in c.name and name[-6:] in c.name:
                    cam = c
                    break
        if cam is None:
            continue
        mask_path = MASKS_DIR / f"{cam.id}.json"
        if not mask_path.is_file():
            continue
        frames = _list_frames(frames_dir, cam.id, limit)
        if len(frames) < 30:
            rows.append({"camera": name, "id": cam.id, "n_frames": len(frames),
                         "confidence": 0.0, "note": "not enough frames"})
            continue
        mask = load_mask(cam.id)
        series = _motion_series(frames, mask)
        stats = cycle_and_green(series)
        stats.update({"camera": name, "id": cam.id, "n_frames": len(frames)})
        # offset vs first high-confidence camera
        if stats["confidence"] >= 0.4 and stats["cycle_s"]:
            # phase of the first peak above median
            above = series > np.median(series)
            first = int(np.argmax(above)) if above.any() else 0
            phase = first * 2.0
            if ref_phase is None:
                ref_phase = phase
            stats["offset_s"] = round((phase - ref_phase) % 90.0, 1)
        rows.append(stats)
    return {
        "meta": {"frames_dir": str(frames_dir), "limit": limit},
        "cameras": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, default=REPO_ROOT / "data" / "frames")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    result = measure(args.frames, args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    n = len(result["cameras"])
    high = sum(1 for r in result["cameras"] if r.get("confidence", 0) >= 0.4)
    print(f"wrote {args.out}: {n} cameras, {high} with confidence >= 0.4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
