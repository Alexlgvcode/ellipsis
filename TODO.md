# Lane Watch — Hackathon TODO

**Team:** **Alex** (detection → events → API) · **Brian** (cameras → simulation → dashboard)
Background: [docs/plan.md](docs/plan.md)

## Git workflow

- One branch per feature: `feat/<name>` off `main`. Keep branches small and merge back fast.
- Open a PR when the "Done when" line is true. The other person skims it, then merge.
- Pull `main` into your branch often (`git pull origin main`) so the two chains don't drift.
- `common/schemas.py` is the contract between us. Change it only in its own small PR, and tell the other person first.

**Priority:** **P0** = needed for the demo · **P1** = makes the demo convincing · **P2** = bonus, only once the P0 chain works end to end.

## Overview

| Branch | Owner | Pri | Depends on |
|---|---|---|---|
| `feat/camera-list` | Brian | P0 | — |
| `feat/frame-poller` | Brian | P0 | camera-list |
| `feat/mock-fixtures` | Alex | P0 | — |
| `feat/detector` | Alex | P0 | a few frames |
| `feat/tracker` | Alex | P0 | detector |
| `feat/lane-masks` | Alex | P0 | recorded frames |
| `feat/event-engine` | Alex | P0 | tracker, lane-masks |
| `feat/replay` | Alex | P0 | event-engine |
| `feat/api` | Alex | P0 | mock-fixtures |
| `feat/sumo-network` | Brian | P0 | camera-list |
| `feat/sim-scenario` | Brian | P0 | sumo-network |
| `feat/signal-retiming` | Brian | P0 | sim-scenario, mock-fixtures |
| `feat/dashboard` | Brian | P0 | api (can start on mocks) |
| `feat/eval-metrics` | Alex | P1 | replay |
| `feat/operator-feedback` | Brian + Alex | P1 | api, dashboard |
| `feat/sim-side-by-side` | Brian | P1 | sim-scenario, dashboard |
| `feat/live-mode` | Brian | P2 | frame-poller, replay |
| `feat/llm-summary` | Alex | P2 | api |

**Suggested order**
- Brian: camera-list → frame-poller (start recording!) → sumo-network → sim-scenario → signal-retiming → dashboard
- Alex: mock-fixtures → detector → tracker → lane-masks → event-engine → replay → api

Both chains meet in `feat/dashboard`. The checkpoint that matters: **one recorded incident goes in, and the dashboard shows the alert, the recommendation and the sim result.** Nothing at P1 or P2 until that works.

## Hand-off points (agree on these first, then don't change them)

1. **Frames on disk** (Brian → Alex): `data/frames/<camera_id>/<YYYYMMDD>/<HHMMSS>.jpg`
2. **Event JSON** (Alex → Brian), from `common/schemas.py`. Mock copies go in `data/mock/`.
3. **Recommendation JSON** (Brian → API), from `common/schemas.py`.

## Scope cuts (we're starting the event with no prep done)

- **No fine-tuning.** Use pretrained YOLO11s on COCO classes (car, truck, bus). Vans show up as car or truck.
- **3–5 cameras get lane masks.** The poller still records ~10.
- **No 311 or parking-ticket matching, and no 511NY.** The test set is ~20 events we tag by hand from today's recordings.
- **Small SUMO area** (6–10 intersections). Demand comes from `randomTrips.py`, roughly scaled.
- **Two retiming rules:** a lane blocked mid-block, and a blocked box.
- **Streamlit dashboard** that polls the API. No websockets and no Next.js.
- **Replay is the demo; live cameras are a bonus.**

> ⚠️ **Record in daylight today.** We have no footage yet, and night frames detect poorly. Get `feat/frame-poller` recording first, even with a quick script, so we have hours of daytime Midtown traffic to find incidents in.

---

## Brian

