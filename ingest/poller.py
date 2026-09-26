"""Async frame poller.

Fetches each camera still every 2-5 s (with jitter), drops duplicates and error images,
flags frozen feeds, and writes frames to data/frames/<camera_id>/<YYYYMMDD>/<HHMMSS>.jpg.
Timestamps in the path are UTC, taken when the frame is received (some cameras burn in a
wrong clock). Frames are ~352x240 JPEG. Poll politely.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from common.config import get_settings
from common.schemas import Camera
from ingest.health import FrozenFeedDetector, decode, error_reason, image_hash, thumbnail

log = logging.getLogger(__name__)

USER_AGENT = "LaneWatch/0.1 (hackathon research; polite polling)"
DEFAULT_INTERVAL_S = 5.0
JITTER_RANGE = (0.8, 1.2)
DEFAULT_CONCURRENCY = 5
REQUEST_TIMEOUT = 15.0
RELOAD_EVERY_S = 6 * 3600.0
RELOAD_AFTER_FAILURES = 12      # ~1 min of failures at 5 s
RELOAD_MIN_GAP_S = 300.0


@dataclass
class FrameResult:
    camera_id: str
    path: Path | None = None
    timestamp: datetime | None = None
    skipped: bool = False
    reason: str | None = None
    frame_hash: str | None = None
    frozen: bool = False


def frame_path(frames_dir: Path, camera_id: str, ts: datetime) -> Path:
    """frames/<camera_id>/<YYYYMMDD>/<HHMMSS>.jpg, with ts in UTC."""
    ts = ts.astimezone(timezone.utc)
    return frames_dir / camera_id / ts.strftime("%Y%m%d") / f"{ts.strftime('%H%M%S')}.jpg"


def _write_frame_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".frame.", suffix=".jpg")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CameraPoller:
    """Polls one camera: dedupes by hash, skips error images, tracks frozen state."""

    def __init__(self, camera: Camera, frames_dir: Path,
                 clock: Callable[[], datetime] = _utcnow):
        self.camera = camera
        self.frames_dir = frames_dir
        self.clock = clock
        self.failures = 0
        self._last_hash: str | None = None
        self._frozen = FrozenFeedDetector()

    @property
    def frozen(self) -> bool:
        return self._frozen.frozen

    def _skip(self, reason: str, **kw) -> FrameResult:
        return FrameResult(self.camera.id, skipped=True, reason=reason, **kw)

    async def fetch_frame(self, client: httpx.AsyncClient) -> FrameResult:
        ts = self.clock()
        try:
            resp = await client.get(self.camera.image_url, headers={"User-Agent": USER_AGENT},
                                    timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.content
        except httpx.TimeoutException as e:
            self.failures += 1
            log.warning("%s: timeout: %s", self.camera.name, e)
            return self._skip("timeout")
        except httpx.HTTPError as e:
            self.failures += 1
            log.warning("%s: http error: %s", self.camera.name, e)
            return self._skip(f"http_error: {e}")

        bad = error_reason(data)
        if bad:
            self.failures += 1
            return self._skip(f"error_image: {bad}")
        self.failures = 0

        h = image_hash(data)
        was_frozen = self.frozen
        frozen = self._frozen.update(thumbnail(decode(data)), ts)
        if frozen != was_frozen:
            if frozen:
                log.warning("%s: feed frozen for %.0f s", self.camera.name, self._frozen.window_s)
            else:
                log.info("%s: feed moving again", self.camera.name)

        if h == self._last_hash:
            return self._skip("duplicate", frame_hash=h, frozen=frozen)
        self._last_hash = h
        if frozen:
            return self._skip("frozen", frame_hash=h, frozen=True)

        path = frame_path(self.frames_dir, self.camera.id, ts)
        _write_frame_atomic(path, data)
        return FrameResult(self.camera.id, path=path, timestamp=ts, frame_hash=h)


def _online(cameras: Sequence[Camera]) -> list[Camera]:
    for c in cameras:
        if not c.is_online:
            log.warning("%s is offline in the camera list; not polling it", c.name)
    return [c for c in cameras if c.is_online]


async def poll_cameras(
    cameras: Sequence[Camera],
    frames_dir: Path | None = None,
    interval_s: float = DEFAULT_INTERVAL_S,
    max_concurrency: int = DEFAULT_CONCURRENCY,
    max_iterations: int | None = None,
    on_frame: Callable[[FrameResult], None] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    stop: asyncio.Event | None = None,
    reload_cameras: Callable[[], Sequence[Camera]] | None = None,
    reload_every_s: float = RELOAD_EVERY_S,
    reload_after_failures: int = RELOAD_AFTER_FAILURES,
    clock: Callable[[], datetime] = _utcnow,
) -> None:
    """Poll all cameras in rounds until `stop` is set or `max_iterations` rounds are done.

    `reload_cameras` (e.g. ingest.camera_list.load_cameras) is called every `reload_every_s`,
    and when a camera fails `reload_after_failures` times in a row, so camera ID changes
    during a long recording are picked up. Pollers keep their state across reloads.
    """
    frames_dir = frames_dir or get_settings().frames_dir
    frames_dir.mkdir(parents=True, exist_ok=True)
    stop = stop or asyncio.Event()
    pollers = {c.id: CameraPoller(c, frames_dir, clock) for c in _online(cameras)}
    semaphore = asyncio.Semaphore(max_concurrency)
    last_reload = time.monotonic()

    async def fetch(p: CameraPoller) -> FrameResult:
        async with semaphore:
            return await p.fetch_frame(client)

    async def maybe_reload() -> None:
        nonlocal pollers, last_reload
        since = time.monotonic() - last_reload
        failing = [p.camera.name for p in pollers.values() if p.failures >= reload_after_failures]
        if not (since >= reload_every_s or (failing and since >= RELOAD_MIN_GAP_S)):
            return
        last_reload = time.monotonic()
        log.info("reloading camera list (%s)", f"failing: {failing}" if failing else "scheduled")
        try:
            fresh = await asyncio.to_thread(reload_cameras)
        except Exception as e:
            log.warning("camera reload failed, keeping current list: %s", e)
            return
        if not fresh:
            log.warning("camera reload returned no cameras, keeping current list")
            return
        pollers = {c.id: pollers.get(c.id) or CameraPoller(c, frames_dir, clock)
                   for c in _online(fresh)}

    client_kwargs: dict = {"timeout": REQUEST_TIMEOUT}
    if transport is not None:
        client_kwargs["transport"] = transport

    async with httpx.AsyncClient(**client_kwargs) as client:
        iteration = 0
        while not stop.is_set() and (max_iterations is None or iteration < max_iterations):
            iteration += 1
            results = await asyncio.gather(*(fetch(p) for p in pollers.values()),
                                           return_exceptions=True)
            for r in results:
                if isinstance(r, BaseException):
                    log.error("unexpected error in poller: %r", r)
                elif on_frame:
                    on_frame(r)

            if reload_cameras is not None:
                await maybe_reload()
            if max_iterations is not None and iteration >= max_iterations:
                break
            try:
                await asyncio.wait_for(stop.wait(), interval_s * random.uniform(*JITTER_RANGE))
            except asyncio.TimeoutError:
                pass


async def poll_once(
    cameras: Sequence[Camera],
    frames_dir: Path | None = None,
    max_concurrency: int = DEFAULT_CONCURRENCY,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[FrameResult]:
    """Poll every camera exactly once."""
    results: list[FrameResult] = []
    await poll_cameras(cameras, frames_dir=frames_dir, max_concurrency=max_concurrency,
                       max_iterations=1, on_frame=results.append, transport=transport)
    return results
