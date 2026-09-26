# NYC Lane Watch: Hackathon Project Plan

Sep 25, 2026 · @Alexandre Lugovoi

## Overview

Lane Watch watches NYC DOT's public traffic cameras, detects vehicles stopped where they block traffic (double parked, stopped in a travel lane, or sitting in the intersection box), and proposes a signal timing fix that a simulation shows clears the jam faster. Crashes are out of scope.

**Problem.** NYC DOT's Traffic Management Center (TMC) has hundreds of cameras but a limited number of operators. A double-parked van or a delivery truck stopped in a travel lane can block traffic for minutes before anyone notices, and fixed time-of-day signal plans keep sending traffic into the blockage.

**Pitch.** An AI co-pilot for TMC operators: it spots blockages automatically, explains what it saw, and recommends a retiming for the nearby signals, with a human approving every change.

**What the demo proves.** Real camera frame in, detected blockage with an explanation, recommended timing change, and a side-by-side simulation showing lower delay than the default plan.

## Goals, scope and non-goals

Scope is 10 to 20 intersections in one Midtown area, near Penn Station or Times Square, where cameras are dense and double parking is constant.

**Goals**

- Detect three kinds of stopped vehicle from live camera stills: double parked, stopped in a travel lane (breakdown, loading, pickup or drop-off), and stopped inside the intersection box.
- Raise an alert within 60 to 120 seconds of a vehicle stopping, with the frame, location, duration and reason.
- Recommend a signal timing change for affected intersections, approved by a human operator.
- Show in SUMO that the recommendation lowers average delay versus the default fixed plan.

**Non-goals**

- Detecting crashes or collisions. We only detect vehicles that stop and stay stopped.
- Controlling real traffic signals. Everything signal-related runs in simulation.
- Citywide coverage, license plate reading, or identifying people.
- Training a detector from scratch. We fine-tune a pretrained one.

## Requirements

The system must work on low resolution stills (about 352x240, one new frame every 2 seconds) and must degrade gracefully when a camera goes offline.

**Functional**

| ID | Requirement | Priority |
| --- | --- | --- |
| F1 | Poll 10 to 20 cameras every 2 to 5 s and store frames with timestamps | Must |
| F2 | Detect cars, trucks, buses and vans in each frame | Must |
| F3 | Track vehicles across frames and measure how long each is stationary | Must |
| F4 | Per camera lane masks: curb lane, travel lanes, intersection box | Must |
| F5 | Classify stopped vehicles as legally parked, double parked, stopped in a travel lane, or blocking the box | Must |
| F6 | Emit an alert with snapshot, camera, event type, duration and confidence | Must |
| F7 | Operator dashboard: map, live alert feed, frame with boxes drawn | Must |
| F8 | Map each camera to its nearby signalized intersections | Must |
| F9 | Generate a timing recommendation for affected signals | Should |
| F10 | Run SUMO default vs recommended plan and report delay and queue length | Should |
| F11 | Operator can accept, reject or mark an alert as a false positive | Should |
| F12 | LLM written plain language incident summary for each alert | Could |
| F13 | Replay mode that runs the pipeline on recorded frames | Must |

**Non-functional**

- **Latency:** alert within 90 s of a blockage starting (30 to 60 s of it is the dwell threshold).
- **Throughput:** 20 cameras at one frame every 2 s on one laptop GPU or a single cloud GPU.
- **Accuracy target:** precision of 80% or more on double parking alerts on our labeled test set. False alarms cost operator trust.
- **Resilience:** detect frozen or offline feeds (identical frames, error images) and skip them.
- **Privacy:** no plates, no faces stored; keep only boxes and event snapshots.
- **Etiquette:** poll the public endpoint politely and cache frames locally.

## System architecture

The system is a five stage vision pipeline feeding an event engine, with retiming and simulation running on each alert and everything surfaced through one dashboard.

&#91;embedded content: Lane Watch pipeline · 9 components\]

Every alert reaches the dashboard directly; the retiming path adds a recommended plan and its simulated effect a few seconds later.

