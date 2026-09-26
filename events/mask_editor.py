"""Local lane-mask editor: drag polygon points over the camera image, then Save.

    python -m events.mask_editor            # http://127.0.0.1:8765
    python -m events.mask_editor --port 8800

Loads events/masks/<camera_id>.json and writes it back on Save (validated first).
Any camera with recorded frames in data/frames/ can be masked, and you can step
through its recorded frames to check the mask at different times, or save the
frame on screen as the camera's new reference frame. Only listens on 127.0.0.1.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from common.config import get_settings
from events.masks import MASKS_DIR, ZONE_COLORS, ZONE_PRIORITY, dump_mask, validate_mask

PAGE = Path(__file__).with_name("mask_editor.html")
CAMERA_ID = re.compile(r"^[0-9a-f-]{8,64}$")
FRAME_REF = re.compile(r"^\d{8}/\d{6}\.jpg$")
MAX_FRAMES = 400


def list_cameras(frames_dir: Path, masks_dir: Path, cameras_path: Path) -> list[dict]:
    names = {}
    if cameras_path.exists():
        names = {c["id"]: c["name"] for c in json.loads(cameras_path.read_text())}
    ids = {p.stem for p in masks_dir.glob("*.json")}
    if frames_dir.exists():
        ids |= {d.name for d in frames_dir.iterdir() if d.is_dir() and CAMERA_ID.match(d.name)}
    cams = [{"id": i, "name": names.get(i, i[:8]),
             "has_mask": (masks_dir / f"{i}.json").exists()} for i in ids]
    return sorted(cams, key=lambda c: (not c["has_mask"], c["name"]))


def list_frames(frames_dir: Path, camera_id: str) -> list[str]:
    """Recorded frames as '<YYYYMMDD>/<HHMMSS>.jpg', oldest first, thinned to MAX_FRAMES."""
    root = frames_dir / camera_id
    frames = sorted(p.relative_to(root).as_posix() for p in root.glob("*/*.jpg"))
    step = max(1, len(frames) // MAX_FRAMES)
    return frames[::step]


def load_or_new(masks_dir: Path, camera_id: str, name: str) -> dict:
    path = masks_dir / f"{camera_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"camera_id": camera_id, "name": name, "frame_size": [352, 240], "zones": []}


def make_handler(frames_dir: Path, masks_dir: Path, cameras_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200) -> None:
            self._send(status, json.dumps(obj).encode(), "application/json")

        def _error(self, status: int, msg: str) -> None:
            self._json({"error": msg}, status)

        def _file(self, path: Path) -> None:
            if path.is_file():
                self._send(200, path.read_bytes(), "image/jpeg")
            else:
                self._error(404, "not found")

        def do_GET(self):  # noqa: N802
            parts = [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p]
            if not parts:
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if parts == ["api", "config"]:
                return self._json({
                    "types": [t.value for t in ZONE_PRIORITY],
                    "colors": {t.value: ZONE_COLORS[t] for t in ZONE_PRIORITY}})
            if parts == ["api", "cameras"]:
                return self._json(list_cameras(frames_dir, masks_dir, cameras_path))
            if len(parts) < 3 or not CAMERA_ID.match(parts[2]):
                return self._error(404, "not found")
            cam = parts[2]
            if parts[:2] == ["api", "mask"]:
                names = {c["id"]: c["name"]
                         for c in list_cameras(frames_dir, masks_dir, cameras_path)}
                return self._json(load_or_new(masks_dir, cam, names.get(cam, cam)))
            if parts[:2] == ["api", "frames"]:
                return self._json({"reference": (masks_dir / f"{cam}.jpg").exists(),
                                   "frames": list_frames(frames_dir, cam)})
            if parts[:2] == ["img", "ref"]:
                return self._file(masks_dir / f"{cam}.jpg")
            if parts[:2] == ["img", "frame"] and len(parts) == 5:
                ref = f"{parts[3]}/{parts[4]}"
                if FRAME_REF.match(ref):
                    return self._file(frames_dir / cam / ref)
            return self._error(404, "not found")

        def do_POST(self):  # noqa: N802
            parts = [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p]
            if len(parts) != 3 or parts[:2] != ["api", "mask"] or not CAMERA_ID.match(parts[2]):
                return self._error(404, "not found")
            cam = parts[2]
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                mask, reference = body["mask"], body.get("reference_frame")
            except (ValueError, KeyError, TypeError):
                return self._error(400, "expected {mask, reference_frame?}")
            mask["camera_id"] = cam
            errors = validate_mask(mask)
            if errors:
                return self._json({"errors": errors}, HTTPStatus.UNPROCESSABLE_ENTITY)
            if reference:
                src = frames_dir / cam / reference
                if not FRAME_REF.match(reference) or not src.is_file():
                    return self._error(400, f"no recorded frame {reference}")
                shutil.copyfile(src, masks_dir / f"{cam}.jpg")
            elif not (masks_dir / f"{cam}.jpg").exists():
                return self._json({"errors": ["this camera has no reference frame yet: tick "
                                              "'save this frame as reference'"]},
                                  HTTPStatus.UNPROCESSABLE_ENTITY)
            (masks_dir / f"{cam}.json").write_text(dump_mask(mask))
            return self._json({"saved": f"events/masks/{cam}.json",
                               "reference_updated": bool(reference)})

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local lane-mask editor.")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    settings = get_settings()
    handler = make_handler(settings.frames_dir, MASKS_DIR, settings.cameras_path)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"mask editor on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
