"""Build data/mock/ (the API's mock mode, the demo fallback) from real incidents (issue #63).

    python scripts/build_mock.py              # needs data/frames/ (snapshots) and SUMO (.[sim])
    python scripts/build_mock.py --no-sim     # recommendations without simulation numbers
    python scripts/build_mock.py --rescore    # run SUMO again even for unchanged incidents
    python scripts/build_mock.py --check      # fail if events.json / congestion.json are stale

Every mock incident is a hand-checked blockage from evaluation/ground_truth.yaml (MOCK_IDS):
the event is what the pipeline raised for it on the cached detections (evaluation/detections/:
its id, box, lane zone and confidence), with the tagged start and end; the snapshot is the
recorded frame from when the alert fired; the recommendation is the worker's SUMO scoring
(signals.retime.recommend) over the whole stop, capped like the worker at 5 min. Congestion
is one reading per masked camera: the tagged level where #47's tags have one, else free, with
the congestion monitor's own occupancy and stuck share over that stretch.

Nothing in data/mock/ is edited by hand: the README's incident table is written here too.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.config import get_settings  # noqa: E402
from common.schemas import (  # noqa: E402
    Congestion,
    CongestionLevel,
    Event,
    EventType,
    Recommendation,
    VehicleClass,
)
from evaluation.metrics import GroundTruth, Truth, evaluate, load_ground_truth  # noqa: E402
from events.masks import load_masks  # noqa: E402
from events.pipeline import CameraPipeline  # noqa: E402
from events.rules import load_rules  # noqa: E402
from scripts.evaluate import cache_path, run_window  # noqa: E402
from vision.detect import Detection  # noqa: E402

MOCK_DIR = REPO_ROOT / "data" / "mock"

# The demo incidents first (docs/demo.md), then the rest by time. Left out: gt_003 (police
# stop) and gt_005 (bus lane), which are debatable as blockages.
MOCK_IDS = ("gt_002", "gt_001", "gt_009", "gt_004", "gt_006", "gt_010", "gt_007", "gt_008",
            "gt_011", "gt_012", "gt_013", "gt_014", "gt_015")

# a tagged blockage the engine never alerted on: its event gets this confidence ("needs review")
MISSED_CONFIDENCE = 0.5
# congestion score floor per tagged level, so the heatmap shows what the tag says even where
# the monitor, at night, barely sees the queue
LEVEL_SCORE = {CongestionLevel.SLOW: 0.45, CongestionLevel.CONGESTED: 0.75}
LEVEL_RANK = [CongestionLevel.FREE, CongestionLevel.SLOW, CongestionLevel.CONGESTED]
DWELL_KEY = {"double_parked": "double_parked", "stopped_in_lane": "stopped_in_lane",
             "blocked_box": "blocked_box"}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _caches(gt: GroundTruth, congestion: bool = False) -> list[dict]:
    windows = gt.congestion_windows if congestion else gt.windows
    out = []
    for w in windows:
        path = cache_path(w)
        if not path.exists():
            raise SystemExit(f"no cached detections for {w.camera[:8]} {w.start:%H:%M}: run "
                             "scripts/evaluate.py --refresh-cache first")
        out.append(json.loads(gzip.decompress(path.read_bytes())))
    return out


def build_events(gt: GroundTruth) -> list[tuple[Event, datetime, Truth, bool]]:
    """(event, alert time, its ground truth, whether the engine caught it) per mock incident."""
    rules = load_rules()
    preds = [p for cache in _caches(gt) for p in run_window(cache, rules)]
    caught = {m.truth.id: m.prediction for m in evaluate(preds, gt).matches
              if m.outcome == "true_positive"}
    truths = {t.id: t for t in gt.blockages}
    masks = load_masks()
    out = []
    for tid in MOCK_IDS:
        t = truths[tid]
        p = caught.get(tid)
        start = min(t.start, p.event.start_ts) if p else t.start
        if p:
            base = p.event
            alert = p.alert_ts
        else:  # missed by the engine: built from the tag
            dwell = rules["dwell_s"][DWELL_KEY[t.type]]
            base = Event(id=f"evt_{t.camera[:8]}_{start:%Y%m%d%H%M%S}_{tid.replace('_', '')}",
                         camera_id=t.camera, type=EventType(t.type), start_ts=start, duration_s=0,
                         bbox=list(t.bbox), lane_zone=masks[t.camera].lane_zone(t.bbox),
                         confidence=MISSED_CONFIDENCE)
            alert = start + timedelta(seconds=dwell)
        event = base.model_copy(update={
            "type": EventType(t.type), "start_ts": start,
            "duration_s": (t.end - start).total_seconds(),
            "bbox": [round(v, 1) for v in base.bbox],
            "snapshot_path": f"data/mock/snapshots/{base.id}.jpg"})
        out.append((event, alert, t, p is not None))
    return out


def build_congestion(gt: GroundTruth) -> list[Congestion]:
    """One reading per masked camera: its most severe congestion tag, else free."""
    rules = load_rules()
    masks = load_masks()
    readings: dict[str, list[Congestion]] = {}
    for cache in _caches(gt, congestion=True):
        pipe = CameraPipeline.for_camera(cache["camera"], rules)
        for row in cache["frames"]:
            ts = _ts(row["ts"])
            dets = [Detection(tuple(d[:4]), VehicleClass(d[4]), d[5]) for d in row["dets"]]
            pipe.step(ts, None, dets, frozen=row["frozen"], view=row.get("view"))
            readings.setdefault(cache["camera"], []).extend(
                r for r in pipe.congestion.readings if r.ts == ts)
    out = []
    for cam, mask in masks.items():
        tags = sorted((c for c in gt.congestion if c.camera == cam),
                      key=lambda c: (LEVEL_RANK.index(CongestionLevel(c.level)), c.end))
        seen = readings.get(cam, [])
        if tags:
            tag = tags[-1]
            level = CongestionLevel(tag.level)
            span = [r for r in seen if tag.start <= r.ts <= tag.end] or seen
            start, end = tag.start, tag.end
        else:
            level = CongestionLevel.FREE
            span = seen[-36:]  # the last 3 minutes it was watched
            start = span[0].ts if span else datetime.fromisoformat("2026-09-26T20:12:16+00:00")
            end = span[-1].ts if span else start
        score = 0.0 if level is CongestionLevel.FREE else \
            max(_mean(span, "score"), LEVEL_SCORE[level])
        approach = mask.approaches[0] if mask.approaches else None
        out.append(Congestion(
            camera_id=cam, approach=approach.name if approach else "road",
            direction=approach.direction if approach else None, ts=end, level=level,
            score=round(score, 3), occupancy=_mean(span, "occupancy"),
            stuck_share=_mean(span, "stuck_share"), since_ts=start))
    return out


def _mean(readings: list[Congestion], field: str) -> float:
    return round(statistics.fmean(getattr(r, field) for r in readings), 3) if readings else 0.0


def _frame_at(frames: list[Path], alert: datetime) -> Path:
    """The last recorded frame at or before the alert (frames are named HHMMSS, UTC)."""
    before = [p for p in frames if p.stem <= f"{alert:%H%M%S}"]
    return before[-1] if before else frames[0]


def write_snapshots(events: list[tuple[Event, datetime, Truth, bool]]) -> None:
    frames_dir = get_settings().frames_dir
    snaps = MOCK_DIR / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    keep = set()
    for event, alert, _, _ in events:
        day = frames_dir / event.camera_id / f"{alert:%Y%m%d}"
        frames = sorted(day.glob("*.jpg"))
        if not frames:
            raise SystemExit(f"no recorded frames in {day}: the snapshots need data/frames/")
        dest = snaps / f"{event.id}.jpg"
        shutil.copyfile(_frame_at(frames, alert), dest)
        keep.add(dest.name)
    for old in snaps.glob("*.jpg"):  # snapshots of incidents no longer in the set
        if old.name not in keep:
            old.unlink()


def build_recommendations(events: list[Event], simulate: bool,
                          rescore: bool) -> list[Recommendation]:
    from signals.mapping import load_mapping
    from signals.retime import recommend

    mapping = load_mapping()
    path = MOCK_DIR / "recommendations.json"
    old = {r["event_id"]: r for r in json.loads(path.read_text())} if path.exists() else {}
    stops = {e.id: e.duration_s for e in _read_json(MOCK_DIR / "events.json", [])} \
        if (MOCK_DIR / "events.json").exists() else {}
    out = []
    for n, event in enumerate(events, 1):
        prev = old.get(event.id)
        unchanged = prev and prev.get("sim") and stops.get(event.id) == event.duration_s
        if simulate and unchanged and not rescore:
            out.append(Recommendation(**prev))
            print(f"  [{n}/{len(events)}] {event.id}: kept (unchanged)")
            continue
        how = "SUMO" if simulate else "rules only"
        print(f"  [{n}/{len(events)}] {event.id}: {how}...", flush=True)
        out.append(recommend(event, mapping, simulate=simulate))
    return out


def _read_json(path: Path, default):
    return [Event(**e) for e in json.loads(path.read_text())] if path.exists() else default


def _dump(models) -> str:
    return json.dumps([m.model_dump(mode="json") for m in models], indent=2) + "\n"


def write_readme(events: list[tuple[Event, datetime, Truth, bool]], congestion: list[Congestion],
                 recs: dict[str, Recommendation]) -> None:
    names = {c["id"]: c["name"] for c in json.loads(get_settings().cameras_path.read_text())}
    rows = []
    for e, _alert, t, found in events:
        rec = recs.get(e.id)
        sim = f"{rec.sim.delay_default:.1f} → {rec.sim.delay_new:.1f} s" \
            if rec and rec.sim else "none"
        conf = f"{e.confidence:.2f}" + ("" if found else " (missed)")
        rows.append(f"| `{e.id}` | `{t.id}` | {names.get(e.camera_id, e.camera_id[:8])} | "
                    f"{e.type.value.replace('_', ' ')} | {e.start_ts:%m-%d %H:%M:%S} | "
                    f"{e.duration_s:.0f} s | {conf} | {sim} |")
    cong = [f"{names.get(c.camera_id, c.camera_id[:8])} {c.level.value}" for c in congestion
            if c.level is not CongestionLevel.FREE]
    text = f"""# Mock fixtures

