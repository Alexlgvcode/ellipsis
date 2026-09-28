# ellipsis

An AI co-pilot for NYC DOT Traffic Management Center operators. It watches public
traffic cameras in Midtown, detects vehicles stopped where they block traffic (double
parked, stopped in a travel lane, blocking the box), and recommends a signal timing change
that a SUMO simulation shows helps. A human approves every change.

**Live site: https://ellipsisnyc.tech.** It shows alerts from the cameras as they happen
when the backend is up, and plays a recorded incident otherwise (`?replay` forces the
recording, `?sample` shows the sample incidents). Hosting: [deploy/README.md](deploy/README.md).

On hand-tagged footage the event engine reaches 82% precision, 90% recall and a median of
63 s from the vehicle stopping to the alert ([evaluation/](evaluation/README.md)).

Scope: 9 cameras with lane masks around Penn Station, Herald Square and Times Square. Crashes are out of
scope. Original plan: [docs/plan.md](docs/plan.md). Demo runbook: [docs/demo.md](docs/demo.md).

## Team

Built by two people, each owning half of the pipeline:

| Who | Owns |
|---|---|
| **Alexandre Lugovoi** ([@Alexlgvcode](https://github.com/Alexlgvcode)) | Detection → events → API: YOLO detector and tracker, lane masks, event engine and congestion monitor, evaluation and ground truth, API, recording, replay, sample incidents |
| **Brian Maina** ([@brianmmaina](https://github.com/brianmmaina)) | Cameras → simulation → dashboard: camera list and frame poller, SUMO network and scenarios, signal retiming and the scoring worker, dashboard, live mode, incident notes and spoken alerts, public site and hosting |

## Pipeline

```
cameras -> ingest (poll, dedupe, health) -> vision (YOLO + IoU tracker)
        -> events (lane masks + dwell rules, congestion) -> api (REST) -> dashboard
                                              \-> signals (retime) -> sim (SUMO A/B) -/
                                              \-> incident note (Gemini / Claude) + spoken alert (ElevenLabs)
```

## Repo layout

| Path | Owner | What |
|---|---|---|
| `common/` | both | Shared schemas (`Event`, `Recommendation`, `Congestion`, `Feedback`) and settings |
| `ingest/` | Brian | Camera list scrape, frame poller, feed health |
| `vision/` | Alex | Detector, tracker, fine-tuning, datasets |
| `events/` | Alex | Event engine, `rules.yaml`, per-camera lane `masks/`, congestion monitor, view check |
| `evaluation/` | Alex | Ground truth, metrics, cached detections ([README](evaluation/README.md)) |
| `signals/` | Brian | Camera→signal mapping, rule-based retiming, scoring worker |
| `sim/` | Brian | SUMO network, routes, scenario runner ([README](sim/network/README.md)) |
| `api/` | Alex; notes and voice by Brian | FastAPI backend, incident notes, spoken alerts |
| `web/` | Brian; congestion heatmap and camera panel by Alex | ellipsis dashboard (React + MapLibre), see [docs/dashboard.md](docs/dashboard.md) |
| `deploy/` | Brian | Server for the live site: Docker Compose + Caddy ([README](deploy/README.md)) |
| `scripts/` | both | Recording, replay, evaluation, sample data (Alex); live mode, signal measurement, demo export (Brian) |
| `tests/` | both | pytest suite, run in CI |
| `data/` | — | Frames, labels, open data (gitignored, kept local); `data/mock/` is committed |

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
make install        # core; `make install-all` adds vision, sim, llm extras
cp .env.example .env
make api            # http://localhost:8000/health
make web-install && make web   # dashboard on http://localhost:5173
```

If `make api` fails with `Address already in use`, find what's on the port with
`lsof -nP -iTCP:8000 -sTCP:LISTEN`, or run on another port with `make api PORT=8001`.

SUMO: install via `pip install -e ".[sim]"` (eclipse-sumo) or Homebrew, and set `SUMO_HOME`.
Build the Midtown network with `make sim-network && make sim-routes`. Commands
and the assumptions register: [sim/network/README.md](sim/network/README.md).

Tests: `pytest -q` and `make lint` for the backend, `make web-test` for the dashboard.

## Running it

**Sample incidents.** With `LW_MOCK_MODE=true` (the default), the API loads `data/mock/` at
startup: real, hand-checked incidents from the recordings with their SUMO recommendations,
congestion and incident notes, built by `python scripts/build_mock.py` (see
`data/mock/README.md`). The database is SQLite at `data/lanewatch.db`; delete it to start fresh.

**Replay.** Start the API with mock mode off so the sample incidents are removed, then run the
worker that scores each new event:

```bash
LW_MOCK_MODE=false make api
make recommend-worker
python scripts/replay.py --camera "7 Ave @ 36 St" --start 18:22 --end 18:30 --as-live --speed 1
```

The dashboard polls the API. The alert opens after about 60 s of the vehicle sitting still,
and the delay and queue appear once the worker finishes.

**Live.** Live mode runs the same pipeline on the masked cameras as their frames arrive
(every 2 s), in place of the replay line above. It needs the vision extra
(`pip install -e ".[vision]"`):

```bash
make live                                   # all masked cameras
python -m scripts.live --camera "7 Ave @ 36 St" --camera "Broadway @ 38 St"
```

Offline cameras aren't polled. A frozen feed isn't sent to the detector and raises a
`frozen_feed` alert after 30 s. Frames are also saved to `data/frames/`, so a live session
doubles as a recording.

**Incident notes and voice.** With `GEMINI_API_KEY` set (and `pip install -e ".[llm]"`), the
worker also asks Gemini for a one-paragraph incident note after scoring each event; the
dashboard shows it on the incident card. `LW_SUMMARY_PROVIDER=claude` with
`ANTHROPIC_API_KEY` uses Claude instead. `python -m api.summarize --post` writes notes for
events that have none. With `ELEVENLABS_API_KEY` set, alerts are also spoken. Without the
keys nothing changes.

## Interfaces

Defined in [common/schemas.py](common/schemas.py).

**Event**

```json
{
  "id": "evt_0001",
  "camera_id": "<nyctmc camera id>",
  "type": "double_parked | stopped_in_lane | blocked_box | frozen_feed",
  "start_ts": "2026-10-03T14:05:12Z",
  "duration_s": 74,
  "bbox": [120, 88, 176, 130],
  "lane_zone": "curb_adjacent",
  "confidence": 0.82,
  "snapshot_path": "data/frames/<camera_id>/20261003/140512.jpg"
}
```

**Recommendation**

```json
{
  "event_id": "evt_0001",
  "intersections": [{"id": "tls_8av_33st", "phase": 2, "change_s": -8}],
  "sim": {"delay_default": 41.2, "delay_new": 33.5, "queue_default": 18, "queue_new": 11}
}
```

## API

`make api`, then open http://localhost:8000/docs to try each endpoint.

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status": "ok", "mock_mode": ..., "source": "live" \| "replay"}` |
| GET | `/cameras` | From `data/cameras.json`, loaded at startup |
| GET | `/events` | Newest first; optional `camera_id`, `type`, `limit` |
| GET | `/events/{id}` | 404 if unknown |
| POST | `/events` | Create, or update by the same `id` (e.g. growing duration); 422 if it doesn't match the schema |
| GET | `/events/{id}/snapshot` | JPEG of the raw frame; draw `bbox` on top of it yourself |
| GET | `/events/{id}/voice` | Spoken alert audio (ElevenLabs), made once; 404 without a key |
| POST | `/congestion` | A camera approach's reading: free / slow / congested (same camera, approach and ts = update) |
| GET | `/congestion` | Latest reading of every camera approach, for the heatmap; optional `since` |
| GET | `/cameras/{id}/congestion` | One camera's readings, newest first |
| POST | `/recommendations` | Create, or update by `event_id` (e.g. to add `sim` later); 404 if the event is unknown |
| GET | `/recommendations/{event_id}` | 404 if none yet |
| POST | `/events/{id}/feedback` | `{"action": "accept" \| "reject" \| "false_positive", "note": ...}`; the latest decision replaces the earlier one; 404 if the event is unknown, 422 for any other action |
| GET | `/events/{id}/feedback` | 404 if no decision yet |
| GET | `/feedback` | Every decision, one request per dashboard poll |
| POST | `/events/{id}/summary` | Store the AI incident note (Gemini or Claude): `{"text": ..., "model": ...}` |
| GET | `/events/{id}/summary` | 404 if none |
| GET | `/summaries` | Every note, one request per dashboard poll |

On the hosted server only reads are open to the public: Caddy refuses every POST.

## Data sources

- Cameras: `https://webcams.nyctmc.org/api/cameras/` (public, undocumented; IDs can change)
- Backup: 511NY developer API
- NYC Open Data: 311 complaints, Parking Violations Issued, Automated Traffic Volume Counts
- OpenStreetMap for the SUMO network