| Component | Job | Runs as |
| --- | --- | --- |
| Frame poller | Fetches each camera still every 2 to 5 s, drops duplicates and error images, writes to disk | Python async worker |
| Detector | Finds vehicles in each frame, returns boxes and classes | YOLO on GPU, batched |
| Tracker | Links boxes across frames into vehicle IDs, keeps position history | ByteTrack in the same worker |
| Event engine | Applies lane masks and dwell rules, emits typed events | Python module, per camera state |
| Backend API | Stores cameras, events, recommendations; serves REST and a websocket feed | FastAPI + Postgres (or SQLite) |
| Retiming engine | Turns an event into a candidate timing change for nearby signals | Python, rule based |
| SUMO simulation | Runs default and candidate plans on the Midtown network, returns delay and queue metrics | SUMO via TraCI |
| Dashboard | Map, alert feed, annotated frames, accept or reject, sim results | Next.js or Streamlit |
| Summarizer (optional) | Writes a one paragraph incident note per alert | Claude API call |

The offline side (camera list scraping, frame recording, labeling, fine-tuning, building the SUMO network) happens before the hackathon and is covered in the data plan.

## Data plan

We need three kinds of data: live frames for the demo, a few hundred labeled frames to fine-tune the detector, and real blockage examples to test the event rules.

**1. Camera frames (live and recorded)**

- Source: NYC DOT's public camera list at nyctmc.org/cameras-list. Each camera has an image endpoint of the form `nyctmc.org/api/cameras/<camera-id>/image`. It is public but undocumented, and camera IDs can change.
- At project start, scrape the camera list (ID, name, lat/long) into `cameras.json`. Never hardcode IDs.
- Backup: register for a free 511NY developer API key, which includes camera listings. Do this early since approval can take time.
- Start recording now: 10 to 20 cameras, one frame every 5 s, day and night, for at least 5 days. At 20 cameras that is about 1.7 million frames, roughly 20 to 30 GB at 10 to 20 KB per frame.

**2. Detector training data**

1. Sample about 500 frames across cameras, times of day and weather, weighted toward busy periods.
2. Auto-label with pretrained YOLO (COCO classes car, truck, bus) or Grounding DINO for van and delivery truck.
3. Correct labels by hand in Roboflow or CVAT. Split 400 train, 100 test, split by time so test frames are not near-duplicates of train frames.
4. Optional extra data: CityCam (CMU, built from NYC DOT webcams) and UA-DETRAC for general traffic camera views.

**3. Stopped vehicle examples for rule testing**

| Source | What it gives | How we use it |
| --- | --- | --- |
| NYC 311 (NYC Open Data) | Double parking and blocked lane complaints with time and location | Find complaints within \~150 m of a camera, pull frames from that time window as weak positives |
| Parking Violations Issued (NYC Open Data) | Double parking tickets with street, time and violation code | Match tickets on streets our cameras cover to find confirmed double parking windows |
| Our own recordings | Midtown double parking and loading stops happen many times a day | Hand-tag 50 to 100 stopped vehicle events with start and end time |

**4. Simulation data**

- Road network: export the Midtown area from OpenStreetMap and convert with SUMO's `netconvert`.
- Demand: NYC DOT Automated Traffic Volume Counts and real time traffic speed data (NYC Open Data) to calibrate vehicle volumes per street.
- Signal timing: real NYC plans are not public. Use SUMO's generated plans with a realistic Midtown cycle (around 90 s) and document the assumption.

## Detection and event logic

Detection is learned, classification is rules: a fine-tuned detector finds vehicles, and hand-drawn lane masks plus dwell time decide what each stopped vehicle means.

**Detector**

- Model: YOLOv8s or YOLO11s, pretrained on COCO, fine-tuned on our \~400 labeled frames at input size 640 (frames upscaled).
- Classes: car, truck, bus, van. Confidence threshold around 0.35, tuned on the test split.
- Target: mAP@0.5 above 0.6 on our test split; check the pretrained baseline first so we can show the gain.

