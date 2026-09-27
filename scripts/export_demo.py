"""Record the demo replay for the static site (issue #55): web/public/demo/.

    python -m scripts.export_demo --frames ~/Downloads/frames     # the demo site's window
    python -m scripts.export_demo --start 18:21:30 --end 18:31 \
        --camera "7 Ave @ 36 St" --camera "8th Ave @ 31st St"       # the live pitch's window

The site plays 20:12-20:32 UTC on 2026-09-26 on every masked camera: one recording
session with the real 6 Ave @ 30 St jam (heatmap), the bus-lane car, the cab pickup, the
delivery van, and one known false alert (8th Ave @ 33rd St) to mark as a false positive.
It's also the window the evaluation's precision and recall were measured on.

Runs the real pipeline on the recorded frames (YOLO -> tracker -> event engine ->
congestion), exactly as scripts/replay.py does, and writes what the API would have served
over time instead of posting it:

    timeline.json   every event and congestion update with its time from the start,
                    each alert's SUMO recommendation (scored as the worker does, when the
                    alert opens) and when it would appear, the cameras
    snapshots/      the frame from when each alert opened
    notes           an AI incident note per alert (api/summarize.py), when a key is set
    voice/          a spoken alert per event (ElevenLabs), when ELEVENLABS_API_KEY is set

The dashboard built with VITE_DEMO=1 plays the timeline back in real time from the moment
the page opens, so the site needs no server, GPU or SUMO. Needs the vision and sim extras.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from common.config import REPO_ROOT, get_settings
from common.schemas import Congestion, Event, EventType
from events.masks import MASKS_DIR
from events.pipeline import CameraPipeline
from scripts.replay import EventSink, _detector, replay, resolve_camera, select_frames
from vision.track import frame_timestamp

OUT = REPO_ROOT / "web" / "public" / "demo"
WORKER_DELAY_S = 25.0  # the worker's SUMO scoring time: the card shows "running" until then
FRAME_EVERY_S = 8.0    # the site's "live" view: NYC DOT stills refresh about this often
FRAME_QUALITY = 60     # WebP: ~17 KB per 352x240 frame


def note_with_retry(event: Event, rec, camera_name: str | None, tries: int = 4) -> str | None:
    """The incident note, retrying a few times: busy models answer 503 at peak times."""
    from api.summarize import summarize

    for attempt in range(tries):
        text = summarize(event, rec, camera_name)
        if text:
            return text
        time.sleep(5 * (attempt + 1))
    return None


def fill_notes(out: Path) -> int:
    """--notes-only: add the notes missing from an existing timeline (no YOLO or SUMO)."""
    from common.schemas import Recommendation

    path = out / "timeline.json"
    timeline = json.loads(path.read_text())
    names = {c["id"]: c["name"] for c in timeline["cameras"]}
    notes = timeline.setdefault("notes", {})
    first: dict[str, dict] = {}
    for u in sorted(timeline["updates"], key=lambda u: u["t"]):
        first.setdefault(u["event"]["id"], u["event"])
    for eid, r in timeline["recommendations"].items():
        if eid in notes:
            continue
        e = Event(**first[eid])
        text = note_with_retry(e, Recommendation(**r["rec"]), names.get(e.camera_id))
        if text:
            notes[eid] = {"t": r["t"], "text": text}
        print(f"{eid}: {'note written' if text else 'still no note'}")
    path.write_text(json.dumps(timeline, separators=(",", ":")))
    return 0 if len(notes) == len(timeline["recommendations"]) else 1


class RecordingSink(EventSink):
    """Keeps every post with the moment it describes, instead of sending it."""

    def __init__(self) -> None:
        super().__init__(None)
        self.events: list[tuple[datetime, Event]] = []
        self.congestion: list[Congestion] = []

    def post(self, event: Event) -> bool:
        self.events.append((event.start_ts + timedelta(seconds=event.duration_s), event))
        return True

    def post_congestion(self, reading: Congestion) -> bool:
        self.congestion.append(reading)
        return True


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--camera", action="append", default=None,
                    help="camera name or id; repeat (default: every camera with a lane mask)")
    ap.add_argument("--frames", type=Path, default=None,
                    help="frames folder <camera_id>/<YYYYMMDD>/<HHMMSS>.jpg (default: data/frames)")
    ap.add_argument("--date", default="20260926")
    ap.add_argument("--start", default="20:12:00", help="UTC")
    ap.add_argument("--end", default="20:32:30", help="UTC")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-sim", action="store_true", help="skip SUMO (recommendations empty)")
    ap.add_argument("--notes-only", action="store_true",
                    help="only add missing incident notes to an existing timeline")
    args = ap.parse_args(argv)
    if args.notes_only:
        return fill_notes(args.out)

    if args.out.exists():
        shutil.rmtree(args.out)
    (args.out / "snapshots").mkdir(parents=True)
    sink = RecordingSink()
    detect = _detector(None)
    starts = []
    recorded: dict[str, list] = {}  # camera -> the frames its "live" view shows
    frames_dir = (args.frames or settings.frames_dir).expanduser()
    masked = sorted(p.stem for p in MASKS_DIR.glob("*.json"))
    for name in args.camera or masked:
        camera_id = resolve_camera(name, settings.cameras_path)
        pipe = CameraPipeline.for_camera(camera_id)
        frames = select_frames(frames_dir, camera_id, args.date, args.start, args.end)
        if pipe is None or not frames:
            print(f"skipping {name}: no lane mask or no frames in the window")
            continue
        starts.append(frame_timestamp(frames[0]))
        recorded[camera_id] = frames
        print(f"{name}: {len(frames)} frames")
        replay(frames, pipe, detect, sink, args.out / "snapshots", speed=0)
    if not starts:
        return 1
    t0 = min(starts)
    rel = lambda ts: round((ts - t0).total_seconds(), 1)  # noqa: E731

    # each camera's recorded stills, so its "live" view shows the same moment as the alerts
    frame_times: dict[str, list[int]] = {}
    for camera_id, frames in recorded.items():
        kept, last = [], None
        for path in frames:
            t = int(rel(frame_timestamp(path)))
            if last is not None and t - last < FRAME_EVERY_S:
                continue
            dest = args.out / "frames" / camera_id / f"{t}.webp"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(path) as img:
                img.save(dest, "WEBP", quality=FRAME_QUALITY, method=6)
            kept.append(t)
            last = t
        frame_times[camera_id] = kept

    # the API's view of each event over time: its latest state at every post
    updates = [{"t": rel(at), "event": e.model_dump(mode="json")} for at, e in sink.events]
    for u in updates:  # snapshots are served from the site, next to timeline.json
        snap = u["event"].get("snapshot_path")
        if snap:
            u["event"]["snapshot_path"] = Path(snap).relative_to(args.out.relative_to(REPO_ROOT)
                                                                 ).as_posix()
    first: dict[str, tuple[float, Event]] = {}
    for at, e in sink.events:
        first.setdefault(e.id, (rel(at), e))

    recs, notes = {}, {}
    cameras = json.loads(settings.cameras_path.read_text())
    names = {c["id"]: c["name"] for c in cameras}
    if not args.no_sim:
        from signals.mapping import load_mapping
        from signals.retime import recommend

        mapping = load_mapping()
        for eid, (t, e) in first.items():
            if e.type is EventType.FROZEN_FEED or e.camera_id not in mapping["cameras"]:
                continue
            rec = recommend(e, mapping, simulate=True)   # as the worker: at first sight
            recs[eid] = {"t": round(t + WORKER_DELAY_S, 1), "rec": rec.model_dump(mode="json")}
            # the worker writes the incident note right after scoring (GEMINI_API_KEY)
            text = note_with_retry(e, rec, names.get(e.camera_id))
            if text:
                notes[eid] = {"t": recs[eid]["t"], "text": text}
            print(f"scored {eid}: delay {rec.sim.delay_default:.1f} -> {rec.sim.delay_new:.1f}")

    voice_files = {}
    from api import voice

    for eid, (_, e) in first.items():
        audio = voice.speak(voice.alert_text(e, names.get(e.camera_id)))
        if audio:
            path = args.out / "voice" / f"{eid}.mp3"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(audio)
            voice_files[eid] = f"voice/{eid}.mp3"

    timeline = {
        "window": {"date": args.date, "start": args.start, "end": args.end},
        "t0": t0.isoformat(),
        "duration_s": max([u["t"] for u in updates] + [0.0]),
        "cameras": cameras,
        "updates": updates,
        "congestion": [{"t": rel(c.ts), "reading": c.model_dump(mode="json")}
                       for c in sink.congestion],
        "recommendations": recs,
        "notes": notes,
        "voice": voice_files,
        "frames": frame_times,
        # open a few seconds after the first alert, so a visitor sees one at once; loop straight
        # back, every camera still in step
        "start_at_s": round(min((u["t"] for u in updates), default=0.0) + 5, 1),
        "loop_pause_s": 5,
    }
    (args.out / "timeline.json").write_text(json.dumps(timeline, separators=(",", ":")))
    print(f"\n{len(first)} events, {len(updates)} updates, {len(sink.congestion)} congestion "
          f"readings, {len(recs)} recommendations, {len(notes)} notes, "
          f"{len(voice_files)} spoken alerts "
          f"-> {args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