### `feat/camera-list` · P0
Files: `ingest/camera_list.py`, `data/cameras.json`
- [ ] Fetch `https://webcams.nyctmc.org/api/cameras/` and filter to the area box in `common/config.py`
- [ ] Write `data/cameras.json` (id, name, lat, lon, image_url, is_online)
- [ ] Pick ~10 cameras around Penn / Herald Sq with fixed views of lanes (no PTZ). Store them by name, not ID
- [ ] Resolve names to current IDs at startup (by name, then nearest coordinates)

**Done when:** `python -m ingest.camera_list` writes the file and prints the ~10 chosen cameras with their current IDs.

### `feat/frame-poller` · P0
Files: `ingest/poller.py`, `ingest/health.py`, `scripts/record_frames.py`
- [ ] **First, start a quick recorder** (a simple loop is fine): chosen cameras, every 5 s, saved to the agreed path
- [ ] Async poller with httpx: 2–5 s interval with jitter, a concurrency limit, a polite User-Agent
- [ ] Drop duplicate frames (hash)
- [ ] `health.py`: flag frozen feeds (near-identical frames for 30 s) and error images
- [ ] `record_frames.py` reuses the poller at 5 s

**Done when:** frames from all chosen cameras keep landing on disk, with no duplicates and no error images.

### `feat/sumo-network` · P0
Files: `sim/network/`, `sim/routes/`
- [ ] Export OSM for the 6–10 intersections around the masked cameras
- [ ] `netconvert` with traffic lights kept and a 90 s cycle. Write the exact commands in `sim/network/README.md`
- [ ] Generate routes with `randomTrips.py`, scaled roughly to Midtown volumes
- [ ] A `.sumocfg` that runs 15 simulated minutes headless in seconds

**Done when:** `sumo -c sim/network/midtown.sumocfg` runs cleanly and the traffic lights cycle.

### `feat/sim-scenario` · P0
Files: `sim/run_scenario.py`
- [ ] Take an event (lane, position, start time, duration) and inject a stopped vehicle with TraCI `vehicle.setStop`
- [ ] Run A (default plan) and B (modified plan) as parallel processes with the same seed
- [ ] Output avg delay per vehicle, max queue on the blocked approach, throughput, queue clear time → `SimResult`
- [ ] Support 3 seeds and average them

**Done when:** a CLI call prints A-vs-B metrics for a hard-coded blockage.

### `feat/signal-retiming` · P0
Files: `signals/mapping.py`, `signals/camera_signals.json`, `signals/retime.py`
- [ ] For each masked camera, map to the TLS it watches plus the upstream and downstream ones
- [ ] Rule 1: a lane blocked mid-block cuts upstream green on the blocked approach by 10–20%
- [ ] Rule 2: a blocked box shortens cross-street green
- [ ] Bounds: keep ped minimums, don't change the cycle length, ≤20% change per phase
- [ ] Event → `Recommendation` → sim-scenario → `POST /recommendations` with the sim numbers filled in

**Done when:** a mock event produces a Recommendation with real sim numbers.

### `feat/dashboard` · P0
Files: `dashboard/` (Streamlit)
- [ ] Map of camera pins; highlight cameras with active alerts
- [ ] Alert feed: snapshot with boxes, event type, duration, confidence
- [ ] Recommendation card: signal changes and delay/queue, default vs recommended
- [ ] Build on `data/mock/` first, then switch to the API; poll every 2–3 s

**Done when:** replaying an incident makes an alert and its recommendation appear without reloading the page.

### `feat/sim-side-by-side` · P1
- [ ] Default vs recommended view: sumo-gui screenshots at matching sim times, or queue-over-time charts
- [ ] Show the "delay saved" number on the recommendation card

### `feat/live-mode` · P2
- [ ] Feed live frames from the poller into the pipeline (2 s interval) for the masked cameras
- [ ] Skip any camera that's offline or frozen, so the dashboard doesn't break

---

## Alex

### `feat/mock-fixtures` · P0 (do this first so Brian isn't blocked)
Files: `data/mock/events.json`, `data/mock/recommendations.json`
- [ ] 3 Events (double parked, stopped in lane, blocked box) that pass `common/schemas.py` validation
- [ ] 1–2 Recommendations with sim numbers filled in

