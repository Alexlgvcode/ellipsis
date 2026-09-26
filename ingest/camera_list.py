"""Scrape the NYC DOT camera list into data/cameras.json.

Source: https://webcams.nyctmc.org/api/cameras/  (public, undocumented)
Fields: id, name, latitude, longitude, area, isOnline, imageUrl

Camera IDs can change: never hardcode them. Chosen cameras are stored by name and
coordinates and resolved to current IDs at startup (name first, then nearest coordinates).

    python -m ingest.camera_list --area penn
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

import httpx

from common.config import AREAS, get_settings
from common.schemas import Camera

log = logging.getLogger(__name__)

USER_AGENT = "LaneWatch/0.1 (hackathon research; polite polling)"

# Chosen cameras around Penn Station / Herald Sq, stored as (name, lat, lon).
# Almost every NYCTMC camera is PTZ hardware; these were picked because their view held
# still across repeated frames.
CHOSEN: list[tuple[str, float, float]] = [
    ("8th Ave @ 31st St", 40.750297, -73.994830),
    ("8th Ave @ 33rd St", 40.751512, -73.993913),
    ("7 Ave @ 32 St", 40.749508, -73.991493),
    ("7 Ave @ 34 St", 40.751020, -73.990629),
    ("7 Ave @ 36 St", 40.752128, -73.989657),
    ("6 Ave @ 30 St", 40.747287, -73.989615),
    ("6 Ave @ 34 St", 40.749808, -73.987746),
    ("Broadway @ 6 Ave / 33 St", 40.749412, -73.988060),
    ("Broadway @ 38 St", 40.752453, -73.987123),
]

# Cameras left out of the system entirely: not written to data/cameras.json, not recorded.
# 8 Ave @ 34 St pans and zooms between views, so no lane mask holds on it (2026-09-26).
EXCLUDED: set[str] = {"8 Ave @ 34 St"}

NAME_MATCH_MAX_M = 150.0
COORD_MATCH_MAX_M = 75.0
MIN_RESOLVED = 8


class CameraListError(RuntimeError):
    pass


# --- fetch / parse -------------------------------------------------------------------


def fetch_raw(client: httpx.Client, url: str, retries: int = 3,
              backoff_s: float = 1.0) -> list[dict]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise CameraListError(f"expected a JSON list, got {type(data).__name__}")
            return data
        except (httpx.HTTPError, ValueError, CameraListError) as e:
            last = e
            log.warning("camera list fetch failed (attempt %d/%d): %s",
                        attempt + 1, retries, e)
            if attempt + 1 < retries:
                time.sleep(backoff_s * 2**attempt)
    raise CameraListError(f"camera list fetch failed after {retries} attempts: {last}")


def _to_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"true", "1", "yes"}


def parse_camera(raw: dict) -> Camera:
    return Camera(
        id=str(raw["id"]),
        name=str(raw["name"]).strip(),
        lat=float(raw["latitude"]),
        lon=float(raw["longitude"]),
        area=raw.get("area"),
        image_url=str(raw["imageUrl"]),
        is_online=_to_bool(raw.get("isOnline", True)),
    )


def parse_cameras(raws: Iterable[dict]) -> list[Camera]:
    cams = []
    for raw in raws:
        try:
            cams.append(parse_camera(raw))
        except (KeyError, TypeError, ValueError) as e:
            log.warning("skipping malformed camera row %r: %s", raw.get("id"), e)
    return cams


# --- filter / match ------------------------------------------------------------------


def in_bbox(cam: Camera, bbox: tuple[float, float, float, float]) -> bool:
    min_lat, min_lon, max_lat, max_lon = bbox
    return min_lat <= cam.lat <= max_lat and min_lon <= cam.lon <= max_lon


def filter_to_area(cams: Iterable[Camera],
                   bbox: tuple[float, float, float, float]) -> list[Camera]:
    return [c for c in cams if in_bbox(c, bbox)]


_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b")
_WORDS = {"avenue": "ave", "av": "ave", "street": "st", "place": "pl", "road": "rd"}


def normalize_name(name: str) -> str:
    s = name.casefold()
    s = re.sub(r"[&/@]", " @ ", s)
    s = _ORDINAL.sub(r"\1", s)
    s = re.sub(r"[^\w@ ]+", " ", s)
    words = [_WORDS.get(w, w) for w in s.split()]
    # Drop a leading W/E before a street number ("W 34 St" -> "34 St").
    out = [w for i, w in enumerate(words)
           if not (w in {"w", "e"} and i + 1 < len(words) and words[i + 1].isdigit())]
    return " ".join(out)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def resolve_one(cams: list[Camera], name: str, lat: float, lon: float) -> Camera | None:
    def dist(c: Camera) -> float:
        return haversine_m(lat, lon, c.lat, c.lon)

    key = normalize_name(name)
    by_name = [c for c in cams if normalize_name(c.name) == key and dist(c) <= NAME_MATCH_MAX_M]
    if by_name:
        return min(by_name, key=dist)
    near = [c for c in cams if dist(c) <= COORD_MATCH_MAX_M]
    if near:
        best = min(near, key=dist)
        log.warning("%r not found by name; using nearest %r (%.0f m)", name, best.name,
                    dist(best))
        return best
    log.warning("could not resolve chosen camera %r", name)
    return None


def resolve_chosen(cams: list[Camera],
                   chosen: Iterable[tuple[str, float, float]] = CHOSEN) -> list[Camera]:
    out: list[Camera] = []
    seen: set[str] = set()
    for name, lat, lon in chosen:
        cam = resolve_one(cams, name, lat, lon)
        if cam is None:
            continue
        if cam.id in seen:
            log.warning("%r resolved to camera %s, already chosen; skipping", name, cam.id)
            continue
        seen.add(cam.id)
        out.append(cam)
    return out


# --- file io -------------------------------------------------------------------------


def write_cameras(cams: list[Camera], path: Path) -> None:
    if not cams:
        raise CameraListError("refusing to write an empty camera list")
    rows = [c.model_dump() for c in sorted(cams, key=lambda c: (c.name, c.id))]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cameras.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(rows, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_cameras(path: Path) -> list[Camera]:
    return [Camera(**row) for row in json.loads(path.read_text())]


# --- entry points --------------------------------------------------------------------


def scrape(client: httpx.Client, url: str, bbox: tuple[float, float, float, float],
           chosen: Iterable[tuple[str, float, float]] = CHOSEN) -> list[Camera]:
    """Fetch the live list and return the area cameras plus any chosen ones outside it,
    minus EXCLUDED ones."""
    excluded = {normalize_name(n) for n in EXCLUDED}
    all_cams = [c for c in parse_cameras(fetch_raw(client, url))
                if normalize_name(c.name) not in excluded]
    area = filter_to_area(all_cams, bbox)
    if not area:
        raise CameraListError(f"no cameras inside area box {bbox}")
    ids = {c.id for c in area}
    extra = [c for c in resolve_chosen(all_cams, chosen) if c.id not in ids]
    return area + extra


def load_cameras(refresh: bool = True, client: httpx.Client | None = None,
                 path: Path | None = None) -> list[Camera]:
    """Chosen cameras with current IDs. Fetches live, falls back to data/cameras.json."""
    settings = get_settings()
    path = path or settings.cameras_path
    cams: list[Camera] | None = None
    if refresh:
        own = client is None
        c = httpx.Client() if own else client
        try:
            cams = scrape(c, settings.camera_list_url, settings.area_bbox)
        except CameraListError as e:
            log.warning("live refresh failed, using %s: %s", path, e)
        finally:
            if own:
                c.close()
    if cams is None:
        cams = read_cameras(path)
    return resolve_chosen(cams)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--area", choices=sorted(AREAS), default=get_settings().area)
    parser.add_argument("--out", type=Path, default=get_settings().cameras_path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        with httpx.Client() as client:
            cams = scrape(client, get_settings().camera_list_url, AREAS[args.area])
    except CameraListError as e:
        log.error("%s; leaving %s unchanged", e, args.out)
        return 1

    write_cameras(cams, args.out)
    print(f"wrote {len(cams)} cameras to {args.out}")

    chosen = resolve_chosen(cams)
    for c in chosen:
        status = "online " if c.is_online else "OFFLINE"
        print(f"{status}  {c.id}  {c.name:<28}  {c.image_url}")
    if len(chosen) < MIN_RESOLVED:
        log.error("only %d/%d chosen cameras resolved", len(chosen), len(CHOSEN))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
