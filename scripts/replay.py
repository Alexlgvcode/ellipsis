"""Replay mode (F13): run the full pipeline on recorded frames and push events to the API.

    LW_MOCK_MODE=false make api        # in another terminal (false = real events only)
    python scripts/replay.py --camera "7 Ave @ 36 St" --start 18:22 --end 18:30 --speed 10

frames (data/frames/<camera_id>/<YYYYMMDD>/<HHMMSS>.jpg, UTC) -> detector -> tracker
-> event engine -> POST /events. When an event opens, its frame is saved as the
snapshot (data/snapshots/<camera_id>/<event_id>.jpg); the dashboard draws the box
from the event's bbox. Events are posted when they open, as they grow, and when
they close. Event ids are deterministic, so replaying again updates the same events.

--speed 10 plays 10x faster than real time; --speed 0 as fast as possible.
--as-live shifts the posted times so the recording starts "now": the dashboard only
counts events seen in the last few minutes as active, so use it for demos
(e.g. --as-live --speed 1 to watch an alert fire at 60 s). Event ids don't change.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.schemas import Congestion, CongestionLevel, Event  # noqa: E402
from events.engine import EngineUpdate  # noqa: E402
from events.pipeline import CameraPipeline  # noqa: E402
from vision.detect import Detection  # noqa: E402
from vision.track import frame_timestamp  # noqa: E402

DetectFn = Callable[[Sequence[Path]], list[list[Detection]]]


def resolve_camera(name_or_id: str, cameras_path: Path) -> str:
    """Camera id from an id, an id prefix, or a name like '7 Ave @ 36 St'."""
    cams = json.loads(cameras_path.read_text()) if cameras_path.exists() else []
    key = " ".join(name_or_id.lower().split())
    for c in cams:
        if c["id"] == name_or_id or " ".join(c["name"].lower().split()) == key:
            return c["id"]
    prefix = [c["id"] for c in cams if c["id"].startswith(name_or_id)]
    if len(prefix) == 1:
        return prefix[0]
    return name_or_id


def _hms(value: str | None) -> str | None:
    """'18:22' / '18:22:09' / '182209' -> '182209' (UTC, as in the frame file names)."""
    if value is None:
        return None
    digits = value.replace(":", "")
    return (digits + "00")[:6] if len(digits) == 4 else digits


def select_frames(frames_dir: Path, camera_id: str, date: str | None = None,
                  start: str | None = None, end: str | None = None) -> list[Path]:
    """Recorded frames for a camera, oldest first, inside [start, end] (UTC HH:MM[:SS])."""
    root = frames_dir / camera_id
    days = [root / date] if date else sorted(p for p in root.glob("*") if p.is_dir())
    frames = [p for d in days for p in d.glob("*.jpg")]
    lo, hi = _hms(start), _hms(end)
    frames = [p for p in frames if (lo is None or p.stem >= lo) and (hi is None or p.stem <= hi)]
    return sorted(frames, key=frame_timestamp)


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


class EventSink:
    """Posts events to the API. Keeps going if the API is briefly unreachable."""

    def __init__(self, client: httpx.Client | None):
        self.client = client
        self.failures = 0

    def post(self, event: Event) -> bool:
        return self._post("/events", event, event.id)

    def post_congestion(self, reading: Congestion) -> bool:
        return self._post("/congestion", reading, f"congestion {reading.approach}")

    def _post(self, path: str, model, what: str) -> bool:
        if self.client is None:
            return True
        try:
            resp = self.client.post(path, json=model.model_dump(mode="json"))
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            self.failures += 1
            print(f"  ! could not post {what}: {e}", file=sys.stderr)
            return False


class Publisher:
    """Saves a snapshot when an event opens, then posts every change to the API.
    Congestion readings are posted when an approach's level changes, and every
    `CONGESTION_HEARTBEAT_S` while it isn't free (so the dashboard can tell a jam that's still
    on from one that stopped being reported). Shared by replay and live mode (scripts/live.py)."""

    CONGESTION_HEARTBEAT_S = 60.0

    def __init__(self, sink: EventSink, snapshots_dir: Path, log: Callable[[str], None] = print,
                 time_shift: timedelta = timedelta(0)):
        self.sink = sink
        self.snapshots_dir = snapshots_dir
        self.log = log
        self.time_shift = time_shift
        self.final: dict[str, Event] = {}  # each event's latest state, as posted
        self.congestion: dict[tuple[str, str], Congestion] = {}  # last posted per approach
        self._snapshots: dict[str, str] = {}

    def publish(self, camera_id: str, frame: Path | None, ts: datetime,
                update: EngineUpdate, congestion: Sequence[Congestion] = ()) -> None:
        """`frame` is the frame the update came from (None for a frozen-feed tick);
        `congestion` the camera's readings (pipe.congestion.readings)."""
        self._publish_congestion(ts, congestion)
        for event in update.opened:
            if frame is None:
                continue
            dest = self.snapshots_dir / camera_id / f"{event.id}.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(frame, dest)
            self._snapshots[event.id] = _repo_relative(dest)
        for kind, events in (("OPEN ", update.opened), ("     ", update.updated),
                             ("CLOSE", update.closed)):
            for event in events:
                event = event.model_copy(update={
                    "snapshot_path": self._snapshots.get(event.id, event.snapshot_path),
                    "start_ts": event.start_ts + self.time_shift})
                self.sink.post(event)
                self.final[event.id] = event
                if kind != "     ":
                    self.log(f"{ts:%H:%M:%S}  {kind}  {event.type.value:<16} "
                             f"{event.duration_s:>5.0f}s  {event.id}")

    def _publish_congestion(self, ts: datetime, readings: Sequence[Congestion]) -> None:
        for r in readings:
            if r.ts != ts:
                continue  # left over from an earlier frame (frozen picture, paused camera)
            key = (r.camera_id, r.approach)
            last = self.congestion.get(key)
            changed = last is None or last.level is not r.level
            beat = last is not None and r.level is not CongestionLevel.FREE and \
                (r.ts + self.time_shift - last.ts).total_seconds() >= self.CONGESTION_HEARTBEAT_S
            if last is None and r.level is CongestionLevel.FREE:
                changed = True  # the first reading of an approach, so the dashboard knows it
            if not (changed or beat):
                continue
            r = r.model_copy(update={"ts": r.ts + self.time_shift,
                                     "since_ts": r.since_ts + self.time_shift})
            self.sink.post_congestion(r)
            self.congestion[key] = r
            if changed and last is not None:
                self.log(f"{ts:%H:%M:%S}  TRAFFIC {r.approach:<16} {r.level.value:<9} "
                         f"score {r.score:.2f}  {r.camera_id[:8]}")


