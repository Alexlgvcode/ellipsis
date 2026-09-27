"""Live mode (F14): poll the masked cameras and run the full pipeline on every new frame.

    LW_MOCK_MODE=false make api        # in another terminal (false = real events only)
    make live                          # python -m scripts.live --interval 2
    make recommend-worker              # optional: scores each new event in SUMO

camera stills every ~2 s (ingest.poller) -> detector -> tracker -> event engine
-> POST /events, exactly as in replay (scripts/replay.py), but on frames as they arrive.
Frames are still written to data/frames/, so a live session doubles as a recording.

Skipped: cameras without a lane mask, cameras the camera list marks offline (the poller
never polls them), and error images or timeouts. A duplicate or frozen frame isn't sent
to the detector: it tells the engine the picture didn't change, so after
dwell_s.frozen_feed a frozen_feed event opens and vehicles stop counting as parked.

Detection runs in a worker thread, so polling keeps its rhythm while YOLO is busy. If
detection falls behind, the oldest waiting frames are dropped (a lower frame rate, not a
growing delay). Losing the network is fine: failed polls and posts are logged and retried
on the next round.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image

from common.config import get_settings
from common.schemas import Camera
from events.pipeline import CameraPipeline
from ingest.camera_list import load_cameras
from ingest.poller import FrameResult, poll_cameras
from scripts.replay import DetectFn, EventSink, Publisher, _detector, resolve_camera

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 2.0
STILL = ("duplicate", "frozen")  # skip reasons that mean "the picture didn't change"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LiveRunner:
    """Collects poller results and runs them through each camera's pipeline in batches."""

    def __init__(self, pipes: dict[str, CameraPipeline], detect: DetectFn,
                 publisher: Publisher, max_backlog: int | None = None,
                 clock: Callable[[], datetime] = _utcnow):
        self.pipes = pipes
        self.detect = detect
        self.publisher = publisher
        self.max_backlog = max_backlog or 5 * max(len(pipes), 1)
        self.clock = clock
        self.dropped = 0
        self._pending: list[tuple[datetime, FrameResult]] = []

    def on_frame(self, r: FrameResult) -> None:
        """Poller callback (runs in the event loop, so it only queues)."""
        if r.camera_id not in self.pipes:
            return
        if r.skipped and r.reason not in STILL:
            return  # timeout, HTTP error, error image: nothing to learn from
        self._pending.append((r.timestamp or self.clock(), r))
        if len(self._pending) > self.max_backlog:
            drop = len(self._pending) - self.max_backlog
            self._pending = self._pending[drop:]
            self.dropped += drop
            log.warning("detection is falling behind: dropped %d old frames", drop)

    def take(self) -> list[tuple[datetime, FrameResult]]:
        batch, self._pending = self._pending, []
        return batch

    def process(self, batch: Sequence[tuple[datetime, FrameResult]]) -> None:
        """Detect on the new frames in one batch, then step each pipeline in time order."""
        fresh = [r for _, r in batch if not r.skipped]
        dets = dict(zip((r.path for r in fresh), self.detect([r.path for r in fresh]),
                        strict=True)) if fresh else {}
        for ts, r in sorted(batch, key=lambda item: item[0]):
            pipe = self.pipes[r.camera_id]
            if r.skipped:
                update = pipe.step(ts, None, [], frozen=True)
            else:
                with Image.open(r.path) as img:
                    update = pipe.step(ts, img, dets[r.path])
            self.publisher.publish(r.camera_id, r.path, ts, update, pipe.congestion.readings)


def masked(cameras: Sequence[Camera]) -> dict[str, CameraPipeline]:
    """A pipeline for each camera that has a lane mask."""
    pipes = {c.id: CameraPipeline.for_camera(c.id) for c in cameras}
    return {cid: p for cid, p in pipes.items() if p is not None}


async def run_live(cameras: Sequence[Camera], runner: LiveRunner, frames_dir: Path,
                   interval_s: float = DEFAULT_INTERVAL_S, stop: asyncio.Event | None = None,
                   max_iterations: int | None = None,
                   transport: httpx.AsyncBaseTransport | None = None,
                   reload_cameras: Callable[[], Sequence[Camera]] | None = None,
                   clock: Callable[[], datetime] = _utcnow) -> None:
    """Poll `cameras` and process what arrives until `stop` is set (or `max_iterations`
    polling rounds are done)."""
    stop = stop or asyncio.Event()
    polling = asyncio.create_task(poll_cameras(
        [c for c in cameras if c.id in runner.pipes], frames_dir=frames_dir,
        interval_s=interval_s, max_iterations=max_iterations, on_frame=runner.on_frame,
        transport=transport, stop=stop, reload_cameras=reload_cameras, clock=clock))
    try:
        while True:
            done, _ = await asyncio.wait({polling}, timeout=max(interval_s / 2, 0.05))
            batch = runner.take()
            if batch:
                await asyncio.to_thread(runner.process, batch)
            if done:
                polling.result()  # re-raise a crash in the poller
                return
    finally:
        polling.cancel()


def main(argv: Iterable[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Run the pipeline on live camera frames.")
    ap.add_argument("--camera", action="append", default=None,
                    help="camera id, id prefix or name; repeat for more (default: all masked)")
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S,
                    help=f"seconds between polls (default: {DEFAULT_INTERVAL_S:g})")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--no-post", action="store_true", help="don't post to the API")
    ap.add_argument("--weights", default=None)
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = ap.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cameras = load_cameras(refresh=True)
    if args.camera:
        wanted = {resolve_camera(c, settings.cameras_path) for c in args.camera}
        cameras = [c for c in cameras if c.id in wanted]
    pipes = masked(cameras)
    if not pipes:
        print("no masked cameras to watch (lane masks are in events/masks/)")
        return 1

    client = None
    if not args.no_post:
        client = httpx.Client(base_url=args.api, timeout=5.0)
        try:
            health = client.get("/health").json()
        except httpx.HTTPError:
            print(f"API not reachable at {args.api}: start it with `make api` "
                  "(or pass --no-post)")
            return 1
        if health.get("mock_mode"):
            print("note: the API is in mock mode, so the dashboard also shows the mock events; "
                  "restart it with LW_MOCK_MODE=false for real events only")

    names = ", ".join(p.engine.mask.name for p in pipes.values())
    print(f"live: {len(pipes)} cameras every {args.interval:g} s ({names}); Ctrl+C to stop")
    publisher = Publisher(EventSink(client), settings.data_dir / "snapshots")
    runner = LiveRunner(pipes, _detector(args.weights), publisher)

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_live(cameras, runner, settings.frames_dir, args.interval, stop,
                       reload_cameras=lambda: load_cameras(refresh=True))

    asyncio.run(run())
    failed = publisher.sink.failures
    print(f"\nstopped: {len(publisher.final)} events"
          + (f", {failed} failed posts" if failed else "")
          + (f", {runner.dropped} frames dropped" if runner.dropped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