**Done when:** it's merged to `main` and Brian can build against it.

### `feat/detector` · P0
Files: `vision/detect.py`
- [ ] Load pretrained YOLO11s; keep car, truck, bus; conf ~0.35; upscale input to 640
- [ ] Batch frames across cameras; return boxes, class and confidence
- [ ] Check it on a sample of recorded frames. Note what it misses at 352x240

**Done when:** it runs on a folder of frames and saves annotated images that look right.

### `feat/tracker` · P0
Files: `vision/track.py`
- [ ] One ByteTrack instance per camera, set for low fps (frames 2–5 s apart)
- [ ] Stationary test: center shift < 5% of box width and IoU > 0.7 vs the previous frame
- [ ] Per-track history: first seen, stationary since, class, last box

**Done when:** a parked vehicle keeps the same ID and its stationary timer keeps climbing across a recorded sequence.

### `feat/lane-masks` · P0
Files: `events/masks/<camera-id>.json`
- [ ] Choose the 3–5 best cameras from the recorded footage
- [ ] Draw polygons for curb, curb-adjacent, travel, box, bus stop and ignore zones (a small labeling tool, or Roboflow)
- [ ] Save a reference frame for each camera, so we can tell when the view shifts

**Done when:** an overlay of each mask on its camera frame lines up with the lanes.

### `feat/event-engine` · P0
Files: `events/engine.py`, `events/rules.yaml`
- [ ] Work out which zone each track is in (box center inside a polygon)
- [ ] Rules: double parked 60 s, stopped in lane 120 s, blocked box 20 s, frozen feed 30 s
- [ ] Alert only on the front vehicle of a queue; ignore buses at stops and short red-light waits
- [ ] Close an event after 3 lost frames and log its duration; compute a confidence score

**Done when:** it fires the right event type on at least one recorded incident of each type.

### `feat/replay` · P0
Files: `scripts/replay.py`
- [ ] Recorded frames for a camera and time window → detect → track → event engine
- [ ] Save a snapshot with boxes drawn (boxes only, no plates or faces)
- [ ] Push events to the API; add a speed-up option for demos

**Done when:** replaying a recorded incident pushes an event to the API at the right point in the replay.

### `feat/api` · P0
Files: `api/main.py`, `api/models.py`
- [ ] SQLite tables for cameras, events and recommendations
- [ ] Endpoints:
  - `POST /events`, `GET /events`, `GET /events/{id}`
  - `GET /cameras`
  - `POST /recommendations`, `GET /recommendations/{event_id}`
  - serve snapshot images
- [ ] Mock mode that serves `data/mock/` while the pipeline isn't ready yet

**Done when:** Brian's dashboard and retiming code can read and write through it.

### `feat/eval-metrics` · P1
- [ ] Hand-tag ~20 stopped-vehicle events from today's recordings (start, end, type)
- [ ] Tune `rules.yaml` against them
- [ ] Report precision (target ≥80%), recall (≥70%), median time to alert (<90 s)
- [ ] Pick 3 daytime demo incidents and note each one's real duration for the pitch hook

### `feat/operator-feedback` · P1 (shared)
- [ ] **Alex:** `POST /events/{id}/feedback` (accept / reject / false positive)
- [ ] **Brian:** buttons on the alert card

### `feat/llm-summary` · P2
Files: `api/summarize.py`
- [ ] Generate a one-paragraph Claude incident note per alert; store it with the event and show it on the card

---

## Demo and submission (both of us, no branch)

- [ ] Feature freeze once the demo path is solid; after that, only fix bugs on the demo path
- [ ] **Brian:** record a backup demo video on replay
- [ ] **Alex:** slides on the problem, how it works, and metrics
- [ ] **Brian:** slides on the sim results and the signal-plan assumption (real NYC plans aren't public)
- [ ] Rehearse the 3-minute script twice: hook → replay → decision → sim payoff → proof and close
- [ ] Submit
