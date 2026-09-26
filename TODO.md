# Lane Watch — TODO

Owners: **V** = Vision lead, **E** = Events lead, **S** = Sim lead, **P** = Product lead.
Details for each item are in [docs/plan.md](docs/plan.md). Check the hackathon rules on
allowed prep: before the event, keep work to data and environment, not product code.

---

## 0. Repo setup (now)

- [ ] Push the initial scaffold; add teammates as collaborators
- [ ] Assign the four roles
- [ ] Everyone: create a venv, `make install`, `cp .env.example .env`, `make api` → `/health` returns ok
- [ ] Decide on Python 3.11 for everyone (the plan's target) or keep 3.10
- [ ] Set up shared storage for `data/` (frames and labels are gitignored)
- [ ] Update the camera URL in `docs/plan.md` to `webcams.nyctmc.org/api/cameras/`

## 1. Pre-hackathon prep

### One to two weeks before
- [ ] **V** Implement `ingest/camera_list.py`: scrape to `data/cameras.json`, filter by area, match cameras by name and coordinates
- [ ] **V/E** Pick the area (Penn or Times Square) and 10–20 cameras with clear, fixed lane views (avoid PTZ cameras)
- [ ] **V** Check that every chosen camera's image endpoint responds
- [ ] **P** Register for a 511NY developer API key as a backup camera source
- [ ] **V** Implement `ingest/poller.py` and `ingest/health.py` (drop duplicate, frozen and error frames)
- [ ] **V** Start `scripts/record_frames.py` on an always-on machine: every 5 s, day and night, at least 5 days (~20–30 GB)

### One week before
- [ ] **E** Download 311 double-parking complaints and Parking Violations Issued for the area
- [ ] **E** Implement `scripts/match_311.py`: complaints within ~150 m of a camera → frame time windows
- [ ] **S** Export the Midtown OSM area, run `netconvert` (keep traffic lights, ~90 s cycle), and write the steps in `sim/network/README.md`
- [ ] **S** Generate demand in `sim/routes/` with `randomTrips.py` / `routeSampler.py`, scaled to NYC DOT volume counts
- [ ] **S** Confirm the network runs headless in SUMO with traffic lights
- [ ] **V** Sample ~500 frames (mixed cameras, times and weather), auto-label with pretrained YOLO, hand-correct in Roboflow or CVAT
- [ ] **V** Split 400 train / 100 test by time; export to `vision/datasets/`
- [ ] **V** Record pretrained baseline mAP@0.5, run a first fine-tune (`vision/train.py`), record fine-tuned mAP
- [ ] **E** Hand-tag 50–100 stopped-vehicle events (start/end time, type) as the rule test set

### Final days
- [ ] **E** Draw lane masks for the 10 best cameras → `events/masks/<camera-id>.json` (include bus stop zones)
- [ ] **S** Build `signals/camera_signals.json`: for each camera, the intersection it watches plus one upstream and one downstream on each approach
- [ ] **P** Pick 3 daytime demo incidents from the recordings: a double-parked van, a vehicle stopped in a travel lane, a blocked box
- [ ] **All** Set up GPU access (laptop or a single A10/L4) and a shared `.env`
- [ ] **All** Review `common/schemas.py` (Event and Recommendation) and agree on it

## 2. Hackathon (36 h)

### Hours 0–2 — lock interfaces
- [ ] **All** Freeze Event and Recommendation JSON; nobody changes `common/schemas.py` without telling the team
- [ ] **P** Write mock `Event` / `Recommendation` fixtures so every workstream can start in parallel
- [ ] **P** Pick the dashboard stack (Next.js + Leaflet, or Streamlit)

### Hours 2–8 — each piece works alone
- [ ] **V** `vision/detect.py`: batched YOLO over all cameras (car, truck, bus, van; conf ~0.35)
- [ ] **V** `vision/track.py`: ByteTrack per camera at low fps, stationary test, per-track history
- [ ] **E** `events/engine.py`: load masks and `rules.yaml`, find each track's zone, first rules working
- [ ] **S** `sim/run_scenario.py`: inject a blockage with TraCI `vehicle.setStop`, collect delay and queue metrics
- [ ] **P** `api/models.py` + `api/main.py`: SQLite tables, `GET /cameras`, `GET /events`, `GET /events/{id}`
- [ ] **P** Dashboard: map with camera pins, running on mock data

### Hours 8–14 — connect the pieces
- [ ] **E** Engine emits real events: double parked (60 s), stopped in lane (120 s), blocked box (20 s), frozen feed (30 s)
- [ ] **E** Front-of-queue only; ignore buses at stops and red-light waits; close an event after 3 lost frames
- [ ] **E** Save snapshots (boxes only, no plates or faces)
- [ ] **S** `signals/retime.py`: rules per event type, within the bounds (ped minimums, fixed cycle, ≤20% per phase)
- [ ] **S** Hook retiming into SUMO: runs A (default) and B (recommended) in parallel, 3 seeds, 15 simulated minutes
- [ ] **P** `api/ws.py`: websocket pushes new alerts and recommendations
- [ ] **P** Dashboard: alert feed with snapshot and boxes, event type, duration, confidence

### Hours 14–18 — GATE: end to end on replay
- [ ] **V/E** `scripts/replay.py`: recorded frames → detect → track → events → API
- [ ] **All** Demo incident in → alert on the dashboard → recommendation → sim result shown
- [ ] If this gate slips, cut scope before adding anything new

### Hours 18–24 — tune and measure
- [ ] **E** Tune thresholds on the test set; fix false positives
- [ ] **E** Report event precision (target ≥80%), recall (≥70%), median time to alert (<90 s)
- [ ] **V** Final detector mAP, baseline vs fine-tuned
- [ ] **S** Delay reduction and queue clear time per demo scenario (mean of 3 seeds)
- [ ] Sleep in shifts

### Hours 24–30 — polish
- [ ] **V** Live camera mode (poll every 2 s)
- [ ] **P** Operator accept / reject / false-positive (`POST /events/{id}/feedback`)
- [ ] **P** `api/summarize.py`: one-paragraph Claude incident note per alert (optional)
- [ ] **S/P** Side-by-side SUMO view (sumo-gui screenshots or synced playback)

### Hours 30–34 — feature freeze
- [ ] **P** Record a backup demo video on replay data
- [ ] **P** Slides, including one slide of metrics

### Hours 34–36 — ship
- [ ] **All** Rehearse the 3-minute demo twice (hook → live → decision → payoff → proof)
- [ ] Submit

## 3. Stretch (only after the hour-18 gate)

- [ ] Search-based retiming: SUMO scores 5–10 candidate splits, best one wins
- [ ] Heatmap of lane-minutes lost per block
- [ ] Real-time 311 matching ("caught before anyone complained")
- [ ] Bus rider impact from MTA Bus Time
- [ ] Turn false-positive clicks into new labeled examples
