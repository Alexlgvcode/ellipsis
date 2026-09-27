# ellipsis

An AI co-pilot for NYC DOT Traffic Management Center operators. It watches public
traffic cameras, detects vehicles stopped where they block traffic (double parked,
stopped in a travel lane, blocking the box), and recommends a signal timing change
that a SUMO simulation shows clears the jam faster. A human approves every change.

Scope: 10–20 intersections in Midtown (Penn Station / Times Square). Crashes are
out of scope. Full plan: [docs/plan.md](docs/plan.md). Task list: [TODO.md](TODO.md).

## Pipeline

```
cameras -> ingest (poll, dedupe, health) -> vision (YOLO + IoU tracker)
        -> events (lane masks + dwell rules) -> api (REST + websocket) -> dashboard
                                              \-> signals (retime) -> sim (SUMO A/B) -/
```

## Repo layout

| Path | Owner | What |
|---|---|---|
| `common/` | all | Shared schemas (`Event`, `Recommendation`) and settings |
| `ingest/` | Vision lead | Camera list scrape, frame poller, feed health |
| `vision/` | Vision lead | Detector, tracker, fine-tuning, datasets |
| `events/` | Events lead | Event engine, `rules.yaml`, per-camera lane `masks/` |
| `signals/` | Sim lead | Camera→signal mapping, rule-based retiming |
| `sim/` | Sim lead | SUMO network, routes, scenario runner |
| `api/` | Product lead | FastAPI backend, websocket feed, summaries |
| `web/` | Product lead | ellipsis dashboard (React + MapLibre), see [docs/dashboard.md](docs/dashboard.md) |
| `data/` | — | Frames, labels, open data (gitignored, kept local) |
| `scripts/` | — | Recording, 311 matching, replay, live mode |

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
make install        # core; `make install-all` adds vision, sim, llm extras
cp .env.example .env
make api            # http://localhost:8000/health
```

If `make api` fails with `Address already in use`, find what's on the port with
`lsof -nP -iTCP:8000 -sTCP:LISTEN`, or run on another port with `make api PORT=8001`.

SUMO: install via `pip install -e ".[sim]"` (eclipse-sumo) or Homebrew, and set `SUMO_HOME`.
Build the Midtown network with `make sim-network && make sim-routes`. Commands
and the assumptions register: [sim/network/README.md](sim/network/README.md).

## Interfaces (lock these in hour one)

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
| GET | `/health` | `{"status": "ok", "mock_mode": ...}` |
| GET | `/cameras` | From `data/cameras.json`, loaded at startup |
| GET | `/events` | Newest first; optional `camera_id`, `type`, `limit` |
| GET | `/events/{id}` | 404 if unknown |
| POST | `/events` | Create, or update by the same `id` (e.g. growing duration); 422 if it doesn't match the schema |
| GET | `/events/{id}/snapshot` | JPEG of the raw frame; draw `bbox` on top of it yourself |
| POST | `/recommendations` | Create, or update by `event_id` (e.g. to add `sim` later); 404 if the event is unknown |
| GET | `/recommendations/{event_id}` | 404 if none yet |
| POST | `/events/{id}/feedback` | `{"action": "accept" \| "reject" \| "false_positive", "note": ...}`; the latest decision replaces the earlier one; 404 if the event is unknown, 422 for any other action |
| GET | `/events/{id}/feedback` | 404 if no decision yet |
| GET | `/feedback` | Every decision, one request per dashboard poll |
| POST | `/events/{id}/summary` | Store the AI incident note (Gemini or Claude): `{"text": ..., "model": ...}` |
| GET | `/events/{id}/summary` | 404 if none |
| GET | `/summaries` | Every note, one request per dashboard poll |

With `LW_MOCK_MODE=true` (the default), the API loads the `data/mock/` events and
recommendations at startup. The database is SQLite at `data/lanewatch.db`; delete it to
start fresh.

For a replay on the dashboard, start the API with mock mode off so those sample
incidents are removed, then run the worker that scores each new event:

```bash
LW_MOCK_MODE=false make api
make recommend-worker
python scripts/replay.py --camera "7 Ave @ 36 St" --start 18:22 --end 18:30 --as-live --speed 1
```

The dashboard (`make web`) polls the API. The alert opens after about 60 s of the
vehicle sitting still, and the delay and queue appear once the worker finishes.

With `GEMINI_API_KEY` set (and `pip install -e ".[llm]"`), the worker also asks Gemini
for a one-paragraph incident note after scoring each event; the dashboard shows it on the
incident card. `LW_SUMMARY_PROVIDER=claude` with `ANTHROPIC_API_KEY` uses Claude instead. `python -m api.summarize --post` writes notes for events that have none,
e.g. the mock ones. Without a key nothing changes.

Live mode runs the same pipeline on the masked cameras as their frames arrive (every 2 s),
in place of the replay line above. It needs the vision extra (`pip install -e ".[vision]"`):

```bash
make live                                   # all masked cameras
python -m scripts.live --camera "7 Ave @ 36 St" --camera "Broadway @ 38 St"
```

Offline cameras aren't polled. A frozen feed isn't sent to the detector and raises a
`frozen_feed` alert after 30 s. Frames are also saved to `data/frames/`, so a live session
doubles as a recording.

## Data sources

- Cameras: `https://webcams.nyctmc.org/api/cameras/` (public, undocumented; IDs can change)
- Backup: 511NY developer API
- NYC Open Data: 311 complaints, Parking Violations Issued, Automated Traffic Volume Counts
- OpenStreetMap for the SUMO network
