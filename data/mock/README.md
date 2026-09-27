# Mock fixtures

Stand-in data so the API, dashboard and retiming work can start before the pipeline exists.
Every file here must validate against `common/schemas.py`; `tests/test_mock_fixtures.py` checks that.

| Event | Camera | Snapshot | Recommendation |
|---|---|---|---|
| `evt_mock_001` double parked | 8th Ave @ 33rd St | `snapshots/double_parked.jpg` | upstream cut, sim done |
| `evt_mock_002` stopped in lane | 7 Ave @ 34 St | `snapshots/stopped_in_lane.jpg` | upstream cut; the recommended plan is slower, so the card says so |
| `evt_mock_003` blocked box | 7 Ave @ 34 St | `snapshots/blocked_box.jpg` | cross-street cut, sim done |

`congestion.json` has one congestion reading per camera approach for the dashboard's heatmap:
7 Ave @ 32 St, 6 Ave @ 30 St and 8th Ave @ 33rd St (behind `evt_mock_001`) congested,
7 Ave @ 34 St and 6 Ave @ 34 St slow, 8th Ave @ 31st St free. The approach names and directions are real (from the lane masks);
the levels and numbers are made up.

What's real and what's made up:

- **Real:**
  - camera IDs, which were live on nyctmc.org on 2026-09-26
  - snapshots, which are real frames from those cameras
  - boxes, which are drawn on the actual vehicle in each frame
- **Made up:**
  - whether each vehicle was actually stopped. Each snapshot is a single frame, so it can't show that. These vehicles were most likely just driving through. **Don't use these as demo incidents or as ground truth for metrics.** Real examples come from hand-tagging recorded frame sequences (issue #16).
  - event types, durations and confidences
  - all sim numbers
  - the signal IDs (`tls_8av_32st`, etc.): placeholders until `signals/camera_signals.json` maps cameras to real SUMO traffic-light IDs

Snapshots are raw frames. The dashboard draws `bbox` on top of them.