**Tracker**

- ByteTrack with a low frame rate setting, since frames arrive every 2 to 5 s and vehicles jump between frames.
- Stationary test: a track is stationary if its box center moves less than \~5% of box width and box IoU with the previous frame stays above 0.7.
- Keep per-track history: first seen, stationary since, lane zone, class.

**Lane masks (per camera, drawn once)**

- Polygons for curb lane, travel lanes, intersection box, and ignore zones (sidewalk, far background).
- Drawn in a small labeling tool or Roboflow and saved as `masks/<camera-id>.json`.
- Start with 10 cameras that have a clear, stable view. Cameras that pan or zoom need their masks disabled when the view changes.

**Event rules**

| Event | Condition | Dwell threshold |
| --- | --- | --- |
| Legally parked | Stationary, box center in curb lane | Ignored |
| Double parked | Stationary in the travel lane next to the curb, other tracks in that lane moving around it | 60 s |
| Stopped in travel lane | Stationary in any other travel lane, and it is the front vehicle with no stopped vehicle ahead of it | 120 s (longer than one signal cycle) |
| Blocked box | Stationary inside the intersection mask | 20 s |
| Frozen feed | Consecutive frames nearly identical, or error image detected | 30 s |

- Confidence score per event from detector confidence, how many frames confirm it, and how cleanly the box sits in the zone.
- An event closes when the vehicle leaves or the track is lost for 3 frames. Duration gets logged.
- Rules are config values, so thresholds can be tuned during the event without code changes.

**Known hard cases**

- Buses at stops look like stopped vehicles. Add bus stop zones to masks and ignore buses there.
- Vehicles waiting at a red light look stationary. Ignore stops shorter than one signal cycle (\~90 s) unless the vehicle is in the curb-adjacent lane or inside the box.
- Cars queued behind a stopped vehicle are stationary too. Only the front vehicle is the event; the queue behind it is its impact, not separate alerts.
- Night and rain drop detection quality. Demo on daytime replays.

## Signal recommendation and SUMO simulation

Each alert produces a candidate timing change, and SUMO scores it against the default plan on the same blockage so the dashboard can show minutes of delay saved.

**Camera to signal mapping**

- Load NYC signalized intersections from the OSM network (nodes tagged as traffic signals).
- For each camera, store the intersection it looks at, plus the one upstream and one downstream on each approach. Precompute into `camera_signals.json`.

**Retiming rules (v1, rule based)**

| Event | Recommended change |
| --- | --- |
| Lane blocked mid-block (double parked or stopped vehicle) | Upstream signal: cut green on the blocked approach by 10 to 20% to stop feeding the queue. Downstream: hold normal timing. |
| Lane blocked near the stop line | Local signal: extend green on the blocked approach by 10 to 15 s so the remaining lanes discharge the queue. |
| Blocked box | Cross street: shorten green briefly; add a short all-red clearance if supported. |
| Queue spilling back past upstream intersection | Upstream: switch to a flush plan favoring the outbound direction. |

- Bounds on every change: minimum pedestrian walk plus clearance time kept, cycle length unchanged, max 20% change per phase. A human approves before anything is applied.
- Stretch: replace rules with a small search, where SUMO tries 5 to 10 candidate splits and the best one wins.

**Simulation setup**

1. Network: 10 to 20 intersection Midtown area from OSM via `netconvert`, with traffic lights kept.
2. Demand: route files generated with `randomTrips.py` or `routeSampler.py`, scaled to match NYC traffic volume counts for those streets.
3. Blockage: inject a stopped vehicle at the event location using TraCI (`vehicle.setStop` on the lane) at the event start time.
4. Runs: A = default plan with blockage, B = recommended plan with blockage, both same random seed, 15 simulated minutes, 3 seeds each.
5. Outputs: average delay per vehicle, max queue length on the blocked approach, total vehicles through the area, time for the queue to clear.

**Speed**