def replay(frames: Sequence[Path], pipe: CameraPipeline, detect: DetectFn, sink: EventSink,
           snapshots_dir: Path, speed: float = 10.0, batch: int = 16,
           log: Callable[[str], None] = print,
           time_shift: timedelta = timedelta(0)) -> dict[str, Event]:
    """Run frames through the pipeline in time order; returns each event's final state
    (as posted: with its snapshot, and start_ts moved by `time_shift`)."""
    publisher = Publisher(sink, snapshots_dir, log, time_shift)
    prev_ts: datetime | None = None
    last_wall = time.monotonic()
    for i in range(0, len(frames), batch):
        chunk = list(frames[i:i + batch])
        for path, dets in zip(chunk, detect(chunk), strict=True):
            ts = frame_timestamp(path)
            if speed > 0 and prev_ts is not None:  # keep the recording's rhythm, sped up
                wait = (ts - prev_ts).total_seconds() / speed - (time.monotonic() - last_wall)
                if wait > 0:
                    time.sleep(wait)
            prev_ts, last_wall = ts, time.monotonic()
            update = pipe.step(ts, Image.open(path), dets)
            publisher.publish(pipe.camera_id, path, ts, update, pipe.congestion.readings)
    return publisher.final


def _detector(weights: str | None) -> DetectFn:
    from events.rules import load_rules
    from vision.detect import Detector

    # down to keep_conf: the tracker uses weak detections to keep existing tracks going
    return Detector(weights, conf=load_rules()["tracking"]["keep_conf"]).detect


def main(argv: Iterable[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="Replay recorded frames through the pipeline.")
    ap.add_argument("--camera", required=True, help="camera id, id prefix, or name")
    ap.add_argument("--date", default=None, help="YYYYMMDD (default: all recorded days)")
    ap.add_argument("--start", default=None, help="UTC HH:MM[:SS]")
    ap.add_argument("--end", default=None, help="UTC HH:MM[:SS]")
    ap.add_argument("--speed", type=float, default=10.0, help="x real time; 0 = no waiting")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--no-post", action="store_true", help="don't post to the API")
    ap.add_argument("--as-live", action="store_true",
                    help="post times shifted so the recording starts now (for demos)")
    ap.add_argument("--weights", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    camera_id = resolve_camera(args.camera, settings.cameras_path)
    pipe = CameraPipeline.for_camera(camera_id)
    if pipe is None:
        print(f"no lane mask for {args.camera!r} ({camera_id}); masked cameras are in "
              "events/masks/")
        return 1
    frames = select_frames(settings.frames_dir, camera_id, args.date, args.start, args.end)
    if not frames:
        print(f"no recorded frames for {pipe.engine.mask.name} in that window "
              f"(data/frames/{camera_id}/)")
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

    span = (frame_timestamp(frames[-1]) - frame_timestamp(frames[0])).total_seconds()
    print(f"replaying {pipe.engine.mask.name}: {len(frames)} frames, "
          f"{frame_timestamp(frames[0]):%H:%M:%S}-{frame_timestamp(frames[-1]):%H:%M:%S} UTC "
          f"({span / 60:.1f} min) at {args.speed:g}x")
    sink = EventSink(client)
    shift = timedelta(0)
    if args.as_live:
        shift = datetime.now(timezone.utc) - frame_timestamp(frames[0])
        print(f"as live: posted times shifted by {shift.total_seconds() / 60:.0f} min")
    final = replay(frames, pipe, _detector(args.weights), sink,
                   settings.data_dir / "snapshots", speed=args.speed, time_shift=shift)
    print(f"\n{len(final)} events" + (f", {sink.failures} failed posts" if sink.failures else ""))
    for e in sorted(final.values(), key=lambda e: -e.duration_s):
        print(f"  {e.type.value:<16} {e.duration_s:>5.0f}s  conf {e.confidence:.2f}  "
              f"{e.snapshot_path or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
