# Lane Watch — Hackathon Checklist

**Team:** **Alex** (detection → events → API) · **Brian** (cameras → simulation → dashboard)
Background: [docs/plan.md](docs/plan.md)

Work through the stages in order. In each stage, Alex and Brian build their features in
parallel. Each feature has two gates:

- **✅ Automated tests.** Pytest in `tests/`, run by CI on every push to every branch.
- **🧪 User test.** Someone other than the author runs it by hand from a clean `git pull`.

Don't start the next stage's features until your own gates pass.

## Rules

- One branch per feature: `feat/<name>` off `main`. Open a PR when both gates pass, and merge fast.
- **CI** (`.github/workflows/ci.yml`) runs `ruff check .` and `pytest` on Python 3.10 and 3.11 for every push and every PR to `main`. `main` only takes merges with green CI.
- Every feature adds `tests/test_<feature>.py`. Run it locally before pushing: `ruff check . && pytest -q`.
- CI installs only the core deps. Tests that need YOLO, SUMO or the Anthropic SDK start with `pytest.importorskip(...)` so they skip in CI; run those locally.
- Unit tests use small files committed under `tests/fixtures/` (a few frames, a tiny mask, a tiny SUMO net), never `data/` (it's gitignored).
- Pull `main` into your branch often (`git pull origin main`).
- `common/schemas.py` is the contract between you. Change it only in its own small PR, and tell the other person first.
- Hand-offs (don't change these):
  - frames at `data/frames/<camera_id>/<YYYYMMDD>/<HHMMSS>.jpg`
  - Event and Recommendation JSON as defined in `common/schemas.py`
- Scope cuts:
  - pretrained YOLO11s, no fine-tuning
  - lane masks on 3–5 cameras
  - no 311 or 511NY
  - 6–10 intersections in SUMO
  - two retiming rules
  - Streamlit dashboard that polls the API
  - replay is the demo; live mode is a bonus

> ⚠️ **Start recording frames in Stage 2, while it's daylight.** We have no footage, and the demo needs daytime incidents from today.

## Sequence

| Stage | Alex | Brian | What you can test at the end |
|---|---|---|---|
| 0 | setup + CI | setup + CI | API runs locally; CI green on `main` |
| 1 | `feat/mock-fixtures` | `feat/camera-list` | Mock data validates; camera list scraped |
| 2 | `feat/api` | `feat/frame-poller` | API serves mocks; frames recording |
| 3 | `feat/detector` | `feat/dashboard` | Boxes on real frames; dashboard on mock data |
| 4 | `feat/tracker` | `feat/sumo-network` | Stationary timers; SUMO runs |
| 5 | `feat/lane-masks` | `feat/sim-scenario` | Masks line up; A/B sim numbers |
| 6 | `feat/event-engine` | `feat/signal-retiming` | Events fire on a clip; mock event → recommendation |
| 7 | `feat/replay` | integration support | **End to end: incident → alert → recommendation → dashboard** |
| 8 | `feat/eval-metrics` | `feat/sim-side-by-side` | Metrics; side-by-side view |
| 9 | `feat/operator-feedback` (API) | `feat/operator-feedback` (UI) | Accept / reject works |
| 10 | `feat/llm-summary` | `feat/live-mode` | Bonus features |
| 11 | demo | demo | Full rehearsal |

---

## Stage 0 · Setup (both)

- [x] Push the scaffold to `main`
- [ ] Both clone, `python3 -m venv .venv && source .venv/bin/activate`, `make install`, `cp .env.example .env`
- [ ] Agree on the Python version (3.10 or 3.11)
- [x] Merge the CI setup to `main`:
  - `.github/workflows/ci.yml`
  - `.github/pull_request_template.md`
  - starter tests in `tests/`
  - pytest config in `pyproject.toml`
- [x] GitHub → Settings → Rules → Rulesets → protect `main`: require a PR, and require the `lint`, `test (3.10)` and `test (3.11)` checks to pass (admin bypass: pull requests only)
- [x] **✅ Automated tests:** the first CI run on `main` is green (Actions tab)
- [ ] **🧪 Test:**
  - `make api`, then open http://localhost:8000/health → `{"status": "ok"}` on both laptops
  - push a throwaway branch with a failing test and confirm CI goes red and the PR can't merge

## Stage 1

### Alex · `feat/mock-fixtures`
- [ ] `data/mock/events.json`: 3 Events (double parked, stopped in lane, blocked box) using real camera IDs from `data/cameras.json`
- [ ] `data/mock/recommendations.json`: 1–2 Recommendations with sim numbers
- [ ] Add a snapshot image or two under `data/mock/` so the dashboard has something to show
- [ ] **✅ Automated tests:** `tests/test_mock_fixtures.py` already exists and skips until the files land; it must now pass instead of skipping
- [ ] **🧪 Test:** every mock file loads into `Event` / `Recommendation` without a validation error
- [ ] Merge

### Brian · `feat/camera-list`
- [ ] Fetch `https://webcams.nyctmc.org/api/cameras/`, filter to the area box, write `data/cameras.json`
- [ ] Pick ~10 cameras around Penn / Herald Sq with fixed lane views (no PTZ); store them by name
- [ ] Resolve names to current IDs at startup (by name, then nearest coordinates)
- [ ] **✅ Automated tests:** `tests/test_camera_list.py`, with no network calls (mock httpx on a saved JSON sample):
  - parsing the raw fields
  - the area-box filter
  - name matching
  - an ID change still resolves to the right camera by name or coordinates
- [ ] **🧪 Test:** `python -m ingest.camera_list` prints the ~10 chosen cameras with IDs; opening 3 of their `image_url`s in a browser shows a live frame
- [ ] Merge

## Stage 2

### Alex · `feat/api`
- [ ] SQLite tables for cameras, events and recommendations (`api/models.py`)
- [ ] Endpoints:
  - `GET /cameras`, `GET /events`, `GET /events/{id}`
  - `POST /events`, `POST /recommendations`, `GET /recommendations/{event_id}`
  - serve snapshot images
- [ ] `LW_MOCK_MODE=true` serves `data/mock/`
- [ ] **✅ Automated tests:** `tests/test_api.py` with FastAPI `TestClient` and a temporary SQLite file:
  - a posted event can be read back
  - posting an invalid event returns 422
  - mock mode returns the 3 mocks
  - `GET /recommendations/{event_id}` returns 404 for an unknown event
- [ ] **🧪 Test:** `make api`, open http://localhost:8000/docs
  - `GET /events` returns the 3 mocks
  - a `POST /events` from the docs page shows up in `GET /events`
  - a snapshot URL opens in the browser
- [ ] Merge

### Brian · `feat/frame-poller`
- [ ] **First:** start a quick recorder (a simple loop is fine), chosen cameras every 5 s to the agreed path. Leave it running
- [ ] Async httpx poller: 2–5 s with jitter, a concurrency limit, a polite User-Agent; drop duplicates by hash
- [ ] `ingest/health.py`: flag frozen feeds (30 s of near-identical frames) and error images
- [ ] `scripts/record_frames.py` uses the poller at 5 s
- [ ] **✅ Automated tests:** `tests/test_poller.py` + `tests/test_health.py`:
  - duplicate frames are dropped
  - the file path matches the agreed format
  - an error image and a frozen sequence are flagged
  - an HTTP timeout doesn't crash the loop (mock the transport)
- [ ] **🧪 Test:** run for 5 minutes, then:
  - every chosen camera has ~60 new frames
  - no two frames in a row are identical
  - unplugging wifi for 30 s doesn't crash it
- [ ] Merge; move the long-running recorder over to the real poller

## Stage 3

### Alex · `feat/detector`
- [ ] `pip install -e ".[vision]"`. Pretrained YOLO11s; keep car, truck, bus; conf ~0.35; upscale input to 640
- [ ] Batch across cameras; return box, class and confidence per detection
- [ ] CLI: `python -m vision.detect <frames_dir> --out <dir>` saves annotated frames
- [ ] **✅ Automated tests:** `tests/test_detect.py`:
  - core-only (runs in CI): mapping from COCO class IDs to our class names, and the confidence filter
  - model-backed (`importorskip("ultralytics")`, local only): 2–3 frames in `tests/fixtures/frames/` each give at least 1 vehicle box
- [ ] **🧪 Test:** run it on 50 recorded frames from 3 cameras
  - most vehicles in the near lanes get a box
  - no boxes on buildings or people
  - write down what it misses at 352x240
- [ ] Merge

### Brian · `feat/dashboard`
- [ ] Streamlit app: `streamlit run dashboard/app.py`
- [ ] Map of camera pins; cameras with an active alert stand out
- [ ] Alert feed: snapshot with boxes, event type, duration, confidence
- [ ] Recommendation card: signal changes and delay/queue, default vs recommended
- [ ] Reads from the API (in mock mode for now) and refreshes every 2–3 s
- [ ] **✅ Automated tests:** `tests/test_dashboard.py`:
  - keep the data-shaping helpers (API response → table rows / map pins / card text) as plain functions outside Streamlit, and unit test those
  - optionally, a smoke test with `streamlit.testing.v1.AppTest` confirming the app renders without an exception
- [ ] **🧪 Test:** with the API in mock mode
  - all 3 mock alerts show with snapshots
  - clicking one shows its recommendation
  - a new event POSTed from `/docs` appears within 5 s, no reload
- [ ] Merge

## Stage 4

### Alex · `feat/tracker`
- [ ] One ByteTrack instance per camera, set for low fps
- [ ] Stationary test: center shift < 5% of box width and IoU > 0.7 vs the previous frame
- [ ] Per-track history: first seen, stationary since, class, last box
- [ ] CLI: saves annotated frames with track ID and stationary seconds drawn on each box
- [ ] **✅ Automated tests:** `tests/test_track.py` on synthetic box sequences (no model needed, runs in CI):
  - a box that barely moves builds up stationary time
  - a moving box never does
  - an IoU just under 0.7 resets the timer
  - track history fields are filled in
- [ ] **🧪 Test:** on ~5 minutes of one camera
  - a parked or double-parked vehicle keeps one ID and its timer climbs
  - moving cars never build up stationary time
- [ ] Merge

### Brian · `feat/sumo-network`
- [ ] `pip install -e ".[sim]"`. Export OSM for the 6–10 intersections around the chosen cameras
- [ ] `netconvert` with traffic lights kept and a 90 s cycle; write the exact commands in `sim/network/README.md`
- [ ] Routes from `randomTrips.py`, roughly Midtown volume
- [ ] `sim/network/midtown.sumocfg` for 15 simulated minutes
- [ ] **✅ Automated tests:** `tests/test_sumo_network.py`:
  - `midtown.net.xml` and the `.sumocfg` exist and parse as XML
  - the net has ≥6 traffic-light junctions
  - SUMO-backed (`importorskip("sumolib")`, local only): a 60 s headless run exits cleanly
- [ ] **🧪 Test:**
  - headless `sumo -c ...` finishes in seconds with no teleport storm
  - in `sumo-gui`, lights cycle and traffic flows on 8th Ave and 34th St
- [ ] Merge

## Stage 5

### Alex · `feat/lane-masks`
- [ ] Pick the 3–5 best cameras from the recorded footage (ideally ones already showing double parking)
- [ ] Draw curb, curb-adjacent, travel, box, bus-stop and ignore polygons → `events/masks/<camera-id>.json`
- [ ] Save a reference frame for each camera
- [ ] Script to draw a mask over a frame
- [ ] **✅ Automated tests:** `tests/test_masks.py`:
  - every file in `events/masks/` has a valid schema, a known zone type and polygons with ≥3 points inside the frame
  - point-in-polygon returns the right zone for a few hand-picked points
- [ ] **🧪 Test:** overlays for each masked camera, at 3 different times of day, line up with the lanes
- [ ] Merge

### Brian · `feat/sim-scenario`
- [ ] `sim/run_scenario.py`: input a lane, position, start time and duration; inject a stopped vehicle with TraCI `vehicle.setStop`
- [ ] Run A (default) and B (modified plan) in parallel with the same seed; 3 seeds averaged
- [ ] Output a `SimResult` (delay, queue) plus throughput and queue clear time
- [ ] **✅ Automated tests:** `tests/test_sim_scenario.py`:
  - core-only: metric aggregation (mean over seeds) builds a valid `SimResult`
  - SUMO-backed (`importorskip("traci")`, local only):
    - a short blockage run gives a longer queue than a run with no blockage
    - the same seed gives the same numbers
- [ ] **🧪 Test:** with a hard-coded blockage on 8th Ave
  - A shows a clearly longer queue than a run with no blockage
  - running twice with the same seed gives identical numbers
- [ ] Merge

## Stage 6

### Alex · `feat/event-engine`
- [ ] Find each track's zone (box center inside a polygon)
- [ ] Rules from `events/rules.yaml`: double parked 60 s, stopped in lane 120 s, blocked box 20 s, frozen feed 30 s
- [ ] Alert only on the front vehicle of a queue; ignore buses at stops and short red-light waits
- [ ] Close an event after 3 lost frames; log its duration; compute a confidence score
- [ ] **✅ Automated tests:** `tests/test_event_engine.py` on synthetic tracks and a tiny mask in `tests/fixtures/`:
  - each event type fires exactly at its dwell threshold
  - a red-light wait shorter than the cycle doesn't fire
  - a bus in a bus-stop zone is ignored
  - only the front vehicle of a queue fires
  - an event closes after 3 lost frames with the right duration
- [ ] **🧪 Test:** feed recorded clips from the masked cameras
  - at least one real incident per event type fires the right type
  - a car waiting at a red light does **not** fire
  - changing a threshold in `rules.yaml` changes behavior with no code edit
- [ ] Merge

### Brian · `feat/signal-retiming`
- [ ] `signals/mapping.py` → `signals/camera_signals.json`: for each masked camera, the TLS it watches plus upstream and downstream
- [ ] `signals/retime.py`:
  - rule 1: a lane blocked mid-block cuts upstream green 10–20%
  - rule 2: a blocked box shortens cross-street green
- [ ] Bounds: ped minimums kept, cycle unchanged, ≤20% per phase
- [ ] Event → Recommendation → sim-scenario → `POST /recommendations`
- [ ] **✅ Automated tests:** `tests/test_retime.py` (pure functions, runs in CI):
  - each rule gives the expected phase change for a mock event
  - no change exceeds 20% or breaks ped minimums
  - cycle length is unchanged
  - every masked camera has an entry in `camera_signals.json`
- [ ] **🧪 Test:** POST each mock event
  - a Recommendation with real sim numbers appears in the API
  - it shows on the dashboard
  - no change breaks the bounds
- [ ] Merge

## Stage 7 · Integration: the must-have demo path

### Alex · `feat/replay`
- [ ] `scripts/replay.py --camera <id> --start <ts> --end <ts> --speed 10`: frames → detect → track → events
- [ ] Save a snapshot with boxes (boxes only, no plates or faces); `POST /events` to the API
- [ ] Turn off mock mode in the API
- [ ] **✅ Automated tests:** `tests/test_replay.py`:
  - frames are ordered by timestamp and the time window is respected
  - with detector and tracker stubbed out, fake tracks produce a `POST /events` against `TestClient`
  - snapshots are written with boxes only
- [ ] Merge

### Brian · integration support
- [ ] Wire a new event → retiming → sim → recommendation automatically (for example, by polling the API for new events)
- [ ] Fix whatever the test below turns up in the dashboard or sim
- [ ] **✅ Automated tests:** `tests/test_integration.py`, where a mock event goes through the API → retiming worker → `GET /recommendations`, with the sim stubbed out

- [ ] **🧪 End-to-end test (both):** from a fresh `git pull` on one laptop, start the API, the retiming worker and the dashboard, then replay one recorded double-parking incident. Check:
  - boxes appear
  - the alert fires at ~60 s of vehicle time
  - the dashboard shows the snapshot, type, duration and confidence
  - the recommendation and sim numbers appear a few seconds later
- [ ] **Don't start Stage 8 until this passes.** If SUMO is the blocker, fall back to a hand-built corridor of 2–3 intersections

## Stage 8

### Alex · `feat/eval-metrics`
- [ ] Hand-tag ~20 stopped-vehicle events from today's recordings (start, end, type)
- [ ] Tune `rules.yaml`
- [ ] Report precision (target ≥80%), recall (≥70%), median time to alert (<90 s)
- [ ] Pick 3 daytime demo incidents (double parked, stopped in lane, blocked box); note each one's real duration
- [ ] **✅ Automated tests:** `tests/test_metrics.py`: precision, recall and time-to-alert on a tiny hand-made set of predicted vs tagged events with known answers
- [ ] **🧪 Test:** the metrics script runs from a clean checkout and prints the table; all 3 demo incidents pass the Stage 7 test
- [ ] Merge

### Brian · `feat/sim-side-by-side`
- [ ] Default vs recommended view on the dashboard: sumo-gui screenshots at matching times, or queue-over-time charts
- [ ] Show the "delay saved" number on the recommendation card
- [ ] **✅ Automated tests:** the "delay saved" calculation and the chart data prep are unit tested in `tests/test_dashboard.py`
- [ ] **🧪 Test:** for each of the 3 demo incidents, someone who hasn't seen it before can say which side is better, and by how much, within 10 seconds
- [ ] Merge

## Stage 9 · `feat/operator-feedback` (shared branch)

- [ ] **Alex:** `POST /events/{id}/feedback` (accept / reject / false positive), stored in SQLite
- [ ] **Brian:** buttons on the alert card; an accepted alert shows as "applied (sim)"
- [ ] **✅ Automated tests:**
  - `tests/test_api.py`: each feedback action is stored and returned; an unknown event returns 404; an invalid action returns 422
- [ ] **🧪 Test:** click each button on 3 alerts, restart the API, and the states are still there
- [ ] Merge

## Stage 10 · Bonus (only with time left)

### Alex · `feat/llm-summary`
- [ ] `api/summarize.py`: one-paragraph Claude incident note per alert, stored with the event and shown on the card
- [ ] **✅ Automated tests:** `tests/test_summarize.py`:
  - prompt building from an Event
  - with no API key, it returns `None` and doesn't crash
  - mock the Anthropic client; CI never calls the real API
- [ ] **🧪 Test:** the 3 demo incidents each get a correct, readable summary; the dashboard still works with no API key
- [ ] Merge

### Brian · `feat/live-mode`
- [ ] Live poller frames → pipeline at 2 s for the masked cameras; skip offline or frozen cameras
- [ ] **✅ Automated tests:** `tests/test_live_mode.py`: offline and frozen cameras are skipped (mocked health results)
- [ ] **🧪 Test:** 10 minutes live with no crash; unplugging wifi doesn't break the dashboard
- [ ] Merge

## Stage 11 · Demo and submit (both)

- [ ] Feature freeze; after this, only fix demo-path bugs on `main`, and CI must stay green
- [ ] **Brian:** record a backup demo video on replay
- [ ] **Alex:** slides on the problem, how it works, and metrics
- [ ] **Brian:** slides on the sim results and the signal-plan assumption (real NYC plans aren't public)
- [ ] **🧪 Test:** full 3-minute rehearsal from a cold start, twice: hook → replay → decision → sim payoff → proof and close
- [ ] Submit