- A 15 minute run on 20 intersections should finish in seconds with the SUMO GUI off. Run A and B in parallel processes.
- For the demo, record SUMO GUI screenshots or use sumo-gui side by side, synced to the same simulated time.

## Tech stack and repo structure

Python end to end for the pipeline and simulation, with a thin web dashboard, so one GPU machine can run the whole demo.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11 | CV, SUMO and backend in one language |
| Detection | Ultralytics YOLO (v8 or 11) | Fast fine-tuning, good small models |
| Tracking | ByteTrack (built into Ultralytics) | Works with low frame rates |
| Labeling | Roboflow or CVAT | Auto-label assist, export in YOLO format |
| Simulation | SUMO + TraCI | Open source, imports OSM, scriptable |
| Backend | FastAPI + websockets | Push alerts live to the dashboard |
| Storage | Postgres (or SQLite for speed) + frames on disk | Simple; no need for object storage |
| Dashboard | Next.js + Mapbox or Leaflet (or Streamlit if short on people) | Map with live alert pins |
| Summaries | Claude API | Plain language incident notes |
| Compute | One laptop with a GPU, or a cloud GPU (e.g. a single A10 or L4) | 20 cameras at 0.5 fps is light |

**Repo layout**

```
lane-watch/
  ingest/        poller.py, camera_list.py, health.py
  vision/        detect.py, track.py, train.py, datasets/
  events/        engine.py, rules.yaml, masks/<camera-id>.json
  signals/       mapping.py, retime.py, camera_signals.json
  sim/           network/, routes/, run_scenario.py
  api/           main.py, models.py, ws.py
  dashboard/     web app
  data/          frames/, labels/, open_data/
  scripts/       record_frames.py, match_311.py, replay.py
```

**Interfaces to agree on first**

- Event JSON: `{id, camera_id, type, start_ts, duration_s, bbox, lane_zone, confidence, snapshot_path}`.
- Recommendation JSON: `{event_id, intersections: [{id, phase, change_s}], sim: {delay_default, delay_new, queue_default, queue_new}}`.
- Fix these on hour one so the four workstreams can build in parallel against mock data.

## Pre-hackathon prep checklist

Most of the risk lives in data and SUMO setup, so finish these before the event; check the hackathon's rules on what prep work is allowed and keep this to data and environment, not product code, if they require it.

**One to two weeks before**

- [ ] Pick the area (Penn Station or Times Square) and 10 to 20 cameras with clear, stable views of lanes
- [ ] Scrape the camera list into `cameras.json` and verify each image endpoint responds
- [ ] Register for a 511NY developer API key as backup
- [ ] Start the frame recorder on an always-on machine (every 5 s, all chosen cameras)

**One week before**

- [ ] Download 311 double parking complaints and Parking Violations Issued data for the area; write `match_311.py` to link complaints to cameras and timestamps
- [ ] Build the SUMO network from OSM and confirm it runs with traffic lights
- [ ] Label 400 to 500 frames and run a first fine-tune; record baseline vs fine-tuned mAP
- [ ] Hand-tag 50 to 100 stopped vehicle events in recorded frames for the rule test set

**Final days**

- [ ] Draw lane masks for the 10 best cameras
- [ ] Pick 3 demo incidents from recordings (one double parked van, one vehicle stopped in a travel lane, one blocked box) with clean daytime frames
- [ ] Set up the repo, environments, GPU access and a shared `.env`
- [ ] Agree on event and recommendation JSON formats

## Hackathon timeline and team roles

The plan assumes a 36 hour event and a team of four; the rule is an end to end demo on recorded frames by hour 18, then polish and live data.

**Roles**

| Role | Owns | Main deliverables |
| --- | --- | --- |
| Vision lead | Detector, tracker, frame poller | Detections and tracks streaming for all chosen cameras |
| Events lead | Lane masks, rules, event engine, evaluation | Typed events with precision and recall on the test set |
| Sim lead | SUMO network, retiming rules, scenario runner | Default vs recommended metrics per event |
| Product lead | Backend API, dashboard, summaries, pitch | Live dashboard and the 3 minute demo |

