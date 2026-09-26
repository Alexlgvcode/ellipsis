#!/usr/bin/env python3
"""Record frames for the chosen cameras every 5 s, day and night.

Usage:
    python -m scripts.record_frames [--interval 5] [--out data/frames] [-v]

Ctrl+C (or SIGTERM) stops after the current round; a second Ctrl+C exits immediately.
Frames are saved to data/frames/<camera_id>/<YYYYMMDD>/<HHMMSS>.jpg (UTC).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from collections import Counter
from pathlib import Path

from common.config import get_settings
from ingest.camera_list import load_cameras
from ingest.poller import FrameResult, poll_cameras

log = logging.getLogger(__name__)

SUMMARY_EVERY_S = 60.0


class Stats:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.frozen: set[str] = set()
        self._last = time.monotonic()

    def on_frame(self, r: FrameResult) -> None:
        self.counts["saved" if not r.skipped else r.reason.split(":")[0]] += 1
        (self.frozen.add if r.frozen else self.frozen.discard)(r.camera_id)
        if r.skipped:
            log.debug("%s: skipped (%s)", r.camera_id[:8], r.reason)
        else:
            log.debug("%s: saved %s", r.camera_id[:8], r.path)
        if time.monotonic() - self._last >= SUMMARY_EVERY_S:
            self.flush()

    def flush(self) -> None:
        if self.counts:
            parts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
            frozen = f"; frozen: {len(self.frozen)}" if self.frozen else ""
            log.info("last %.0f s: %s%s", time.monotonic() - self._last, parts, frozen)
        self.counts.clear()
        self._last = time.monotonic()


async def run(frames_dir: Path, interval_s: float, max_concurrency: int) -> None:
    cameras = load_cameras(refresh=True)
    log.info("recording %d cameras every %.1f s to %s (Ctrl+C to stop)",
             len(cameras), interval_s, frames_dir)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def handle_signal(sig: signal.Signals) -> None:
        log.info("%s received, stopping after this round (again to force)", sig.name)
        stop.set()
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(s)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig)

    stats = Stats()
    await poll_cameras(
        cameras,
        frames_dir=frames_dir,
        interval_s=interval_s,
        max_concurrency=max_concurrency,
        on_frame=stats.on_frame,
        stop=stop,
        reload_cameras=lambda: load_cameras(refresh=True),
    )
    stats.flush()
    log.info("stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--interval", type=float, default=5.0,
                        help="polling interval in seconds (default: 5)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory (default: data/frames)")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="max concurrent requests (default: 5)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        asyncio.run(run(args.out or get_settings().frames_dir, args.interval, args.concurrency))
    except KeyboardInterrupt:
        log.info("forced exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
