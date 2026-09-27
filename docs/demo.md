# Demo runbook

The 3-minute demo (#21): hook → replay → decision → sim payoff → proof and close. It plays
recorded footage through the real pipeline, so it doesn't depend on what's happening on
7th Ave today. Rehearse it twice from a cold start before submitting.

## Demo incidents

Picked and checked in #16, from the 2026-09-26 recording (times UTC; EDT is UTC−4).

| When in the replay | Camera | What | Ground truth | Dashboard |
|---|---|---|---|---|
| 0:03 stops, **1:04 alert** | 7 Ave @ 36 St | far delivery truck, double parked 565 s | `gt_002` | Confirmed (conf 0.85) |
| 0:14 stops, **1:14 alert** | 7 Ave @ 36 St | near white box truck by the planters, double parked 521 s | `gt_001` | *Needs review* (0.69) |
| 1:25 stops, **2:42 alert** | 8th Ave @ 31st St | cab stopped in the travel lane, 82 s | `gt_009` | *Needs review* (0.52) |
| 3:07 stops, 4:08 alert | 7 Ave @ 36 St | NYPD SUV pulls up behind the near truck, 107 s | `gt_003` | Confirmed (0.89), after the 3 minutes |

Replay window: **18:21:30–18:31:00**. It has two event types. Real blocked boxes were
recorded later, at dusk at Broadway @ 6 Ave / 33 St (`gt_011`–`gt_014`, 22:46–23:05 UTC,
caught by the engine); they're in mock mode (below), not in this replay.

**Sim numbers: present what the card shows.** The worker scores each alert once, when it
opens, so the sim assumes a stop of about 60 s. In a test run, that gave the near truck
**95.1 → 88.9 s per vehicle** (queue 7 → 9). Simulated with its full 5-minute stop it gives
124.4 → 119.4 s. With 3 seeds, gains of a few percent are within the noise (see #52). So
call it a modest gain, never a promise: retiming limits spillback, it doesn't clear the truck.
If the card says "Default is faster", say so. It's the tool refusing to push a change that
doesn't help.

⚠️ Re-run the check below after anything touching the engine merges (in particular #47
Part A, "hold alerts until traffic passes"), and before recording the video.

```bash
python scripts/replay.py --camera "7 Ave @ 36 St" --date 20260926 --start 18:21:30 --end 18:31 --speed 0 --no-post
python scripts/replay.py --camera "8th Ave @ 31st St" --date 20260926 --start 18:21:30 --end 18:31 --speed 0 --no-post
```

Expect the three OPEN lines above for 7 Ave (18:22:34, 18:22:44, 18:25:38) and one for
8th Ave (18:24:12).

## One-time setup (demo laptop)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"                  # vision (YOLO), sim (SUMO), llm (Claude notes), dev
make web-install
cp .env.example .env                     # then set ANTHROPIC_API_KEY for incident notes
```

- **Frames:** `data/frames/b0cbb042-…/20260926/` and `data/frames/ec9ffb62-…/20260926/` must
  cover 18:21–18:31. Brian's laptop has them; copy them to the demo laptop if it's a different one.
- **YOLO weights:** `yolo11s.pt` downloads on the first run. Run the check above once on
  good wifi so it's cached.
- **Map tiles and the "Live camera" view need internet.** Everything else runs offline. If the
  venue wifi is bad, play the backup video.

## Cold start (every rehearsal, and the real thing)

Four terminals from the repo root, each with `source .venv/bin/activate`:

```bash
rm -f data/lanewatch.db && LW_MOCK_MODE=false LW_DATA_SOURCE=replay make api   # 1. fresh DB, real events, badge says REPLAY
make recommend-worker                                      # 2. SUMO scoring + Claude notes
make web                                                   # 3. http://localhost:5173
```

Open http://localhost:5173 full screen. The top bar should say **REPLAY** with 0 incidents. Say
that it's recorded footage run through the live pipeline; the same code runs on live
cameras (`make live`, with the badge showing LIVE).
Then start the replays together in terminal 4:

```bash
python scripts/replay.py --camera "7 Ave @ 36 St" --date 20260926 --start 18:21:30 --end 18:31 --as-live --speed 1 &
python scripts/replay.py --camera "8th Ave @ 31st St" --date 20260926 --start 18:21:30 --end 18:31 --as-live --speed 1
```

`--as-live` shifts the times so the recording starts now; `--speed 1` is real time. Start
the replays as you begin the hook: the first alert lands about a minute in.

## The 3 minutes

| Time | Beat | On screen |
|---|---|---|
| 0:00–0:45 | **Hook.** Double parking on a Midtown avenue backs up the whole corridor; TMC operators watch hundreds of feeds by eye. | Map of the Midtown cameras; replay running |
| ~1:04 | **Alert.** Two delivery trucks double parked on 7 Ave @ 36 St. | The alerts appear in the list |
| 1:15–1:45 | **Decision.** Open the near truck (*Needs review*): the frame from when it alerted, with the box, how long it has been stopped, the lane. The card opens on the alert frame, with a line saying why it needs review. Click **Accept** in the decision bar pinned to the bottom of the card. | Card shows *Applied (sim)*, plus the Claude incident note if the key is set |
| 1:45–2:30 | **Sim payoff.** **Compare in simulation** (in the pinned decision bar, right under Accept): default versus recommended timing on the same signal, with delay per vehicle and the queue chart. Read out the card's numbers as they are. | Simulation mode |
| ~2:42 | Second alert: cab stopped in the lane on 8th Ave @ 31st St. It's another type, and it also goes through a human decision. | New alert in the list |
| 2:30–3:00 | **Proof and close.** Precision 82%, recall 90%, median time to alert 63 s on hand-tagged footage. Every change goes through a human. | Metrics slide |

## Mock mode (fallback)

If the replay can't run (no recorded frames, YOLO or SUMO on the laptop, or no time for the
cold start), show mock mode. It serves `data/mock/`: **13 real, hand-checked incidents** from
the recordings, all three types (7 double parked, 3 stopped in lane, 4 blocked boxes; day,
dusk and night), with their real frames, boxes and durations, SUMO-scored recommendations,
and the congestion heatmap. Nothing to start but the API and the dashboard:

```bash
rm -f data/lanewatch.db && LW_MOCK_MODE=true make api
make web
```

The top bar says **SAMPLE DATA**. Say it's the recorded incidents loaded as a snapshot, not a
live feed; the list and `data/mock/README.md` say where each one comes from. Rebuild it after
tagging new incidents with `python scripts/build_mock.py` (needs `data/frames/` and `.[sim]`).

## Backup video

Record one full run on replay with QuickTime (File → New Screen Recording) at 1440×900 or
larger, after a cold start, with the key set so the notes show. Keep it under 3:30. Store it
next to the slides, not in the repo.

## Slide notes: simulation and signal timing (Brian)

**How the recommendation is scored**
- SUMO model of Midtown: 9th–5th Ave, 29th–39th St. Weekday midday demand from the 15 Penn FEIS
  counts × 0.89 (MTA congestion pricing, −11% vehicle entries).
- Each alert becomes a stopped vehicle in the same lane. The simulation warms up for 300 s,
  holds the stop for as long as the real one lasted (up to 5 min), then runs 3 min of
  recovery, over 3 random seeds.
- Three candidate timing plans are scored against the current plan:
  - cut the upstream green by 15%
  - add 20% green to the blocked approach
  - both

  The best one is recommended. The cycle stays 90 s, no green goes under 8 s, and no phase
  moves more than 20%.
- **Delay counts the vehicles whose trip goes through the blocked block or the retimed
  signals, cross streets included**, so a plan can't win by starving a side street.

**Results on the demo incidents** (simulated with each stop's full length, capped at 5 min)

| Incident | Recommended | Delay per vehicle | Queue |
|---|---|---|---|
| 7 Ave @ 36 St box truck | upstream green −6.8 s | 124.4 → 119.4 s (−4%) | 9 → 8 |
| NYPD SUV behind it | own approach +9 s | 101.8 → 99.1 s | 8 → 7 |
| 8th Ave @ 31st St cab | own approach +9 s | 64.3 → 62.9 s | 2 → 1 |

The same truck simulated with a 3-minute stop gets no gain from any plan (105.3 s at best
110.2 s). The honest range is "a few percent either way, depending on how long the vehicle
stays". Say that, and don't pick the best number.

**The signal-plan assumption.** NYC's real timing plans aren't public, so the model uses a
pre-timed plan built from published sources:

| Parameter | Value | Status |
|---|---|---|
| Cycle | 90 s, pre-timed | verified: 15 Penn FEIS, and 9 of 10 cameras on footage |
| Leading pedestrian interval | 7 s where DOT lists one | verified: NYC Open Data |
| Barnes dance at 7 Ave @ 32 St | 24 s | verified: NYC Open Data |
| Yellow / all-red | 3 s / 2 s | assumed (ITE practice at 25 mph) |
| Avenue / street green split | 62% / 38% of the remaining green | assumed; checked against FEIS counts |
| Midtown in Motion (adaptive) | not modeled | stated as a limitation |

Full register: `sim/network/README.md` and `sim/sources/sources.yaml`.

**Say plainly:** the gains are a few percent on the affected trips. They'd need to be
validated against real controller data before anyone acts on them, and the tool is built
so an operator makes that call.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Address already in use` on 8000 | `lsof -nP -iTCP:8000 -sTCP:LISTEN`, or `make api PORT=8001` and `LW_API_URL=http://localhost:8001 make web` |
| No alerts after 1:30 | Was the API started with `LW_MOCK_MODE=false`, and did replay print `OPEN` lines? Rerun the check above |
| Alert shows but no recommendation | Is the worker terminal running? Scoring takes about 25 s per event. Is SUMO installed (`pip install -e ".[sim]"`)? |
| Card has no incident note | Set `ANTHROPIC_API_KEY` in `.env` and restart the worker. Without a key, the demo works without notes |
| Mock incidents show up | Delete `data/lanewatch.db` and restart the API with `LW_MOCK_MODE=false` |
| Map is blank | No internet for map tiles: play the backup video |
