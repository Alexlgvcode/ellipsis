# Evaluation

How well does the event engine catch real blockages? Targets from the plan: precision
≥ 80%, recall ≥ 70%, median time to alert < 90 s.

```bash
python scripts/evaluate.py                          # masks + events/rules.yaml
python scripts/evaluate.py --rules my_rules.yaml    # try other thresholds (takes seconds)
python scripts/evaluate.py --exclude bus_lane police camera_moved
```

| File | What |
|---|---|
| `ground_truth.yaml` | Reviewed windows, real `blockages`, and rejected alerts (`not_blockages`) with the reason |
| `metrics.py` | Matching (same camera, overlapping in time, box IoU ≥ 0.3) and the scores |
| `detections/` | Cached YOLO detections per window (+ frozen flag + view similarity), so the evaluation runs without frames or the model |

**Reading the report.** Every alert is a true positive, a duplicate (second alert on
one incident), a known false alert, or **unreviewed**: it matches nothing in the
ground truth. Unreviewed alerts count as false and are listed. After a rule or mask
change, judge them and add each one to `ground_truth.yaml`.

**Verdict rule:** does the vehicle **block traffic**? Parked out of the flow, even
illegally, is not a blockage. Debatable groups get a `category` (`bus_lane`,
`police`, `camera_moved`), so results can be shown with and without them.

**Demo incidents.** `demo: true` marks the blockages the demo replays (picked in #16; script and
timings in [docs/demo.md](../docs/demo.md)):

| Id | Camera | Type | Real duration |
|---|---|---|---|
| `gt_001` | 7 Ave @ 36 St | double parked (near box truck) | 521 s |
| `gt_002` | 7 Ave @ 36 St | double parked (far delivery truck) | 565 s |
| `gt_009` | 8th Ave @ 31st St | stopped in lane (cab) | 82 s |

Durations come from Brian's longer recording; this window clips the trucks. No real blocked
box has been recorded yet. `tests/test_demo_incidents.py` fails if a rule or engine change
stops any of them alerting as the right type within 90 s.

**Adding footage.**
1. Record it with `scripts/record_frames.py`.
2. Add a `windows` entry per camera to `ground_truth.yaml`.
3. Run `python scripts/evaluate.py --refresh-cache` (needs `.[vision]`) to cache its detections.
4. Judge the unreviewed alerts it lists, and look for blockages it missed.

Recall is only as good as that last step: a blockage nobody tagged can't be counted as missed.

**Congestion** (issue #47) is scored after the blockages, on `congestion_windows`: footage
reviewed for congestion, where the camera is free except during its `congestion` intervals
(`slow`, or `congested`: a jam, the queue doesn't clear on green). The report gives
precision / recall of the monitor's runs at each level, time to detect, and how often the
level agrees with the tags, frame by frame.

To tag new footage: `python scripts/evaluate.py --congestion-review` writes, for every cached
window not reviewed yet, a sheet with one frame a minute labelled with the monitor's level,
and `runs/eval/congestion_review/congestion_review.yaml` with the windows and the monitor's
intervals pre-filled. Fix the intervals, then copy both into `ground_truth.yaml`.

After adding or changing a reference frame (`events/masks/<camera_id>.jpg`, or an extra one
like `<camera_id>.night.jpg`), `--refresh-view` updates the cached view similarity without YOLO.
