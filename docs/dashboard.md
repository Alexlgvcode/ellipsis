# ellipsis dashboard

The operator screen for ellipsis: a map-first view of Midtown incidents, the live source camera, the
traffic impact, and a focused signal-timing simulation. It's a React app in [`web/`](../web). The
product and visual spec it follows is [dashboard-design-spec.md](dashboard-design-spec.md). Section
numbers below (§) point into it.

```bash
make api            # backend on :8000 (LW_MOCK_MODE=true serves data/mock/)
make web-install    # once
make web            # http://localhost:5173, proxies /api to LW_API_URL
make web-test       # vitest + typecheck
```

## What's on screen

| Region | Spec | Component |
|---|---|---|
| 56px top bar: wordmark, `New York City / Manhattan / Midtown`, incident count, camera health, feed state, NY time | §6 | `TopBar`, `BrandMark` |
| 288px incident rail: Critical / Review / All filters, sort by severity or newest, grouped by severity, collapsible to 48px | §10 | `IncidentRail` |
| Full-bleed 3D map (MapLibre, OpenFreeMap vector tiles repainted to the §8 palette, building footprints extruded at 0.55× height) | §8, §9 | `MapShell` |
| Incident markers by status, selected ring and label, one pulse for new incidents, source camera, affected road segment | §11–13, §17 | `MapShell` |
| Layer toggles (Incidents, Traffic, Cameras, Signals) and navigation (+, −, 3D, reset) | §27 | `MapControls` |
| 380px floating inspector, only when an incident is selected: incident, camera feed, traffic impact, recommended response, detection details, timeline | §14–20 | `IncidentInspector`, `LiveCameraFeed` |
| Simulation comparison (fix brief §49–65), in three layers:<br>• **Main map:** the bird's-eye corridor, with car glyphs coloured stopped / slowing / flowing.<br>• **Top left:** a "Base vs Sim" summary (seconds saved, % delay, fewer queued, one interpretive line) and the Base / Sim toggle for the main map.<br>• **Top right:** paired Base / Sim close-ups of the treated intersection from one fixed side-angle camera, with delay, queue, green phase (`45s → 39s`) and flow.<br>Two translucent beams project from the incident to the close-ups and animate once. | §21–26, UI fixes §38–68 | `SimulationMode`, `IntersectionView` |
| Loading, empty, disconnected, camera offline, pending and failed simulation states | §30–35 | across components |

## Data

The app polls the API every 2.5 s (`/health`, `/cameras`, `/events`, `/recommendations/{id}`)
and keeps the last good payload when a poll fails. All shaping is in `web/src/lib/` as plain,
unit-tested functions:

- **`incidents.ts`**: API event + camera + recommendation → the spec's `Incident` (§45).
  - **Status:** `needs_review` below 75% confidence; `critical` at 5× the dwell threshold or more;
    otherwise `confirmed`. An event not updated for 5 min is `resolved` (mock events never resolve).
  - **Elapsed time** counts up from when the browser first saw the incident and never goes backwards.
- **`grid.ts`**: per-avenue lines fitted to the camera coordinates (~14 m residual). It places the
  queue upstream of a blockage, against the avenue's one-way flow, and places changed signals from
  their IDs (`tls_8av_32st`).
- **`rules.ts`**: dwell thresholds mirrored from `events/rules.yaml`, with a test that fails if they drift.
- **`scenario.ts`**: before/after green times. The API only carries the change (`change_s`), so
  the "before" value is the modeled plan in `sim/network/signal_plans.yaml`: a 90 s cycle, 45 s
  avenue green and 28 s cross-street green. Queue pressure (High / Moderate / Low) uses the same
  thresholds as the road colouring.
- **`traffic.ts`**: car states (stopped < 15% of free-flow speed, slowing < 60%, else flowing),
  their fixed colours, and the close-up scene parameters. Both close-ups share geometry and camera;
  only the queue, slowdown and green time change, scaled from the simulated queues.
- **`palettes.ts`**: the Night Shift surface palette, as CSS variables plus matching map colours.
  Semantic colours (green / amber / coral / deep red) are fixed in `semantic.ts` and `tokens.css`.
  Tests check AA contrast and that no component hardcodes a surface colour.

**Night Shift** is the product palette (fix brief §38). It has the refined depth order:

1. quiet city mass
2. brighter roads
3. semantic traffic
4. charcoal panels

Rail lines are muted to 30% opacity, with the dash layers hidden.

## What's real and what isn't yet

- **Traffic impact** shows the simulated baseline: delay per vehicle, queue in vehicles, and queue
  length at 7.5 m per vehicle. The API has no added-delay, lane-capacity or downstream-speed fields
  yet, so those §19 rows are left out rather than invented.
- **Simulation playback** eases the queue between the recorded baseline and recommended maximum
  queues. Car positions and the close-ups are illustrative and labelled so. Replace them with
  per-vehicle or per-edge output from SUMO when `sim/run_scenario.py` emits it.
- **Camera feed:** NYC DOT cameras publish stills every few seconds. The feed says
  "Live camera · updated Ns ago" and never claims video (§16). "At alert" shows the flagged frame
  with a thin box on the vehicle.
- **Feed state:** mock mode shows `SAMPLE DATA` in the top bar. The spec bans a visible `MOCK`,
  but the screen still never presents sample data as `LIVE`.
- **No operator approval step.** The spec's flow ends at the simulation result, and signal
  changes are shown as simulated. `docs/plan.md` still describes accept/reject; update it if
  that's the final call.

## Issue #7 checklist, as built

| Issue item | Where |
|---|---|
| App runs | `make web` (React + Vite; the issue originally named Streamlit) |
| Map of camera pins; active alerts stand out | `MapShell`: status-coloured incident markers, camera layer |
| Alert feed: snapshot with boxes, type, duration, confidence | Rail (type, duration, status) + inspector camera block ("At alert" frame with box; confidence in the header) |
| Recommendation: signal changes, delay/queue default vs recommended | Inspector "Recommended response" + simulation mode |
| Reads the API (mock mode), refreshes every 2–3 s | `usePolling`, 2.5 s |
| Automated tests | `web/src/**/*.test.ts(x)`: data shaping, grid, rule sync, app flows with the map mocked |
