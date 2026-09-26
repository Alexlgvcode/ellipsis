# Design handoff: Lane Watch operator dashboard

Paste this whole doc into Claude Design, and attach the images listed in
[Attach these files](#attach-these-files). It's self-contained: everything needed to design the
screen is here.

---

## The brief in one paragraph

Design the single-screen operator dashboard for **Lane Watch**, an AI co-pilot for New York City's
Traffic Management Center. It watches public traffic cameras around Penn Station, spots vehicles
stopped where they block traffic (double parked, stopped in a travel lane, blocking the
intersection box), explains what it saw, and recommends a traffic-signal timing change that a
simulation shows clears the jam faster. A human approves every change. The screen will be shown on
a projector to hackathon judges for 3 minutes, so it must **look like a real control-room product
at first glance**, stay perfectly readable, and make three moments land: *alert fires*,
*decision*, *payoff*. Visual direction: the ctOS city-surveillance interface from the video game
Watch Dogs 1, reinterpreted as a serious traffic-operations tool. Original design only; no game
logos, fonts or assets.

## What judges must feel, in order

1. **"This is watching the whole city."** A dark, tilted 3D map of Midtown Manhattan with camera
   nodes, live and alive. Numbers ticking. Nothing static.
2. **"It caught something a human would have missed."** An alert fires: the camera node flares
   red, heat blooms over the spot, the alert slides into the feed, a timer counts up.
3. **"It shows its work."** The alert opens: the camera frame with the stopped van targeted, a
   plain-English reason ("Stopped 4 min 15 s in the travel lane next to the curb; threshold 60 s"),
   confidence, and the live camera beside it.
4. **"It knows what to do, and a human stays in control."** A signal recommendation with its
   simulated effect: delay per vehicle 48 s down to 39 s, queue 21 down to 13 cars. The operator
   clicks **Accept (simulation)**.
5. **"It works."** A side-by-side of the default vs recommended plan, and "delay saved" as the
   biggest number on screen.

Design for those five beats. Everything else is secondary.

## Canvas and layout

- **Frame:** 1440 x 900, dark. Must also read well on a projector (think 3 m away): minimum body
  text around 14 px, key numbers large.
- **One screen, no navigation, no scrolling for the core story** at 1440 x 900.
- Current structure (keep the logic, change anything about the arrangement):

```
+--------------------------------------------------------------------------------+
| HEADER  product name | active alerts | cameras online | NYC time | system status  |
+---------------------------------------------+----------------------------------+
|                                             | ALERT DETAIL                     |
|  MAP (hero)                                 |  type, camera, timer, confidence |
|  camera nodes, alert rings, heat            |  reason line                     |
|  [Pins] [Heat] layer toggle                 |  [snapshot at alert][live camera]|
|                                             |                                  |
+---------------------------------------------+  SIGNAL RECOMMENDATION           |
| ALERT FEED  (compact rows, active first)    |  changes, delay/queue A vs B,    |
|                                             |  delay saved, [Accept] [Reject]  |
+---------------------------------------------+----------------------------------+
```

## Components to design

### 1. Header bar
- Product name `LANE WATCH` with area `MIDTOWN`.
- **Active alerts** count: the most important number in the header; red and alive when above 0.
- Cameras online (e.g. `10 / 10`), current New York time (live seconds), and a system status:
  `API LINKED` / `API OFFLINE`, plus a data-mode badge: `MOCK`, `REPLAY` or `LIVE`.
  The badge must be honest and visible: judges should see when they're watching a replay.

### 2. Map (the hero)
- Dark 3D basemap of Midtown (8th Ave to 5th Ave, 30th St to 40th St), tilted about 40 degrees.
- **Camera nodes:** 17 cameras. Idle = small cyan node. Alert = larger red node with an outer
  ring (pulse is welcome). Offline = grey.
- **Heat of stopped vehicles:** soft heat bloom at each alerting camera; hotter the longer the
  vehicle has been stopped past its threshold and the higher the confidence.
  Ramp: transparent, cyan, orange, red.
- Hover a node: camera name, active alerts.
- Layer toggle: Pins / Heat (both on by default).
- Optional ideas welcome: faint street labels, a scan sweep, lines from the alert camera to the
  signals the recommendation touches.

### 3. Alert feed
- Compact rows: event type (color coded), camera name, a large `MM:SS` timer, confidence, start
  time. Active first, then newest. Ended alerts dimmed with `ENDED`.
- Selected row clearly highlighted. New rows should feel like they *arrive* (slide or flash once).
- Empty state: "No alerts. Watching 10 cameras."

### 4. Alert detail (selected alert)
- Type (big, color coded), camera name, timer, confidence, lane zone, started-at time.
- **Reason line**, always present, reads like an explanation:
  "Stopped 4 min 15 s in the travel lane next to the curb (double parked threshold 60 s)".
- **Two images side by side:** *Snapshot at alert* (with targeting brackets around the vehicle
  and a tag `DOUBLE PARKED // 04:15 // 84%`) and *Live camera* (refreshes every 5 s, with a small
  LIVE indicator). Images are small, low-res 352 x 240 street-camera frames with a burned-in
  timestamp strip at the top; design the frames around that, don't expect crisp photos.
- Space for a one-paragraph AI incident summary (comes later; show it in the design).

### 5. Signal recommendation card
- Label: **Signal recommendation (simulation only)**. Nothing here controls real signals.
- One line per change: e.g. `8 Ave @ 32 St: phase 0, cut green 6 s` (IDs may show as
  `tls_8av_32st` until mapped).
- **Simulated effect, default vs recommended:** average delay per vehicle and max queue on the
  blocked approach. Make the improvement unmistakable, and give **delay saved** (e.g. `-9.2 s per
  vehicle, -19%`) hero treatment.
- **Accept (simulation)**, **Reject**, **False positive** buttons. Accepted shows
  `APPLIED (SIM)`.
- States: *No recommendation yet*, *Simulation running* (feels like it's computing), *Done*.
- Room for a small side-by-side (default vs recommended queue over time, two sparklines or two
  mini charts) for the payoff beat.

## Screens / states to deliver

Please design each at 1440 x 900:

1. **Watching:** no active alerts; map calm, cyan nodes, feed empty state.
2. **Alert firing:** a new double-parked alert just arrived: node flares, heat blooms, feed row
   arrives, header count goes to 1. (Show the "moment" style: what animates, how.)
3. **Alert selected, simulation running:** detail filled in, recommendation card computing.
4. **Recommendation ready:** delay and queue numbers, delay saved, Accept/Reject/False positive.
5. **Accepted:** `APPLIED (SIM)` state, side-by-side payoff visible.
6. **API offline:** header shows offline, calm warning, last-known data dimmed, retrying.

Plus a small component sheet: header, feed row (idle / active / selected / ended), detail card,
recommendation card (3 states), buttons, badges, map node styles, heat ramp.

## Sample data to design with

Cameras (a subset of the 17; real names and positions):

| Camera | Lat | Lon |
|---|---|---|
| 8 Ave @ 34 St | 40.752197 | -73.993456 |
| 8th Ave @ 31st St | 40.750297 | -73.994830 |
| 8th Ave @ 33rd St | 40.751512 | -73.993913 |
| 7 Ave @ 32 St | 40.749508 | -73.991493 |
| 7 Ave @ 34 St | 40.751020 | -73.990629 |
| 7 Ave @ 36 St | 40.752128 | -73.989657 |
| 6 Ave @ 30 St | 40.747287 | -73.989615 |
| 6 Ave @ 34 St | 40.749808 | -73.987746 |
| Broadway @ 6 Ave / 33 St | 40.749412 | -73.988060 |
| Broadway @ 38 St | 40.752453 | -73.987123 |

Alerts:

| Type | Camera | Timer | Confidence | Zone | Started (NYC) | Reason |
|---|---|---|---|---|---|---|
| Double parked | 8th Ave @ 33rd St | 04:15 | 84% | travel lane next to the curb | 11:58:40 AM | Stopped 4 min 15 s in the travel lane next to the curb (double parked threshold 60 s) |
| Stopped in lane | 7 Ave @ 34 St | 03:05 | 71% | travel lane | 11:59:50 AM | Stopped 3 min 5 s in a travel lane (stopped in lane threshold 120 s) |
| Blocking the box | 8 Ave @ 34 St | 00:28 | 77% | intersection box | 12:02:41 PM | Stopped 28 s in the intersection box (blocking the box threshold 20 s) |

Recommendations:

| For | Change | Delay per vehicle (default to recommended) | Max queue | State |
|---|---|---|---|---|
| Double parked, 8th Ave @ 33rd St | 8 Ave @ 32 St: phase 0, cut green 6 s | 48.3 s to 39.1 s | 21 to 13 vehicles | done |
| Blocking the box, 8 Ave @ 34 St | 8 Ave @ 34 St: phase 2, cut green 5 s | 36.4 s to 31.8 s | 14 to 10 vehicles | done |
| Stopped in lane, 7 Ave @ 34 St | 7 Ave @ 34 St: phase 0, extend green 10 s | - | - | simulation running |

Example AI summary (for the reserved slot): "A white delivery van has been double parked on 8th
Avenue at 33rd Street for over four minutes, blocking the right travel lane during the midday peak.
Northbound traffic is merging around it and the queue reaches back toward 32nd Street."

## Visual language

Starting palette (refine freely, but keep the meanings):

| Token | Value | Meaning |
|---|---|---|
| Background | `#0a0c0f` | page |
| Panel | `#12161b` | cards, header |
| Text | `#e6edf3` | body |
| Muted | `#8b98a5` | labels, offline, ended |
| Cyan | `#00d8ff` | system, idle, "recommended" / good |
| Red | `#ff3344` | double parked, active alert, "default" / bad |
| Orange | `#ff8a00` | stopped in lane, warnings |
| Yellow | `#ffd400` | blocking the box |

- Monospace or technical sans; uppercase letter-spaced labels; tabular numbers for timers.
- Thin panel borders with corner brackets, faint scanlines, subtle glow on key numbers.
- Motion with purpose only: alert arrival, pulse on active count, "computing" on simulation,
  confirmation on accept. No constant flashing; nothing that hurts readability on a projector.
- The same color for an event type everywhere: feed, detail, targeting brackets, map node.

## Hard constraints

- **Privacy:** never show or imply face or license-plate recognition. Only vehicles get targeted.
- **Simulation only:** every signal action says "simulation"; nothing suggests real signals
  change.
- **Honesty:** mock and replay data are labeled on screen.
- **Real footage is low-res** (352 x 240). Don't design around crisp close-ups.
- **Build target is Streamlit** (Python) with a deck.gl map, and custom HTML/CSS for panels.
  That means:
  - map: deck.gl layers (scatter nodes, rings, heatmap, lines, 3D extrusions are possible), dark
    Carto basemap, tooltips on hover
  - panels, header, cards, badges, typography, colors and CSS animations: fully custom
  - images: regular `<img>` frames
  - interactions: buttons and toggles; selecting an alert happens in the feed (clicking map nodes
    to select is unreliable)
  - animations should be CSS (keyframes, transitions); avoid effects that need custom JavaScript

## What to hand back

1. The six state screens and the component sheet (images).
2. **HTML/CSS** for the header, feed row, detail card, recommendation card, buttons and badges
   (static markup with classes is ideal; it gets ported into the Streamlit app).
3. Final design tokens: colors, font stacks, sizes, spacing, border and glow styles, animation
   timings.
4. Map styling notes: node sizes and colors per state, ring and pulse, heat ramp and radius,
   camera tilt and zoom.

## Attach these files

From the repo (`Alexlgvcode/ellipsis`, branch `feat/dashboard`):

- `docs/images/dashboard-v1.jpg`: the current first version, to improve on
- `data/mock/snapshots/double_parked.jpg`, `stopped_in_lane.jpg`, `blocked_box.jpg`: real
  camera frames used for the alerts
- any frame from `data/frames/<camera>/<date>/` for the "live camera" panel