What the API serves with `LW_MOCK_MODE=true`: the dashboard's data when no pipeline is
running, and the demo's fallback. **Built by `python scripts/build_mock.py`; don't edit by
hand.** Every file here must validate against `common/schemas.py` (`tests/test_mock_fixtures.py`).

## Incidents

Real, hand-checked blockages from `evaluation/ground_truth.yaml` (#16, #63), times UTC:

| Event | Tag | Camera | Type | Stopped | For | Confidence | Delay per vehicle, default → plan |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

- **Real:** the incidents, cameras, times, durations and boxes (the pipeline's own event on the
  cached detections), the snapshots (the recorded frame when the alert fired), and the
  simulation numbers (SUMO, the worker's scoring over the whole stop, capped at 5 min).
- **Not from the pipeline:** an incident marked *missed* wasn't alerted on by the engine; its
  event is built from the tag with confidence {MISSED_CONFIDENCE}.
- Left out: `gt_003` (police stop) and `gt_005` (bus lane), which are debatable as blockages.
- Decisions and incident notes start empty: they come from the operator and the worker.

## Congestion

`congestion.json` has one reading per masked camera for the heatmap: {", ".join(cong) or "none"};
the rest free. Levels are #47's congestion tags (the night ones are a first pass); occupancy
and stuck share are the monitor's own, and the score is at least {LEVEL_SCORE[CongestionLevel.SLOW]}
(slow) / {LEVEL_SCORE[CongestionLevel.CONGESTED]} (congested) so the heatmap shows the tagged level.
"""
    (MOCK_DIR / "README.md").write_text(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-sim", action="store_true", help="recommendations without SUMO")
    ap.add_argument("--rescore", action="store_true", help="run SUMO for every incident again")
    ap.add_argument("--check", action="store_true",
                    help="only check that events.json and congestion.json are up to date")
    args = ap.parse_args(argv)

    gt = load_ground_truth()
    events = build_events(gt)
    congestion = build_congestion(gt)
    new_events, new_congestion = _dump(e for e, *_ in events), _dump(congestion)
    if args.check:
        built = (("events.json", new_events), ("congestion.json", new_congestion))
        stale = [name for name, text in built
                 if not (MOCK_DIR / name).exists() or (MOCK_DIR / name).read_text() != text]
        if stale:
            print(f"data/mock/ is stale ({', '.join(stale)}): run python scripts/build_mock.py")
            return 1
        print("data/mock/ is up to date")
        return 0

    busy = sum(c.level is not CongestionLevel.FREE for c in congestion)
    print(f"{len(events)} incidents, {busy} congested / slow cameras")
    write_snapshots(events)
    recs = build_recommendations([e for e, *_ in events], simulate=not args.no_sim,
                                 rescore=args.rescore)
    (MOCK_DIR / "events.json").write_text(new_events)
    (MOCK_DIR / "recommendations.json").write_text(_dump(recs))
    (MOCK_DIR / "congestion.json").write_text(new_congestion)
    write_readme(events, congestion, {r.event_id: r for r in recs})
    print(f"wrote {MOCK_DIR.relative_to(REPO_ROOT)}/: events, snapshots, recommendations, "
          "congestion, README")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