**Timeline**

| Hours | Milestone |
| --- | --- |
| 0 to 2 | Lock JSON formats, split work, everyone runs on mock data |
| 2 to 8 | Detector plus tracker on recorded frames; first rules; SUMO scenario with injected blockage; API skeleton and map |
| 8 to 14 | Event engine emitting real events; retiming rules wired to SUMO; dashboard shows alerts with snapshots |
| 14 to 18 | **End to end on replay:** recorded incident in, alert, recommendation, sim result on dashboard |
| 18 to 24 | Tune thresholds on test set, fix false positives, compute metrics; sleep in shifts |
| 24 to 30 | Live camera mode, LLM summaries, accept and reject flow, side by side sim view |
| 30 to 34 | Freeze features. Record a backup demo video. Build slides with metrics |
| 34 to 36 | Rehearse the pitch twice, submit |

## Demo script and evaluation metrics

The demo is three minutes built around one real incident, with metrics on a single slide to show it is not a one-off.

**Demo script (3 minutes)**

1. **Hook (20 s):** a real frame of a van double parked on 8th Ave. "This blocked a lane for 11 minutes. Nobody at the TMC was alerted." (Use the real duration from our recordings.)
2. **Live system (40 s):** dashboard map with live cameras, then switch to replay of the incident. Boxes appear, the van's timer climbs, an alert fires at 60 s.
3. **The decision (40 s):** alert card with snapshot, event type, confidence, and the LLM summary. Recommended change for the upstream signal. Operator clicks accept.
4. **The payoff (40 s):** side by side SUMO, default vs recommended. Queue on the left backs up past the upstream intersection; the right clears. Show delay saved.
5. **Proof it works (30 s):** metrics slide, then the close: "AI eyes for every camera, humans in control of every signal."

**Metrics to report**

| Metric | How measured | Target |
| --- | --- | --- |
| Detector mAP@0.5 | Test split, baseline vs fine-tuned | Above 0.6, and a visible gain over baseline |
| Event precision | Correct alerts / all alerts on hand-tagged events | 80% or more |
| Event recall | Detected / all tagged blockages | 70% or more |
| Time to alert | Blockage start to alert, median | Under 90 s |
| Delay reduction | Avg delay per vehicle, default vs recommended, mean of 3 seeds | Report whatever we get, honestly |
| Queue clear time | Minutes until blocked approach queue returns to normal | Report per scenario |

## Risks, mitigations and stretch goals

The biggest risks are an unreliable public camera feed and SUMO setup eating the clock; both are covered by replay mode and doing SUMO before the event.

**Risks**

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Camera endpoint changes, rate-limits or goes down during judging | Medium | Replay mode on recorded frames is the primary demo; live is a bonus. Backup via 511NY key |
| Camera IDs change | Medium | Scrape the list at startup; match by name and coordinates, not ID |
| Low resolution hurts detection | High | Fine-tune on our frames, upscale input, pick cameras with close views |
| Red lights and queues cause false stopped vehicle alerts | High | Dwell longer than one signal cycle in travel lanes; alert only on the front vehicle of a queue |
| Cameras pan or zoom, breaking masks | Medium | Detect view change by comparing to a reference frame; pause that camera's rules |
| SUMO network or demand unrealistic | Medium | Build before the event; calibrate to NYC volume counts; present results as relative, not absolute |
| Real signal plans unknown | Certain | State the assumption clearly; the method, not the exact numbers, is the point |
| Scope creep | High | Hour 18 end to end gate; features freeze at hour 30 |

**Stretch goals (only after the hour 18 gate)**

- Search based retiming: SUMO evaluates 5 to 10 candidate plans per event and picks the best.
- Lane loss heatmap: which blocks lose the most lane-minutes to double parking per day, for enforcement planning.
- Match alerts against 311 in real time to show we catch blockages before anyone complains.
- Bus impact: pull MTA Bus Time data to show how many bus riders each blockage delayed.
- Operator feedback loop: false positive clicks become new labeled examples for the next fine-tune.
