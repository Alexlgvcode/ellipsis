# Mock fixtures

What the API serves with `LW_MOCK_MODE=true`: the dashboard's data when no pipeline is
running, and the demo's fallback. **Built by `python scripts/build_mock.py`; don't edit by
hand.** Every file here must validate against `common/schemas.py` (`tests/test_mock_fixtures.py`).

## Incidents

Real, hand-checked blockages from `evaluation/ground_truth.yaml` (#16, #63), times UTC:

| Event | Tag | Camera | Type | Stopped | For | Confidence | Delay per vehicle, default → plan |
|---|---|---|---|---|---|---|---|
| `evt_b0cbb042_20260926182209_8` | `gt_002` | 7 Ave @ 36 St | double parked | 09-26 18:22:09 | 417 s | 0.88 | 124.4 → 119.4 s |
| `evt_b0cbb042_20260926182209_7` | `gt_001` | 7 Ave @ 36 St | double parked | 09-26 18:22:09 | 417 s | 0.79 | 124.4 → 119.4 s |
| `evt_ec9ffb62_20260926182256_10` | `gt_009` | 8th Ave @ 31st St | stopped in lane | 09-26 18:22:51 | 96 s | 0.52 | 65.0 → 65.1 s |
| `evt_83655dbc_20260926201217_8` | `gt_004` | Broadway @ 38 St | double parked | 09-26 20:12:17 | 90 s | 0.70 | 68.6 → 68.7 s |
| `evt_ec9ffb62_20260926202237_162` | `gt_006` | 8th Ave @ 31st St | stopped in lane | 09-26 20:22:37 | 332 s | 0.68 | 78.2 → 80.1 s |
| `evt_ec9ffb62_20260926202451_193` | `gt_010` | 8th Ave @ 31st St | stopped in lane | 09-26 20:24:51 | 89 s | 0.77 | 64.5 → 63.9 s |
| `evt_f06979b2_20260926202809_329` | `gt_007` | 6 Ave @ 34 St | double parked | 09-26 20:28:09 | 243 s | 0.64 | 154.0 → 116.6 s |
| `evt_83655dbc_20260926202844_gt008` | `gt_008` | Broadway @ 38 St | double parked | 09-26 20:28:44 | 147 s | 0.50 (missed) | 70.5 → 70.4 s |
| `evt_8ee72946_20260926224657_69` | `gt_011` | Broadway @ 6 Ave / 33 St | blocked box | 09-26 22:46:57 | 52 s | 0.74 | 108.1 → 106.9 s |
| `evt_8ee72946_20260926225126_106` | `gt_012` | Broadway @ 6 Ave / 33 St | blocked box | 09-26 22:51:26 | 35 s | 0.69 | 108.3 → 106.8 s |
| `evt_8ee72946_20260926230332_188` | `gt_013` | Broadway @ 6 Ave / 33 St | blocked box | 09-26 23:03:32 | 32 s | 0.80 | 108.2 → 107.0 s |
| `evt_8ee72946_20260926230410_183` | `gt_014` | Broadway @ 6 Ave / 33 St | blocked box | 09-26 23:04:10 | 35 s | 0.73 | 108.3 → 106.8 s |
| `evt_6a85384f_20260927011845_42` | `gt_015` | 8th Ave @ 33rd St | double parked | 09-27 01:18:45 | 680 s | 0.80 | 73.9 → 68.3 s |

- **Real:** the incidents, cameras, times, durations and boxes (the pipeline's own event on the
  cached detections), the snapshots (the recorded frame when the alert fired), and the
  simulation numbers (SUMO, the worker's scoring over the whole stop, capped at 5 min).
- **Not from the pipeline:** an incident marked *missed* wasn't alerted on by the engine; its
  event is built from the tag with confidence 0.5.
- Left out: `gt_003` (police stop) and `gt_005` (bus lane), which are debatable as blockages.
- Incident notes (`summaries.json`): 7 of 13, written once by
  gemini-3.7-flash from each incident's facts
  (`facts`, the same prompt the worker sends), so they load without calling the model.
- Operator decisions start empty.

## Congestion

`congestion.json` has one reading per masked camera for the heatmap: 6 Ave @ 30 St congested, 7 Ave @ 32 St slow, 7 Ave @ 36 St slow, 8th Ave @ 31st St slow, 7 Ave @ 34 St slow, 6 Ave @ 34 St slow;
the rest free. Levels are #47's congestion tags (the night ones are a first pass); occupancy
and stuck share are the monitor's own, and the score is at least 0.45
(slow) / 0.75 (congested) so the heatmap shows the tagged level.
