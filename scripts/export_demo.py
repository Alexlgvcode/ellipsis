"""Record the demo replay for the static site (issue #55): web/public/demo/.

    python -m scripts.export_demo                       # the docs/demo.md window
    python -m scripts.export_demo --start 18:21:30 --end 18:31

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

from common.config import REPO_ROOT, get_settings
from common.schemas import Congestion, Event, EventType
from events.pipeline import CameraPipeline
from scripts.replay import EventSink, _detector, replay, resolve_camera, select_frames
from vision.track import frame_timestamp

OUT = REPO_ROOT / "web" / "public" / "demo"
CAMERAS = ("7 Ave @ 36 St", "8th Ave @ 31st St")
WORKER_DELAY_S = 25.0  # the worker's SUMO scoring time: the card shows "running" until then


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
                    help="camera name or id; repeat (default: the two demo cameras)")
    ap.add_argument("--date", default="20260926")
    ap.add_argument("--start", default="18:21:30", help="UTC")
    ap.add_argument("--end", default="18:31:00", help="UTC")
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
    for name in args.camera or CAMERAS:
        camera_id = resolve_camera(name, settings.cameras_path)
        pipe = CameraPipeline.for_camera(camera_id)
        frames = select_frames(settings.frames_dir, camera_id, args.date, args.start, args.end)
        if pipe is None or not frames:
            print(f"skipping {name}: no lane mask or no frames in the window")
            continue
        starts.append(frame_timestamp(frames[0]))
        print(f"{name}: {len(frames)} frames")
        replay(frames, pipe, detect, sink, args.out / "snapshots", speed=0)
    if not starts:
        return 1
    t0 = min(starts)
    rel = lambda ts: round((ts - t0).total_seconds(), 1)  # noqa: E731

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
    }
    (args.out / "timeline.json").write_text(json.dumps(timeline, separators=(",", ":")))
    print(f"\n{len(first)} events, {len(updates)} updates, {len(sink.congestion)} congestion "
          f"readings, {len(recs)} recommendations, {len(notes)} notes, "
          f"{len(voice_files)} spoken alerts "
          f"-> {args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
